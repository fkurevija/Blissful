"""Small persistent job queue for album downloads (BLISS-11 / BLISS-13).

Jobs are stored in a JSON file so they survive a container restart. A single
background worker drains pending jobs; duplicate enqueues for the same album
are collapsed by a dedupe key so a failing album is not retried forever.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {'succeeded', 'failed'}


def _now():
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """Persist and process download requests."""

    def __init__(self, config_manager, album_manager, storage_path='config/jobs.json'):
        self.config_manager = config_manager
        self.album_manager = album_manager
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.jobs = self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            if self.storage_path.exists():
                data = json.loads(self.storage_path.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    # A worker killed mid-run cannot still be running.
                    for job in data:
                        if job.get('status') == 'running':
                            job['status'] = 'pending'
                            job['failure_reason'] = 'Interrupted by restart'
                    return data
        except Exception as exc:
            logger.warning("Could not load jobs file: %s", exc)
        return []

    def _persist(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(self.jobs, indent=2), encoding='utf-8')
        tmp.replace(self.storage_path)

    # ------------------------------------------------------------------ public API
    def enqueue(self, kind, payload, dedupe_key=None):
        """Add a job, returning an existing live job when the key matches."""
        with self._lock:
            key = dedupe_key or self._dedupe_key(kind, payload)
            for job in self.jobs:
                if job.get('dedupe_key') == key and job.get('status') not in TERMINAL_STATUSES:
                    return dict(job), True

            job = {
                'id': uuid.uuid4().hex,
                'kind': kind,
                'status': 'pending',
                'dedupe_key': key,
                'payload': payload,
                'album_id': payload.get('album_id') or payload.get('foreignAlbumId'),
                'track_id': payload.get('track_id'),
                'source': payload.get('source', 'manual'),
                'failure_reason': None,
                'attempts': 0,
                'result': None,
                'created_at': _now(),
                'updated_at': _now(),
            }
            self.jobs.insert(0, job)
            self._persist()
            logger.info("Enqueued job %s (%s)", job['id'], key)
            return dict(job), False

    @staticmethod
    def _dedupe_key(kind, payload):
        album = payload.get('album_id') or payload.get('foreignAlbumId') or payload.get('album', '')
        artist = payload.get('artist', '')
        title = payload.get('album') or payload.get('title', '')
        return f"{kind}:{album or title}:{artist}".lower()

    def list_jobs(self, limit=100, status=None):
        with self._lock:
            jobs = self.jobs if not status else [j for j in self.jobs if j.get('status') == status]
            return [dict(j) for j in jobs[:max(1, min(int(limit), 500))]]

    def get_job(self, job_id):
        with self._lock:
            for job in self.jobs:
                if job['id'] == job_id:
                    return dict(job)
        return None

    def retry(self, job_id):
        """Reset a failed/succeeded job so the worker picks it up again."""
        with self._lock:
            for job in self.jobs:
                if job['id'] == job_id:
                    if job.get('status') not in TERMINAL_STATUSES:
                        return dict(job), False
                    job['status'] = 'pending'
                    job['failure_reason'] = None
                    job['updated_at'] = _now()
                    job['attempts'] = int(job.get('attempts', 0)) + 1
                    self._persist()
                    return dict(job), True
        return None, False

    def prune(self, days=None):
        """Drop old terminal jobs beyond the configured retention window."""
        if days is None:
            days = int(self.config_manager.get_setting('job_retention_days', 7) or 7)
        if days <= 0:
            return 0
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        with self._lock:
            kept = []
            for job in self.jobs:
                if job.get('status') in TERMINAL_STATUSES:
                    try:
                        created = datetime.fromisoformat(job['created_at'])
                        if created < cutoff:
                            removed += 1
                            continue
                    except (KeyError, ValueError):
                        pass
                kept.append(job)
            if removed:
                self.jobs = kept
                self._persist()
        return removed

    # ------------------------------------------------------------------ worker
    def start_worker(self, poll_interval=2.0):
        if not self.config_manager.get_setting('enable_jobs', True):
            logger.info("Job worker disabled by configuration; jobs can still be enqueued")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def run():
            logger.info("Job worker started")
            while not self._stop.is_set():
                try:
                    job = self._next_pending()
                    if job:
                        self._process(job)
                    else:
                        self._stop.wait(poll_interval)
                except Exception as exc:
                    logger.error("Job worker error: %s", exc, exc_info=True)
                    self._stop.wait(poll_interval)
            logger.info("Job worker stopped")

        self._thread = threading.Thread(target=run, name='blissful-jobs', daemon=True)
        self._thread.start()

    def stop_worker(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _next_pending(self):
        with self._lock:
            for job in self.jobs:
                if job.get('status') == 'pending':
                    job['status'] = 'running'
                    job['updated_at'] = _now()
                    self._persist()
                    return dict(job)
        return None

    def _process(self, job):
        payload = job.get('payload', {})
        logger.info("Processing job %s for %s - %s", job['id'], payload.get('artist'), payload.get('album'))
        try:
            if job.get('kind') == 'album':
                result = self.album_manager.download_album(
                    artist=payload.get('artist', ''),
                    album=payload.get('album', ''),
                    tracks=payload.get('tracks', []),
                    target_path=payload.get('target_path', ''),
                )
            else:
                result = {'success': False, 'error': f"Unknown job type: {job.get('kind')}"}
            status = 'succeeded' if result.get('success') else 'failed'
            reason = None if result.get('success') else result.get('error', 'Download failed')
        except Exception as exc:
            logger.error("Job %s failed: %s", job['id'], exc, exc_info=True)
            status, reason, result = 'failed', str(exc), None

        with self._lock:
            for current in self.jobs:
                if current['id'] == job['id']:
                    current['status'] = status
                    current['failure_reason'] = reason
                    current['result'] = {
                        'successful': (result or {}).get('successful'),
                        'failed': (result or {}).get('failed'),
                        'total_tracks': (result or {}).get('total_tracks'),
                    } if result else None
                    current['updated_at'] = _now()
                    break
            self._persist()
        logger.info("Job %s finished: %s", job['id'], status)

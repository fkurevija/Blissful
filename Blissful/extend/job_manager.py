"""Small persistent job queue for album downloads (BLISS-11 / BLISS-13).

Jobs are stored in a JSON file so they survive a container restart. A single
background worker drains pending jobs; duplicate enqueues for the same album
are collapsed by a dedupe key so a failing album is not retried forever.
"""

import json
import logging
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from extend.domain import TERMINAL_STATUSES

RETRY_BASE_SECONDS = 30.0
RETRY_MAX_SECONDS = 300.0


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
        self._threads = []
        # Only these kinds are executed by the built-in worker; other kinds
        # (e.g. a long-running API search) are driven by their own service.
        self.managed_kinds = {'album'}
        # Jobs written by a previous process must never be revived or
        # deduped into a new run - each run gets a fresh job id. An exact
        # in-process marker is required here: comparing an ISO timestamp to
        # time.time() loses a few microseconds to float rounding and makes
        # dedupe fail intermittently.
        self._instance_id = uuid.uuid4().hex
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
                            job['status'] = 'cancelled'
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
    def enqueue(self, kind, payload, dedupe_key=None, parent_id=None):
        """Add a job, returning an existing live job when the key matches.

        ``parent_id`` marks this as a child import job of a search/cleanup
        run; child jobs are hidden from the top-level history list.
        """
        with self._lock:
            key = dedupe_key or self._dedupe_key(kind, payload)
            for job in self.jobs:
                if job.get('dedupe_key') != key or job.get('status') in TERMINAL_STATUSES:
                    continue
                # Only reuse a job created by this process; a restart
                # must start a fresh job id rather than revive an orphan.
                if job.get('_instance_id') == self._instance_id:
                    return dict(job), True

            job = {
                'id': uuid.uuid4().hex,
                '_instance_id': self._instance_id,
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
                'log': [],
                'parent_id': parent_id,
                'progress_total': len(payload.get('tracks') or []),
                'created_at': _now(),
                'started_at': None,
                'finished_at': None,
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

    def list_jobs(self, limit=100, status=None, include_children=False):
        """List top-level jobs; child import jobs are hidden by default."""
        with self._lock:
            jobs = self.jobs if not status else [j for j in self.jobs if j.get('status') == status]
            if not include_children:
                jobs = [j for j in jobs if not j.get('parent_id')]
            selected = jobs[:max(1, min(int(limit), 500))]
            result = []
            for job in selected:
                item = dict(job)
                if not include_children:
                    item['child_count'] = sum(
                        1 for child in self.jobs
                        if child.get('parent_id') == job.get('id'))
                result.append(item)
            return result

    def delete_job(self, job_id):
        """Remove one job from history (including stuck pending records)."""
        with self._lock:
            before = len(self.jobs)
            self.jobs = [job for job in self.jobs if job.get('id') != job_id]
            if len(self.jobs) == before:
                return False
            self._persist()
            return True

    def cancel_job(self, job_id):
        """Mark a pending or running job as cancelled (terminal)."""
        with self._lock:
            for job in self.jobs:
                if job['id'] == job_id:
                    if job.get('status') not in ('pending', 'running'):
                        return False
                    job['status'] = 'cancelled'
                    job['failure_reason'] = 'cancelled by user'
                    job['updated_at'] = _now()
                    job['finished_at'] = _now()
                    self._append_log_locked(job, 'cancelled')
                    self._persist()
                    return True
            return False

    def clear_finished(self):
        """Remove all terminal jobs, keeping pending/running ones."""
        with self._lock:
            before = len(self.jobs)
            self.jobs = [job for job in self.jobs
                         if job.get('status') not in TERMINAL_STATUSES]
            removed = before - len(self.jobs)
            if removed:
                self._persist()
            return removed

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
                    # Manual retry is due now: no timestamp means the UI
                    # shows plain 'pending' and the worker picks it up.
                    job.pop('next_attempt_at', None)
                    job.pop('finished_at', None)
                    job.pop('result', None)
                    job.pop('progress', None)
                    payload = dict(job.get('payload') or {})
                    payload.pop('pending_tracks', None)
                    payload.pop('resume_state', None)
                    job['payload'] = payload
                    # A manual retry should run next: enqueue() inserts at
                    # the front, so restore that position here.
                    self.jobs.remove(job)
                    self.jobs.insert(0, job)
                    self._append_log_locked(job, 'retry requested')
                    self._persist()
                    return dict(job), True
        return None, False

    @staticmethod
    def retry_delay(attempts):
        """Capped exponential backoff with jitter for automatic retries."""
        try:
            attempt = max(1, int(attempts))
        except (TypeError, ValueError):
            attempt = 1
        delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        return delay * random.uniform(0.8, 1.2)

    def schedule_retry(self, job_id, reason=''):
        """Keep a failed job alive and retry it after a bounded backoff.

        The job stays ``pending`` (so the UI can still cancel it) with a
        ``next_attempt_at`` timestamp. Cancelled jobs are never revived.
        """
        with self._lock:
            for job in self.jobs:
                if job['id'] != job_id:
                    continue
                if job.get('status') == 'cancelled':
                    return None
                attempts = int(job.get('attempts', 0)) + 1
                delay = self.retry_delay(attempts)
                job['status'] = 'pending'
                job['failure_reason'] = reason or None
                job['attempts'] = attempts
                job['next_attempt_at'] = time.time() + delay
                job['updated_at'] = _now()
                self._append_log_locked(job, 'auto-retry scheduled',
                                        attempt=attempts,
                                        wait_seconds=round(delay))
                self._persist()
                return dict(job)
        return None

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
    def start_worker(self, poll_interval=2.0, workers=2):
        if not self.config_manager.get_setting('enable_jobs', True):
            logger.info("Job worker disabled by configuration; jobs can still be enqueued")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._threads = []

        def run():
            logger.info("Job worker started")
            while not self._stop.is_set():
                try:
                    job = self._next_pending()
                    if job:
                        downloader = getattr(
                            self.album_manager, 'download_manager', None)
                        context = (downloader if downloader is not None
                                   and hasattr(downloader, 'set_progress_context')
                                   else None)
                        if context:
                            context.set_progress_context(job['id'])
                        try:
                            self._process(job)
                        finally:
                            if context:
                                context.clear_progress_context()
                    else:
                        self._stop.wait(poll_interval)
                except Exception as exc:
                    logger.error("Job worker error: %s", exc, exc_info=True)
                    self._stop.wait(poll_interval)
            logger.info("Job worker stopped")

        for number in range(max(1, int(workers))):
            thread = threading.Thread(
                target=run, name=f'blissful-jobs-{number + 1}', daemon=True)
            self._threads.append(thread)
            thread.start()
        self._thread = self._threads[0]

    def stop_worker(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads = []
        self._thread = None

    @staticmethod
    def _provider_label(source):
        """Human provider name for a yt-dlp source string."""
        text = str(source or '').lower()
        if 'site:music.youtube.com' in text:
            return 'YouTube Music'
        if text.startswith('ytsearch') or 'youtube' in text:
            return 'YouTube'
        if text.startswith('scsearch') or 'soundcloud' in text:
            return 'SoundCloud'
        if text.startswith('bandcamp') or 'bandcamp' in text:
            return 'Bandcamp'
        if text.startswith('dzsearch') or 'deezer' in text:
            return 'Deezer'
        if 'apple' in text:
            return 'Apple Music'
        if 'mixcloud' in text:
            return 'Mixcloud'
        if 'archive.org' in text:
            return 'Archive.org'
        if 'tidal' in text:
            return 'Tidal'
        return 'Source'

    @staticmethod
    def _log_line(message, **details):
        """Build one structured job log entry for the UI snapshot view.

        Returns a dict with the timestamp, phase message and every detail
        field. The UI renders it as a grouped "Job Snapshot" with a
        Download Attempts section; nothing is silently dropped.
        """
        entry = {'ts': datetime.now().strftime('%H:%M:%S')}
        if message and message != 'progress':
            entry['phase'] = message
        for key, value in details.items():
            if key == 'phase' or value is None or value == '':
                continue
            entry[key] = value
        return entry

    def _append_log_locked(self, job, message, **details):
        """Append a log line to a job and mirror it to its parent run.

        Consecutive identical lines (ignoring the timestamp) are skipped
        so a 2-second poll does not fill the log with duplicates.
        """
        entry = self._log_line(message, **details)
        log = job.setdefault('log', [])
        # Ignore the timestamp when comparing consecutive entries so a
        # repeating 2-second poll is not appended again and again.
        def body_of(item):
            if isinstance(item, dict):
                return {k: v for k, v in item.items() if k != 'ts'}
            return item
        if log and body_of(log[-1]) == body_of(entry):
            return
        log.append(entry)
        del log[:-200]
        parent_id = job.get('parent_id')
        if parent_id:
            for parent in self.jobs:
                if parent['id'] == parent_id:
                    plog = parent.setdefault('log', [])
                    plog.append(entry)
                    del plog[:-200]
                    parent['updated_at'] = _now()
                    break

    def append_log(self, job_id, message, **details):
        """Append a line to a job's live log (bounded to 200 lines)."""
        with self._lock:
            for job in self.jobs:
                if job['id'] == job_id:
                    self._append_log_locked(job, message, **details)
                    job['updated_at'] = _now()
                    self._persist()
                    return dict(job)
        return None

    def _mirror_child_progress_locked(self, job):
        """Surface child album track counts on the parent run for the UI bar."""
        parent_id = job.get('parent_id') or job.get('id')
        parent = next((p for p in self.jobs if p.get('id') == parent_id), None)
        if parent is None:
            return
        children = [c for c in self.jobs if c.get('parent_id') == parent_id]
        if not children:
            return
        completed = sum(int((c.get('progress') or {}).get('completed_tracks') or 0)
                        for c in children)
        total = sum(int((c.get('progress') or {}).get('total_tracks') or 0)
                    for c in children)
        if not total:
            return
        parent_progress = dict(parent.get('progress') or {})
        parent_progress['completed_tracks'] = completed
        parent_progress['total_tracks'] = total
        parent['progress'] = parent_progress
        parent['updated_at'] = _now()

    def update_job(self, job_id, **changes):
        """Update an externally-managed job (search runs, etc.)."""
        with self._lock:
            for job in self.jobs:
                if job['id'] == job_id:
                    # Auto-log progress/status transitions so a running
                    # job has a live log without callers doing extra work.
                    progress = changes.get('progress')
                    if isinstance(progress, dict):
                        message = str(progress.get('phase') or 'progress')
                        self._append_log_locked(job, message, **progress)
                    elif 'status' in changes and changes['status'] != job.get('status'):
                        self._append_log_locked(job, 'status: %s' % changes['status'])
                    if changes.get('failure_reason'):
                        self._append_log_locked(job, 'failure',
                                                failure_reason=changes['failure_reason'])
                    job.update(changes)
                    now = _now()
                    job['updated_at'] = now
                    if changes.get('status') == 'running' and not job.get('started_at'):
                        job['started_at'] = now
                    if changes.get('status') in TERMINAL_STATUSES and not job.get('finished_at'):
                        job['finished_at'] = now
                    self._mirror_child_progress_locked(job)
                    self._persist()
                    return dict(job)
        return None

    def _next_pending(self):
        with self._lock:
            now = time.time()
            for job in self.jobs:
                if job.get('status') != 'pending' or \
                        job.get('kind') not in self.managed_kinds:
                    continue
                # Two workers must not download the same album at once.
                if any(other.get('status') == 'running'
                       and other.get('dedupe_key') == job.get('dedupe_key')
                       and other.get('id') != job.get('id')
                       for other in self.jobs):
                    continue
                due = job.get('next_attempt_at')
                if isinstance(due, (int, float)) and due > now:
                    continue
                job.pop('next_attempt_at', None)
                job['status'] = 'running'
                job['started_at'] = job.get('started_at') or _now()
                job['updated_at'] = _now()
                self._persist()
                return dict(job)
        return None

    def _with_download_snapshot(self, job_id, details):
        """Attach the job's current source/attempts to a progress snapshot."""
        merged = dict(details or {})
        downloader = getattr(getattr(self, 'album_manager', None),
                             'download_manager', None)
        if downloader is None or not hasattr(downloader, 'get_download_progress'):
            return merged
        try:
            snap = downloader.get_download_progress(job_id) or {}
        except Exception:
            return merged
        mapping = {
            'source': 'download_source',
            'status': 'download_status',
            'attempts': 'download_attempts',
            'pending': 'download_pending',
            'candidate_index': 'download_candidate_current',
            'candidate_total': 'download_candidate_total',
        }
        for key, name in mapping.items():
            if key in snap:
                merged[name] = snap[key]
        return merged

    def _process(self, job):
        payload = job.get('payload', {})
        logger.info("Processing job %s for %s - %s", job['id'], payload.get('artist'), payload.get('album'))
        self.append_log(job['id'], 'job started',
                        artist=payload.get('artist'),
                        album_title=payload.get('album'))
        try:
            if job.get('kind') == 'album':
                tracks = payload.get('pending_tracks') or payload.get('tracks', [])
                result = self.album_manager.download_album(
                    artist=payload.get('artist', ''),
                    album=payload.get('album', ''),
                    tracks=tracks,
                    target_path=payload.get('target_path', ''),
                    total_tracks=int(job.get('progress_total') or 0) or len(tracks),
                    resume_state=payload.get('resume_state'),
                    should_cancel=lambda: (
                        (self.get_job(job['id']) or {}).get('status') == 'cancelled'),
                    retry_delay=self.retry_delay,
                    on_progress=lambda **details:
                        self.update_job(job['id'], progress=self._with_download_snapshot(job['id'], details)),
                )
            else:
                result = {'success': False, 'error': f"Unknown job type: {job.get('kind')}"}
            if result.get('cancelled'):
                status, reason = 'cancelled', 'cancelled by user'
            elif result.get('pending_tracks'):
                # Some tracks failed this round; requeue this job so the
                # single worker can serve other jobs and retries in between.
                status, reason = 'pending', None
            else:
                status = 'succeeded' if result.get('success') else 'failed'
            failures = [{
                'title': track.get('title'),
                'error': track.get('error'),
                'attempts': track.get('attempts') or [],
            } for track in (result.get('tracks') or [])
                if isinstance(track, dict) and not track.get('success')
                and (track.get('error') or track.get('attempts'))]
            if result.get('success'):
                reason = None
            elif failures:
                reason = '; '.join(
                    f"{item.get('title') or 'track'}: {item.get('error')}"
                    for item in failures[:5])
            else:
                reason = result.get('error', 'Download failed')
        except Exception as exc:
            logger.error("Job %s failed: %s", job['id'], exc, exc_info=True)
            status, reason, result = 'failed', str(exc), None

        with self._lock:
            for current in self.jobs:
                if current['id'] == job['id']:
                    if current.get('status') == 'cancelled':
                        status = 'cancelled'
                        reason = 'cancelled by user'
                    current['status'] = status
                    current['failure_reason'] = reason
                    completed = (result or {}).get(
                        'completed_tracks', (result or {}).get('successful'))
                    total = (result or {}).get('total_tracks')
                    current['result'] = {
                        'successful': (result or {}).get('successful'),
                        'failed': (result or {}).get('failed'),
                        'total_tracks': total,
                        'completed_tracks': completed,
                        'rounds': (result or {}).get('rounds'),
                        'cancelled': bool((result or {}).get('cancelled')),
                        'failures': failures[:50],
                    } if result else None
                    if isinstance(completed, int) and isinstance(total, int):
                        current['progress'] = {
                            'phase': 'complete' if status == 'succeeded' else (
                                'cancelled' if status == 'cancelled' else 'retrying'),
                            'completed_tracks': completed,
                            'current_track': completed,
                            'total_tracks': total,
                        }
                    if status == 'pending':
                        embedded = dict(current.get('payload') or {})
                        embedded['pending_tracks'] = result.get('pending_tracks')
                        embedded['resume_state'] = result.get('resume_state')
                        current['payload'] = embedded
                        current['next_attempt_at'] = time.time() + self.retry_delay(
                            (result or {}).get('rounds', 1))
                        current.pop('finished_at', None)
                    else:
                        current['finished_at'] = _now()
                    current['updated_at'] = _now()
                    break
            self._persist()
        self.append_log(job['id'],
                        'retry round scheduled' if status == 'pending'
                        else 'job finished', status=status,
                        completed=(result or {}).get('completed_tracks')
                        if isinstance(result, dict) else None,
                        total=(result or {}).get('total_tracks')
                        if isinstance(result, dict) else None,
                        rounds=(result or {}).get('rounds')
                        if isinstance(result, dict) else None,
                        imported=(result or {}).get('successful') if isinstance(result, dict) else None,
                        failure_reason=reason,
                        failures=failures[:5])
        logger.info("Job %s finished: %s", job['id'], status)
        if status == 'failed' and job.get('kind') in self.managed_kinds:
            self.schedule_retry(job['id'], reason)

"""Wanted-item search and stale-torrent cleanup for Blissful.

This module follows the manager-driven style of :mod:`extend.failed_imports`:
it never talks HTTP itself, it only uses the client/managers handed to its
constructor.  It reads the full wanted/missing list, finds stale torrents in
Lidarr's queue, optionally re-searches their albums and removes the queue
items *only after* the missing tracks are confirmed imported.  A JSON state
file records handled albums/queue items so a stale torrent is never cleaned
twice.

Public interface::

    WantedSearchService(config_manager, lidarr_client_class,
                        state_path='/app/downloads/wanted-search-state.json')

    service.get_wanted()
    service.get_stale()
    service.search(album_ids=None, apply=False)
    service.cleanup_stale(record_ids=None, apply=False, wait_minutes=10)
    service.run_scheduled(apply=True)
    service.start_scheduler(poll_seconds=30) / service.stop_scheduler()
    service.reset_state()
"""

import json
import os
import threading
import time
from pathlib import Path


# Queue error text that Lidarr emits for a torrent Blissful can repair.
UNHEALTHY_PATTERNS = (
    'stalled with no connections',
    'no files found are eligible',
    'unable to communicate',
    'download client',
    'downloading metadata',
    'stalled',
)

_COMMAND_TERMINAL = {
    'completed', 'complete', 'succeeded', 'success',
    'failed', 'error', 'cancelled', 'canceled', 'timeout',
}
_COMMAND_OK = {'completed', 'complete', 'succeeded', 'success'}

_POLL_INTERVAL_S = 2
_COMMAND_TIMEOUT_S = 180
_MAX_WANTED_PAGES = 200


def _lower(value):
    return str(value or '').lower()


def _record_text(record):
    """Build the searchable error text for a Lidarr queue record."""
    if not isinstance(record, dict):
        return ''
    parts = [str(record.get('errorMessage') or ''), str(record.get('text') or '')]
    messages = record.get('statusMessages') or []
    if isinstance(messages, (dict, str)):
        messages = [messages]
    for message in messages:
        if isinstance(message, dict):
            parts.append(str(message.get('title') or ''))
            parts.append(str(message.get('message') or ''))
            parts.append(str(message.get('text') or ''))
        else:
            parts.append(str(message or ''))
    return ' '.join(parts)


def _safe_label(record):
    """A plain, bounded, human-readable label - never a path or secret."""
    album = str((record or {}).get('albumTitle') or '')
    title = str((record or {}).get('title') or '')
    if album and title:
        label = '%s - %s' % (album, title)
    else:
        label = album or title or 'Wanted album %s' % ((record or {}).get('id') or '')
    # Drop control characters; keep ordinary whitespace only.
    label = ''.join(ch for ch in label if ch >= ' ' or ch in '\t')
    return label.strip()[:200]


class WantedSearchService:
    """Search wanted albums and clean up stale torrents in Lidarr's queue."""

    def __init__(self, config_manager, lidarr_client_class,
                 state_path='/app/downloads/wanted-search-state.json',
                 gapfill=None):
        self.config_manager = config_manager
        self.lidarr_client_class = lidarr_client_class
        self.state_path = Path(state_path)
        self.gapfill = gapfill
        self._client = None
        self._stop_event = None
        self._scheduler_thread = None
        self._last_scheduled = 0.0
        self._active = None
        self._last_activity = None
        self._active_lock = threading.Lock()
        self._run_lock = threading.Lock()

    # ------------------------------------------------------------ gap fill
    def _prefer_gapfill(self):
        return self._config().get('prefer_blissful_for_stale', True) is not False

    def _gapfill_album(self, album_id, apply=True):
        """Hand an album to Blissful's own download/tag/link engine."""
        if self.gapfill is None:
            return {'status': 'failed',
                    'reason': 'Blissful gap-fill engine unavailable'}
        engine = getattr(self.gapfill, 'gapfill_album', None)
        if callable(engine):
            def progress(phase, **details):
                self._set_active(phase=phase, album=album_id, **details)

            return engine(album_id, apply=apply, source='stale-cleanup',
                          progress=progress)
        if callable(self.gapfill):
            return self.gapfill(album_id, apply=apply)
        return {'status': 'failed', 'reason': 'Blissful gap-fill engine unavailable'}

    # --------------------------------------------------------- single flight
    def _busy_report(self):
        return {
            'success': False,
            'already_running': True,
            'error': 'A wanted search or cleanup is already running',
            'active': self.get_active(),
        }

    def search(self, album_ids=None, apply=False) -> dict:
        """Public search entry point; only one run may be active at a time."""
        if not self._run_lock.acquire(blocking=False):
            return self._busy_report()
        self._set_active(kind='search', phase='preparing', started_at=time.time(),
                         apply=bool(apply))
        try:
            return self._search_impl(album_ids=album_ids, apply=apply)
        finally:
            if self.get_active() is not None:
                self._finish_active('completed')
            self._run_lock.release()

    def cleanup_stale(self, record_ids=None, apply=False, wait_minutes=10) -> dict:
        """Public cleanup entry point; only one run may be active at a time."""
        if not self._run_lock.acquire(blocking=False):
            return self._busy_report()
        self._set_active(kind='cleanup', phase='starting', started_at=time.time(),
                         apply=bool(apply))
        try:
            return self._cleanup_impl(record_ids=record_ids, apply=apply,
                                      wait_minutes=wait_minutes)
        finally:
            if self.get_active() is not None:
                self._finish_active('failed')
            self._run_lock.release()

    # ------------------------------------------------------------- progress
    def get_active(self):
        """Snapshot of the in-flight run (safe to read from the web thread)."""
        with self._active_lock:
            return dict(self._active) if self._active else None

    def get_last_activity(self):
        with self._active_lock:
            return dict(self._last_activity) if self._last_activity else None

    def _set_active(self, **updates):
        with self._active_lock:
            if self._active is None:
                self._active = {}
            self._active.update(updates)
            self._active['updated_at'] = time.time()
            return dict(self._active)

    def _finish_active(self, status):
        with self._active_lock:
            if self._active:
                self._active.update(status=status, finished_at=time.time())
                self._last_activity = dict(self._active)
            self._active = None

    # ------------------------------------------------------------------ client
    def _get_client(self):
        """Instantiate the Lidarr client once from app configuration."""
        if self._client is not None:
            return self._client
        factory = self.lidarr_client_class
        cfg = self._config()
        url = cfg.get('lidarr_url') or ''
        key = cfg.get('lidarr_api_key') or ''
        markers = ('get_all_queue_records', 'get_wanted_missing',
                   'post_command', 'get_album_tracks', 'get_command')
        try:
            if isinstance(factory, type):
                try:
                    self._client = factory(url=url, api_key=key)
                except TypeError:
                    try:
                        self._client = factory(url, key)
                    except TypeError:
                        self._client = factory()
            elif any(hasattr(factory, name) for name in markers):
                self._client = factory
            else:
                try:
                    self._client = factory(url, key)
                except TypeError:
                    try:
                        self._client = factory(url=url, api_key=key)
                    except TypeError:
                        self._client = factory()
        except Exception:
            self._client = None
        return self._client

    def _config(self):
        try:
            return self.config_manager.get_config() or {}
        except Exception:
            return {}

    def _safe_error(self, exc):
        """Truncate an exception string and scrub the configured API key."""
        text = str(exc)
        key = self._config().get('lidarr_api_key') or ''
        if key:
            text = text.replace(str(key), '***')
        return text[:300]

    # ------------------------------------------------------------------- state
    def _load_state(self):
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    albums = data.get('albums')
                    last_run = data.get('last_run')
                    data['albums'] = albums if isinstance(albums, dict) else {}
                    data['last_run'] = last_run if isinstance(last_run, dict) else {}
                    return data
        except Exception:
            pass
        return {'albums': {}, 'last_run': {}}

    def _save_state(self, state):
        try:
            state.setdefault('albums', {})
            state.setdefault('last_run', {})
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + '.tmp')
            tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            tmp.replace(self.state_path)
        except Exception:
            # A state write failure must not turn a successful run into an error.
            pass

    def reset_state(self):
        """Delete the state file so every album is eligible again."""
        try:
            if self.state_path.exists():
                self.state_path.unlink()
        except OSError:
            pass
        self._last_scheduled = 0.0
        return True

    # -------------------------------------------------------------- pagination
    @staticmethod
    def _normalize_page(data):
        """Return ``(records, total_or_None)`` from a client page response."""
        if data is None:
            return [], None
        if hasattr(data, 'json') and callable(data.json):
            try:
                data = data.json()
            except Exception:
                return [], None
        if isinstance(data, list):
            return data, None
        if isinstance(data, dict):
            records = data.get('records')
            if records is None:
                records = data.get('items') or data.get('data') or []
            total = data.get('totalRecords')
            if total is None:
                total = data.get('total') or data.get('totalItems')
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            return (records if isinstance(records, list) else []), total
        return [], None

    @staticmethod
    def _call_page(fn, page, page_size, path=None):
        """Try common call signatures for a paged client method."""
        variants = [
            ((), {'page': page, 'page_size': page_size}),
            ((), {'page': page, 'pageSize': page_size}),
            ((page, page_size), {}),
            ((page,), {}),
            ((), {}),
        ]
        for args, kwargs in variants:
            try:
                return fn(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    def _fetch_wanted_page(self, client, page, page_size):
        """Fetch one wanting/missing page using whatever the client offers."""
        path = '/api/v1/wanted/missing'
        for name in ('get_wanted_missing', 'get_wanted', 'get_wanted_albums',
                     'get_missing_wanted'):
            fn = getattr(client, name, None)
            if callable(fn):
                data = self._call_page(fn, page, page_size, path)
                if data is not None:
                    return data
        # Fall back to a generic GET helper on the client.
        params = {'page': page, 'pageSize': page_size}
        for name in ('get', 'get_json', 'request'):
            fn = getattr(client, name, None)
            if not callable(fn):
                continue
            for args, kwargs in (
                ((path,), {'params': params}),
                ((path,), params),
            ):
                try:
                    data = fn(*args, **kwargs)
                except TypeError:
                    continue
                except Exception:
                    return None
                if data is not None:
                    return data
        return None

    # ------------------------------------------------------------------ wanted
    def get_wanted(self, page_size=200) -> list:
        """Collect every record from ``GET /api/v1/wanted/missing``."""
        try:
            page_size = max(1, int(page_size))
        except (TypeError, ValueError):
            page_size = 200
        client = self._get_client()
        results = []
        seen = set()
        page = 1
        while page <= _MAX_WANTED_PAGES:
            data = self._fetch_wanted_page(client, page, page_size)
            if data is None:
                break
            records, total = self._normalize_page(data)
            if not records:
                break
            added = 0
            for record in records:
                if not isinstance(record, dict):
                    continue
                key = record.get('id')
                if key is None:
                    key = json.dumps(record, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                artist_obj = record.get('artist') or {}
                artist_name = str(artist_obj.get('artistName') or '')
                secondary = record.get('secondaryTypes') or []
                album_type = str(record.get('albumType') or '')
                results.append({
                    'id': record.get('id'),
                    'albumId': record.get('id') or record.get('albumId'),
                    'artistId': record.get('artistId'),
                    'artist': artist_name,
                    'title': str(record.get('title') or record.get('albumTitle') or ''),
                    'albumType': album_type,
                    'secondaryTypes': [str(t) for t in secondary],
                    'releaseDate': str(record.get('releaseDate') or ''),
                    'monitored': bool(record.get('monitored', False)),
                    'label': _safe_label(record),
                })
                added += 1
            if added == 0:
                break
            if total is not None and len(seen) >= total:
                break
            if total is None and len(records) < page_size:
                break
            page += 1
        return results

    # ------------------------------------------------------------------- stale
    def get_stale(self) -> list:
        """Return projected queue records whose error text looks unhealthy."""
        client = self._get_client()
        if client is None:
            return []
        try:
            queue = client.get_all_queue_records(page_size=200)
        except Exception:
            queue = []
        if isinstance(queue, dict):
            queue = queue.get('records') or []
        if not isinstance(queue, list):
            queue = []

        ordered = []
        by_download = {}
        for record in queue:
            if not isinstance(record, dict):
                continue
            text = _lower(_record_text(record))
            if not any(pattern in text for pattern in UNHEALTHY_PATTERNS):
                continue
            projected = {
                'id': record.get('id'),
                'albumId': record.get('albumId'),
                'downloadId': record.get('downloadId'),
                'title': str(record.get('title') or ''),
                'errorMessage': str(record.get('errorMessage') or ''),
                'trackedDownloadState': record.get('trackedDownloadState') or '',
            }
            download_id = record.get('downloadId')
            if download_id:
                if download_id in by_download:
                    # Keep one record per download, preferring one with an album.
                    index = by_download[download_id]
                    if not ordered[index].get('albumId') and projected.get('albumId'):
                        ordered[index] = projected
                    continue
                by_download[download_id] = len(ordered)
            ordered.append(projected)
        return ordered

    # ------------------------------------------------------------------ search
    def _search_impl(self, album_ids=None, apply=False) -> dict:
        """Search all wanted albums or a selected subset (dry-run by default)."""
        if self._config().get('wanted_search_enabled') is False:
            return {'success': False, 'error': 'Wanted search is disabled'}

        apply = bool(apply)
        ids = []
        for value in (album_ids or []):
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        mode = 'selected' if ids else 'all'
        report = {
            'success': True,
            'mode': mode,
            'count': len(ids),
            'applied': apply,
            'command_id': None,
            'note': '',
        }
        if not apply:
            report['note'] = 'dry run - no command posted'
            return report

        client = self._get_client()
        if client is None:
            report['success'] = False
            report['error'] = 'Lidarr client unavailable'
            return report
        try:
            if ids:
                response = client.post_command('AlbumSearch', albumIds=ids)
            else:
                response = client.post_command('MissingAlbumSearch')
        except Exception as exc:
            report['success'] = False
            report['error'] = self._safe_error(exc)
            return report

        command_id = (response or {}).get('id') if isinstance(response, dict) else None
        if not command_id:
            report['success'] = False
            report['error'] = 'Lidarr did not return a command id'
            return report
        report['command_id'] = command_id
        return report

    # ----------------------------------------------------------------- cleanup
    @staticmethod
    def _missing_count(tracks):
        if not isinstance(tracks, list):
            return 0
        return sum(1 for track in tracks
                   if isinstance(track, dict) and track.get('hasFile') is False)

    def _poll_command(self, client, command_id):
        deadline = time.monotonic() + _COMMAND_TIMEOUT_S
        last = {}
        while time.monotonic() < deadline:
            try:
                last = client.get_command(command_id) or {}
            except Exception as exc:
                return {'status': 'failed', 'message': self._safe_error(exc)}
            if not isinstance(last, dict):
                last = {}
            if _lower(last.get('status')) in _COMMAND_TERMINAL:
                return last
            time.sleep(_POLL_INTERVAL_S)
        return {'status': 'timeout', 'message': 'command poll timeout'}

    def _wait_for_import(self, client, album_id, timeout_s):
        """Wait until no track of the album is still missing its file."""
        deadline = time.monotonic() + timeout_s
        last_error = ''
        while time.monotonic() < deadline:
            try:
                tracks = client.get_album_tracks(album_id) or []
                if not isinstance(tracks, list):
                    tracks = []
            except Exception as exc:
                last_error = self._safe_error(exc)
                time.sleep(_POLL_INTERVAL_S)
                continue
            if self._missing_count(tracks) == 0:
                return True, ''
            time.sleep(_POLL_INTERVAL_S)
        return False, (last_error or
                       'import not complete for album %s after %s minutes'
                       % (album_id, int(timeout_s // 60)))

    @staticmethod
    def _empty_cleanup_report(applied=False):
        report = {
            'applied': bool(applied),
            'scanned': [],
            'searched': [],
            'imported': [],
            'deleted': [],
            'kept': [],
            'skipped': [],
            'errors': [],
        }
        report['counts'] = {key: 0 for key in
                            ('scanned', 'searched', 'imported', 'deleted',
                             'kept', 'skipped', 'errors')}
        return report

    def _cleanup_impl(self, record_ids=None, apply=False, wait_minutes=10) -> dict:
        """Re-search and remove stale queue items once their files are imported.

        One bad album never aborts the rest; it is recorded in ``skipped`` or
        ``errors`` and the loop continues.  Dry runs never post commands,
        never delete queue items and never write state.
        """
        apply = bool(apply)
        report = self._empty_cleanup_report(apply)
        self._set_active(kind='cleanup', apply=apply, phase='scanning',
                         started_at=time.time(), scanned=0, searched=0,
                         imported=0, deleted=0, kept=0, skipped=0, errors=0)
        state = self._load_state()
        albums_state = state.get('albums')
        if not isinstance(albums_state, dict):
            albums_state = {}
            state['albums'] = albums_state

        stale = self.get_stale()
        if record_ids is not None:
            selected = {str(value) for value in record_ids}
            stale = [record for record in stale
                     if str(record.get('id')) in selected]
        report['scanned'] = list(stale)
        self._set_active(phase='searching', scanned=len(stale))

        def already_recorded(album_id):
            if str(album_id) in albums_state:
                return True
            for entry in albums_state.values():
                if isinstance(entry, dict) and entry.get('album') is not None \
                        and str(entry.get('album')) == str(album_id):
                    return True
            return False

        by_album = {}
        for record in stale:
            album_id = record.get('albumId')
            if not album_id:
                report['skipped'].append({'id': record.get('id'),
                                          'reason': 'no album id'})
                continue
            by_album.setdefault(album_id, []).append(record)

        client = self._get_client()
        if client is None:
            report['errors'].append('Lidarr client unavailable')
            report['counts'] = {key: len(report[key]) for key in
                                ('scanned', 'searched', 'imported', 'deleted',
                                 'kept', 'skipped', 'errors')}
            self._finish_active('failed')
            return report
        try:
            wait_s = max(1, int(float(wait_minutes)) * 60)
        except (TypeError, ValueError):
            wait_s = 600

        for album_id, records in by_album.items():
            title = next((str(record.get('title') or '') for record in records
                          if record.get('title')), '')
            try:
                if already_recorded(album_id):
                    report['skipped'].append({'album': album_id,
                                              'reason': 'already recorded in state'})
                    continue
                baseline = client.get_album_tracks(album_id) or []
                baseline_missing = self._missing_count(baseline)

                if not apply:
                    report['searched'].append({
                        'album': album_id,
                        'title': title,
                        'baseline_missing': baseline_missing,
                        'note': 'dry run - no command posted',
                    })
                    continue

                if self._prefer_gapfill():
                    # Stale items are stuck precisely because Lidarr search
                    # failed; use Blissful's own yt-dlp bridge instead.
                    self._set_active(phase='gap-filling with Blissful',
                                     album=album_id,
                                     searched=len(report['searched']))
                    try:
                        gap = self._gapfill_album(album_id, apply=True) or {}
                    except Exception as exc:
                        gap = {'status': 'failed', 'reason': self._safe_error(exc)}
                    status = _lower(str(gap.get('status') or ''))
                    report['searched'].append({
                        'album': album_id,
                        'title': title,
                        'baseline_missing': baseline_missing,
                        'engine': 'blissful',
                        'status': status,
                        'reason': str(gap.get('reason') or '')[:200],
                    })
                    if status not in ('succeeded', 'success'):
                        reason = str(gap.get('reason') or 'gap-fill did not succeed')
                        report['errors'].append(reason[:300])
                        report['skipped'].append({'album': album_id,
                                                  'reason': reason[:200]})
                        report['kept'].extend(record.get('id') for record in records)
                        continue
                else:
                    try:
                        response = client.post_command('AlbumSearch',
                                                       albumIds=[int(album_id)])
                    except Exception as exc:
                        report['errors'].append(self._safe_error(exc))
                        report['skipped'].append({'album': album_id,
                                                  'reason': 'AlbumSearch failed'})
                        continue
                    command_id = ((response or {}).get('id')
                                  if isinstance(response, dict) else None)
                    if not command_id:
                        report['errors'].append(
                            'AlbumSearch returned no command id for album %s' % album_id)
                        report['skipped'].append({'album': album_id,
                                                  'reason': 'no command id'})
                        continue
                    report['searched'].append({
                        'album': album_id,
                        'title': title,
                        'baseline_missing': baseline_missing,
                        'engine': 'lidarr',
                        'command_id': command_id,
                    })
                    self._set_active(phase='waiting for import', album=album_id,
                                     searched=len(report['searched']))

                    command = self._poll_command(client, command_id)
                    status = _lower(command.get('status'))
                    if status and status not in _COMMAND_OK:
                        report['errors'].append(
                            'AlbumSearch command %s status %s' % (command_id, status))
                        report['kept'].extend(record.get('id') for record in records)
                        continue

                    imported, error = self._wait_for_import(client, album_id, wait_s)
                    if not imported:
                        if error:
                            report['errors'].append(error)
                        report['kept'].extend(record.get('id') for record in records)
                        continue

                report['imported'].append({
                    'album': album_id,
                    'title': title,
                    'baseline_missing': baseline_missing,
                    'engine': 'blissful' if self._prefer_gapfill() else 'lidarr',
                })
                self._set_active(phase='removing stale queue entry',
                                 imported=len(report['imported']))
                for record in records:
                    record_id = record.get('id')
                    try:
                        client.delete_queue_item(
                            record_id, delete_files=False,
                            add_import_exclusion=False)
                    except Exception as exc:
                        report['errors'].append(self._safe_error(exc))
                        report['kept'].append(record_id)
                        continue
                    report['deleted'].append(record_id)
                    albums_state[str(record_id)] = {
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'album': album_id,
                        'title': title,
                        'status': 'deleted',
                    }
                self._set_active(deleted=len(report['deleted']),
                                 kept=len(report['kept']),
                                 errors=len(report['errors']),
                                 skipped=len(report['skipped']))
            except Exception as exc:
                # Never let one bad album abort the whole cleanup run.
                report['errors'].append(self._safe_error(exc))
                report['skipped'].append({'album': album_id,
                                          'reason': 'unexpected error'})

        if apply and report['deleted']:
            self._save_state(state)
        report['counts'] = {key: len(report[key]) for key in
                            ('scanned', 'searched', 'imported', 'deleted',
                             'kept', 'skipped', 'errors')}
        self._finish_active('completed' if not report['errors'] else 'completed with errors')
        return report

    # ---------------------------------------------------------------- scheduler
    def _last_run_timestamp(self):
        last_run = self._load_state().get('last_run') or {}
        stamp = last_run.get('timestamp') if isinstance(last_run, dict) else None
        if stamp:
            try:
                return time.mktime(time.strptime(str(stamp), '%Y-%m-%dT%H:%M:%S'))
            except (TypeError, ValueError):
                pass
        return 0.0

    def _interval_hours(self):
        try:
            value = float(self._config().get('stale_cleanup_interval_hours', 6) or 6)
        except (TypeError, ValueError):
            value = 6.0
        return max(0.01, value)

    def start_scheduler(self, poll_seconds=30):
        """Start a daemon thread that runs cleanup at most once per interval."""
        try:
            poll = max(0.1, float(poll_seconds))
        except (TypeError, ValueError):
            poll = 30.0

        stop_event = self._stop_event or threading.Event()
        self._stop_event = stop_event
        stop_event.clear()
        self._last_scheduled = max(self._last_scheduled,
                                   self._last_run_timestamp())

        def loop():
            while not stop_event.wait(poll):
                try:
                    if self._config().get('stale_cleanup_enabled') is False:
                        continue
                    now = time.time()
                    if now - self._last_scheduled < self._interval_hours() * 3600:
                        continue
                    self._last_scheduled = now
                    self.run_scheduled(apply=True)
                except Exception:
                    # A scheduler tick must never kill the thread.
                    continue

        thread = threading.Thread(target=loop, name='wanted-search-scheduler',
                                  daemon=True)
        thread.start()
        self._scheduler_thread = thread
        return thread

    def stop_scheduler(self):
        """Signal the scheduler thread to stop and wait briefly for it."""
        if self._stop_event is not None:
            self._stop_event.set()
        thread = self._scheduler_thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=2.0)
        self._scheduler_thread = None
        return True

    def run_scheduled(self, apply=True) -> dict:
        """Run stale cleanup and record ``last_run`` metadata in state."""
        if self._config().get('stale_cleanup_enabled') is False:
            report = self._empty_cleanup_report(False)
            report.update(success=True, noop=True, disabled=True,
                          reason='Stale cleanup is disabled')
            return report

        report = self.cleanup_stale(apply=bool(apply))
        if report.get('already_running'):
            return report
        state = self._load_state()
        state['last_run'] = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'applied': bool(apply),
            'scanned': len(report.get('scanned') or []),
            'searched': len(report.get('searched') or []),
            'imported': len(report.get('imported') or []),
            'deleted': len(report.get('deleted') or []),
            'kept': len(report.get('kept') or []),
            'skipped': len(report.get('skipped') or []),
            'errors': len(report.get('errors') or []),
        }
        self._save_state(state)
        report['last_run'] = state['last_run']
        return report

"""Native recovery of Lidarr failed/unhealthy imports for Blissful.

Port of the proven external bridge ``lidarr-failed-to-blissful.py``.  The
bridge used to (a) page Lidarr's queue, (b) pick only *unhealthy* download
failures it could actually fix, (c) re-download the missing tracks through
Blissful using Lidarr's own naming template, (d) verify the placed files and
(e) hand them back to Lidarr with a single ``ManualImport`` command.  A JSON
state file prevents an album from being sent twice.

This module is deliberately manager-driven: it never talks HTTP itself and
never duplicates the naming renderer.  It only uses the client/managers that
are handed to its constructor.

Public interface::

    FailedImportsRetry(config_manager, lidarr_client_class, download_manager,
                       album_manager, job_manager,
                       state_path='/app/downloads/failed-imports-state.json',
                       host_prefix=None)

    report = FailedImportsRetry(...).run(album_id=None, apply=False, reset=False)
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

try:  # package import (normal case)
    from .naming import render_track_filename
except ImportError:  # pragma: no cover - direct execution / flat import
    from naming import render_track_filename  # type: ignore


# Text Lidarr emits for a download problem Blissful can actually repair.
UNHEALTHY_PATTERNS = (
    'stalled with no connections',
    'no files found are eligible',
    'unable to communicate',
    'download client',
)

# Rejections that mean "there is nothing to link into" - report, never fix.
UNSUPPORTED_PATTERNS = (
    'sequence contains no matching element',
    'album match is not close enough',
    'has missing tracks',
)

# ffprobe tag aliases for the seven mandatory id3 frames.  Different ffmpeg
# builds spell a few of these differently (``disc`` vs ``discnumber``, etc.).
_REQUIRED_TAGS = {
    'title': ('title', 'titles', 'TIT2'),
    'artist': ('artist', 'artists', 'TPE1'),
    'album_artist': ('album_artist', 'albumartist', 'album artist', 'TPE2'),
    'album': ('album', 'TALB'),
    'track': ('track', 'tracknumber', 'TRCK'),
    'disc': ('disc', 'discnumber', 'disk', 'TPOS'),
    'date': ('date', 'year', 'TDRC', 'TYER'),
}

_JOB_TIMEOUT_S = 360          # ~6 minutes, as specified
_COMMAND_TIMEOUT_S = 180
_POLL_INTERVAL_S = 2
# 'cancelled' is terminal: a user-cancelled (or deleted) download job must
# never leave cleanup polling until the 15-minute timeout.
_JOB_TERMINAL = {'succeeded', 'failed', 'complete', 'completed', 'error',
                'cancelled', 'canceled'}
_COMMAND_TERMINAL = {'completed', 'failed', 'complete', 'error'}

_DEFAULT_STANDARD_FORMAT = '{track:00} - {title}'
_DEFAULT_MULTI_FORMAT = '{disc:00}-{track:00} - {title}'


def _sanitize_token(value):
    """Sanitize a *single* template value, never the rendered whole string.

    Removing path separators from the rendered template would destroy the
    directory structure Lidarr encodes in ``standardTrackFormat``.  We only
    clean the values we inject into the context and leave ``/`` untouched.
    ``&`` is preserved so combined-file names survive verbatim.
    """
    return re.sub(r'[\\/:*?"<>|]', '', str(value)).strip()


def _record_text(record):
    """Build the searchable error text for a queue record."""
    parts = [str((record or {}).get('errorMessage') or '')]
    messages = (record or {}).get('statusMessages') or []
    if isinstance(messages, dict):
        messages = [messages]
    for message in messages:
        if isinstance(message, dict):
            parts.append(str(message.get('title') or message.get('message') or ''))
        else:
            parts.append(str(message or ''))
    return ' '.join(parts)


def _lower(value):
    return str(value or '').lower()


class FailedImportsRetry:
    """Retry Lidarr's failed imports through Blissful's native pipeline."""

    def __init__(self, config_manager, lidarr_client_class, download_manager,
                 album_manager, job_manager,
                 state_path='/app/downloads/failed-imports-state.json',
                 host_prefix=None):
        self.config_manager = config_manager
        self.lidarr_client_class = lidarr_client_class
        self.download_manager = download_manager
        self.album_manager = album_manager
        self.job_manager = job_manager
        self.state_path = Path(state_path)
        self.host_prefix = host_prefix
        self._client = None

    # ------------------------------------------------------------------ client
    def _get_client(self):
        """Instantiate the Lidarr client once from the app configuration."""
        if self._client is not None:
            return self._client
        factory = self.lidarr_client_class
        if isinstance(factory, type):
            cfg = {}
            try:
                cfg = self.config_manager.get_config() or {}
            except Exception:
                cfg = {}
            url = cfg.get('lidarr_url') or ''
            key = cfg.get('lidarr_api_key') or ''
            try:
                self._client = factory(url=url, api_key=key)
            except TypeError:
                self._client = factory(url, key)
        elif hasattr(factory, 'get_all_queue_records'):
            self._client = factory
        else:
            cfg = {}
            try:
                cfg = self.config_manager.get_config() or {}
            except Exception:
                cfg = {}
            self._client = factory(cfg.get('lidarr_url') or '',
                                   cfg.get('lidarr_api_key') or '')
        return self._client

    def _config(self):
        try:
            return self.config_manager.get_config() or {}
        except Exception:
            return {}

    # ------------------------------------------------------------------- state
    def _load_state(self):
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_state(self, state):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + '.tmp')
            tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            tmp.replace(self.state_path)
        except Exception:
            # A state write failure must not turn a successful import into an
            # exception; the report still records what happened this run.
            pass

    @staticmethod
    def _album_report(aid, title='', status='', reason='', missing=0,
                      sent=0, imported=0):
        return {
            'id': aid,
            'title': title or '',
            'status': status,
            'reason': reason or '',
            'missing': missing,
            'sent': sent,
            'imported': imported,
        }

    @staticmethod
    def _empty_report(queue_total=0, failures=0, applied=False, reset=False):
        report = {
            'queue_total': queue_total,
            'failures': failures,
            'unsupported': [],
            'albums': [],
            'applied': bool(applied),
        }
        if reset:
            report['reset'] = True
        return report

    # ------------------------------------------------------------------- paths
    def _host_path(self, lidarr_path):
        """Translate a Lidarr-view path to the path visible to this process."""
        path = str(lidarr_path or '')
        if self.host_prefix and path.startswith('/media/Music'):
            return str(self.host_prefix).rstrip('/') + path[len('/media/Music'):]
        # Fall back to Blissful's configured mapping (micro path -> Lidarr path).
        mapping = self._config().get('lidarr_path_mapping') or {}
        if isinstance(mapping, dict):
            for micro, lidarr in mapping.items():
                if lidarr and path.startswith(str(lidarr)):
                    return path.replace(str(lidarr), str(micro), 1)
        return path

    @staticmethod
    def _render_target(template, context, artist_path, extension='mp3'):
        """Render a Lidarr-view host path from a naming template.

        ``naming.render_track_filename`` is the single source of truth for
        token rendering.  We pass a context whose values are already
        sanitized and *no* whole-string sanitizer, so directory separators in
        the template are preserved.
        """
        try:
            rendered = render_track_filename(template, context)
        except Exception:
            rendered = ''
        rendered = str(rendered or '')
        # Defensive cleanups; the parent naming.py also drops empty year
        # groups, but repeating it here is harmless and keeps us robust.
        rendered = re.sub(r'\(\s*\)', '', rendered)
        rendered = re.sub(r'\s+/', '/', rendered)
        rendered = re.sub(r'/{2,}', '/', rendered)
        rendered = re.sub(r'[ \t]{2,}', ' ', rendered)
        rendered = rendered.strip().strip('/')
        ext = str(extension or 'mp3').strip()
        if ext and not ext.startswith('.'):
            ext = '.' + ext
        base = str(artist_path or '').rstrip('/')
        if rendered:
            return base + '/' + rendered + ext
        return base + ext

    # ---------------------------------------------------------------- verification
    def _ffprobe(self, path):
        """Return ffprobe's JSON for *path*, or ``None`` if unavailable."""
        candidates = []
        env_binary = os.environ.get('FFPROBE_BIN')
        if env_binary:
            candidates.append(env_binary)
        candidates.extend((
            'ffprobe',
            '/usr/bin/ffprobe',
            '/usr/local/bin/ffprobe',
        ))
        for binary in candidates:
            try:
                result = subprocess.run(
                    [binary, '-v', 'error', '-show_format', '-of', 'json', path],
                    capture_output=True, text=True, timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode != 0:
                return None
            try:
                return json.loads(result.stdout)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _duration_ok(actual, expected_ms):
        """True when actual seconds are within 10% of the expected Lidarr ms."""
        try:
            expected = float(expected_ms or 0) / 1000.0
        except (TypeError, ValueError):
            return True  # unknown expectation: nothing to compare against
        if expected <= 0:
            return True  # no expectation to compare against
        if actual is None:
            return False  # an unverifiable file must never be linked
        return abs(actual - expected) / expected <= 0.10

    @staticmethod
    def _tags_ok(tags, require_date=True):
        if not isinstance(tags, dict):
            return False
        lowered = {str(k).strip().lower(): v for k, v in tags.items()}
        for name, aliases in _REQUIRED_TAGS.items():
            if name == 'date' and not require_date:
                continue
            if not any(lowered.get(alias) not in (None, '') for alias in aliases):
                return False
        return True

    @staticmethod
    def _delete_file(path):
        try:
            os.unlink(path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ releases
    @staticmethod
    def _monitored_release_id(album, tracks):
        """Pick the monitored release with the largest track count.

        Lidarr's track API returns ``albumReleaseId: null``; the authoritative
        per-release track counts live on ``album['releases']``.
        """
        releases = (album or {}).get('releases') or []
        candidates = [r for r in releases if isinstance(r, dict) and
                      (r.get('monitored') is True or r.get('Monitored') is True)]
        if not candidates:
            return None

        def count(release):
            value = release.get('trackCount')
            if value not in (None, ''):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
            # Fallback: count tracks sharing this release id, when present.
            return sum(1 for t in tracks
                       if (t or {}).get('albumReleaseId') == release.get('id'))

        best = max(candidates, key=count)
        return best.get('id')

    @staticmethod
    def _combined_key(track):
        number = str((track or {}).get('trackNumber') or '')
        title = str((track or {}).get('title') or '')
        if '&' in number:
            return ('num', number)
        if '&' in title:
            return ('title', title)
        return None

    @classmethod
    def _group_tracks(cls, missing):
        """Group combined-file tracks into a single payload entry.

        Lidarr represents a combined file (e.g. ``01 & 02 - Prologue &
        Twilight``) with a shared ``&`` track number across two track rows.
        Consecutive missing tracks with the same combined key become one
        entry with a ``trackIds`` list so ManualImport links both ids.
        """
        groups = []
        index = 0
        total = len(missing)
        while index < total:
            track = missing[index]
            key = cls._combined_key(track)
            if key is None:
                groups.append([track])
                index += 1
                continue
            group = [track]
            index += 1
            while index < total and cls._combined_key(missing[index]) == key:
                group.append(missing[index])
                index += 1
            groups.append(group)
        return groups

    # ------------------------------------------------------------------- payload
    def _build_entries(self, missing, template, artist, album_title, year,
                       artist_path, extension):
        """Render one payload entry per (possibly combined) missing track."""
        entries = []
        naming_config = self._config()
        for group in self._group_tracks(missing):
            first = group[0]
            raw_number = str(first.get('trackNumber') or '')
            titles = [str(t.get('title') or '') for t in group]
            combined_title = ' & '.join(t for t in titles if t)
            medium_number = first.get('mediumNumber', 1) or 1
            medium_format = (first.get('mediumFormat') or
                             next((t.get('mediumFormat') for t in group
                                   if t.get('mediumFormat')), None) or 'CD')
            track_number = _sanitize_token(raw_number)
            sanitized_artist = _sanitize_token(artist)
            sanitized_album = _sanitize_token(album_title)
            sanitized_title = _sanitize_token(combined_title)
            sanitized_medium = _sanitize_token(medium_format)
            context = {
                # Short tokens
                'artist': sanitized_artist,
                'album': sanitized_album,
                'title': sanitized_title,
                'track': track_number,
                'trackNumber': track_number,
                'disc': medium_number,
                'medium': medium_number,
                'mediumNumber': medium_number,
                'year': str(year or ''),
                'releaseYear': str(year or ''),
                'mediumFormat': sanitized_medium,
                # Lidarr's native spellings
                'Artist Name': sanitized_artist,
                'Album Title': sanitized_album,
                'Track Title': sanitized_title,
                'Release Year': str(year or ''),
                'Medium Format': sanitized_medium,
            }
            target = self._render_target(template, context, artist_path,
                                         extension)
            duration_ms = sum(int(t.get('duration') or 0) for t in group)
            entries.append({
                'title': combined_title,
                'target_path': target,
                'trackId': first.get('id'),
                'trackIds': [t.get('id') for t in group if t.get('id') is not None],
                'trackNumber': raw_number,
                'mediumNumber': medium_number,
                'duration': duration_ms,
            })
        return entries

    # ----------------------------------------------------------------- polling
    def _poll_job(self, job_id, progress=None, timeout_s=None):
        deadline = time.monotonic() + (timeout_s or _JOB_TIMEOUT_S)
        last = {}
        while time.monotonic() < deadline:
            try:
                last = self.job_manager.get_job(job_id)
            except Exception as exc:
                return {'status': 'failed', 'failure_reason': str(exc)}
            if not last:
                # Job was deleted from history while this run was polling it.
                return {'status': 'cancelled',
                        'failure_reason': 'download job was removed'}
            status = _lower(last.get('status'))
            if progress:
                try:
                    progress('download job running', job_status=status or 'pending')
                except Exception:
                    pass
            if status in _JOB_TERMINAL:
                return last
            time.sleep(_POLL_INTERVAL_S)
        return {'status': 'timeout', 'failure_reason': 'job poll timeout'}

    def _poll_command(self, command_id):
        deadline = time.monotonic() + _COMMAND_TIMEOUT_S
        last = {}
        while time.monotonic() < deadline:
            try:
                last = self._get_client().get_command(command_id) or {}
            except Exception as exc:
                return {'status': 'failed', 'message': str(exc)}
            status = _lower(last.get('status'))
            if status in _COMMAND_TERMINAL:
                return last
            time.sleep(_POLL_INTERVAL_S)
        return {'status': 'timeout', 'message': 'command poll timeout'}

    # -------------------------------------------------------------- gap fill
    def gapfill_album(self, aid, apply=True, state=None, naming_config=None,
                      extension=None, source='failed-imports',
                      respect_state=True, progress=None, timeout_s=None):
        """Run the full Blissful gap-fill for one album.

        This is the shared engine behind ``--retry-failed-imports`` and stale
        cleanup: download missing tracks, verify/tag/place them, then link with
        ManualImport. Returns a per-album report entry and never raises.
        """
        entry = self._album_report(aid)
        client = self._get_client()

        extra = {'album_id': aid}

        def report_phase(phase, **details):
            if not progress:
                return
            payload = dict(details)
            payload.update(extra)
            try:
                downloader = getattr(self, 'download_manager', None)
                if downloader is not None and hasattr(downloader,
                                                      'get_download_progress'):
                    snap = downloader.get_download_progress() or {}
                    for key in ('title', 'artist', 'source', 'status',
                                'attempts', 'pending'):
                        if key in snap:
                            name = 'track' if key == 'title' else key
                            payload['download_' + name] = snap[key]
            except Exception:
                pass
            try:
                progress(phase, **payload)
            except Exception:
                pass

        if timeout_s is None:
            try:
                minutes = int(self._config().get('gapfill_job_timeout_minutes', 15) or 15)
            except (TypeError, ValueError):
                minutes = 15
            timeout_s = max(60, minutes * 60)
        if client is None:
            entry.update(status='skipped', reason='Lidarr client unavailable')
            return entry
        if state is None:
            state = self._load_state()
        if respect_state and str(aid) in state:
            entry.update(status='skipped', reason='already recorded in state',
                         title=str(state.get(str(aid), {}).get('title') or ''))
            return entry
        if naming_config is None:
            try:
                naming_config = client.get_naming_config() or {}
            except Exception:
                naming_config = {}
        if not extension:
            extension = self._config().get('output_format', 'mp3') or 'mp3'

        try:
            album = client.get_album(aid)
            if not album:
                entry.update(status='skipped', reason='album not found')
                return entry
            title = str(album.get('title') or '')
            extra['album_title'] = title
            entry['title'] = title
            if not album.get('monitored'):
                entry.update(status='skipped', reason='album is unmonitored')
                return entry

            artist_obj = album.get('artist') or {}
            artist = str(artist_obj.get('artistName') or '')
            artist_path = str(artist_obj.get('path') or '')
            year = album.get('releaseYear') or album.get('year')

            try:
                tracks = client.get_album_tracks(aid) or []
            except Exception:
                tracks = []
            missing = [t for t in tracks
                       if isinstance(t, dict) and not t.get('hasFile')]
            entry['missing'] = len(missing)
            report_phase('preparing download', missing=len(missing))
            if not missing:
                entry.update(status='skipped', reason='no missing tracks')
                return entry

            mediums = {t.get('mediumNumber', 1) for t in missing}
            if len(mediums) > 1:
                template = (naming_config.get('multiDiscTrackFormat')
                            or naming_config.get('multiDiscFormat')
                            or _DEFAULT_MULTI_FORMAT)
            else:
                template = (naming_config.get('standardTrackFormat')
                            or naming_config.get('trackFormat')
                            or _DEFAULT_STANDARD_FORMAT)

            payload_tracks = self._build_entries(
                missing, template, artist, title, year, artist_path, extension)
            entry['sent'] = len(payload_tracks)
            if not apply:
                entry.update(status='dry-run', reason='dry run - nothing sent')
                return entry

            job_payload = {
                'artist': artist,
                'album': title,
                'album_id': aid,
                'tracks': payload_tracks,
                'target_path': artist_path,
                'source': source,
            }
            try:
                job, _duplicate = self.job_manager.enqueue('album', job_payload)
            except Exception as exc:
                entry.update(status='failed',
                             reason='enqueue error: %s' % str(exc)[:200])
                return entry
            job_id = (job or {}).get('id') if isinstance(job, dict) else None
            report_phase('download job queued', tracks=len(payload_tracks),
                         job_id=job_id)
            if not job_id:
                entry.update(status='failed',
                             reason='enqueue returned no job id')
                return entry

            finished = self._poll_job(job_id, progress=report_phase,
                                       timeout_s=timeout_s)
            if _lower(finished.get('status')) != 'succeeded':
                reason = (finished.get('failure_reason')
                          or finished.get('message')
                          or 'download job did not succeed')
                entry.update(status='failed', reason=str(reason)[:200])
                return entry

            release_id = self._monitored_release_id(album, tracks)
            if not release_id:
                entry.update(status='failed',
                             reason='no monitored release to link into')
                return entry

            accepted = []
            rejected = []
            report_phase('verifying files', files=len(payload_tracks))
            for index, payload_track in enumerate(payload_tracks, 1):
                report_phase('verifying files', verified=index,
                             total=len(payload_tracks))
                track_title = str(payload_track.get('title') or '')
                lidarr_path = payload_track.get('target_path') or ''
                host_path = self._host_path(lidarr_path)
                if not os.path.exists(host_path):
                    rejected.append((track_title, 'file not found'))
                    continue
                info = self._ffprobe(host_path) or {}
                fmt = info.get('format') or {}
                raw_duration = fmt.get('duration')
                try:
                    actual = (float(raw_duration)
                              if raw_duration not in (None, '') else None)
                except (TypeError, ValueError):
                    actual = None
                if not self._duration_ok(actual, payload_track.get('duration')):
                    rejected.append((track_title, 'duration outside 10% tolerance'))
                    self._delete_file(host_path)
                    continue
                if not self._tags_ok(fmt.get('tags'), require_date=bool(year)):
                    rejected.append((track_title, 'missing required tags'))
                    self._delete_file(host_path)
                    continue
                accepted.append(payload_track)

            entry['imported'] = 0
            if not accepted:
                reason = 'all files rejected: ' + '; '.join(
                    '%s (%s)' % (t[:30], why) for t, why in rejected[:5])
                entry.update(status='failed', reason=reason[:300])
                return entry

            report_phase('linking tracks with Lidarr', files=len(accepted))
            artist_id = artist_obj.get('id') or album.get('artistId')
            files = [{
                'path': item.get('target_path'),
                'artistId': artist_id,
                'albumId': aid,
                'albumReleaseId': release_id,
                'trackIds': item.get('trackIds') or [item.get('trackId')],
                'quality': {'id': 28, 'name': 'MP3-320'},
                'downloadId': '',
                'disableReleaseSwitching': True,
            } for item in accepted]
            try:
                response = client.post_command(
                    'ManualImport', files=files, importMode=2,
                    replaceExistingFiles=False)
            except Exception as exc:
                entry.update(status='failed',
                             reason='ManualImport error: %s' % str(exc)[:200])
                return entry
            command_id = ((response or {}).get('id')
                          if isinstance(response, dict) else None)
            if not command_id:
                entry.update(status='failed',
                             reason='ManualImport returned no command id')
                return entry
            command_result = self._poll_command(command_id)
            if _lower(command_result.get('status')) != 'completed':
                reason = (command_result.get('message')
                          or 'ManualImport did not complete')
                entry.update(status='failed', reason=str(reason)[:200])
                return entry

            entry['imported'] = len(files)
            report_phase('import complete', imported=len(files))
            entry.update(status='succeeded', reason='')
            state[str(aid)] = {
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'title': title,
                'sent': len(payload_tracks),
                'imported': len(files),
                'status': 'succeeded',
            }
            self._save_state(state)
        except Exception as exc:
            entry.update(status='failed', reason=str(exc)[:200])
        return entry

    # --------------------------------------------------------------------- run
    def run(self, album_id=None, apply=False, reset=False) -> dict:
        """Select failed imports, optionally re-download and re-import them.

        Args:
            album_id: Optional Lidarr album id to limit the run to.
            apply: When false (default) only build the report (dry run).
            reset: Delete the state file and return an empty report.

        Returns:
            A report dict.  A single bad album never raises out of this
            method - it is recorded with a failed/skipped status instead.
        """
        apply = bool(apply)
        report = self._empty_report(applied=apply, reset=bool(reset))

        if reset:
            try:
                if self.state_path.exists():
                    self.state_path.unlink()
            except OSError:
                pass
            return report

        client = None
        try:
            client = self._get_client()
            queue = client.get_all_queue_records(page_size=200)
            if isinstance(queue, dict):
                queue = queue.get('records') or []
            if not isinstance(queue, list):
                queue = []
        except Exception:
            queue = []
        report['queue_total'] = len(queue)
        if client is None:
            report['error'] = 'Lidarr client unavailable'
            return report

        # Unsupported rejections are reported but never handed to Blissful.
        unsupported = []
        candidates = []
        for record in queue:
            if not isinstance(record, dict):
                continue
            text = _lower(_record_text(record))
            matched_unsupported = next(
                (p for p in UNSUPPORTED_PATTERNS if p in text), None)
            if matched_unsupported:
                item = {
                    'album_id': record.get('albumId'),
                    'download_id': record.get('downloadId'),
                    'title': str(record.get('title') or ''),
                    'reason': matched_unsupported,
                }
                if album_id is None or str(item['album_id']) == str(album_id):
                    unsupported.append(item)
                continue
            has_error = (record.get('trackedDownloadState') == 'importFailed'
                         or bool(record.get('errorMessage'))
                         or bool(record.get('statusMessages')))
            if has_error and any(p in text for p in UNHEALTHY_PATTERNS):
                candidates.append(record)

        report['unsupported'] = unsupported
        if album_id is not None:
            candidates = [r for r in candidates
                          if str(r.get('albumId')) == str(album_id)]
        report['failures'] = len(candidates)

        # Group by album, dedupe by download id.
        by_album = {}
        seen_downloads = set()
        for record in candidates:
            aid = record.get('albumId')
            if not aid:
                continue
            download_id = record.get('downloadId')
            if download_id:
                key = (aid, download_id)
                if key in seen_downloads:
                    continue
                seen_downloads.add(key)
            by_album.setdefault(aid, []).append(record)

        state = self._load_state()
        cfg = self._config()
        try:
            naming_config = client.get_naming_config() or {}
        except Exception:
            naming_config = {}
        extension = cfg.get('output_format', 'mp3') or 'mp3'

        for aid in by_album:
            report['albums'].append(self.gapfill_album(
                aid, apply=apply, state=state, naming_config=naming_config,
                extension=extension, source='failed-imports'))

        return report

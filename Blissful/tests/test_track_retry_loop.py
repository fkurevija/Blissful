"""Regression tests for stuck retries and per-track retry loops."""

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.album_manager import AlbumManager  # noqa: E402
from extend.job_manager import JobManager  # noqa: E402
from extend.wanted_search import WantedSearchService  # noqa: E402


class ConfigStub:
    def get_setting(self, key, default=None):
        return default

    def get_config(self):
        return {'output_format': 'mp3', 'embed_metadata': False,
                'embed_thumbnail': False, 'source_priorities': []}


class AlbumManagerStub:
    def download_album(self, **kwargs):
        return {'success': False, 'error': 'boom'}


def make_manager(tmp_path):
    return JobManager(ConfigStub(), AlbumManagerStub(),
                      storage_path=str(tmp_path / 'jobs.json'))


def test_manual_retry_of_cleanup_job_is_due(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup', 'apply': True})
    manager.update_job(job['id'], status='failed', failure_reason='boom')
    manager.retry(job['id'])

    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    called = {}
    service.cleanup_stale = lambda **kwargs: called.update(kwargs)
    service._process_due_retries()
    assert called['retry_job_id'] == job['id']


def test_busy_retry_is_deferred_not_left_pending(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('search', {'album_ids': [1], 'apply': True})
    manager.update_job(job['id'], status='failed', failure_reason='boom')
    manager.schedule_retry(job['id'], 'boom')
    manager.update_job(job['id'], next_attempt_at=0)

    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    service.search = lambda **kwargs: {'already_running': True}
    service._process_due_retries()
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'pending'
    assert stored['next_attempt_at'] > time.time()


class Downloads:
    def __init__(self, fail_once):
        self.fail_once = set(fail_once)
        self.calls = []
        self.progress = []

    def download_track(self, **kwargs):
        title = kwargs['title']
        self.calls.append(title)
        if title in self.fail_once:
            self.fail_once.remove(title)
            return {'success': False, 'error': 'boom', 'attempts': []}
        return {'success': True, 'file_path': '/tmp/track.mp3',
                'duration': 100, 'thumbnail_path': None}

    def _set_download_progress(self, **kwargs):
        self.progress.append(kwargs)


class Converter:
    def convert(self, **kwargs):
        return kwargs['input_file']

    def add_metadata(self, *args, **kwargs):
        return True


def make_album_manager(fail_once):
    downloads = Downloads(fail_once)
    manager = AlbumManager(ConfigStub(), object, downloads, Converter())
    return manager, downloads


def test_album_loop_skips_failed_track_then_completes_it():
    manager, downloads = make_album_manager(['A'])
    first = manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: False)
    assert downloads.calls == ['A', 'B']
    assert first['success'] is False
    assert first['completed_tracks'] == 1
    assert first['pending_tracks'] == [{'title': 'A'}]
    second = manager.download_album(
        'Artist', 'Album', first['pending_tracks'],
        should_cancel=lambda: False, resume_state=first['resume_state'])
    assert downloads.calls == ['A', 'B', 'A']
    assert second['success'] is True
    assert second['completed_tracks'] == 2
    assert second['successful'] == 2
    assert second['rounds'] == 2
    assert downloads.progress[-1]['download_index'] == 2


def test_album_loop_stops_when_cancelled():
    manager, downloads = make_album_manager(['A'])
    result = manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: True)
    assert result['cancelled'] is True
    assert result['success'] is False
    assert result['completed_tracks'] == 0


def test_album_loop_reports_progress_callback():
    manager, downloads = make_album_manager(['A'])
    seen = []
    manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: False, retry_delay=lambda round_no: 0,
        on_progress=lambda **details: seen.append(details))
    assert any(d.get('completed_tracks') == 1 and d.get('total_tracks') == 2
               for d in seen)
    assert seen[-1]['completed_tracks'] == 1
    assert seen[-1]['round'] == 1


def test_job_manager_passes_live_progress_callback(tmp_path):
    class CaptureAlbum:
        def __init__(self):
            self.kwargs = {}

        def download_album(self, **kwargs):
            self.kwargs = kwargs
            return {'success': True, 'completed_tracks': 1, 'total_tracks': 1,
                    'successful': 1, 'failed': 0, 'rounds': 1, 'tracks': []}

    album = CaptureAlbum()
    manager = JobManager(ConfigStub(), album,
                         storage_path=str(tmp_path / 'jobs.json'))
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager._process(manager._next_pending())
    assert callable(album.kwargs.get('on_progress'))
    album.kwargs['on_progress'](phase='track', completed_tracks=1, total_tracks=1)
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'succeeded'
    assert stored['progress']['completed_tracks'] == 1


def test_cancel_active_cancels_this_runs_jobs_only(tmp_path):
    manager = make_manager(tmp_path)
    parent, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup'})
    manager.update_job(parent['id'], status='running')
    child, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'},
                               parent_id=parent['id'])
    manager.update_job(child['id'], status='running')
    unrelated, _ = manager.enqueue('album', {'artist': 'X', 'album': 'Y'})
    manager.update_job(unrelated['id'], status='running')

    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    service._active = {'kind': 'cleanup', 'run_job_id': parent['id'],
                       'phase': 'download job running'}
    assert service.cancel_active() is True
    assert manager.get_job(parent['id'])['status'] == 'cancelled'
    assert manager.get_job(child['id'])['status'] == 'cancelled'
    assert manager.get_job(unrelated['id'])['status'] == 'running'
    assert service._cancel_event.is_set()


def test_worker_reschedules_failed_tracks_without_blocking_queue(tmp_path):
    class RoundAlbum:
        def download_album(self, **kwargs):
            return {'success': False, 'completed_tracks': 1, 'total_tracks': 2,
                    'successful': 1, 'failed': 1, 'rounds': 1, 'tracks': [],
                    'pending_tracks': [{'title': 'B'}],
                    'resume_state': {'rounds': 1, 'completed_tracks': 1}}

    manager = JobManager(ConfigStub(), RoundAlbum(),
                         storage_path=str(tmp_path / 'jobs.json'))
    other, _ = manager.enqueue('album', {'artist': 'X', 'album': 'Y'})
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager._process(manager._next_pending())
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'pending'
    assert stored['next_attempt_at'] > time.time()
    assert stored['payload']['pending_tracks'] == [{'title': 'B'}]
    assert manager._next_pending()['id'] == other['id']


def test_cancel_stamps_finished_at_and_retry_clears_stale_fields(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager.update_job(job['id'], status='running')
    assert manager.cancel_job(job['id'])
    cancelled = manager.get_job(job['id'])
    assert cancelled['status'] == 'cancelled'
    assert cancelled['finished_at']
    assert (cancelled.get('log') or [])[-1]['phase'] == 'cancelled'
    manager.update_job(job['id'], result={'successful': 0}, progress={'phase': 'failed'})
    _, changed = manager.retry(job['id'])
    assert changed is True
    retried = manager.get_job(job['id'])
    assert retried['status'] == 'pending'
    assert 'finished_at' not in retried
    assert 'result' not in retried
    assert 'next_attempt_at' not in retried


def test_cancelled_run_finishes_cancelled_not_failed(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup', 'apply': True})
    manager.update_job(job['id'], status='running')
    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    service._cancel_event.set()
    changes = {}
    service._finish_job(job['id'], lambda **kw: manager.update_job(job['id'], **kw),
                        success=False, failed=True, reason='boom',
                        result={'command': 'stale-cleanup'})
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'cancelled'
    assert stored['failure_reason'] == 'cancelled by user'


def test_failed_run_schedules_retry_without_cancel(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup', 'apply': True})
    manager.update_job(job['id'], status='running')
    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    changes = {}
    service._finish_job(job['id'], lambda **kw: manager.update_job(job['id'], **kw),
                        success=False, failed=True, reason='boom',
                        result={'command': 'stale-cleanup'})
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'pending'
    assert stored['next_attempt_at'] > time.time()


def test_succeeded_run_finishes_successful(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup', 'apply': True})
    manager.update_job(job['id'], status='running')
    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    changes = {}
    service._finish_job(job['id'], lambda **kw: manager.update_job(job['id'], **kw),
                        success=True, failed=False, reason=None,
                        result={'command': 'stale-cleanup'})
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'succeeded'


def test_manual_retry_is_picked_before_newer_pending_jobs(tmp_path):
    manager = make_manager(tmp_path)
    old, _ = manager.enqueue('album', {'artist': 'A', 'album': 'Old'})
    manager.update_job(old['id'], status='cancelled')
    for name in ('New1', 'New2', 'New3'):
        manager.enqueue('album', {'artist': 'B', 'album': name})
    _, changed = manager.retry(old['id'])
    assert changed is True
    assert manager.jobs[0]['id'] == old['id']
    picked = manager._next_pending()
    assert picked['id'] == old['id']
    assert (picked.get('log') or [])[-1]['phase'] == 'retry requested'

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
    result = manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: False, retry_delay=lambda round_no: 0)
    assert downloads.calls == ['A', 'B', 'A']
    assert result['success'] is True
    assert result['completed_tracks'] == 2
    assert result['successful'] == 2
    assert result['failed'] == 0
    assert result['rounds'] == 2
    assert downloads.progress[-1]['download_index'] == 2


def test_album_loop_stops_when_cancelled():
    manager, downloads = make_album_manager(['A'])
    result = manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: len(downloads.progress) >= 2,
        retry_delay=lambda round_no: 0)
    assert result['cancelled'] is True
    assert result['success'] is False
    assert result['completed_tracks'] == 1


def test_album_loop_reports_progress_callback():
    manager, downloads = make_album_manager(['A'])
    seen = []
    manager.download_album(
        'Artist', 'Album', [{'title': 'A'}, {'title': 'B'}],
        should_cancel=lambda: False, retry_delay=lambda round_no: 0,
        on_progress=lambda **details: seen.append(details))
    assert any(d.get('completed_tracks') == 1 and d.get('total_tracks') == 2
               for d in seen)
    assert seen[-1]['completed_tracks'] == 2
    assert seen[-1]['round'] == 2


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

"""Tests for automatic retry of failed jobs and wanted/cleanup runs."""

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.job_manager import JobManager  # noqa: E402
from extend.wanted_search import WantedSearchService  # noqa: E402


class ConfigStub:
    def get_setting(self, key, default=None):
        return default


class AlbumManagerStub:
    def __init__(self, result):
        self.result = result

    def download_album(self, **kwargs):
        return self.result


def make_manager(tmp_path, result=None):
    return JobManager(ConfigStub(), AlbumManagerStub(result or {}),
                      storage_path=str(tmp_path / 'jobs.json'))


def test_retry_delay_is_capped(monkeypatch):
    monkeypatch.setattr('extend.job_manager.random.uniform', lambda a, b: 1.0)
    assert JobManager.retry_delay(1) == 30
    assert JobManager.retry_delay(3) == 120
    assert JobManager.retry_delay(20) == 300


def test_schedule_retry_keeps_job_pending_and_delays_worker(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager.update_job(job['id'], status='failed', failure_reason='boom')
    retried = manager.schedule_retry(job['id'], 'boom')
    assert retried['status'] == 'pending'
    assert retried['attempts'] == 1
    assert retried['next_attempt_at'] > time.time()
    assert manager._next_pending() is None
    manager.update_job(job['id'], next_attempt_at=0)
    assert manager._next_pending()['id'] == job['id']


def test_cancelled_jobs_are_never_revived(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager.update_job(job['id'], status='running')
    assert manager.cancel_job(job['id'])
    assert manager.schedule_retry(job['id'], 'boom') is None
    assert manager.get_job(job['id'])['status'] == 'cancelled'


def test_worker_auto_retries_failed_album_job(tmp_path, monkeypatch):
    monkeypatch.setattr('extend.job_manager.random.uniform', lambda a, b: 1.0)
    manager = make_manager(tmp_path, {'success': False, 'error': 'boom'})
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    manager._process(manager._next_pending())
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'pending'
    assert stored['attempts'] == 1
    assert stored['next_attempt_at'] > time.time()


def test_worker_keeps_cancelled_status(tmp_path):
    manager = make_manager(tmp_path, {'success': False, 'error': 'boom'})
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B'})
    running = manager._next_pending()
    manager.cancel_job(job['id'])
    manager._process(running)
    stored = manager.get_job(job['id'])
    assert stored['status'] == 'cancelled'
    assert stored.get('next_attempt_at') is None


def test_due_top_level_retry_is_started_with_original_job(tmp_path):
    manager = make_manager(tmp_path)
    job, _ = manager.enqueue('search', {'album_ids': [7], 'apply': True},
                             dedupe_key='retry-test')
    manager.update_job(job['id'], status='failed', failure_reason='boom')
    manager.schedule_retry(job['id'], 'boom')
    manager.update_job(job['id'], next_attempt_at=0)

    service = WantedSearchService(ConfigStub(), object, job_manager=manager)
    called = {}
    service.search = lambda **kwargs: called.update(kwargs)
    service._process_due_retries()

    assert called['retry_job_id'] == job['id']
    assert called['album_ids'] == [7]
    assert called['apply'] is True

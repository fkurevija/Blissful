"""Persisted state-machine invariants for the real JobManager.

Assertions go through get_job()/list_jobs() and the public mutators. These
tests describe the state machine itself, not a stub that mirrors it, so a
broken status write fails them no matter which service performs the write.
"""

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from extend.job_manager import JobManager, TERMINAL_STATUSES  # noqa: E402


def _enqueue(jobs, kind='album', payload=None, **kwargs):
    job, reused = jobs.enqueue(kind, payload or {'artist': 'A', 'album': 'B'},
                               **kwargs)
    assert reused is False
    return job['id']


def test_one_top_level_job_per_run(jobs):
    run_id = _enqueue(jobs, 'search', {'album_ids': [1, 2], 'apply': True},
                      dedupe_key='run-42')
    children = [
        _enqueue(jobs, 'album', {'artist': 'A', 'album': 'One'},
                 dedupe_key='album-one', parent_id=run_id),
        _enqueue(jobs, 'album', {'artist': 'A', 'album': 'Two'},
                 dedupe_key='album-two', parent_id=run_id),
    ]

    visible = jobs.list_jobs()
    assert [job['id'] for job in visible] == [run_id]
    assert visible[0]['child_count'] == 2
    assert {job['id'] for job in jobs.list_jobs(include_children=True)} == {
        run_id, *children}
    for child_id in children:
        assert jobs.get_job(child_id)['parent_id'] == run_id
    assert jobs.get_job(run_id)['parent_id'] is None


def test_finished_at_is_set_if_and_only_if_terminal(jobs):
    pending_id = _enqueue(jobs, dedupe_key='pending')
    running_id = _enqueue(jobs, dedupe_key='running')
    ok_id = _enqueue(jobs, dedupe_key='ok')
    failed_id = _enqueue(jobs, dedupe_key='failed')
    cancelled_id = _enqueue(jobs, dedupe_key='cancelled')

    jobs.update_job(running_id, status='running')
    jobs.update_job(ok_id, status='succeeded')
    jobs.update_job(failed_id, status='failed', failure_reason='boom')
    assert jobs.cancel_job(cancelled_id) is True

    for job_id in (pending_id, running_id):
        stored = jobs.get_job(job_id)
        assert stored['status'] not in TERMINAL_STATUSES
        assert stored.get('finished_at') is None
    for job_id in (ok_id, failed_id, cancelled_id):
        stored = jobs.get_job(job_id)
        assert stored['status'] in TERMINAL_STATUSES
        assert stored.get('finished_at')


def test_cancel_is_terminal_with_log_and_finished_at(jobs):
    job_id = _enqueue(jobs)
    jobs.update_job(job_id, status='running')
    assert jobs.cancel_job(job_id) is True

    stored = jobs.get_job(job_id)
    assert stored['status'] == 'cancelled'
    assert stored.get('finished_at')
    assert any(entry.get('phase') == 'cancelled' for entry in stored['log'])

    assert jobs.cancel_job(job_id) is False
    assert jobs.schedule_retry(job_id) is None
    assert jobs.get_job(job_id)['status'] == 'cancelled'


def test_retry_clears_stale_state_and_moves_job_to_head(jobs):
    job_id = _enqueue(jobs, dedupe_key='retry-me')
    newer_id = _enqueue(jobs, dedupe_key='newer')
    jobs.update_job(job_id, status='running',
                    result={'success': False},
                    progress={'phase': 'partial', 'completed_tracks': 1,
                              'total_tracks': 2},
                    next_attempt_at=123.0,
                    payload={'artist': 'A', 'album': 'B',
                             'pending_tracks': [{'title': 'track'}],
                             'resume_state': {'rounds': 1}})
    jobs.update_job(job_id, status='failed', failure_reason='boom')
    before = jobs.get_job(job_id)
    assert before['status'] == 'failed'
    assert before['result'] and before['progress'] and before['finished_at']

    updated, ok = jobs.retry(job_id)
    assert ok is True
    assert updated['id'] == job_id
    stored = jobs.get_job(job_id)
    assert stored['status'] == 'pending'
    assert stored.get('result') is None
    assert stored.get('progress') is None
    assert stored.get('finished_at') is None
    assert stored.get('next_attempt_at') is None
    assert 'pending_tracks' not in stored['payload']
    assert 'resume_state' not in stored['payload']
    assert any(entry.get('phase') == 'retry requested' for entry in stored['log'])

    ids = [job['id'] for job in jobs.list_jobs(include_children=True)]
    assert ids[0] == job_id
    assert ids.index(job_id) < ids.index(newer_id)


def test_automatic_requeue_does_not_occupy_the_worker(jobs, frozen_clock):
    stalled_id = _enqueue(jobs, dedupe_key='stalled')
    ready_id = _enqueue(jobs, dedupe_key='ready')
    jobs.update_job(stalled_id, status='running',
                    payload={'artist': 'A', 'album': 'B',
                             'pending_tracks': [{'title': 'track'}],
                             'resume_state': {'rounds': 1}})
    jobs.update_job(stalled_id, status='failed', failure_reason='transient')
    requeued = jobs.schedule_retry(stalled_id, 'transient')

    assert requeued['status'] == 'pending'
    stored = jobs.get_job(stalled_id)
    assert stored['status'] == 'pending'
    assert stored['next_attempt_at'] > frozen_clock.time()
    assert stored['payload']['pending_tracks']
    assert stored['payload']['resume_state']

    # A backoff job is pending but not due: another job must be available.
    assert jobs._next_pending()['id'] == ready_id
    assert jobs.get_job(stalled_id)['status'] == 'pending'
    assert jobs._next_pending() is None


def test_dedupe_only_reuses_jobs_from_this_manager(jobs):
    first_id = _enqueue(jobs, dedupe_key='same-key')
    again, reused = jobs.enqueue('album', {'artist': 'A', 'album': 'B'},
                                 dedupe_key='same-key')
    assert reused is True
    assert again['id'] == first_id
    assert len(jobs.list_jobs(include_children=True)) == 1

    restarted = JobManager(jobs.config_manager, jobs.album_manager,
                           storage_path=str(jobs.storage_path))
    fresh, reused = restarted.enqueue('album', {'artist': 'A', 'album': 'B'},
                                      dedupe_key='same-key')
    assert reused is False
    assert fresh['id'] != first_id
    assert restarted.get_job(first_id)['status'] == 'pending'
    assert restarted.get_job(fresh['id'])['status'] == 'pending'


def test_terminal_job_is_not_deduped(jobs):
    first_id = _enqueue(jobs, dedupe_key='done-key')
    jobs.update_job(first_id, status='succeeded')
    again, reused = jobs.enqueue('album', {'artist': 'A', 'album': 'B'},
                                 dedupe_key='done-key')
    assert reused is False
    assert again['id'] != first_id


def test_running_job_from_previous_instance_is_not_revived(jobs):
    old_id = _enqueue(jobs, dedupe_key='orphan')
    jobs.update_job(old_id, status='running')

    restarted = JobManager(jobs.config_manager, jobs.album_manager,
                           storage_path=str(jobs.storage_path))
    stored = restarted.get_job(old_id)
    assert stored['status'] == 'cancelled'
    assert stored['failure_reason'] == 'Interrupted by restart'
    assert restarted.schedule_retry(old_id) is None
    assert restarted.get_job(old_id)['status'] == 'cancelled'


def test_terminal_children_are_hidden_and_resolved_with_parent(jobs):
    run_id = _enqueue(jobs, 'search', {'album_ids': [1], 'apply': True},
                      dedupe_key='run-children')
    child_id = _enqueue(jobs, 'album', {'artist': 'C', 'album': 'Child'},
                        dedupe_key='child-c', parent_id=run_id)
    live_id = _enqueue(jobs, 'album', {'artist': 'C', 'album': 'Live'},
                       dedupe_key='child-live', parent_id=run_id)

    assert jobs.cancel_job(child_id) is True
    child = jobs.get_job(child_id)
    assert child['status'] == 'cancelled'
    assert child.get('finished_at')
    assert any(entry.get('phase') == 'cancelled' for entry in child['log'])
    assert any(entry.get('phase') == 'cancelled'
               for entry in jobs.get_job(run_id)['log'])

    assert [job['id'] for job in jobs.list_jobs()] == [run_id]
    assert jobs.list_jobs()[0]['child_count'] == 2

    assert jobs.clear_finished() == 1
    assert jobs.get_job(child_id) is None
    assert jobs.get_job(live_id)['status'] == 'pending'
    assert [job['id'] for job in jobs.list_jobs()] == [run_id]

"""Single owner for wanted-search and stale-cleanup run state.

Before this module, one logical run was described by four separate holders:
JobManager's persisted records, WantedSearchService's active dict, per-kind
locks/cancel events/job-id sets, and DownloadManager's thread-local progress
context. Divergence between those copies caused the cancel, retry and phantom
run regressions recorded in the architecture review.

All run-scoped state now lives here. Callers pass ``kind`` explicitly; the
legacy last-updated kind is only used to resolve a snapshot for older callers
that ask for ``get_active()`` without an argument.
"""

import threading
import time
from dataclasses import dataclass, field

from extend.domain import RUN_KINDS, SEARCH, CANCELLED

# Fields promoted to typed attributes on RunState; everything else is data.
_TYPED_FIELDS = frozenset({
    'kind', 'phase', 'status', 'started_at', 'finished_at', 'updated_at',
    'cancel_requested', 'run_job_id', 'job_ids',
})


@dataclass
class RunState:
    """The authoritative, in-memory description of one active run."""

    kind: str
    phase: str = 'starting'
    status: str = None
    started_at: float = None
    finished_at: float = None
    updated_at: float = None
    cancel_requested: bool = False
    run_job_id: str = None
    job_ids: set = field(default_factory=set)
    data: dict = field(default_factory=dict)

    def snapshot(self):
        """Flat dict in the shape consumed by /api/wanted/status and the UI."""
        snap = dict(self.data)
        snap.update({
            'kind': self.kind,
            'phase': self.phase,
            'updated_at': self.updated_at if self.updated_at is not None else time.time(),
            'cancel_requested': bool(self.cancel_requested),
        })
        if self.status is not None:
            snap['status'] = self.status
        if self.started_at is not None:
            snap['started_at'] = self.started_at
        if self.finished_at is not None:
            snap['finished_at'] = self.finished_at
        if self.run_job_id is not None:
            snap['run_job_id'] = self.run_job_id
        return snap


class RunCoordinator:
    """Own run admission, cancellation, job membership and status snapshots."""

    def __init__(self, job_manager=None):
        self.job_manager = job_manager
        self._lock = threading.RLock()
        self._run_locks = {kind: threading.Lock() for kind in RUN_KINDS}
        self._cancel_events = {kind: threading.Event() for kind in RUN_KINDS}
        self._states = {kind: None for kind in RUN_KINDS}
        self._last_kind = None
        self._last_activity = None

    # ------------------------------------------------------------- admission
    @property
    def run_locks(self):
        return self._run_locks

    @property
    def cancel_events(self):
        return self._cancel_events

    @property
    def states(self):
        return self._states

    def is_locked(self, kind):
        return self._run_locks[kind].locked()

    def begin(self, kind, **updates):
        """Claim this kind's single-flight slot; return None when busy."""
        if not self._run_locks[kind].acquire(blocking=False):
            return None
        with self._lock:
            self._cancel_events[kind].clear()
            self._states[kind] = None
            self.job_ids(kind).clear()
        return self.update(kind, **updates)

    def release(self, kind):
        try:
            self._run_locks[kind].release()
        except RuntimeError:  # never released by us
            pass

    # ----------------------------------------------------------- state reads
    def update(self, kind, **updates):
        with self._lock:
            state = self._states[kind]
            if state is None:
                state = RunState(kind=kind, updated_at=time.time())
                self._states[kind] = state
            for key, value in updates.items():
                if key in _TYPED_FIELDS and key != 'kind' and value is not None:
                    setattr(state, key, value)
                else:
                    state.data[key] = value
            state.updated_at = time.time()
            self._last_kind = kind
            return state.snapshot()

    def finish(self, kind, status):
        with self._lock:
            state = self._states[kind]
            if state is None:
                return None
            state.status = status
            state.finished_at = time.time()
            snap = state.snapshot()
            self._last_activity = snap
            self._states[kind] = None
            return snap

    def get(self, kind=None):
        with self._lock:
            if kind is not None:
                state = self._states[kind]
                return state.snapshot() if state else None
            if self._last_kind and self._states.get(self._last_kind):
                return self._states[self._last_kind].snapshot()
            for candidate in RUN_KINDS:
                state = self._states.get(candidate)
                if state:
                    return state.snapshot()
            return None

    def get_all(self):
        with self._lock:
            return {kind: state.snapshot()
                    for kind, state in self._states.items() if state}

    def get_last_activity(self):
        with self._lock:
            return dict(self._last_activity) if self._last_activity else None

    @property
    def last_kind(self):
        return self._last_kind

    # ----------------------------------------------------------- cancellation
    def cancel_event(self, kind):
        return self._cancel_events[kind]

    def is_cancelled(self, kind):
        return self._cancel_events[kind].is_set()

    def job_ids(self, kind):
        with self._lock:
            state = self._states[kind]
            if state is None:
                state = RunState(kind=kind, updated_at=time.time())
                self._states[kind] = state
            return state.job_ids

    def register_job(self, kind, job_id):
        if job_id:
            self.job_ids(kind).add(job_id)

    def cancel(self, kind, cancel_all=False):
        """Cancel exactly this run's jobs (including children), never others."""
        kinds = RUN_KINDS if cancel_all else (kind,)
        changed = False
        with self._lock:
            for run_kind in kinds:
                state = self._states[run_kind]
                if state is None and not self._run_locks[run_kind].locked():
                    continue
                self._cancel_events[run_kind].set()
                if state is not None:
                    state.cancel_requested = True
                    state.data['cancel_requested'] = True
                ids = set(state.job_ids) if state is not None else set()
                run_job_id = state.run_job_id if state is not None else None
                if run_job_id:
                    ids.add(run_job_id)
                    if self.job_manager is not None:
                        try:
                            for job in self.job_manager.list_jobs(
                                    limit=500, include_children=True) or []:
                                if job.get('parent_id') == run_job_id:
                                    ids.add(job['id'])
                        except Exception:
                            pass
                if self.job_manager is not None:
                    for job_id in ids:
                        try:
                            self.job_manager.cancel_job(job_id)
                        except Exception:
                            pass
                changed = True
        return changed

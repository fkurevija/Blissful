# 🧱 Architecture

Blissful is a single Flask process with a bounded job worker and a wanted-run
scheduler. It is intentionally not a microservice: the fragility we set out to
remove came from state duplication, not from process boundaries.

## Module boundaries

| Module | Owns | Does not own |
|---|---|---|
| `Blissful.py` | Flask app, manager wiring, CLI modes | Run lifecycle |
| `extend/domain.py` | Status vocabulary, Lidarr status sets, health patterns | Persistence |
| `extend/run_coordinator.py` | Run admission, cancellation, child job IDs, snapshots | Download details |
| `extend/job_manager.py` | Persisted jobs in `jobs.json`, retries, logs | Run-level policy |
| `extend/orchestration.py` | Pure selection/polling stages | Service state |
| `extend/config_schema.py` | Config shape validation at load time | Secret masking (save path) |
| `extend/wanted_search.py` | Search/cleanup pipelines | Its own run state (delegated) |
| `extend/failed_imports.py` | Gap-fill engine | Its own terminal-status set |

## One run, one owner

`RunCoordinator` is the only holder of a run's in-memory state. It grants the
single-flight slot per kind (`search`/`cleanup`), records the top-level job id
and its children, sets and checks the cancellation event, and produces the
snapshot served by `/api/wanted/status`.

Consequences enforced in code:

- A second request of the same kind is queued as a top-level job; a search and a
  cleanup still overlap.
- Cancellation targets exactly that run's jobs and children, and a cancelled run
  finishes as `cancelled` rather than overwriting children with `failed`.
- Progress callbacks receive the owning run's kind explicitly. There is no
  thread-local kind fallback and no inference from a source string.
- Download progress is keyed by job id; a cross-thread reader passes the key.

## Configuration

Configuration is validated on load by `extend/config_schema.py` and on save by
`ConfigManager._validate_config()`. A malformed `source_priorities` list, an
unknown metadata provider or an out-of-range search depth is repaired at startup
instead of failing during a download. The browser keeps config state in one
store and serialises it from that store, not from DOM text.

## Frontend

The browser scripts are plain JavaScript with no build step. `boot.js` owns a
single `window.Blissful` namespace and installs thin global aliases for existing
inline handlers. Feature state lives in one state store; the DOM is a projection
of it. Job tables and log entries are reconciled by stable keys so expanded
sections, text selection and scroll position survive polling. One toast manager
owns every sticky notification, and all polls have tracked timers, in-flight
guards and sequence ids so an older response cannot overwrite newer state.

## Verification

The `Tests` workflow runs on every push and pull request:

```bash
py -3.11 -m pytest -q          # three consecutive runs to expose flakes
node --check Blissful/static/js/*.js
```

The suite uses real managers on temporary paths for job state assertions and
exercises HTTP contracts through the real Flask app. Tests that only returned a
boolean were removed from collection; they were always passing regardless of
their result.

## Invariants to preserve when changing this code

1. One user-visible run = one top-level job; children are hidden unless asked for.
2. `finished_at` is set if and only if a job is terminal.
3. Cancel is terminal: check the run's cancel token again at the final status write.
4. Manual retry clears `next_attempt_at` and moves the job to the queue head;
   automatic backoff keeps a due timestamp and does not occupy a worker.
5. Child progress mirrors to its parent; dedupe uses an exact in-process marker.
6. Run kind is explicit at every callback boundary.
7. Secrets are masked on read and round-trip with `***KEEP_EXISTING***` on save.
8. Stale candidates come only from Lidarr's Activity Queue; skipping a
   re-download never skips the queue-row deletion after import is confirmed.

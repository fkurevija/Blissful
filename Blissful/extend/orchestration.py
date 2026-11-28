"""Small, reusable orchestration primitives shared by services.

These are deliberately pure of service state: they take callables and return
values, so a stage can be tested without constructing managers or mocking a
worker thread.
"""

import time

from extend.domain import lower


def coerce_ids(values):
    """Drop non-integer ids from a caller-supplied selection."""
    ids = []
    for value in values or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def poll_until(fetch, terminal, timeout_s, interval_s=2, on_tick=None,
               cancelled=None, error_result=None, timeout_result=None):
    """Poll ``fetch`` until a terminal status, timeout or cancellation.

    ``on_tick`` receives the fetched record; ``cancelled`` is checked at every
    boundary. Error and timeout results are supplied by the caller so each
    service keeps its existing response shape.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cancelled and cancelled():
            return {'status': 'cancelled'}
        try:
            last = fetch() or {}
        except Exception as exc:
            if error_result:
                return error_result(exc)
            return {'status': 'failed', 'message': str(exc)}
        if on_tick:
            on_tick(last)
        if lower(last.get('status')) in terminal:
            return last
        time.sleep(interval_s)
    return timeout_result or {'status': 'timeout', 'message': 'poll timeout'}

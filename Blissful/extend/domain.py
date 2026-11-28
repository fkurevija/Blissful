"""Shared domain vocabulary for Blissful jobs and runs.

This module is the single source of truth for status values, Lidarr status
normalisation and the queue-health patterns used by both wanted search and
failed-import recovery. Import it rather than redefining these in a service;
duplicated terminal sets and patterns have caused repeated regressions.
"""

# --- job lifecycle -------------------------------------------------------
PENDING = 'pending'
RUNNING = 'running'
SUCCEEDED = 'succeeded'
FAILED = 'failed'
CANCELLED = 'cancelled'

# Statuses that end a job managed by JobManager.
TERMINAL_STATUSES = {SUCCEEDED, FAILED, CANCELLED}

# Statuses Lidarr may report for a job/command, including its spelling variants.
JOB_TERMINAL_STATUSES = frozenset({
    SUCCEEDED, FAILED, CANCELLED, 'complete', 'completed', 'error', 'canceled',
})
COMMAND_TERMINAL_STATUSES = frozenset({'completed', 'failed', 'complete', 'error'})
COMMAND_OK_STATUSES = frozenset({'completed', 'complete', 'succeeded', 'success'})

# --- run kinds -----------------------------------------------------------
SEARCH = 'search'
CLEANUP = 'cleanup'
RUN_KINDS = (SEARCH, CLEANUP)

# --- Lidarr queue health -------------------------------------------------
UNHEALTHY_PATTERNS = (
    'stalled with no connections',
    'no files found are eligible',
    'unable to communicate',
    'download client',
)


def lower(value):
    """Normalise a possibly-None Lidarr value for comparisons."""
    return str(value or '').lower()


def record_text(record):
    """Build one searchable error string from a Lidarr queue record."""
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


def is_terminal(status):
    """True when a JobManager status is terminal."""
    return lower(status) in TERMINAL_STATUSES


def normalize_kind(kind, default=SEARCH):
    """Return a known run kind, never an arbitrary string from a caller."""
    return kind if kind in RUN_KINDS else default

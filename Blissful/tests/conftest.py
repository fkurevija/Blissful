"""Shared fixtures for the invariant suite.

Everything here uses the real JobManager persistence path (a jobs.json under
pytest's tmp_path); collaborators are strict Mocks spec'd from the real
classes, so a renamed or missing method fails loudly instead of being
silently invented by a hand-rolled stub.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from extend import job_manager as job_manager_module  # noqa: E402
from extend.album_manager import AlbumManager  # noqa: E402
from extend.config_manager import ConfigManager  # noqa: E402
from extend.job_manager import JobManager  # noqa: E402

FROZEN_AT = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def spec_mock():
    """Factory for Mocks restricted to a real class's public surface."""
    def _make(spec, **attributes):
        mock = Mock(spec=spec)
        for name, value in attributes.items():
            setattr(mock, name, value)
        return mock
    return _make


@pytest.fixture
def jobs(tmp_path, spec_mock):
    """A real JobManager with real JSON persistence on tmp_path."""
    config = spec_mock(ConfigManager)
    config.get_setting.side_effect = lambda key, default=None: default
    album_manager = spec_mock(AlbumManager)
    return JobManager(config, album_manager,
                      storage_path=str(tmp_path / 'jobs.json'))


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the clock used by JobManager; expose advance() for due-time tests.

    Both time.time() and the ISO timestamp helper are pinned to the same
    instant, so a due timestamp or finished_at can be compared exactly.
    """
    class Clock:
        def __init__(self, epoch):
            self.epoch = epoch

        def time(self):
            return self.epoch

        def advance(self, seconds):
            self.epoch += seconds

    clock = Clock(FROZEN_AT.timestamp())

    def frozen_now():
        return datetime.fromtimestamp(clock.time(), tz=timezone.utc).isoformat()

    monkeypatch.setattr(job_manager_module, 'time', clock, raising=True)
    monkeypatch.setattr(job_manager_module, '_now', frozen_now, raising=True)
    return clock


@pytest.fixture
def fake_response():
    """Factory for a spec'd requests.Response with a controllable payload."""
    def _make(status_code=200, payload=None, text=None, headers=None):
        response = Mock(spec=requests.Response)
        response.status_code = status_code
        response.json.return_value = {} if payload is None else payload
        response.text = '' if text is None else text
        response.headers = {} if headers is None else headers
        return response
    return _make

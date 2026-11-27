"""Tests for the optional YouTube login helpers."""
import pytest

from extend.youtube_login import (YouTubeLoginService, cookies_to_netscape,
                                  clear_relogin_required,
                                  is_relogin_required,
                                  mark_relogin_required)


def test_cookies_to_netscape():
    text = cookies_to_netscape([
        {'domain': '.youtube.com', 'name': 'SID', 'value': 'abc',
         'path': '/', 'secure': True, 'expiry': 1234567890},
        {'domain': 'youtube.com', 'name': 'HSID', 'value': 'def',
         'path': '/', 'secure': False, 'expiry': None},
        {'domain': 'example.com', 'name': 'IGNORED', 'value': 'x'},
    ])
    lines = text.strip().splitlines()
    assert lines[0] == '# Netscape HTTP Cookie File'
    assert '.youtube.com\tTRUE\t/\tTRUE\t1234567890\tSID\tabc' in lines
    assert 'youtube.com\tFALSE\t/\tFALSE\t0\tHSID\tdef' in lines
    assert 'IGNORED' in text  # helper does not filter domains; service does


def test_relogin_flag():
    clear_relogin_required()
    assert is_relogin_required() is False
    mark_relogin_required()
    assert is_relogin_required() is True
    clear_relogin_required()


def test_service_defaults(monkeypatch):
    monkeypatch.delenv('SELENIUM_URL', raising=False)
    service = YouTubeLoginService()
    assert service.selenium_url == 'http://youtube-login:4444'
    assert service.novnc_port == '7900'
    assert service.novnc_url('media-of-moria:7373') == \
        'http://media-of-moria:7900/'


def test_finish_without_session():
    class Config:
        def get_config(self):
            return {}

        def save_config(self, config):
            return True

    result = YouTubeLoginService().finish(Config())
    assert result['success'] is False

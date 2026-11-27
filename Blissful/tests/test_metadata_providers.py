"""Tests for the optional Discogs metadata and AcoustID verification providers."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.acoustid_client import AcoustIDClient  # noqa: E402
from extend.config_manager import ConfigManager  # noqa: E402
from extend.discogs_client import DiscogsClient  # noqa: E402
from extend.download_manager import DownloadManager  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_new_provider_defaults_are_opt_in():
    cfg = ConfigManager(config_file=str(Path(__file__).parent / 'missing-config.json')).get_config()
    for key in ('discogs_metadata_enabled', 'acoustid_verify_enabled'):
        assert cfg[key] is False
    for key in ('discogs_token', 'discogs_consumer_key', 'discogs_consumer_secret',
                'acoustid_api_key', 'acoustid_user_key', 'acoustid_fpcalc_path'):
        assert cfg[key] == ''
    assert cfg['acoustid_min_score'] == 0.75
    assert all('discog' not in str(p).lower() and 'acoustid' not in str(p).lower()
               for p in cfg['source_priorities'])


def test_env_overrides_for_provider_keys(monkeypatch, tmp_path):
    monkeypatch.setenv('DISCOGS_TOKEN', 'discogs-secret')
    monkeypatch.setenv('ACOUSTID_API_KEY', 'acoustid-app-key')
    monkeypatch.setenv('ACOUSTID_USER_KEY', 'acoustid-user-key')
    monkeypatch.setenv('ACOUSTID_VERIFY_ENABLED', 'true')
    cfg = ConfigManager(config_file=str(tmp_path / 'config.json')).get_config()
    assert cfg['discogs_token'] == 'discogs-secret'
    assert cfg['acoustid_api_key'] == 'acoustid-app-key'
    assert cfg['acoustid_user_key'] == 'acoustid-user-key'
    assert cfg['acoustid_verify_enabled'] is True


def test_validation_masks_kept_secrets_and_drops_metadata_sources(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'discogs_token': 'saved-token',
                                'acoustid_min_score': 0.9}), encoding='utf-8')
    cm = ConfigManager(config_file=str(path))
    out = cm._validate_config({
        'discogs_token': '***KEEP_EXISTING***',
        'acoustid_min_score': 2.0,
        'source_priorities': [
            {'name': 'Discogs', 'search': 'discogs.com', 'enabled': True},
            {'name': 'AcoustID', 'search': 'acoustid.org', 'enabled': True},
            {'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True},
        ],
    })
    assert out['discogs_token'] == 'saved-token'
    assert out['acoustid_min_score'] == 0.9
    assert [s['name'] for s in out['source_priorities']] == ['Bandcamp']


def test_discogs_resolve_and_query(monkeypatch):
    client = DiscogsClient({'discogs_token': 'token'})
    assert client.is_configured()
    monkeypatch.setattr(client, '_throttle', lambda: None)
    monkeypatch.setattr('requests.get', lambda *a, **k: FakeResponse(200, {
        'results': [
            {'title': 'M83 - Before the Dawn Heals Us', 'year': 2005,
             'label': ['Mute'], 'uri': '/release/123', 'id': 123},
        ]}))
    meta = client.resolve_track('M83', 'Lower Your Eyelids',
                                album='Before the Dawn Heals Us', year=2005)
    assert meta['artist'] == 'M83'
    assert meta['album'] == 'Before the Dawn Heals Us'
    assert meta['release_year'] == 2005
    assert meta['external_url'] == 'https://www.discogs.com/release/123'
    query = client.build_search_query(meta)
    assert 'M83' in query and '2005' in query and 'Lower Your Eyelids' in query


def test_discogs_unconfigured_returns_none():
    monkeypatch_env = {}
    for key in ('DISCOGS_TOKEN', 'DISCOGS_CONSUMER_KEY', 'DISCOGS_CONSUMER_SECRET'):
        monkeypatch_env[key] = os.environ.pop(key, None)
    try:
        client = DiscogsClient({})
        assert not client.is_configured()
        assert client.resolve_track('A', 'B') is None
    finally:
        for key, value in monkeypatch_env.items():
            if value is not None:
                os.environ[key] = value


def test_acoustid_fingerprint_and_lookup(monkeypatch):
    client = AcoustIDClient({'acoustid_api_key': 'app-key'})
    monkeypatch.setattr(client, 'fpcalc_path', lambda: '/bin/fpcalc')
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({'FINGERPRINT': 'AQABfake', 'DURATION': 201})))
    fingerprint = client.fingerprint_file('/tmp/song.mp3')
    assert fingerprint == {'fingerprint': 'AQABfake', 'duration': 201}

    monkeypatch.setattr(client, '_throttle', lambda: None)
    monkeypatch.setattr('requests.post', lambda *a, **k: FakeResponse(200, {
        'status': 'ok', 'results': [{
            'id': 'acoustid-id', 'score': 0.96,
            'recordings': [{'id': 'mbid', 'title': 'Lower Your Eyelids',
                            'artists': [{'name': 'M83'}],
                            'releasegroups': [{'title': 'Before the Dawn Heals Us'}]}],
        }]}))
    meta = client.lookup('AQABfake', 201)
    assert meta['score'] == pytest.approx(0.96)
    assert meta['name'] == 'Lower Your Eyelids'
    assert meta['artist'] == 'M83'


def test_acoustid_verify_requires_score_and_matching_metadata(monkeypatch):
    client = AcoustIDClient({'acoustid_api_key': 'k', 'acoustid_min_score': 0.8})
    monkeypatch.setattr(client, 'fingerprint_file', lambda path: {
        'fingerprint': 'fp', 'duration': 100})
    monkeypatch.setattr(client, 'lookup', lambda fp, duration: {
        'score': 0.7, 'name': 'Different Song', 'artist': 'Someone Else'})
    result = client.verify_file('/tmp/x.mp3', artist='M83', title='Lower Your Eyelids')
    assert result['verified'] is False

    monkeypatch.setattr(client, 'lookup', lambda fp, duration: {
        'score': 0.95, 'name': 'lower-your-eyelids!', 'artist': 'M83'})
    result = client.verify_file('/tmp/x.mp3', artist='M83', title='Lower Your Eyelids')
    assert result['verified'] is True


def test_download_manager_uses_discogs_query_and_rejects_bad_acoustid(
        monkeypatch, tmp_path):
    config = {'discogs_metadata_enabled': True, 'acoustid_verify_enabled': True,
              'acoustid_min_score': 0.75}
    discogs = DiscogsClient({'discogs_token': 'token'})
    monkeypatch.setattr(discogs, 'resolve_track', lambda *a, **k: {
        'name': 'Lower Your Eyelids', 'artist': 'M83',
        'album': 'Before the Dawn Heals Us', 'release_year': 2005})
    acoustid = AcoustIDClient({'acoustid_api_key': 'key'})
    monkeypatch.setattr(acoustid, 'verify_file', lambda path, artist=None, title=None: {
        'score': 0.2 if 'bad' in path else 0.98,
        'name': 'Wrong Song' if 'bad' in path else 'Lower Your Eyelids',
        'verified': 'bad' not in path})

    manager = DownloadManager(download_dir=str(tmp_path), config_manager=config,
                              discogs_client=discogs, acoustid_client=acoustid)
    paths = {'bad': tmp_path / 'bad.mp3', 'good': tmp_path / 'good.mp3'}
    for path in paths.values():
        path.write_text('audio', encoding='utf-8')
    tried = []

    def fake_download(source, artist, title, expected_duration=None):
        tried.append(source)
        kind = 'bad' if len(tried) == 1 else 'good'
        return {'success': True, 'file_path': str(paths[kind]), 'duration': 100}

    monkeypatch.setattr(manager, '_download_from_source', fake_download)
    result = manager.download_track(
        'M83', 'Lower Your Eyelids', album='Before the Dawn Heals Us',
        source_priorities=[{'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True},
                           {'name': 'SoundCloud', 'search': 'soundcloud.com', 'enabled': True}])
    assert result['success'] is True
    assert 'M83 - Before the Dawn Heals Us - Lower Your Eyelids' in tried[0]
    assert not paths['bad'].exists(), 'bad candidate should have been deleted'
    assert result['file_path'] == str(paths['good'])
    assert result['acoustid']['score'] == pytest.approx(0.98)

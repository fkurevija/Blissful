"""Tests for the opt-in MusicBrainz metadata provider."""

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.config_manager import ConfigManager  # noqa: E402
from extend.download_manager import DownloadManager  # noqa: E402
from extend.musicbrainz_client import MusicBrainzClient  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_musicbrainz_defaults_off_and_env_enables(tmp_path, monkeypatch):
    cfg = ConfigManager(config_file=str(Path(__file__).parent / 'missing-config.json')).get_config()
    assert cfg['musicbrainz_metadata_enabled'] is False
    monkeypatch.setenv('MUSICBRAINZ_METADATA_ENABLED', 'true')
    enabled = ConfigManager(config_file=str(tmp_path / 'config.json')).get_config()
    assert enabled['musicbrainz_metadata_enabled'] is True
    monkeypatch.delenv('MUSICBRAINZ_METADATA_ENABLED')


def test_musicbrainz_resolve_and_query(monkeypatch):
    client = MusicBrainzClient({})
    assert client.is_configured() is True
    monkeypatch.setattr(client, '_throttle', lambda: None)
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers)
        return FakeResponse({'recordings': [{
            'id': 'recording-id',
            'title': 'Lower Your Eyelids to Die With the Sun',
            'length': 387000,
            'artist-credit': [{'artist': {'name': 'M83'}}],
            'releases': [{'title': 'Before the Dawn Heals Us', 'date': '2005-07-18'}],
        }]})

    monkeypatch.setattr('requests.get', fake_get)
    meta = client.resolve_track('M83', 'Lower Your Eyelids', album='Before the Dawn Heals Us')
    assert captured['params']['fmt'] == 'json'
    assert 'recording:' in captured['params']['query']
    assert 'Blissful' in captured['headers']['User-Agent']
    assert meta['artist'] == 'M83'
    assert meta['album'] == 'Before the Dawn Heals Us'
    assert meta['release_year'] == '2005'
    assert meta['duration_ms'] == 387000
    assert meta['external_url'] == 'https://musicbrainz.org/recording/recording-id'
    query = client.build_search_query(meta)
    assert 'M83' in query and '2005' in query


def test_musicbrainz_picks_closest_duration(monkeypatch):
    client = MusicBrainzClient({})
    monkeypatch.setattr(client, '_throttle', lambda: None)
    monkeypatch.setattr('requests.get', lambda *a, **k: FakeResponse({'recordings': [
        {'title': 'Long version', 'length': 600000, 'artist-credit': []},
        {'title': 'Exact version', 'length': 200000, 'artist-credit': []},
    ]}))
    meta = client.resolve_track('Artist', 'Song', duration_ms=201000)
    assert meta['name'] == 'Exact version'


def test_musicbrainz_is_never_a_download_source(tmp_path):
    cm = ConfigManager(config_file=str(tmp_path / 'config.json'))
    out = cm._validate_config({'source_priorities': [
        {'name': 'MusicBrainz', 'search': 'musicbrainz.org', 'enabled': True},
        {'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True},
    ]})
    assert [s['name'] for s in out['source_priorities']] == ['Bandcamp']

    manager = DownloadManager(download_dir=str(tmp_path))
    sources = manager._build_source_list('A - B', [
        {'name': 'MusicBrainz', 'search': 'musicbrainz.org', 'enabled': True},
        {'name': 'SoundCloud', 'search': 'soundcloud.com', 'enabled': True},
    ])
    assert all('musicbrainz' not in s.lower() for s in sources)
    assert any(s.startswith('scsearch') for s in sources)


def test_download_manager_uses_musicbrainz_query(tmp_path, monkeypatch):
    mb = MusicBrainzClient({})
    monkeypatch.setattr(mb, 'resolve_track', lambda *a, **k: {
        'name': 'Lower Your Eyelids', 'artist': 'M83',
        'album': 'Before the Dawn Heals Us', 'release_year': 2005})
    manager = DownloadManager(
        download_dir=str(tmp_path),
        config_manager={'musicbrainz_metadata_enabled': True},
        musicbrainz_client=mb)
    tried = []
    monkeypatch.setattr(manager, '_download_from_source',
                        lambda source, *a, **k: (tried.append(source), {'success': False})[1])
    manager.download_track('M83', 'Lower Your Eyelids', album='Wrong Album',
                           source_priorities=[
                               {'name': 'SoundCloud', 'search': 'soundcloud.com', 'enabled': True}])
    assert '2005' in tried[0]
    assert 'Wrong Album' not in tried[0]

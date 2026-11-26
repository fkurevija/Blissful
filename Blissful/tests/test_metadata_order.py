"""Tests for metadata-provider ordering and first-match-wins refinement."""

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / 'extend'))

from config_manager import ConfigManager  # noqa: E402
from download_manager import DownloadManager  # noqa: E402


class StubProvider:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def resolve_track(self, *args, **kwargs):
        self.calls.append(self.name)
        return {'name': 'Track', 'artist': 'Artist', 'album': self.name.upper(),
                'release_year': 2005}

    def build_search_query(self, metadata):
        return f"Artist Track {metadata['album']} 2005"


def test_default_order_and_validation(tmp_path):
    cfg = ConfigManager(config_file=str(Path(__file__).parent / 'missing-config.json')).get_config()
    assert cfg['metadata_provider_order'] == [
        'spotify', 'discogs', 'musicbrainz', 'acoustid']
    cm = ConfigManager(config_file=str(tmp_path / 'config.json'))
    cleaned = cm._validate_config({'metadata_provider_order': [
        'musicbrainz', 'bogus', 'musicbrainz', 'spotify']})['metadata_provider_order']
    assert cleaned == ['musicbrainz', 'spotify', 'discogs', 'acoustid']


def test_first_enabled_provider_wins_in_configured_order(tmp_path):
    calls = []
    config = {
        'spotify_metadata_enabled': True,
        'discogs_metadata_enabled': True,
        'musicbrainz_metadata_enabled': True,
        'metadata_provider_order': ['discogs', 'musicbrainz', 'spotify', 'acoustid'],
    }
    manager = DownloadManager(
        download_dir=str(tmp_path), config_manager=config,
        spotify_client=StubProvider('spotify', calls),
        discogs_client=StubProvider('discogs', calls),
        musicbrainz_client=StubProvider('musicbrainz', calls))
    query, source = manager._refine_search_query('Artist', 'Track', album='Old Album')
    assert source == 'discogs'
    assert calls == ['discogs']
    assert 'DISCOGS' in query and 'Old Album' not in query


def test_order_falls_through_when_provider_disabled(tmp_path):
    calls = []
    config = {
        'spotify_metadata_enabled': False,
        'discogs_metadata_enabled': True,
        'musicbrainz_metadata_enabled': True,
        'metadata_provider_order': ['spotify', 'musicbrainz', 'discogs', 'acoustid'],
    }
    manager = DownloadManager(
        download_dir=str(tmp_path), config_manager=config,
        spotify_client=StubProvider('spotify', calls),
        discogs_client=StubProvider('discogs', calls),
        musicbrainz_client=StubProvider('musicbrainz', calls))
    query, source = manager._refine_search_query('Artist', 'Track', album='')
    assert source == 'musicbrainz'
    assert calls == ['musicbrainz']
    assert 'MUSICBRAINZ' in query


def test_acoustid_never_refines_query(tmp_path):
    calls = []
    manager = DownloadManager(
        download_dir=str(tmp_path),
        config_manager={'metadata_provider_order': ['acoustid', 'spotify'],
                        'spotify_metadata_enabled': False},
        spotify_client=StubProvider('spotify', calls))
    query, source = manager._refine_search_query('Artist', 'Track', album='')
    assert source == 'plain'
    assert calls == []
    assert query == 'Artist - Track'

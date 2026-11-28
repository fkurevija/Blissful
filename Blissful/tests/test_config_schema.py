"""Config shape is repaired at load time, not discovered mid-download."""

import json

from extend.config_manager import ConfigManager


def _write(tmp_path, data):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


def test_malformed_source_priorities_are_repaired_on_load(tmp_path):
    path = _write(tmp_path, {'source_priorities': ['youtube', 'soundcloud']})
    cfg = ConfigManager(path).get_config()
    assert cfg['source_priorities'] == []
    assert all(isinstance(entry, dict) for entry in cfg['source_priorities'])


def test_search_depth_is_clamped_on_load(tmp_path):
    cfg = ConfigManager(_write(tmp_path, {'search_results_per_source': 50})).get_config()
    assert 1 <= cfg['search_results_per_source'] <= 10


def test_unknown_metadata_providers_are_dropped_and_deduplicated(tmp_path):
    cfg = ConfigManager(_write(tmp_path, {
        'metadata_provider_order': ['musicbrainz', 'bogus', 'musicbrainz', 'spotify'],
    })).get_config()
    assert cfg['metadata_provider_order'] == ['musicbrainz', 'spotify']


def test_valid_config_survives_unchanged(tmp_path):
    original = {
        'source_priorities': [
            {'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True}],
        'metadata_provider_order': ['discogs', 'musicbrainz'],
        'search_results_per_source': 4,
    }
    cfg = ConfigManager(_write(tmp_path, original)).get_config()
    for key, value in original.items():
        assert cfg[key] == value

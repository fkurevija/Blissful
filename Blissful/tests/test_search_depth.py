"""Tests for the configurable per-source search depth."""

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.config_manager import ConfigManager  # noqa: E402
from extend.download_manager import DownloadManager  # noqa: E402


def test_search_depth_defaults_to_three():
    cfg = ConfigManager(config_file=str(Path(__file__).parent / 'missing-config.json')).get_config()
    assert cfg['search_results_per_source'] == 3
    manager = DownloadManager(download_dir='unused', config_manager=cfg)
    assert manager._search_prefix('ytsearch') == 'ytsearch3:'
    assert manager._search_prefix('scsearch') == 'scsearch3:'


def test_search_depth_clamps_to_supported_range(tmp_path):
    for value, expected in ((1, 'ytsearch1:'), (10, 'ytsearch10:'),
                            (0, 'ytsearch1:'), (99, 'ytsearch10:'),
                            ('bad', 'ytsearch3:')):
        manager = DownloadManager(download_dir=str(tmp_path),
                                  config_manager={'search_results_per_source': value})
        assert manager._search_prefix('ytsearch') == expected


def test_search_depth_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv('SEARCH_RESULTS_PER_SOURCE', '5')
    cfg = ConfigManager(config_file=str(tmp_path / 'config.json')).get_config()
    assert cfg['search_results_per_source'] == 5
    monkeypatch.delenv('SEARCH_RESULTS_PER_SOURCE')


def test_saved_search_depth_is_validated(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'search_results_per_source': 7}), encoding='utf-8')
    cm = ConfigManager(config_file=str(path))
    assert cm._validate_config({'search_results_per_source': 50})['search_results_per_source'] == 7
    assert cm._validate_config({'search_results_per_source': 4})['search_results_per_source'] == 4


def test_source_priorities_use_configured_depth(tmp_path):
    manager = DownloadManager(download_dir=str(tmp_path),
                              config_manager={'search_results_per_source': 4})
    sources = manager._build_source_list('Artist - Title', [
        {'name': 'YouTube Music', 'search': 'music.youtube.com', 'enabled': True},
        {'name': 'SoundCloud', 'search': 'soundcloud.com', 'enabled': True},
        {'name': 'Deezer', 'search': 'deezer.com', 'enabled': True},
    ])
    assert sum(s.startswith('ytsearch4:') for s in sources) == 2  # YTM + Deezer fallback
    assert sum(s.startswith('scsearch4:') for s in sources) == 1
    assert sum(s.startswith('dzsearch4:') for s in sources) == 1

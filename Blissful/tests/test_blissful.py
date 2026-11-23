"""Focused regression tests for the M1-M3 backlog.

Run with:  python -m pytest tests -q
"""

import json
import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from extend.config_manager import ConfigManager  # noqa: E402
from extend.download_manager import DownloadManager  # noqa: E402
from extend.audio_converter import AudioConverter  # noqa: E402
from extend.album_manager import AlbumManager  # noqa: E402
from extend.auth import install_auth  # noqa: E402
from extend.job_manager import JobManager  # noqa: E402
from extend.naming import render_track_filename  # noqa: E402
from extend.bandcamp_resolver import BandcampResolver  # noqa: E402


def test_config_defaults_include_runtime_keys_without_spotify_source():
    cfg = ConfigManager(config_file=str(Path(__file__).parent / 'missing-config.json')).get_config()
    assert cfg['auth_token'] == ''
    assert cfg['enable_pot_provider'] is True
    assert cfg['pot_provider_url'] == 'http://blissful-pot:4416'
    assert cfg['max_duration_deviation'] == 0.10
    assert all('spotify' not in str(p).lower() for p in cfg['source_priorities'])
    assert cfg['spotify_metadata_enabled'] is False


def test_env_overrides_are_applied(monkeypatch, tmp_path):
    monkeypatch.setenv('BLISSFUL_AUTH_TOKEN', 'env-secret')
    monkeypatch.setenv('POT_PROVIDER_URL', 'http://sidecar:9000')
    monkeypatch.setenv('ENABLE_POT_PROVIDER', 'false')
    cfg = ConfigManager(config_file=str(tmp_path / 'config.json')).get_config()
    assert cfg['auth_token'] == 'env-secret'
    assert cfg['pot_provider_url'] == 'http://sidecar:9000'


def test_ydl_opts_include_deno_and_pot_provider(monkeypatch, tmp_path):
    deno = tmp_path / 'deno'
    deno.write_text('fake', encoding='utf-8')
    monkeypatch.setenv('DENO_PATH', str(deno))
    monkeypatch.setenv('POT_PROVIDER_URL', 'http://blissful-pot:4416')
    monkeypatch.delenv('YT_DLP_JS_RUNTIMES', raising=False)
    monkeypatch.delenv('YT_DLP_EXTRACTOR_ARGS', raising=False)
    monkeypatch.delenv('ENABLE_POT_PROVIDER', raising=False)
    manager = DownloadManager(download_dir=str(tmp_path / 'downloads'))
    opts = manager._build_ydl_opts(str(tmp_path / 'song.%(ext)s'))
    assert opts['extractor_args']['youtubepot-bgutilhttp']['base_url'] == [
        'http://blissful-pot:4416']
    assert opts['js_runtimes']['deno']['path'] == str(deno)


def test_pot_provider_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv('ENABLE_POT_PROVIDER', 'false')
    monkeypatch.delenv('YT_DLP_JS_RUNTIMES', raising=False)
    manager = DownloadManager(download_dir=str(tmp_path / 'downloads'))
    opts = manager._build_ydl_opts('out.%(ext)s')
    assert 'youtubepot-bgutilhttp' not in opts.get('extractor_args', {})


def test_source_list_has_no_spotify_and_uses_bandcamp_prefix(tmp_path):
    manager = DownloadManager(download_dir=str(tmp_path / 'downloads'))
    priorities = [
        {'name': 'Spotify', 'search': 'spotify.com', 'enabled': True},
        {'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True},
        {'name': 'YouTube Music', 'search': 'music.youtube.com', 'enabled': True},
    ]
    sources = manager._build_source_list('Artist - Title', priorities)
    assert not any('spotify' in s.lower() for s in sources)
    assert any(s.startswith('bandcamp:') for s in sources)
    assert any('ytsearch' in s for s in sources)


def test_duration_validation():
    assert DownloadManager.is_duration_acceptable(300, 300.12)
    assert not DownloadManager.is_duration_acceptable(371, 300.12)


def test_add_metadata_builds_ffmpeg_command(monkeypatch, tmp_path):
    converter = AudioConverter()
    captured = {}

    class FakeResult:
        returncode = 0
        stderr = ''

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        Path(cmd[-1]).write_bytes(b'tagged')
        return FakeResult()

    monkeypatch.setattr('subprocess.run', fake_run)
    audio = tmp_path / 'song.mp3'
    audio.write_bytes(b'id3')
    ok = converter.add_metadata(
        str(audio), artist='Artist', title='Title', album='Album',
        year='2026', track_number='3', album_artist='Album Artist',
        disc='2', genre='Rock',
    )
    assert ok is True
    cmd = captured['cmd']
    for tag in ('artist=Artist', 'title=Title', 'album=Album', 'date=2026',
                'track=3', 'album_artist=Album Artist', 'disc=2', 'genre=Rock'):
        assert f'-metadata' in cmd and tag in cmd


def test_naming_render_handles_multidisc():
    name = render_track_filename(
        '{track:00} - {title}',
        {'track': 3, 'title': 'Song', 'disc': 2, 'artist': 'A', 'album': 'B'},
    )
    assert name == '02 03 - Song'  # multi-disc tracks get a disc prefix
    tagged = render_track_filename(
        '{disc:00}-{track:00} - {title}',
        {'track': 3, 'title': 'Song', 'disc': 2},
    )
    assert tagged == '02-03 - Song'


def test_empty_album_tracks_is_success():
    class Config:
        def get_config(self):
            return {'lidarr_url': 'http://lidarr:8686', 'lidarr_api_key': 'key'}

    class Client:
        def __init__(self, **kwargs):
            pass

        def get_album_tracks(self, album_id):
            return []

    result = AlbumManager(Config(), Client, None, None).get_album_tracks(1)
    assert result['success'] is True
    assert result['tracks'] == []
    assert result['total'] == 0


def test_bandcamp_resolver_never_returns_search_page(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ('<a class="search-item" href="https://artist.bandcamp.com/track/real-song">'
                'Real Song</a>')

    monkeypatch.setattr('requests.get', lambda *a, **k: FakeResponse())
    url = BandcampResolver().resolve('artist real song')
    assert url and '/track/' in url
    assert 'search?q=' not in url


def test_auth_gates_api_but_not_health(monkeypatch, tmp_path):
    from flask import Flask, jsonify
    from extend.routes import register_routes

    monkeypatch.setenv('BLISSFUL_AUTH_TOKEN', 'topsecret')
    cfg = ConfigManager(config_file=str(tmp_path / 'config.json'))
    app = Flask(__name__)
    install_auth(app, cfg)

    class Stub:
        def __init__(self, *a, **k):
            pass

        def check_ffmpeg(self):
            return True

        def check_ytdlp(self):
            return True

        def check_runtime_health(self):
            return {'js_runtime_available': False, 'pot_provider_reachable': False}

    register_routes(
        app=app, config_manager=cfg, lidarr_client=Stub,
        download_manager=Stub(), audio_converter=Stub(), source_manager=Stub(),
        auth_manager=Stub(), request_manager=Stub(), album_manager=Stub(),
        track_manager=Stub(), sources_api=Stub(), system_utils=Stub(),
        job_manager=None,
    )
    with app.test_client() as client:
        cross_site = {'Origin': 'https://evil.example'}
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/config', headers=cross_site).status_code == 401
        ok = dict(cross_site, Authorization='Bearer topsecret')
        assert client.get('/api/config', headers=ok).status_code == 200
        assert client.post('/api/config', json={}, headers=cross_site).status_code == 401
        # The bundled UI is same-origin and needs no token header.
        assert client.get('/api/config', headers={'Origin': 'http://localhost'}).status_code == 200


def test_job_queue_dedupe_and_retry(tmp_path):
    class Config:
        def get_setting(self, key, default=None):
            return 7 if key == 'job_retention_days' else default

    class Albums:
        def download_album(self, **kwargs):
            return {'success': True, 'successful': 1, 'failed': 0, 'total_tracks': 1}

    manager = JobManager(Config(), Albums(), str(tmp_path / 'jobs.json'))
    job, dup = manager.enqueue('album', {'artist': 'A', 'album': 'B', 'tracks': []})
    again, dup2 = manager.enqueue('album', {'artist': 'A', 'album': 'B', 'tracks': []})
    assert dup is False and dup2 is True
    assert again['id'] == job['id']
    assert manager.get_job(job['id'])['status'] == 'pending'
    assert len(manager.list_jobs()) == 1


def test_userscript_injects_token_and_server_url(tmp_path):
    from extend.system_utils import SystemUtils

    cfg_file = tmp_path / 'config.json'
    cfg_file.write_text(json.dumps({'auth_token': 'script-token'}), encoding='utf-8')
    cfg = ConfigManager(config_file=str(cfg_file))
    script, error = SystemUtils(cfg).generate_userscript('http://blissful.local:7373')
    assert error is None
    assert 'authToken: "script-token"' in script
    assert 'microserviceUrl: "http://blissful.local:7373"' in script
    assert '${CONFIG.authToken}' in script


def test_source_manager_never_advertises_spotify():
    from extend.source_manager import SourceManager

    manager = SourceManager()
    sources = manager.get_all_extractors()
    assert sources, "expected yt-dlp extractors to load"
    assert not any('spotify' in (s['name'] + s['ie_key']).lower() for s in sources)
    assert manager.search_extractors('spotify') == []


def test_saved_spotify_priority_is_dropped(tmp_path):
    cfg_file = tmp_path / 'config.json'
    cfg_file.write_text(json.dumps({
        'source_priorities': [
            {'name': 'YouTube', 'search': 'youtube.com', 'enabled': True},
            {'name': 'Spotify', 'search': 'spotify.com', 'enabled': True},
        ]
    }), encoding='utf-8')
    cfg = ConfigManager(config_file=str(cfg_file))
    merged = cfg.get_config()
    assert cfg.save_config(merged)
    assert all('spotify' not in str(p).lower() for p in cfg.get_config()['source_priorities'])


def test_security_card_lives_inside_tools_tab():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / 'templates' / 'tabs' /
                'tools_tab.html').read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    tab_start = template.index('<div id="tools-tab"')
    style_start = template.index('\n<style>')
    assert tab_start < template.index('API Security') < style_start

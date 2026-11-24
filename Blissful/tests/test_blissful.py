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


def test_job_queue_cancel_pending_and_running(tmp_path):
    class Config:
        def get_setting(self, key, default=None):
            return default

    class Albums:
        def download_album(self, **kwargs):
            return {'success': True, 'successful': 1, 'failed': 0, 'total_tracks': 1}

    manager = JobManager(Config(), Albums(), str(tmp_path / 'jobs.json'))
    pending, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B', 'tracks': []})
    assert manager.cancel_job(pending['id']) is True
    assert manager.get_job(pending['id'])['status'] == 'cancelled'

    # Cannot cancel an already-terminal job.
    assert manager.cancel_job(pending['id']) is False
    assert manager.delete_job(pending['id']) is True
    assert manager.get_job(pending['id']) is None

    # clear_finished removes cancelled jobs.
    running, _ = manager.enqueue('album', {'artist': 'C', 'album': 'D', 'tracks': []})
    manager.jobs[0]['status'] = 'running'
    manager._persist()
    assert manager.cancel_job(running['id']) is True
    removed = manager.clear_finished()
    assert removed >= 1
    assert [j['status'] for j in manager.list_jobs()] == []


def test_userscript_injects_token_and_server_url(tmp_path):
    from extend.system_utils import SystemUtils

    cfg_file = tmp_path / 'config.json'
    cfg_file.write_text(json.dumps({'auth_token': 'script-token'}), encoding='utf-8')
    cfg = ConfigManager(config_file=str(cfg_file))
    script, error = SystemUtils(cfg).generate_userscript('http://blissful.local:7373')
    assert error is None
    assert 'authToken: "script-token"' in script
    assert 'DEFAULT_MICROSERVICE_URL = "http://blissful.local:7373"' in script
    assert 'microserviceUrl: DEFAULT_MICROSERVICE_URL' in script
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


def test_naming_preserves_vinyl_positions_and_drops_empty_year():
    from extend.naming import render_track_filename

    name = render_track_filename(
        '{Artist Name}/{Album Title} ({Release Year})/{track:00} - {Track Title}',
        {'artist': 'A', 'album': 'B', 'year': '', 'track': 'A1', 'title': 'Song'},
    )
    assert 'A1 - Song' in name
    assert '()' not in name


def test_naming_supports_lidarr_medium_tokens():
    from extend.naming import render_track_filename

    name = render_track_filename(
        '{medium:00}-{track:00} - {Track Title} [{Medium Format}]',
        {'disc': 2, 'track': 3, 'title': 'Song', 'mediumFormat': 'LP'},
    )
    assert name == '02-03 - Song [LP]'


def test_lidarr_queue_is_paginated(monkeypatch):
    from extend.lidarr_client import LidarrClient

    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            page = calls[-1]['params']['page']
            size = calls[-1]['params']['pageSize']
            count = 250
            start = (page - 1) * size
            return {'totalRecords': count, 'records': [{'id': i} for i in range(start, min(start + size, count))]}

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr('requests.get', fake_get)
    client = LidarrClient('http://lidarr:8686', 'key')
    records = client.get_all_queue_records(page_size=200)
    assert len(records) == 250
    assert [c['params']['page'] for c in calls] == [1, 2]


def test_lidarr_post_and_poll_command(monkeypatch):
    from extend.lidarr_client import LidarrClient

    posted = {}

    class FakeResponse:
        status_code = 201

        def json(self):
            return {'id': 77, 'status': 'queued'}

    def fake_post(url, **kwargs):
        posted['json'] = kwargs['json']
        return FakeResponse()

    def fake_get(url, **kwargs):
        class Poll:
            status_code = 200

            def json(self):
                return {'id': 77, 'status': 'completed'}
        return Poll()

    monkeypatch.setattr('requests.post', fake_post)
    monkeypatch.setattr('requests.get', fake_get)
    client = LidarrClient('http://lidarr:8686', 'key')
    assert client.post_command('ManualImport', files=[], importMode=2)['id'] == 77
    assert posted['json']['name'] == 'ManualImport'
    assert client.get_command(77)['status'] == 'completed'


def test_album_places_files_at_exact_target(tmp_path, monkeypatch):
    from extend.album_manager import AlbumManager

    class Config:
        def get_config(self):
            return {'output_format': 'mp3', 'quality': '320k', 'lidarr_path_mapping': {}}

    class Client:
        def __init__(self, **kwargs):
            pass

    class Downloads:
        def __init__(self):
            self.moves = []

        def download_track(self, **kwargs):
            return {'success': True, 'file_path': str(tmp_path / 'src.mp3')}

        def _sanitize_filename(self, name):
            return name

        def move_to_target(self, source_file, target_path, path_mapping=None):
            self.moves.append(target_path)
            return target_path

    class Converter:
        def convert(self, **kwargs):
            return kwargs['input_file']

        def add_metadata(self, *a, **k):
            return True

    downloads = Downloads()
    result = AlbumManager(Config(), Client, downloads, Converter()).download_album(
        'Artist', 'Album',
        [{'title': 'Song', 'target_path': '/media/Music/Artist/Album/01 - Song.mp3'}],
    )
    assert result['success'] is True
    assert downloads.moves == ['/media/Music/Artist/Album/01 - Song.mp3']


def _failed_imports_fixtures():
    queue = [
        {'albumId': 10, 'downloadId': 'd1', 'title': 'healthy candidate',
         'errorMessage': 'The download is stalled with no connections'},
        {'albumId': 10, 'downloadId': 'd1', 'title': 'duplicate',
         'errorMessage': 'The download is stalled with no connections'},
        {'albumId': 11, 'downloadId': 'd2', 'title': 'compilation',
         'errorMessage': 'Sequence contains no matching element'},
    ]
    album = {
        'id': 10, 'title': 'Aeolian', 'monitored': True, 'releaseYear': 2026,
        'artist': {'id': 5, 'artistName': 'The Ocean',
                   'path': '/media/Music/The Ocean'},
        'releases': [{'id': 99, 'monitored': True, 'trackCount': 1}],
    }
    tracks = [{'id': 101, 'title': 'Swoon', 'trackNumber': '8',
               'duration': 300120, 'hasFile': False, 'mediumNumber': 1}]
    return queue, album, tracks


def test_failed_imports_dry_run_filters_and_renders_targets(tmp_path, monkeypatch):
    from extend.failed_imports import FailedImportsRetry

    queue, album, tracks = _failed_imports_fixtures()

    class Client:
        def get_all_queue_records(self, page_size=200):
            return queue

        def get_naming_config(self):
            return {'standardTrackFormat':
                    '{Artist Name}/{Album Title} ({Release Year})/{track:00} - {Track Title}'}

        def get_album(self, aid):
            return album

        def get_album_tracks(self, aid):
            return tracks

        def post_command(self, *a, **k):
            raise AssertionError('dry run must not import')

    class Config:
        def get_config(self):
            return {'output_format': 'mp3', 'lidarr_path_mapping': {}}

    class Jobs:
        def enqueue(self, *a, **k):
            raise AssertionError('dry run must not enqueue')

    retry = FailedImportsRetry(Config(), Client(), None, None, Jobs(),
                               state_path=str(tmp_path / 'state.json'))
    report = retry.run()
    assert report['queue_total'] == 3
    assert report['failures'] == 2  # duplicate removed
    assert len(report['unsupported']) == 1
    assert report['albums'][0]['status'] == 'dry-run'
    assert report['albums'][0]['sent'] == 1
    # target path rendered from Lidarr naming template, not torrent title
    assert not hasattr(retry, '_last_payload')


def test_failed_imports_apply_verifies_and_records_state(tmp_path, monkeypatch):
    from extend.failed_imports import FailedImportsRetry

    queue, album, tracks = _failed_imports_fixtures()
    calls = {}

    class Client:
        def get_all_queue_records(self, page_size=200):
            return queue

        def get_naming_config(self):
            return {'standardTrackFormat': '{track:00} - {Track Title}'}

        def get_album(self, aid):
            return album

        def get_album_tracks(self, aid):
            return tracks

        def post_command(self, name, **body):
            calls['command'] = (name, body)
            return {'id': 77}

        def get_command(self, cid):
            return {'status': 'completed'}

    class Config:
        def get_config(self):
            return {'output_format': 'mp3', 'lidarr_path_mapping': {}}

    class Jobs:
        def __init__(self):
            self.payload = None

        def enqueue(self, kind, payload, **kwargs):
            self.payload = payload
            return {'id': 'job-1'}, False

        def get_job(self, jid):
            return {'id': jid, 'status': 'succeeded',
                    'result': {'successful': 1, 'failed': 0}}

    jobs = Jobs()
    retry = FailedImportsRetry(Config(), Client(), None, None, jobs,
                               state_path=str(tmp_path / 'state.json'))
    monkeypatch.setattr('os.path.exists', lambda p: True)
    monkeypatch.setattr(retry, '_ffprobe', lambda p: {
        'format': {'duration': '300.12', 'tags': {
            'title': 'Swoon', 'artist': 'The Ocean',
            'album_artist': 'The Ocean', 'album': 'Aeolian',
            'track': '8/11', 'disc': '1/1', 'date': '2026'}}})

    report = retry.run(apply=True)
    assert report['albums'][0]['status'] == 'succeeded'
    assert jobs.payload['tracks'][0]['duration'] == 300120
    name, body = calls['command']
    assert name == 'ManualImport'
    assert body['files'][0]['trackIds'] == [101]
    assert body['files'][0]['albumReleaseId'] == 99
    assert body['importMode'] == 2
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert '10' in state

    # A second run must not re-send the album.
    report2 = retry.run(apply=True)
    assert report2['albums'][0]['status'] == 'skipped'
    assert 'already recorded' in report2['albums'][0]['reason']


def test_failed_imports_rejects_bad_duration(tmp_path):
    from extend.failed_imports import FailedImportsRetry

    assert FailedImportsRetry._duration_ok(300.12, 300120)
    assert not FailedImportsRetry._duration_ok(7929, 452000)
    assert not FailedImportsRetry._duration_ok(None, 300120)
    tags = {'title': 'T', 'artist': 'A', 'album_artist': 'A',
            'album': 'B', 'track': '1', 'disc': '1', 'date': '2026'}
    assert FailedImportsRetry._tags_ok(tags)
    assert not FailedImportsRetry._tags_ok({k: v for k, v in tags.items()
                                            if k != 'date'})
    assert FailedImportsRetry._tags_ok(
        {k: v for k, v in tags.items() if k != 'date'}, require_date=False)


def test_failed_imports_reset_clears_state(tmp_path):
    from extend.failed_imports import FailedImportsRetry

    state = tmp_path / 'state.json'
    state.write_text('{"10": {}}', encoding='utf-8')
    retry = FailedImportsRetry(None, None, None, None, None, state_path=str(state))
    report = retry.run(reset=True)
    assert report['reset'] is True
    assert not state.exists()


def test_config_has_wanted_search_defaults(tmp_path):
    cfg = ConfigManager(config_file=str(tmp_path / 'config.json')).get_config()
    assert cfg['wanted_search_enabled'] is False
    assert cfg['stale_cleanup_enabled'] is False
    assert cfg['stale_cleanup_interval_hours'] == 6
    assert cfg['stale_cleanup_wait_minutes'] == 10
    assert cfg['prefer_blissful_for_stale'] is True
    assert cfg['gapfill_job_timeout_minutes'] == 15
    assert cfg['stale_cleanup_remove_from_client'] is True
    assert cfg['wanted_search_timeout_minutes'] == 10
    assert cfg['prefer_blissful_for_wanted'] is True


def test_lidarr_wanted_and_queue_delete(monkeypatch):
    from extend.lidarr_client import LidarrClient

    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {'totalRecords': 0, 'records': []}

    class FakeDelete:
        status_code = 204

    def fake_get(url, **kwargs):
        calls.append(('get', kwargs.get('params')))
        return FakeResponse()

    def fake_delete(url, **kwargs):
        calls.append(('delete', url, kwargs.get('params')))
        return FakeDelete()

    monkeypatch.setattr('requests.get', fake_get)
    monkeypatch.setattr('requests.delete', fake_delete)
    client = LidarrClient('http://lidarr:8686', 'key')
    client.get_wanted_missing(page=2, page_size=50)
    result = client.delete_queue_item(123)
    assert result['success'] is True
    assert calls[0] == ('get', {'page': 2, 'pageSize': 50,
                                'sortKey': 'releaseDate',
                                'sortDirection': 'descending'})
    assert calls[1][0] == 'delete'
    assert calls[1][1].endswith('/api/v1/queue/123')
    assert calls[1][2] == {'removeFromClient': True, 'blocklist': False,
                           'skipRedownload': True, 'changeCategory': False}


def _wanted_service(tmp_path, enabled=True, client=None, gapfill=None,
                    prefer_gapfill=True):
    from extend.wanted_search import WantedSearchService

    class Config:
        def get_config(self):
            return {
                'wanted_search_enabled': enabled,
                'stale_cleanup_enabled': False,
                'stale_cleanup_interval_hours': 6,
                'stale_cleanup_wait_minutes': 10,
                'prefer_blissful_for_stale': prefer_gapfill,
                'wanted_search_timeout_minutes': 10,
                'prefer_blissful_for_wanted': True,
                'stale_cleanup_remove_from_client': True,
            }

    svc = WantedSearchService(Config(), client or object(),
                              str(tmp_path / 'wanted-state.json'),
                              gapfill=gapfill)
    if client is not None:
        svc._client = client
    return svc


def test_wanted_search_dry_run_and_gate(tmp_path):
    class Client:
        def get_wanted_missing(self, page=1, page_size=200):
            return {'totalRecords': 2, 'records': [
                {'id': 1, 'title': 'One', 'artist': {'artistName': 'A'}},
                {'id': 2, 'title': 'Two', 'artist': {'artistName': 'B'}},
            ]}

    svc = _wanted_service(tmp_path, enabled=True, client=Client())
    report = svc.search(album_ids=[1, 2], apply=False)
    assert report['success'] is True
    assert report['applied'] is False
    assert report['count'] == 2
    assert 'dry run' in report['note']

    disabled = _wanted_service(tmp_path, enabled=False)
    blocked = disabled.search(apply=True)
    assert blocked['success'] is False
    assert 'disabled' in blocked['error']


def test_wanted_search_apply_posts_commands(tmp_path):
    calls = []

    class Client:
        def get_wanted_missing(self, page=1, page_size=200):
            return {'totalRecords': 1, 'records': [{
                'id': 3, 'title': 'Still Missing',
                'artist': {'artistName': 'Artist'}, 'albumType': 'Album',
                'releaseDate': '2026-01-01T00:00:00Z', 'monitored': True,
            }]}

        def get_album_tracks(self, aid):
            return [{'id': 1, 'hasFile': False}]

        def post_command(self, name, **body):
            calls.append((name, body))
            return {'id': 42}

        def get_command(self, cid):
            return {'id': cid, 'status': 'completed', 'message': '0 reports downloaded'}

    class Gapfill:
        def gapfill_album(self, aid, apply=True, source='', progress=None, **kwargs):
            calls.append(('gapfill', aid, source))
            return {'status': 'succeeded', 'imported': 1}

    svc = _wanted_service(tmp_path, client=Client(), gapfill=Gapfill())
    selected = svc.search(album_ids=['3', 'bad'], apply=True)
    assert selected['command_id'] == 42
    assert selected['command_status'] == 'completed'
    assert calls[0] == ('AlbumSearch', {'albumIds': [3]})
    assert ('gapfill', 3, 'wanted-search-fallback') in calls
    assert selected['fallback'][0]['status'] == 'succeeded'

    all_report = svc.search(apply=True)
    assert all_report['mode'] == 'all'
    assert ('MissingAlbumSearch', {}) in calls


def test_stale_cleanup_deletes_only_after_import(tmp_path, monkeypatch):
    import extend.wanted_search as wanted_mod

    monkeypatch.setattr(wanted_mod.time, 'sleep', lambda *a, **k: None)

    calls = []
    track_calls = {'n': 0}

    class Client:
        def get_all_queue_records(self, page_size=200):
            return [
                {'id': 11, 'albumId': 10, 'downloadId': 'd1',
                 'title': 'Stalled album',
                 'errorMessage': 'The download is stalled with no connections'},
                {'id': 12, 'albumId': 20, 'downloadId': 'd2',
                 'title': 'Healthy', 'errorMessage': ''},
            ]

        def get_album_tracks(self, aid):
            track_calls['n'] += 1
            return [{'id': 1, 'hasFile': False}]

        def post_command(self, name, **body):
            calls.append(('search', name, body))
            return {'id': 77}

        def get_command(self, cid):
            return {'id': cid, 'status': 'completed'}

        def delete_queue_item(self, rid, **kwargs):
            calls.append(('delete', rid, kwargs))
            return {'success': True}

    class Gapfill:
        def gapfill_album(self, aid, apply=True, source='', progress=None, **kwargs):
            calls.append(('gapfill', aid, apply, source))
            return {'status': 'succeeded', 'imported': 1}

    svc = _wanted_service(tmp_path, client=Client(), gapfill=Gapfill())
    stale = svc.get_stale()
    assert [record['id'] for record in stale] == [11]

    dry = svc.cleanup_stale(apply=False)
    assert dry['counts']['deleted'] == 0
    assert not any(c[0] == 'delete' for c in calls)

    applied = svc.cleanup_stale(apply=True, wait_minutes=1)
    assert applied['counts']['imported'] == 1
    assert applied['counts']['deleted'] == 1
    assert calls[0] == ('gapfill', 10, True, 'stale-cleanup')
    assert not any(c[0] == 'search' for c in calls)
    assert calls[-1][0] == 'delete' and calls[-1][1] == 11

    again = svc.cleanup_stale(apply=True, wait_minutes=1)
    assert again['counts']['deleted'] == 0
    assert any('already recorded' in str(s) for s in again['skipped'])


def test_get_stale_resolves_album_metadata_from_lidarr(tmp_path):
    """Queue rows carry only albumId; stale list must show artist/album.

    The raw torrent title (often a hash) is kept separately.
    """
    class Client:
        def get_all_queue_records(self, page_size=200):
            return [{'id': 11, 'albumId': 18768, 'downloadId': 'd1',
                     'title': '4c492c3fb526923bd80a487a4cf6e1098d951bbf',
                     'errorMessage': 'qBittorrent is downloading metadata'}]

        def get_album(self, aid):
            return {'title': 'The Best Of Blue Öyster Cult',
                    'artist': {'artistName': 'Blue Öyster Cult'}}

    svc = _wanted_service(tmp_path, client=Client())
    stale = svc.get_stale()
    assert len(stale) == 1
    assert stale[0]['artist'] == 'Blue Öyster Cult'
    assert stale[0]['albumTitle'] == 'The Best Of Blue Öyster Cult'
    assert stale[0]['title'] == 'The Best Of Blue Öyster Cult'
    assert stale[0]['downloadTitle'].startswith('4c492c3f')


def test_get_stale_only_uses_activity_queue_records(tmp_path):
    """Stale detection must ignore anything that is not a live queue download.

    Every candidate comes from GET /api/v1/queue and must carry Lidarr's
    queue id and downloadId; history-style records are excluded.
    """
    class Client:
        def get_all_queue_records(self, page_size=200):
            return [
                # genuine activity-queue download (unhealthy)
                {'id': 11, 'albumId': 10, 'downloadId': 'd1',
                 'title': 'Stalled',
                 'errorMessage': 'The download is stalled with no connections'},
                # history-style record: no queue id / downloadId -> ignored
                {'albumId': 99, 'title': 'Old history item',
                 'errorMessage': 'The download is stalled with no connections'},
                # another queue item missing downloadId -> ignored
                {'id': 12, 'albumId': 88,
                 'errorMessage': 'The download is stalled with no connections'},
                # healthy queue item -> not unhealthy
                {'id': 13, 'albumId': 77, 'downloadId': 'd3',
                 'title': 'Healthy', 'errorMessage': ''},
            ]

    svc = _wanted_service(tmp_path, client=Client())
    stale = svc.get_stale()
    assert [record['id'] for record in stale] == [11]
    assert all(record.get('downloadId') for record in stale)

def test_cli_json_only_emits_pure_json():
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env['WANTED_SEARCH_ENABLED'] = 'true'
    result = subprocess.run(
        [sys.executable, 'Blissful.py', '--wanted-search', '--json-only'],
        cwd=str(APP_DIR), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=30
    )
    payload = json.loads(result.stdout)
    assert payload['success'] is True
    assert payload['applied'] is False


def test_wanted_service_tracks_active_run(tmp_path):
    svc = _wanted_service(tmp_path)
    assert svc.get_active() is None
    svc._set_active(kind='cleanup', phase='searching', scanned=2)
    active = svc.get_active()
    assert active['kind'] == 'cleanup'
    assert active['phase'] == 'searching'
    svc._finish_active('completed')
    assert svc.get_active() is None
    assert svc.get_last_activity()['status'] == 'completed'


def test_wanted_status_route_exposes_progress():
    from flask import Flask
    from extend.routes import register_routes

    class Stub:
        def __init__(self, *a, **k):
            pass

    class Config:
        def get_config(self):
            return {'wanted_search_enabled': True, 'stale_cleanup_enabled': False,
                    'stale_cleanup_interval_hours': 6,
                    'stale_cleanup_wait_minutes': 10}

    class Wanted:
        def get_active(self):
            return {'kind': 'cleanup', 'phase': 'waiting for import', 'searched': 1}

        def get_last_activity(self):
            return None

    app = Flask(__name__)
    register_routes(app=app, config_manager=Config(), lidarr_client=Stub,
                    download_manager=Stub(), audio_converter=Stub(),
                    source_manager=Stub(), auth_manager=Stub(),
                    request_manager=Stub(), album_manager=Stub(),
                    track_manager=Stub(), sources_api=Stub(), system_utils=Stub(),
                    job_manager=None, wanted_search=Wanted())
    with app.test_client() as client:
        data = client.get('/api/wanted/status').get_json()
    assert data['active']['phase'] == 'waiting for import'


def test_wanted_single_flight_blocks_second_run(tmp_path):
    svc = _wanted_service(tmp_path, client=object())
    assert svc._run_lock.acquire(blocking=False) is True
    try:
        blocked = svc.search()
        assert blocked['already_running'] is True
        assert 'already running' in blocked['error']
    finally:
        svc._run_lock.release()
    again = _wanted_service(tmp_path, client=object()).search()
    assert not again.get('already_running', False)


def test_wanted_search_route_returns_409_when_busy():
    from flask import Flask
    from extend.routes import register_routes

    class Stub:
        def __init__(self, *a, **k):
            pass

    class Config:
        def get_config(self):
            return {'wanted_search_enabled': True, 'stale_cleanup_enabled': False}

    class BusyWanted:
        def search(self, **kwargs):
            return {'success': False, 'already_running': True,
                    'error': 'A wanted search or cleanup is already running',
                    'active': {'kind': 'cleanup'}}

    app = Flask(__name__)
    register_routes(app=app, config_manager=Config(), lidarr_client=Stub,
                    download_manager=Stub(), audio_converter=Stub(),
                    source_manager=Stub(), auth_manager=Stub(),
                    request_manager=Stub(), album_manager=Stub(),
                    track_manager=Stub(), sources_api=Stub(), system_utils=Stub(),
                    job_manager=None, wanted_search=BusyWanted())
    with app.test_client() as client:
        response = client.post('/api/wanted/search', json={'apply': False})
    assert response.status_code == 409
    assert response.get_json()['already_running'] is True


def test_stale_cleanup_can_use_lidarr_search_when_flag_false(tmp_path, monkeypatch):
    import extend.wanted_search as wanted_mod

    monkeypatch.setattr(wanted_mod.time, 'sleep', lambda *a, **k: None)
    calls = []

    class Client:
        def __init__(self):
            self.track_calls = 0

        def get_all_queue_records(self, page_size=200):
            return [{'id': 11, 'albumId': 10, 'downloadId': 'd1',
                     'title': 'Stalled',
                     'errorMessage': 'The download is stalled with no connections'}]

        def get_album_tracks(self, aid):
            self.track_calls += 1
            return [{'id': 1, 'hasFile': self.track_calls > 1}]

        def post_command(self, name, **body):
            calls.append((name, body))
            return {'id': 77}

        def get_command(self, cid):
            return {'status': 'completed'}

        def delete_queue_item(self, rid, **kwargs):
            calls.append(('delete', rid))
            return {'success': True}

    svc = _wanted_service(tmp_path, client=Client(), prefer_gapfill=False)
    report = svc.cleanup_stale(apply=True, wait_minutes=1)
    assert calls[0] == ('AlbumSearch', {'albumIds': [10]})
    assert report['counts']['deleted'] == 1


def test_gapfill_job_poll_reports_progress(monkeypatch):
    import extend.failed_imports as failed_mod
    from extend.failed_imports import FailedImportsRetry

    monkeypatch.setattr(failed_mod.time, 'sleep', lambda *a, **k: None)

    class Config:
        def get_config(self):
            return {'output_format': 'mp3', 'gapfill_job_timeout_minutes': 15}

    class Jobs:
        def __init__(self):
            self.n = 0

        def get_job(self, jid):
            self.n += 1
            return {'status': 'succeeded' if self.n > 1 else 'running'}

    phases = []
    svc = FailedImportsRetry(Config(), object(), None, None, Jobs())
    result = svc._poll_job('job-1',
                           progress=lambda phase, **kw: phases.append(phase),
                           timeout_s=5)
    assert result['status'] == 'succeeded'
    assert 'download job running' in phases


def test_download_manager_reports_source_attempts(monkeypatch, tmp_path):
    manager = DownloadManager(download_dir=str(tmp_path / 'downloads'))
    manager.reset_download_progress()

    calls = {'n': 0}

    def fake_download(source, artist, title, expected_duration=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return {'success': False, 'error': 'DRM protected'}
        return {'success': True, 'file_path': str(tmp_path / 'song.mp3'),
                'duration': 180.0}

    monkeypatch.setattr(manager, '_download_from_source', fake_download)
    result = manager.download_track(
        'Artist', 'Song', album='Album',
        source_priorities=[{'name': 'YouTube Music', 'search': 'music.youtube.com',
                            'enabled': True},
                           {'name': 'SoundCloud', 'search': 'soundcloud.com',
                            'enabled': True}],
    )
    assert result['success'] is True
    progress = manager.get_download_progress()
    assert progress['title'] == 'Song'
    assert progress['album'] == 'Album'
    assert [a['status'] for a in progress['attempts']] == ['failed', 'success']
    assert progress['status'] == 'downloaded'


def test_wanted_list_exposes_artist_type_and_release(tmp_path):
    from extend.wanted_search import WantedSearchService

    class Client:
        def get_wanted_missing(self, page=1, page_size=200):
            return {'totalRecords': 1, 'records': [{
                'id': 77, 'artistId': 5,
                'artist': {'artistName': 'The Ocean'},
                'title': 'Aeolian', 'albumType': 'Album',
                'secondaryTypes': ['Compilation'],
                'releaseDate': '2026-01-02T00:00:00Z', 'monitored': True,
            }]}

    class Config:
        def get_config(self):
            return {'wanted_search_enabled': True}

    svc = WantedSearchService(Config(), Client(), str(tmp_path / 'state.json'))
    svc._client = Client()
    items = svc.get_wanted()
    assert items[0]['artist'] == 'The Ocean'
    assert items[0]['albumType'] == 'Album'
    assert items[0]['secondaryTypes'] == ['Compilation']
    assert items[0]['releaseDate'] == '2026-01-02T00:00:00Z'
    assert items[0]['albumId'] == 77


def test_stale_item_with_no_missing_tracks_is_skipped_with_reason(tmp_path, monkeypatch):
    import extend.wanted_search as wanted_mod

    monkeypatch.setattr(wanted_mod.time, 'sleep', lambda *a, **k: None)

    class Client:
        def get_all_queue_records(self, page_size=200):
            return [{'id': 11, 'albumId': 1746, 'downloadId': 'd1',
                     'title': 'Deftones - Gore',
                     'errorMessage': 'The download is stalled with no connections'}]

        def get_album_tracks(self, aid):
            return [{'id': 1, 'hasFile': True}]

        def post_command(self, *a, **k):
            raise AssertionError('nothing should be searched')

        def delete_queue_item(self, *a, **k):
            raise AssertionError('nothing should be deleted')

    svc = _wanted_service(tmp_path, client=Client(), gapfill=object())
    report = svc.cleanup_stale(apply=True)
    assert report['counts']['kept'] == 0
    assert report['counts']['deleted'] == 0
    assert report['skipped'][0]['reason'] == 'no missing tracks in Lidarr'


def test_wanted_search_creates_downloads_job(tmp_path):
    from extend.wanted_search import WantedSearchService

    class Config:
        def get_config(self):
            return {'wanted_search_enabled': True,
                    'wanted_search_timeout_minutes': 10,
                    'prefer_blissful_for_wanted': True}

    class Client:
        def get_wanted_missing(self, page=1, page_size=200):
            return {'totalRecords': 1, 'records': [{
                'id': 9, 'title': 'Album', 'artist': {'artistName': 'Artist'}}]}

        def get_album_tracks(self, aid):
            return [{'id': 1, 'hasFile': False}]

        def post_command(self, name, **body):
            return {'id': 5}

        def get_command(self, cid):
            return {'id': cid, 'status': 'completed', 'message': 'ok'}

    class Gapfill:
        def gapfill_album(self, aid, apply=True, source='', progress=None, **kwargs):
            return {'status': 'succeeded', 'imported': 1}

    class Jobs:
        def __init__(self):
            self.record = {}

        def enqueue(self, kind, payload, dedupe_key=None, **kwargs):
            self.record = {'id': 'job-1', 'kind': kind, 'payload': payload,
                           'status': 'pending'}
            return self.record, False

        def update_job(self, job_id, **changes):
            self.record.update(changes)
            return self.record

    jobs = Jobs()
    svc = WantedSearchService(Config(), Client(), str(tmp_path / 'state.json'),
                              gapfill=Gapfill(), job_manager=jobs)
    svc._client = Client()
    result = svc.search(apply=True)
    assert result['success'] is True
    assert jobs.record['kind'] == 'search'
    assert jobs.record['status'] == 'succeeded'
    assert jobs.record['progress']['phase'] == 'search finished'
    assert jobs.record['result']['blissful_fallback'] == 1


def test_cancel_active_stops_run_and_job(tmp_path):
    from extend.wanted_search import WantedSearchService

    class Config:
        def get_config(self):
            return {'wanted_search_enabled': True}

    class Jobs:
        def __init__(self):
            self.items = [{'id': 'j', 'status': 'running'}]

        def list_jobs(self, limit=100, include_children=False):
            return list(self.items)

        def cancel_job(self, jid):
            for job in self.items:
                if job['id'] == jid:
                    job['status'] = 'cancelled'
                    return True
            return False

    jobs = Jobs()
    svc = WantedSearchService(Config(), object(),
                              str(tmp_path / 'state.json'), job_manager=jobs)
    svc._set_active(kind='cleanup', phase='searching')
    assert svc.cancel_active() is True
    assert svc._cancel_event.is_set()
    assert jobs.items[0]['status'] == 'cancelled'
    assert svc.get_active()['cancel_requested'] is True


def test_poll_job_stops_on_cancelled_or_missing_job(monkeypatch):
    import extend.failed_imports as failed_mod
    from extend.failed_imports import FailedImportsRetry

    monkeypatch.setattr(failed_mod.time, 'sleep', lambda *a, **k: None)

    class Config:
        def get_config(self):
            return {'gapfill_job_timeout_minutes': 15}

    class Jobs:
        def __init__(self, result):
            self.result = result

        def get_job(self, jid):
            return self.result

    svc = FailedImportsRetry(Config(), object(), None, None,
                             Jobs({'status': 'cancelled'}))
    assert svc._poll_job('j', timeout_s=5)['status'] == 'cancelled'

    # A deleted job (get_job -> None) must also stop, not poll to timeout.
    svc = FailedImportsRetry(Config(), object(), None, None, Jobs(None))
    assert svc._poll_job('j', timeout_s=5)['status'] == 'cancelled'


def test_child_jobs_hidden_and_log_mirrored_to_parent(tmp_path):
    from extend.job_manager import JobManager

    class Config:
        def get_setting(self, key, default=None):
            return default

    class Albums:
        def download_album(self, **kwargs):
            return {'success': True}

    manager = JobManager(Config(), Albums(), str(tmp_path / 'jobs.json'))
    parent, _ = manager.enqueue('cleanup', {'mode': 'stale-cleanup'})
    child, _ = manager.enqueue('album', {'album': 'X'}, parent_id=parent['id'])
    # Only the top-level cleanup job is listed.
    listed = manager.list_jobs()
    assert len(listed) == 1 and listed[0]['id'] == parent['id']
    assert len(manager.list_jobs(include_children=True)) == 2
    # Child log lines mirror into the parent so the Details pane shows all.
    manager.append_log(child['id'], 'child phase', artist='A')
    manager.update_job(child['id'], progress={'phase': 'downloaded'})
    parent_log = manager.get_job(parent['id'])['log']
    assert any('child phase' in line for line in parent_log)
    assert any('phase=downloaded' in line for line in parent_log)


def test_job_records_live_log_on_progress(tmp_path):
    from extend.job_manager import JobManager

    class Config:
        def get_setting(self, key, default=None):
            return default

    class Albums:
        def download_album(self, **kwargs):
            return {'success': True}

    manager = JobManager(Config(), Albums(), str(tmp_path / 'jobs.json'))
    job, _ = manager.enqueue('search', {'album': 'X'})
    manager.update_job(job['id'], status='running')
    manager.update_job(job['id'], progress={'phase': 'searching',
                                             'artist': 'A', 'album_title': 'X'})
    manager.append_log(job['id'], 'manual entry', verified=3)
    stored = manager.get_job(job['id'])
    log = stored['log']
    assert len(log) >= 3
    assert any('status: running' in line for line in log)
    assert any('phase=searching' in line for line in log)
    assert any('manual entry' in line and 'verified=3' in line for line in log)
    assert stored['progress']['phase'] == 'searching'


def test_failed_job_records_per_track_rejection_reason(tmp_path):
    from extend.job_manager import JobManager

    class Config:
        def get_setting(self, key, default=None):
            return 7 if key == 'job_retention_days' else default

    class Albums:
        def download_album(self, **kwargs):
            return {
                'success': False,
                'error': 'Download failed',
                'successful': 0, 'failed': 1, 'total_tracks': 1,
                'tracks': [{
                    'title': 'Rare Demo', 'success': False,
                    'error': 'Could not find track from any source',
                    'attempts': [{'source': 'ytsearch1:Rare Demo',
                                  'status': 'failed', 'reason': 'no results'}],
                }],
            }

    manager = JobManager(Config(), Albums(), str(tmp_path / 'jobs.json'))
    job, _ = manager.enqueue('album', {'artist': 'A', 'album': 'B', 'tracks': []})
    manager._process(manager._next_pending())
    stored = manager.get_job(job['id'])
    assert 'Rare Demo' in stored['failure_reason']
    assert stored['result']['failures'][0]['error'] == 'Could not find track from any source'
    assert stored['result']['failures'][0]['attempts'][0]['source'].startswith('ytsearch1:')


def test_downloads_js_declares_failures_before_use():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / 'static' / 'js' /
          'downloads.js').read_text(encoding='utf-8')
    declaration = js.index('const failures = result.failures || []')
    first_use = js.index('failures.length')
    assert declaration < first_use

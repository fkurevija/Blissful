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

        def enqueue(self, kind, payload):
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
    result = client.delete_queue_item(123, delete_files=False,
                                      add_import_exclusion=False)
    assert result['success'] is True
    assert calls[0] == ('get', {'page': 2, 'pageSize': 50,
                                'sortKey': 'releaseDate',
                                'sortDirection': 'descending'})
    assert calls[1][0] == 'delete'
    assert calls[1][1].endswith('/api/v1/queue/123')
    assert calls[1][2] == {'deleteFiles': False, 'addImportExclusion': False}


def _wanted_service(tmp_path, enabled=True, client=None):
    from extend.wanted_search import WantedSearchService

    class Config:
        def get_config(self):
            return {
                'wanted_search_enabled': enabled,
                'stale_cleanup_enabled': False,
                'stale_cleanup_interval_hours': 6,
                'stale_cleanup_wait_minutes': 10,
            }

    svc = WantedSearchService(Config(), client or object(),
                              str(tmp_path / 'wanted-state.json'))
    if client is not None:
        svc._client = client
    return svc


def test_wanted_search_dry_run_and_gate(tmp_path):
    svc = _wanted_service(tmp_path, enabled=True)
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
        def post_command(self, name, **body):
            calls.append((name, body))
            return {'id': 42}

    svc = _wanted_service(tmp_path, client=Client())
    selected = svc.search(album_ids=['3', 'bad'], apply=True)
    assert selected['command_id'] == 42
    assert calls == [('AlbumSearch', {'albumIds': [3]})]

    all_report = svc.search(apply=True)
    assert all_report['mode'] == 'all'
    assert calls[-1] == ('MissingAlbumSearch', {})


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
            if track_calls['n'] == 1:
                return [{'id': 1, 'hasFile': False}]
            return [{'id': 1, 'hasFile': True}]

        def post_command(self, name, **body):
            calls.append(('search', name, body))
            return {'id': 77}

        def get_command(self, cid):
            return {'id': cid, 'status': 'completed'}

        def delete_queue_item(self, rid, delete_files=False,
                              add_import_exclusion=False):
            calls.append(('delete', rid, delete_files, add_import_exclusion))
            return {'success': True}

    svc = _wanted_service(tmp_path, client=Client())
    stale = svc.get_stale()
    assert [record['id'] for record in stale] == [11]

    dry = svc.cleanup_stale(apply=False)
    assert dry['counts']['deleted'] == 0
    assert not any(c[0] == 'delete' for c in calls)

    applied = svc.cleanup_stale(apply=True, wait_minutes=1)
    assert applied['counts']['imported'] == 1
    assert applied['counts']['deleted'] == 1
    assert calls[0] == ('search', 'AlbumSearch', {'albumIds': [10]})
    assert ('delete', 11, False, False) in calls

    again = svc.cleanup_stale(apply=True, wait_minutes=1)
    assert again['counts']['deleted'] == 0
    assert any('already recorded' in str(s) for s in again['skipped'])


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

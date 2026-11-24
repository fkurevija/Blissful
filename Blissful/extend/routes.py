"""
API Routes for Blissful
Defines all Flask routes and integrates with manager classes
"""

from flask import request, jsonify, render_template, Response
import logging

logger = logging.getLogger(__name__)


def register_routes(app, config_manager, lidarr_client, download_manager, 
                    audio_converter, source_manager, auth_manager, 
                    request_manager, album_manager, track_manager, 
                    sources_api, system_utils, job_manager=None,
                    wanted_search=None):
    """
    Register all API routes with the Flask app
    
    Args:
        app: Flask application instance
        config_manager: Configuration manager
        lidarr_client: Lidarr client class
        download_manager: Download manager
        audio_converter: Audio converter
        source_manager: Source manager
        auth_manager: Authentication manager
        request_manager: Request manager
        album_manager: Album manager
        track_manager: Track download manager
        sources_api: Sources API manager
        system_utils: System utilities
    """
    
    # ==================== PAGE ROUTES ====================
    
    @app.route('/')
    def index():
        """Serve the configuration web interface"""
        return render_template('index.html')
    
    @app.route('/request')
    def request_page():
        """Serve the music request page"""
        return render_template('request.html')
    
    # ==================== HEALTH & CONFIG ====================
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Public health endpoint (never echoes credentials)."""
        health = {
            'status': 'healthy',
            'version': '1.0.0',
            'ffmpeg_available': audio_converter.check_ffmpeg(),
            'ytdlp_available': download_manager.check_ytdlp(),
        }
        try:
            health.update(system_utils.check_runtime_health())
        except Exception as exc:
            logger.warning("Runtime health check failed: %s", exc)
        health['lidarr_reachable'] = False
        try:
            config = config_manager.get_config()
            if config.get('lidarr_url') and config.get('lidarr_api_key'):
                probe = lidarr_client(url=config['lidarr_url'],
                                      api_key=config['lidarr_api_key'])
                health['lidarr_reachable'] = bool(probe.test_connection().get('success'))
        except Exception as exc:
            logger.debug("Lidarr health probe failed: %s", exc)
        return jsonify(health)
    
    @app.route('/api/config', methods=['GET'])
    def get_config():
        """Get current configuration"""
        config = config_manager.get_config()
        safe_config = config.copy()
        if 'lidarr_api_key' in safe_config and safe_config['lidarr_api_key']:
            safe_config['lidarr_api_key'] = '***MASKED***'
        if 'jellyfin_api_key' in safe_config and safe_config['jellyfin_api_key']:
            safe_config['jellyfin_api_key'] = '***MASKED***'
        if 'emby_api_key' in safe_config and safe_config['emby_api_key']:
            safe_config['emby_api_key'] = '***MASKED***'
        for secret_key in ('auth_token', 'spotify_client_secret'):
            if safe_config.get(secret_key):
                safe_config[secret_key] = '***MASKED***'
        return jsonify(safe_config)
    
    @app.route('/api/config', methods=['POST'])
    def save_config():
        """Merge the submitted fields over saved configuration and persist."""
        try:
            data = request.json or {}
            merged = config_manager.get_config()
            merged.update(data)
            if not config_manager.save_config(merged):
                return jsonify({'success': False, 'error': 'Could not write configuration'}), 500
            return jsonify({'success': True, 'message': 'Configuration saved successfully'})
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # ==================== AUTHENTICATION ROUTES ====================
    
    @app.route('/api/auth/jellyfin', methods=['POST'])
    def auth_jellyfin():
        """Authenticate with Jellyfin"""
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        result = auth_manager.authenticate_jellyfin(username, password)
        status_code = result.pop('status_code', 200)
        return jsonify(result), status_code
    
    @app.route('/api/auth/emby', methods=['POST'])
    def auth_emby():
        """Authenticate with Emby"""
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        result = auth_manager.authenticate_emby(username, password)
        status_code = result.pop('status_code', 200)
        return jsonify(result), status_code
    
    @app.route('/api/auth/plex', methods=['POST'])
    def auth_plex():
        """Authenticate with Plex"""
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        result = auth_manager.authenticate_plex(username, password)
        status_code = result.pop('status_code', 200)
        return jsonify(result), status_code
    
    # ==================== REQUEST SYSTEM ROUTES ====================
    
    @app.route('/api/request/config', methods=['GET'])
    def get_request_config():
        """Get request system configuration"""
        return jsonify(request_manager.get_request_config())
    
    @app.route('/api/request/search', methods=['POST'])
    def search_artists_for_request():
        """Search for artists via Lidarr API"""
        data = request.json
        term = data.get('term', '')
        result = request_manager.search_artists(term)
        return jsonify(result)
    
    @app.route('/api/request/add', methods=['POST'])
    def add_artist_request():
        """Add an artist to Lidarr"""
        data = request.json
        artist_data = data.get('artist')
        monitored = data.get('monitored', False)
        username = data.get('username', 'Anonymous')
        
        result = request_manager.add_artist_request(artist_data, username, monitored)
        return jsonify(result)
    
    # ==================== ALBUM ROUTES ====================
    
    @app.route('/api/album-info/<album_id>', methods=['GET'])
    def get_album_info(album_id):
        """Fetch album information from Lidarr API"""
        result = album_manager.get_album_info(album_id)
        if not result['success']:
            return jsonify(result), 404 if 'not found' in result.get('error', '') else 400
        return jsonify(result)
    
    @app.route('/api/album-tracks/<album_id>', methods=['GET'])
    def get_album_tracks(album_id):
        """Fetch album tracks with their file status"""
        result = album_manager.get_album_tracks(album_id)
        if not result['success']:
            return jsonify(result), 404 if 'not found' in result.get('error', '') else 400
        return jsonify(result)
    
    @app.route('/api/download-album', methods=['POST'])
    def download_album():
        """Download all tracks in an album"""
        data = request.json
        
        required_fields = ['artist', 'album', 'tracks']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        payload = {
            'artist': data.get('artist'),
            'album': data.get('album'),
            'album_id': data.get('album_id'),
            'tracks': data.get('tracks', []),
            'target_path': data.get('target_path', ''),
            'source': data.get('source', 'manual'),
        }
        if job_manager and config_manager.get_setting('enable_jobs', True):
            job, duplicate = job_manager.enqueue('album', payload)
            return jsonify({
                'success': True,
                'queued': True,
                'duplicate': duplicate,
                'job': job,
            }), 202
        result = album_manager.download_album(**{k: payload[k] for k in
                                                 ('artist', 'album', 'tracks', 'target_path')})
        return jsonify(result)

    # ==================== JOB ROUTES ====================

    @app.route('/api/jobs', methods=['GET'])
    def list_jobs():
        """List recent download jobs."""
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        status = request.args.get('status')
        limit = request.args.get('limit', 100)
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100
        return jsonify({'success': True, 'jobs': job_manager.list_jobs(limit=limit, status=status)})

    @app.route('/api/jobs/<job_id>/retry', methods=['POST'])
    def retry_job(job_id):
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        job, changed = job_manager.retry(job_id)
        if job is None:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        return jsonify({'success': True, 'job': job, 'restarted': changed})

    @app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
    def cancel_job(job_id):
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        ok = job_manager.cancel_job(job_id)
        if not ok:
            return jsonify({'success': False, 'error': 'Job not found or not cancellable'}), 404
        return jsonify({'success': True})

    @app.route('/api/jobs/<job_id>', methods=['DELETE'])
    def delete_job(job_id):
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        removed = job_manager.delete_job(job_id)
        return jsonify({'success': removed, 'removed': removed}), (200 if removed else 404)

    @app.route('/api/jobs/clear-finished', methods=['POST'])
    def clear_finished_jobs():
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        removed = job_manager.clear_finished()
        return jsonify({'success': True, 'removed': removed})

    @app.route('/api/lidarr/webhook', methods=['POST'])
    def lidarr_webhook():
        """Accept a Lidarr webhook and enqueue the album it refers to."""
        if not job_manager:
            return jsonify({'success': False, 'error': 'Job queue unavailable'}), 404
        data = request.json or {}
        tracks = data.get('tracks') or []
        payload = {
            'artist': (data.get('artist') or {}).get('artistName') or data.get('artistName', ''),
            'album': data.get('album') or data.get('albumTitle', ''),
            'album_id': data.get('albumId'),
            'tracks': tracks,
            'target_path': data.get('path', ''),
            'source': 'lidarr-webhook',
        }
        if not payload['artist'] or not payload['album']:
            return jsonify({'success': False, 'error': 'Webhook missing artist/album'}), 400
        job, duplicate = job_manager.enqueue('album', payload)
        return jsonify({'success': True, 'queued': True, 'duplicate': duplicate, 'job': job}), 202
    
    # ==================== TRACK DOWNLOAD ROUTE ====================
    
    @app.route('/api/download-track', methods=['POST'])
    def download_track():
        """Download a track based on metadata"""
        data = request.json
        
        # Validate required fields
        required_fields = ['artist', 'title']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        result = track_manager.download_track(
            artist=data.get('artist'),
            title=data.get('title'),
            album=data.get('album', ''),
            album_id=data.get('album_id'),
            track_number=data.get('track_number', 1),
            expected_duration=data.get('duration'),
            disc_number=data.get('disc_number'),
            year=data.get('year'),
            genre=data.get('genre')
        )
        
        if not result['success']:
            return jsonify(result), 400
        
        return jsonify(result)
    
    # ==================== LIDARR ROUTES ====================
    
    def _lidarr_from_request(data):
        """Build a client from the request, falling back to saved settings."""
        saved = config_manager.get_config()
        url = data.get('lidarr_url') or saved.get('lidarr_url', '')
        api_key = data.get('lidarr_api_key') or saved.get('lidarr_api_key', '')
        if api_key in ('***KEEP_EXISTING***', '***MASKED***'):
            api_key = saved.get('lidarr_api_key', '')
        if not url or not api_key:
            return None, 'Lidarr URL and API key are required'
        return lidarr_client(url=url, api_key=api_key), None

    @app.route('/api/test-lidarr', methods=['POST'])
    def test_lidarr_connection():
        """Test Lidarr connection without ever returning the API key."""
        try:
            client, error = _lidarr_from_request(request.json or {})
            if error:
                return jsonify({'success': False, 'error': error}), 400
            return jsonify(client.test_connection())
        except Exception as e:
            logger.error(f"Error testing Lidarr connection: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/lidarr-paths', methods=['POST'])
    def get_lidarr_paths():
        """Get root folders from Lidarr for path mapping"""
        try:
            client, error = _lidarr_from_request(request.json or {})
            if error:
                return jsonify({'success': False, 'error': error}), 400
            lidarr = client
            
            status = lidarr.test_connection()
            if not status.get('success'):
                return jsonify(status), 400
            
            paths = lidarr.get_root_folders()
            
            if paths:
                return jsonify({
                    'success': True,
                    'paths': paths
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No root folders found in Lidarr'
                })
                
        except Exception as e:
            logger.error(f"Error getting Lidarr paths: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # ==================== WANTED SEARCH / STALE CLEANUP ====================

    @app.route('/api/wanted', methods=['GET'])
    def get_wanted_items():
        if not wanted_search:
            return jsonify({'success': False, 'error': 'Wanted search unavailable'}), 404
        return jsonify({'success': True, 'items': wanted_search.get_wanted()})

    @app.route('/api/stale-torrents', methods=['GET'])
    def get_stale_torrents():
        if not wanted_search:
            return jsonify({'success': False, 'error': 'Wanted search unavailable'}), 404
        return jsonify({'success': True, 'items': wanted_search.get_stale()})

    @app.route('/api/wanted/search', methods=['POST'])
    def run_wanted_search():
        if not wanted_search:
            return jsonify({'success': False, 'error': 'Wanted search unavailable'}), 404
        data = request.json or {}
        result = wanted_search.search(
            album_ids=data.get('album_ids'),
            apply=bool(data.get('apply', False))
        )
        if result.get('already_running'):
            return jsonify(result), 409
        if not result.get('success', True):
            return jsonify(result), 400
        return jsonify(result)

    @app.route('/api/stale-torrents/cleanup', methods=['POST'])
    def run_stale_cleanup():
        if not wanted_search:
            return jsonify({'success': False, 'error': 'Wanted search unavailable'}), 404
        data = request.json or {}
        result = wanted_search.cleanup_stale(
            record_ids=data.get('record_ids'),
            apply=bool(data.get('apply', False))
        )
        if result.get('already_running'):
            return jsonify(result), 409
        return jsonify(result)

    @app.route('/api/wanted/status', methods=['GET'])
    def wanted_status():
        config = config_manager.get_config()
        return jsonify({
            'success': True,
            'wanted_search_enabled': bool(config.get('wanted_search_enabled')),
            'stale_cleanup_enabled': bool(config.get('stale_cleanup_enabled')),
            'stale_cleanup_interval_hours': config.get('stale_cleanup_interval_hours', 6),
            'stale_cleanup_wait_minutes': config.get('stale_cleanup_wait_minutes', 10),
            'prefer_blissful_for_stale': bool(config.get('prefer_blissful_for_stale', True)),
            'gapfill_job_timeout_minutes': config.get('gapfill_job_timeout_minutes', 15),
            'stale_cleanup_remove_from_client': bool(config.get('stale_cleanup_remove_from_client', True)),
            'wanted_search_timeout_minutes': config.get('wanted_search_timeout_minutes', 10),
            'prefer_blissful_for_wanted': bool(config.get('prefer_blissful_for_wanted', True)),
            'active': (wanted_search.get_active() if wanted_search else None),
            'last_activity': (wanted_search.get_last_activity()
                              if wanted_search else None),
        })

    @app.route('/api/wanted/reset', methods=['POST'])
    def reset_wanted_state():
        if not wanted_search:
            return jsonify({'success': False, 'error': 'Wanted search unavailable'}), 404
        wanted_search.reset_state()
        return jsonify({'success': True, 'message': 'Wanted search state cleared'})

    # ==================== SOURCES ROUTES ====================
    
    @app.route('/api/supported-sources', methods=['GET'])
    def get_supported_sources():
        """Get list of supported download sources from yt-dlp"""
        category = request.args.get('category', None)
        tier = request.args.get('tier', None)
        search_query = request.args.get('q', None)
        music_only = request.args.get('music_only', 'false').lower() == 'true'
        
        result = sources_api.get_supported_sources(category, tier, search_query, music_only)
        return jsonify(result)
    
    @app.route('/api/sources/search', methods=['GET'])
    def search_sources():
        """Search for specific sources"""
        query = request.args.get('q', '')
        result = sources_api.search_sources(query)
        if not result['success']:
            return jsonify(result), 400
        return jsonify(result)
    
    @app.route('/api/sources/stats', methods=['GET'])
    def get_source_stats():
        """Get statistics about available sources"""
        return jsonify(sources_api.get_source_stats())
    
    @app.route('/api/sources/categories', methods=['GET'])
    def get_source_categories():
        """Get available source categories"""
        return jsonify(sources_api.get_source_categories())
    
    # ==================== SYSTEM UTILITIES ====================
    
    @app.route('/api/ytdlp/version', methods=['GET'])
    def get_ytdlp_version():
        """Get current yt-dlp version"""
        return jsonify(system_utils.get_ytdlp_version())
    
    @app.route('/api/ytdlp/upgrade', methods=['POST'])
    def upgrade_ytdlp():
        """Upgrade yt-dlp to latest version"""
        result = system_utils.upgrade_ytdlp()
        if not result['success']:
            return jsonify(result), 500
        return jsonify(result)
    
    @app.route('/api/system/info', methods=['GET'])
    def get_system_info():
        """Get system information"""
        return jsonify(system_utils.get_system_info())
    
    @app.route('/userscript')
    def serve_userscript():
        """Serve the userscript file with customized server URL and Lidarr URL"""
        server_url = request.host_url.rstrip('/')
        script_content, error = system_utils.generate_userscript(server_url)
        
        if error:
            return jsonify({'error': 'Failed to load userscript'}), 500
        
        response = Response(
            script_content,
            mimetype='text/javascript',
            headers={
                'Content-Disposition': 'attachment; filename="blissful-lidarr.user.js"',
                'Content-Type': 'text/javascript; charset=utf-8',
                'Cache-Control': 'no-cache'
            }
        )
        
        return response
    
    # ==================== DOCUMENTATION ROUTES ====================
    
    @app.route('/api/docs/<doc_name>', methods=['GET'])
    def get_documentation(doc_name):
        """Serve markdown documentation files"""
        import os
        
        # Sanitize filename
        safe_name = doc_name.replace('..', '').replace('/', '').replace('\\', '')
        
        # Try to read the markdown file
        docs_path = os.path.join('docs', f'{safe_name}.md')
        
        if not os.path.exists(docs_path):
            return jsonify({
                'success': False,
                'error': f'Documentation file not found: {safe_name}.md'
            }), 404
        
        try:
            with open(docs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return Response(
                content,
                mimetype='text/plain; charset=utf-8',
                headers={
                    'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
                }
            )
        except Exception as e:
            logger.error(f"Error reading documentation file {docs_path}: {e}")
            return jsonify({
                'success': False,
                'error': f'Error reading file: {str(e)}'
            }), 500

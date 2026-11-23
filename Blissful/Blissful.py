"""
Blissful - Lidarr Music Downloader Microservice
Main application file with modular architecture
"""

from flask import Flask, request
import os
import logging
from urllib.parse import urlparse

# Import configuration and managers from extend folder
from extend.config_manager import ConfigManager
from extend.lidarr_client import LidarrClient
from extend.download_manager import DownloadManager
from extend.audio_converter import AudioConverter
from extend.source_manager import SourceManager

# Import new modular managers
from extend.auth_manager import AuthManager
from extend.request_manager import RequestManager
from extend.album_manager import AlbumManager
from extend.track_manager import TrackManager
from extend.sources_api import SourcesAPI
from extend.system_utils import SystemUtils
from extend.spotify_client import SpotifyClient
from extend.auth import install_auth, is_enabled
from extend.job_manager import JobManager
from extend.routes import register_routes

# Initialize Flask app
app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("=" * 60)
logger.info("🎵 Blissful - Lidarr Music Downloader")
logger.info("=" * 60)

# Initialize core managers
logger.info("📦 Initializing core managers...")

config_manager = ConfigManager()
spotify_client = SpotifyClient(config_manager)
download_manager = DownloadManager(config_manager=config_manager,
                                    spotify_client=spotify_client)
audio_converter = AudioConverter()
source_manager = SourceManager()

logger.info("✅ Core managers initialized")

# Initialize new modular managers
logger.info("🔧 Initializing modular managers...")

auth_manager = AuthManager(config_manager)
request_manager = RequestManager(config_manager, LidarrClient)
album_manager = AlbumManager(config_manager, LidarrClient, download_manager, audio_converter)
track_manager = TrackManager(config_manager, LidarrClient, download_manager, audio_converter)
sources_api = SourcesAPI(source_manager)
system_utils = SystemUtils(config_manager)
job_manager = JobManager(config_manager, album_manager)

logger.info("✅ All modular managers initialized")

# Restrict CORS: same-origin plus explicitly configured origins (e.g. Lidarr
# for the userscript). Never fall back to a wildcard.
def _allowed_origins():
    origins = set()
    for value in os.environ.get('BLISSFUL_ALLOWED_ORIGINS', '').split(','):
        if value.strip():
            origins.add(value.strip().rstrip('/'))
    lidarr_url = config_manager.get_setting('lidarr_url', '')
    if lidarr_url:
        parsed = urlparse(lidarr_url)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return origins


@app.after_request
def _apply_cors(response):
    origin = request.headers.get('Origin')
    if not origin:
        return response
    origin = origin.rstrip('/')
    same_origin = urlparse(origin).netloc == request.host
    if same_origin or origin in _allowed_origins():
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Headers'] = (
            'Content-Type, Authorization, X-Blissful-Token'
        )
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Vary'] = 'Origin'
    return response


# Optional API token gates every /api/ route except /api/health.
install_auth(app, config_manager)

# Register all API routes
logger.info("🛣️  Registering API routes...")
register_routes(
    app=app,
    config_manager=config_manager,
    lidarr_client=LidarrClient,
    download_manager=download_manager,
    audio_converter=audio_converter,
    source_manager=source_manager,
    auth_manager=auth_manager,
    request_manager=request_manager,
    album_manager=album_manager,
    track_manager=track_manager,
    sources_api=sources_api,
    system_utils=system_utils,
    job_manager=job_manager
)
logger.info("✅ All routes registered successfully")

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs('downloads', exist_ok=True)
    os.makedirs('downloads/temp', exist_ok=True)
    os.makedirs('config', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    if not is_enabled(config_manager):
        logger.warning("⚠️  API token is OFF. Anyone who can reach Blissful can change "
                       "settings and trigger downloads. Set auth_token (or "
                       "BLISSFUL_AUTH_TOKEN) before exposing beyond LAN/VPN.")
    else:
        logger.info("🔒 API token protection is enabled")

    health = system_utils.check_runtime_health()
    if health.get('js_runtime_available'):
        logger.info("✅ Deno JavaScript runtime available: %s", health.get('js_runtime'))
    else:
        logger.warning("⚠️  No Deno JavaScript runtime found; YouTube downloads may fail")
    if health.get('pot_provider_enabled'):
        if health.get('pot_provider_reachable'):
            logger.info("✅ PO token provider reachable at %s", health.get('pot_provider_url'))
        else:
            logger.warning("⚠️  PO token provider at %s is not reachable",
                           health.get('pot_provider_url'))

    job_manager.start_worker()

    logger.info("🚀 Starting Flask application...")
    logger.info("")
    port = int(os.environ.get('PORT', 7373))
    logger.info(f"📍 Server running at: http://localhost:{port}")
    logger.info(f"📱 Request page: http://localhost:{port}/request")
    logger.info(f"⚙️  Config page: http://localhost:{port}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    app.run(host='0.0.0.0', port=port, debug=False)

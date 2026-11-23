"""
System Utilities for Blissful
Handles system info, yt-dlp updates, and userscript generation
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SystemUtils:
    """System utilities and tools"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def get_system_info(self):
        """
        Get system information (OS, Docker, Python version, etc.)
        
        Returns:
            dict: System information
        """
        try:
            # Detect if running in Docker
            is_docker = False
            try:
                with open('/proc/1/cgroup', 'r') as f:
                    is_docker = 'docker' in f.read()
            except:
                # Check for .dockerenv file (another Docker indicator)
                is_docker = os.path.exists('/.dockerenv')
            
            return {
                'success': True,
                'is_docker': is_docker,
                'os': platform.system(),
                'os_version': platform.version(),
                'python_version': platform.python_version(),
                'architecture': platform.machine()
            }
            
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _ytdlp_target(self):
        """Directory used for runtime yt-dlp upgrades (must be writable)."""
        return (os.environ.get('YT_DLP_TARGET')
                or self.config_manager.get_setting('ytdlp_target', '/app/downloads/pylib'))

    def _ytdlp_version(self, target=None):
        target = target or self._ytdlp_target()
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "import yt_dlp; print(yt_dlp.version.__version__)")
        try:
            result = subprocess.run(
                [sys.executable, '-c', code, target],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[-1]
        except Exception:
            pass
        try:
            result = subprocess.run(['yt-dlp', '--version'], capture_output=True,
                                    text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return 'Unknown'

    def get_ytdlp_version(self):
        """Get current and latest yt-dlp version."""
        try:
            current_version = self._ytdlp_version()
            latest_version = 'Unknown'
            try:
                import requests
                response = requests.get(
                    'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest',
                    timeout=3
                )
                if response.status_code == 200:
                    latest_version = response.json().get('tag_name', '').strip()
            except Exception:
                pass

            needs_update = False
            if current_version != 'Unknown' and latest_version != 'Unknown':
                needs_update = current_version < latest_version

            return {
                'success': True,
                'current_version': current_version,
                'latest_version': latest_version,
                'needs_update': needs_update,
                'target': self._ytdlp_target()
            }
        except Exception as e:
            logger.error(f"Error getting yt-dlp version: {e}")
            return {'success': False, 'error': str(e)}

    def upgrade_ytdlp(self):
        """Upgrade yt-dlp into a user-writable directory (works as non-root)."""
        try:
            target = self._ytdlp_target()
            Path(target).mkdir(parents=True, exist_ok=True)
            logger.info("Upgrading yt-dlp into %s", target)
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--upgrade',
                 '--force-reinstall', '--target', target,
                 'yt-dlp', 'bgutil-ytdlp-pot-provider'],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error("yt-dlp upgrade failed: %s", result.stderr)
                return {'success': False, 'error': 'Upgrade failed',
                        'output': result.stderr}

            new_version = self._ytdlp_version(target)
            return {
                'success': True,
                'message': (f'Installed yt-dlp {new_version} and the PO token '
                            'provider into the persistent target. Restart Blissful '
                            'to load the new version.'),
                'new_version': new_version,
                'target': target,
                'output': result.stdout
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Upgrade timed out (>120s)'}
        except Exception as e:
            logger.error(f"Error upgrading yt-dlp: {e}")
            return {'success': False, 'error': str(e)}

    def check_runtime_health(self):
        """Report JS runtime and PO token provider reachability without secrets."""
        config = self.config_manager.get_config()
        deno_path = (os.environ.get('DENO_PATH')
                     or config.get('deno_path')
                     or shutil.which('deno'))
        js_available = False
        if deno_path:
            candidate = Path(str(deno_path))
            js_available = candidate.exists() or shutil.which(str(deno_path)) is not None
        if not js_available:
            js_available = shutil.which('deno') is not None

        pot_url = (os.environ.get('POT_PROVIDER_URL')
                   or config.get('pot_provider_url')
                   or 'http://blissful-pot:4416')
        pot_enabled = bool(config.get('enable_pot_provider', True)) and \
            os.environ.get('ENABLE_POT_PROVIDER', 'true').lower() not in ('false', '0', 'no')
        pot_reachable = False
        if pot_enabled:
            try:
                import requests
                response = requests.get(pot_url.rstrip('/') + '/', timeout=2)
                pot_reachable = response.status_code < 500
            except Exception as exc:
                logger.debug("PO token provider not reachable at %s: %s", pot_url, exc)

        return {
            'js_runtime_available': js_available,
            'js_runtime': str(deno_path) if deno_path else None,
            'pot_provider_enabled': pot_enabled,
            'pot_provider_url': pot_url,
            'pot_provider_reachable': pot_reachable,
        }

    def generate_userscript(self, server_url):
        """
        Generate userscript with customized server URL and Lidarr URL
        
        Args:
            server_url: Base URL of the Blissful server
            
        Returns:
            tuple: (script_content, error_message)
        """
        try:
            config = self.config_manager.get_config()
            lidarr_url = config.get('lidarr_url', '')
            
            logger.info(f"Generating userscript with Lidarr URL: {lidarr_url}")
            logger.info(f"Microservice URL: {server_url}")
            
            # Read userscript template
            script_path = (Path(__file__).resolve().parents[1] / 'static' /
                           'lidarr-userscript.user.js')
            with open(script_path, 'r', encoding='utf-8') as f:
                script_content = f.read()
            
            # Generate @match patterns based on Lidarr URL
            if lidarr_url:
                try:
                    parsed = urlparse(lidarr_url)
                    lidarr_host = parsed.netloc or 'localhost:8686'
                    lidarr_scheme = parsed.scheme or 'http'
                    
                    logger.info(f"Parsed Lidarr - Host: {lidarr_host}, Scheme: {lidarr_scheme}")
                    
                    # Create specific match patterns for configured Lidarr
                    match_patterns = f"""// @match        {lidarr_scheme}://{lidarr_host}/*"""
                    
                    # Also add alternate scheme
                    alt_scheme = 'https' if lidarr_scheme == 'http' else 'http'
                    match_patterns += f"""
// @match        {alt_scheme}://{lidarr_host}/*"""
                    
                    logger.info(f"Generated match patterns:\n{match_patterns}")
                    
                except Exception as e:
                    logger.warning(f"Could not parse Lidarr URL: {e}")
                    # Fallback to localhost patterns
                    match_patterns = """// @match        http://localhost:8686/*
// @match        https://localhost:8686/*
// @match        http://127.0.0.1:8686/*
// @match        https://127.0.0.1:8686/*"""
            else:
                # No Lidarr URL configured, use localhost defaults
                logger.warning("No Lidarr URL configured, using localhost defaults")
                match_patterns = """// @match        http://localhost:8686/*
// @match        https://localhost:8686/*
// @match        http://127.0.0.1:8686/*
// @match        https://127.0.0.1:8686/*"""
            
            # Replace match patterns in script
            old_patterns = """// @match        http://localhost:8686/*
// @match        https://localhost:8686/*
// @match        http://127.0.0.1:8686/*
// @match        https://127.0.0.1:8686/*"""
            
            script_content = script_content.replace(old_patterns, match_patterns)
            
            # Replace microservice URL (both legacy and current defaults)
            script_content = script_content.replace(
                "microserviceUrl: 'http://localhost:5000'",
                f"microserviceUrl: {json.dumps(server_url)}"
            )
            script_content = script_content.replace(
                "microserviceUrl: 'http://localhost:7373'",
                f"microserviceUrl: {json.dumps(server_url)}"
            )

            # Replace the DEFAULT_MICROSERVICE_URL constant
            script_content = script_content.replace(
                "DEFAULT_MICROSERVICE_URL = 'http://localhost:7373'",
                f"DEFAULT_MICROSERVICE_URL = {json.dumps(server_url)}"
            )

            # Wire the optional API token into the generated userscript.
            token = os.environ.get('BLISSFUL_AUTH_TOKEN', '') or config.get('auth_token', '')
            script_content = script_content.replace(
                "authToken: '__BLISSFUL_AUTH_TOKEN__'",
                f"authToken: {json.dumps(str(token))}"
            )
            if token:
                logger.info("Generated userscript with API token configured")
            
            logger.info("Userscript generated successfully")
            
            return (script_content, None)
            
        except Exception as e:
            logger.error(f"Error generating userscript: {e}", exc_info=True)
            return (None, str(e))

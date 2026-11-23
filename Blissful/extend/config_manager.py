import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ConfigManager:
    """Manager for application configuration"""
    
    def __init__(self, config_file: str = 'config.json'):
        """
        Initialize configuration manager
        
        Args:
            config_file: Path to configuration file
        """
        self.config_file = Path(config_file)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file
        
        Returns:
            Configuration dictionary
        """
        try:
            defaults = self._get_default_config()
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                logger.info("Configuration loaded successfully")
                # Merge defaults so upgrades always see newly introduced keys.
                merged = defaults.copy()
                merged.update(config if isinstance(config, dict) else {})
                return self._apply_env_overrides(merged)
            else:
                # Return default configuration
                logger.info("No config file found, using defaults")
                return self._apply_env_overrides(defaults)
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return self._apply_env_overrides(self._get_default_config())

    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply deployment secrets/settings supplied through environment variables.

        Environment values win over config.json so secrets never need to be written
        to disk. Only known keys are read.
        """
        env_map = {
            'BLISSFUL_AUTH_TOKEN': 'auth_token',
            'LIDARR_URL': 'lidarr_url',
            'LIDARR_API_KEY': 'lidarr_api_key',
            'SPOTIFY_CLIENT_ID': 'spotify_client_id',
            'SPOTIFY_CLIENT_SECRET': 'spotify_client_secret',
            'POT_PROVIDER_URL': 'pot_provider_url',
            'DENO_PATH': 'deno_path',
            'YT_DLP_CONFIG_FILE': 'ytdlp_config_file',
        }
        bool_keys = {'enable_pot_provider', 'spotify_metadata_enabled'}
        for env_key, config_key in env_map.items():
            value = os.environ.get(env_key)
            if value is None or value == '':
                continue
            if config_key in bool_keys:
                config[config_key] = value.strip().lower() in ('1', 'true', 'yes', 'on')
            else:
                config[config_key] = value
        return config

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get default configuration
        
        Returns:
            Default configuration dictionary
        """
        return {
            'lidarr_url': '',
            'lidarr_api_key': '',
            'output_format': 'mp3',
            'quality': '320k',
            'lidarr_path_mapping': {},
            'microservice_port': 5000,
            'auto_cleanup': True,
            'normalize_audio': False,
            'mono_audio': False,
            'sample_rate': 'original',
            'remove_silence': False,
            'loudness_normalization': False,
            'channels': 'original',
            'embed_metadata': True,
            'embed_thumbnail': True,
            'source_priorities': [
                {'name': 'YouTube Music', 'search': 'music.youtube.com', 'enabled': True},
                {'name': 'SoundCloud', 'search': 'soundcloud.com', 'enabled': True},
                {'name': 'YouTube', 'search': 'youtube.com', 'enabled': True},
                {'name': 'Bandcamp', 'search': 'bandcamp.com', 'enabled': True}
            ],
            # Metadata providers do not serve audio; they only refine search metadata.
            'spotify_metadata_enabled': False,
            'spotify_client_id': '',
            'spotify_client_secret': '',
            # Optional API token. Off by default; enable when exposing Blissful
            # beyond a trusted LAN/VPN. BLISSFUL_AUTH_TOKEN env wins.
            'auth_token': '',
            # yt-dlp runtime / PO token provider (Deno + bgutil sidecar).
            'enable_pot_provider': True,
            'pot_provider_url': 'http://blissful-pot:4416',
            'deno_path': '/usr/local/bin/deno',
            'ytdlp_config_file': '',
            'ytdlp_extractor_args': {},
            'ytdlp_js_runtimes': {},
            # Download trust settings.
            'validate_duration': True,
            'max_duration_deviation': 0.10,
            'use_lidarr_naming': True,
            'enable_jobs': True,
            'auto_retry_failed': False,
            'job_retention_days': 7,
            # Request system defaults
            'enable_requests': False,
            'auto_monitor_requests': False,
            'enable_jellyfin': False,
            'jellyfin_url': '',
            'jellyfin_api_key': '',
            'enable_emby': False,
            'emby_url': '',
            'emby_api_key': '',
            'enable_plex': False,
            'plex_url': '',
            'request_default_monitored': False,
            'request_search_missing': False
        }
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get current configuration
        
        Returns:
            Configuration dictionary
        """
        return self.config.copy()
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        Save configuration to file
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if successful
        """
        try:
            # Validate configuration
            validated_config = self._validate_config(config)
            
            # Save to file
            with open(self.config_file, 'w') as f:
                json.dump(validated_config, f, indent=2)
            
            # Update in-memory config
            self.config = validated_config
            
            logger.info("Configuration saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize configuration
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Validated configuration dictionary
        """
        # Start with current config to preserve values not being updated
        validated = self.config.copy()
        
        # Update with provided values
        if 'lidarr_url' in config:
            validated['lidarr_url'] = str(config['lidarr_url']).rstrip('/')
        
        # Handle API key with special marker to preserve existing
        if 'lidarr_api_key' in config:
            api_key = config['lidarr_api_key']
            if api_key == '***KEEP_EXISTING***':
                # Keep the existing key (don't change it)
                pass
            else:
                # Update with new value (even if empty string)
                validated['lidarr_api_key'] = str(api_key)
        
        if 'output_format' in config:
            format_value = str(config['output_format']).lower()
            if format_value in ['mp3', 'flac', 'wav', 'ogg', 'opus', 'm4a', 'aac']:
                validated['output_format'] = format_value
        
        if 'quality' in config:
            validated['quality'] = str(config['quality'])
        
        if 'lidarr_path_mapping' in config and isinstance(config['lidarr_path_mapping'], dict):
            validated['lidarr_path_mapping'] = config['lidarr_path_mapping']
        
        if 'microservice_port' in config:
            try:
                port = int(config['microservice_port'])
                if 1 <= port <= 65535:
                    validated['microservice_port'] = port
            except (ValueError, TypeError):
                pass
        
        if 'auto_cleanup' in config:
            validated['auto_cleanup'] = bool(config['auto_cleanup'])
        
        if 'normalize_audio' in config:
            validated['normalize_audio'] = bool(config['normalize_audio'])
        
        if 'mono_audio' in config:
            validated['mono_audio'] = bool(config['mono_audio'])
        
        if 'sample_rate' in config:
            validated['sample_rate'] = str(config['sample_rate'])
        
        if 'remove_silence' in config:
            validated['remove_silence'] = bool(config['remove_silence'])
        
        if 'loudness_normalization' in config:
            validated['loudness_normalization'] = bool(config['loudness_normalization'])
        
        if 'channels' in config:
            validated['channels'] = str(config['channels'])
        
        if 'embed_metadata' in config:
            validated['embed_metadata'] = bool(config['embed_metadata'])
        
        if 'embed_thumbnail' in config:
            validated['embed_thumbnail'] = bool(config['embed_thumbnail'])
        
        if 'source_priorities' in config and isinstance(config['source_priorities'], list):
            # Spotify is metadata-only in this fork; drop stale saved entries.
            validated['source_priorities'] = [
                source for source in config['source_priorities']
                if not isinstance(source, dict)
                or ('spotify' not in str(source.get('name', '')).lower()
                    and 'spotify' not in str(source.get('search', '')).lower())
            ]
        
        # Request system settings
        if 'enable_requests' in config:
            validated['enable_requests'] = bool(config['enable_requests'])
        
        if 'auto_monitor_requests' in config:
            validated['auto_monitor_requests'] = bool(config['auto_monitor_requests'])
        
        if 'enable_jellyfin' in config:
            validated['enable_jellyfin'] = bool(config['enable_jellyfin'])
        
        if 'jellyfin_url' in config:
            validated['jellyfin_url'] = str(config['jellyfin_url']).rstrip('/')
        
        if 'jellyfin_api_key' in config:
            validated['jellyfin_api_key'] = str(config['jellyfin_api_key'])
        
        if 'enable_emby' in config:
            validated['enable_emby'] = bool(config['enable_emby'])
        
        if 'emby_url' in config:
            validated['emby_url'] = str(config['emby_url']).rstrip('/')
        
        if 'emby_api_key' in config:
            validated['emby_api_key'] = str(config['emby_api_key'])
        
        if 'enable_plex' in config:
            validated['enable_plex'] = bool(config['enable_plex'])
        
        if 'plex_url' in config:
            validated['plex_url'] = str(config['plex_url']).rstrip('/')
        
        if 'request_default_monitored' in config:
            validated['request_default_monitored'] = bool(config['request_default_monitored'])
        
        if 'request_search_missing' in config:
            validated['request_search_missing'] = bool(config['request_search_missing'])
        
        # Metadata provider, API token and yt-dlp runtime settings.
        for key in ('spotify_metadata_enabled', 'enable_pot_provider',
                    'validate_duration', 'use_lidarr_naming', 'enable_jobs',
                    'auto_retry_failed'):
            if key in config:
                validated[key] = bool(config[key])
        for key in ('spotify_client_id', 'spotify_client_secret', 'auth_token'):
            if key in config:
                value = config[key]
                if value in ('***KEEP_EXISTING***', '***MASKED***'):
                    continue
                validated[key] = str(value)
        for key in ('pot_provider_url', 'deno_path', 'ytdlp_config_file'):
            if key in config:
                validated[key] = str(config[key])
        if 'ytdlp_extractor_args' in config and isinstance(config['ytdlp_extractor_args'], dict):
            validated['ytdlp_extractor_args'] = config['ytdlp_extractor_args']
        if 'ytdlp_js_runtimes' in config and isinstance(config['ytdlp_js_runtimes'], dict):
            validated['ytdlp_js_runtimes'] = config['ytdlp_js_runtimes']
        if 'max_duration_deviation' in config:
            try:
                deviation = float(config['max_duration_deviation'])
                if 0 <= deviation <= 1:
                    validated['max_duration_deviation'] = deviation
            except (ValueError, TypeError):
                pass
        if 'job_retention_days' in config:
            try:
                days = int(config['job_retention_days'])
                if days >= 0:
                    validated['job_retention_days'] = days
            except (ValueError, TypeError):
                pass
        
        return validated
    
    def update_setting(self, key: str, value: Any) -> bool:
        """
        Update a single configuration setting
        
        Args:
            key: Setting key
            value: Setting value
            
        Returns:
            True if successful
        """
        try:
            config = self.config.copy()
            config[key] = value
            return self.save_config(config)
        except Exception as e:
            logger.error(f"Error updating setting: {e}")
            return False
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a specific configuration setting
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            Setting value
        """
        return self.config.get(key, default)

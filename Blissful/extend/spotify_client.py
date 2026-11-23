"""Spotify metadata client for Blissful.

Metadata only: Spotify is never used as a download source. Uses the Spotify
Web API client-credentials flow with ``requests``. Credentials come from the
ConfigManager or environment variables and are never logged.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_TOKEN_URL = 'https://accounts.spotify.com/api/token'
_SEARCH_URL = 'https://api.spotify.com/v1/search'
_TIMEOUT = 10


class SpotifyClient:
    """Resolve track metadata via the Spotify Web API (client credentials)."""

    def __init__(self, config_manager: Any = None):
        self.config_manager = config_manager
        self._token: Optional[str] = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        cm = self.config_manager
        if cm is None:
            return default
        try:
            if hasattr(cm, 'get_setting') and callable(cm.get_setting):
                value = cm.get_setting(key, default)
            elif isinstance(cm, dict):
                value = cm.get(key, default)
            elif hasattr(cm, 'get_config') and callable(cm.get_config):
                value = (cm.get_config() or {}).get(key, default)
            else:
                value = getattr(cm, key, default)
        except Exception:
            return default
        return default if value is None else value

    def _setting(self, key: str, env_name: str, default: str = '') -> str:
        env_value = os.environ.get(env_name)
        if env_value is not None and str(env_value).strip():
            return str(env_value).strip()
        cfg_value = self._cfg(key, default)
        return str(cfg_value).strip() if cfg_value is not None else default

    def _credentials(self):
        client_id = self._setting('spotify_client_id', 'SPOTIFY_CLIENT_ID')
        secret = self._setting('spotify_client_secret', 'SPOTIFY_CLIENT_SECRET')
        if not secret:
            secret = self._setting('spotify_secret', 'SPOTIFY_CLIENT_SECRET')
        return client_id, secret

    def is_configured(self) -> bool:
        """True when both client id and secret are available."""
        client_id, secret = self._credentials()
        return bool(client_id and secret)

    # ------------------------------------------------------------------
    # Token handling
    # ------------------------------------------------------------------
    def _get_token(self) -> Optional[str]:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        client_id, client_secret = self._credentials()
        if not client_id or not client_secret:
            return None

        try:
            response = requests.post(
                _TOKEN_URL,
                data={'grant_type': 'client_credentials'},
                auth=(client_id, client_secret),
                timeout=_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning('Spotify token request failed (HTTP %s)', response.status_code)
                return None
            payload = response.json()
        except Exception as exc:  # never log the exception body: it may echo credentials
            logger.debug('Spotify token request failed: %s', type(exc).__name__)
            return None

        token = payload.get('access_token') if isinstance(payload, dict) else None
        if not token:
            return None

        try:
            expires_in = float(payload.get('expires_in', 3600))
        except (TypeError, ValueError):
            expires_in = 3600.0

        self._token = token
        self._token_expires_at = time.monotonic() + max(30.0, expires_in - 60.0)
        return token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve_track(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[Dict]:
        """Resolve a track to Spotify metadata, or None if unavailable."""
        try:
            token = self._get_token()
            if not token:
                return None

            query = f'track:{title} artist:{artist}'
            if album:
                query += f' album:{album}'
            params = {'q': query, 'type': 'track', 'limit': 5}

            response = requests.get(
                _SEARCH_URL,
                params=params,
                headers={'Authorization': 'Bearer ' + token},
                timeout=_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning('Spotify search failed (HTTP %s)', response.status_code)
                return None

            payload = response.json()
            items = ((payload or {}).get('tracks') or {}).get('items') or []
            if not items:
                return None

            best = self._pick_best(items, duration_ms)
            return self._to_metadata(best) if best else None

        except Exception as exc:
            logger.debug('Spotify resolve_track failed: %s', type(exc).__name__)
            return None

    @staticmethod
    def _pick_best(items, duration_ms):
        if duration_ms is None:
            return items[0]
        try:
            target = float(duration_ms)
        except (TypeError, ValueError):
            return items[0]

        best, best_diff = None, None
        for item in items:
            value = item.get('duration_ms') if isinstance(item, dict) else None
            if not value:
                continue
            try:
                diff = abs(float(value) - target) / max(target, 1.0)
            except (TypeError, ValueError):
                continue
            if best_diff is None or diff < best_diff:
                best, best_diff = item, diff
        return best or items[0]

    @staticmethod
    def _to_metadata(item: Dict) -> Dict:
        artists = item.get('artists') or []
        artist_name = ', '.join(
            a.get('name', '') for a in artists
            if isinstance(a, dict) and a.get('name')
        )
        album = item.get('album') or {}
        release_date = str(album.get('release_date') or '')
        release_year = release_date[:4] if release_date[:4].isdigit() else None
        external = (item.get('external_urls') or {}).get('spotify')

        return {
            'name': item.get('name'),
            'artist': artist_name or None,
            'album': album.get('name'),
            'release_year': release_year,
            'duration_ms': item.get('duration_ms'),
            'external_url': external,
        }

    def build_search_query(self, metadata: Any) -> Optional[str]:
        """Build a high-confidence search query from Spotify metadata."""
        if not isinstance(metadata, dict):
            return None

        artist = str(metadata.get('artist') or '').strip()
        name = str(metadata.get('name') or '').strip()
        album = str(metadata.get('album') or '').strip()
        year = metadata.get('release_year')

        parts = []
        if artist:
            parts.append(artist)
        if name:
            parts.append(name)
        if album and album.lower() != name.lower():
            parts.append(album)
        if year is not None:
            year_text = str(year).strip()
            if year_text.isdigit() and len(year_text) == 4:
                parts.append(year_text)

        if not parts:
            return None
        return ' '.join(parts) + ' official audio'

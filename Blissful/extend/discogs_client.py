"""Discogs metadata client for Blissful.

Metadata only: Discogs is never used as a download source. It resolves a
release through the Discogs database search API so the search query sent to
YouTube / SoundCloud / Bandcamp can include the right year and edition.

Credentials come from ConfigManager or environment variables and are never
logged. A personal access token is preferred; consumer key + secret also work.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = 'https://api.discogs.com/database/search'
_TIMEOUT = 10
_USER_AGENT = 'Blissful/1.0 (+https://github.com/fkurevija/Blissful)'
_MIN_INTERVAL = 1.0  # Discogs allows 60 req/min; stay well under it.


class DiscogsClient:
    """Resolve release metadata via the Discogs database search API."""

    def __init__(self, config_manager: Any = None):
        self.config_manager = config_manager
        self._last_request_at = 0.0

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
                cfg = cm.get_config() or {}
                value = cfg.get(key, default) if isinstance(cfg, dict) else default
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
        token = self._setting('discogs_token', 'DISCOGS_TOKEN')
        key = self._setting('discogs_consumer_key', 'DISCOGS_CONSUMER_KEY')
        secret = self._setting('discogs_consumer_secret', 'DISCOGS_CONSUMER_SECRET')
        return token, key, secret

    def is_configured(self) -> bool:
        """True when a token, or a consumer key/secret pair, is available."""
        token, key, secret = self._credentials()
        return bool(token or (key and secret))

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve_track(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        year: Optional[Any] = None,
    ) -> Optional[Dict]:
        """Resolve a release, or None when Discogs is unavailable/unconfigured."""
        if not self.is_configured():
            return None

        params = {'type': 'release', 'artist': artist, 'track': title, 'per_page': 5}
        if album:
            params['release_title'] = album
        if year is not None and str(year).strip().isdigit():
            params['year'] = str(year).strip()[:4]

        token, key, secret = self._credentials()
        headers = {'User-Agent': _USER_AGENT}
        if token:
            headers['Authorization'] = 'Discogs token=' + token
        else:
            headers['Authorization'] = 'Discogs key=%s, secret=%s' % (key, secret)

        self._throttle()
        try:
            response = requests.get(
                _SEARCH_URL, params=params, headers=headers, timeout=_TIMEOUT)
        except Exception as exc:
            logger.debug('Discogs search failed: %s', type(exc).__name__)
            return None
        if response.status_code == 429:
            logger.warning('Discogs rate limited; skipping metadata lookup')
            return None
        if response.status_code != 200:
            logger.warning('Discogs search failed (HTTP %s)', response.status_code)
            return None

        try:
            results = (response.json() or {}).get('results') or []
        except Exception:
            return None
        best = self._pick_best(results, artist, album, year)
        return self._to_metadata(best, artist, title) if best else None

    @staticmethod
    def _pick_best(results, artist, album, year):
        """Prefer a result whose artist and year agree with the Lidarr track."""
        def score(item):
            if not isinstance(item, dict):
                return -1
            value = 0
            text = str(item.get('title') or '')
            if artist and artist.lower() in text.lower():
                value += 2
            if album and album.lower() in text.lower():
                value += 2
            try:
                if year is not None and int(item.get('year') or 0) == int(year):
                    value += 1
            except (TypeError, ValueError):
                pass
            return value

        ranked = sorted(results, key=score, reverse=True)
        return ranked[0] if ranked and score(ranked[0]) >= 0 else None

    @staticmethod
    def _to_metadata(item: Dict, artist: str, title: str) -> Dict:
        raw = str(item.get('title') or '')
        release = raw
        if ' - ' in raw:
            maybe_artist, maybe_release = raw.split(' - ', 1)
            if not artist or artist.lower() in maybe_artist.lower():
                release = maybe_release.strip()
        uri = str(item.get('uri') or '')
        external = 'https://www.discogs.com' + uri if uri.startswith('/') else (uri or None)
        return {
            'name': title,
            'artist': artist or None,
            'album': release or None,
            'release_year': item.get('year'),
            'label': ', '.join(item.get('label') or []) or None,
            'external_url': external,
            'discogs_id': item.get('id'),
        }

    def build_search_query(self, metadata: Any) -> Optional[str]:
        """Build a high-confidence search query from Discogs release metadata."""
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
        return ' '.join(parts) if parts else None

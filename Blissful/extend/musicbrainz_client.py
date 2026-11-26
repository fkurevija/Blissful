"""MusicBrainz metadata client for Blissful.

Metadata only: MusicBrainz never serves audio. It resolves a recording through
the public MusicBrainz web service so the search query sent to YouTube,
SoundCloud or Bandcamp can use the exact recording title, artist, release and
year. No credentials are required, but the API asks for a identifying
User-Agent and a maximum of one request per second.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = 'https://musicbrainz.org/ws/2/recording'
_USER_AGENT = 'Blissful/1.0 ( https://github.com/fkurevija/Blissful )'
_TIMEOUT = 10
_MIN_INTERVAL = 1.1  # MusicBrainz requires no more than one request/second.


class MusicBrainzClient:
    """Resolve recording metadata via the MusicBrainz web service."""

    def __init__(self, config_manager: Any = None):
        self.config_manager = config_manager
        self._last_request_at = 0.0

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

    def is_configured(self) -> bool:
        """No credentials are needed; only the enable checkbox matters."""
        return True

    def _user_agent(self) -> str:
        configured = str(self._cfg('musicbrainz_user_agent') or '').strip()
        env_value = os.environ.get('MUSICBRAINZ_USER_AGENT')
        if env_value and str(env_value).strip():
            return str(env_value).strip()
        return configured or _USER_AGENT

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

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
        """Resolve a recording, or None when MusicBrainz is unavailable."""
        query = 'recording:%s AND artist:%s' % (self._quote(title), self._quote(artist))
        if album:
            query += ' AND release:%s' % self._quote(album)
        params = {'query': query, 'fmt': 'json', 'limit': 5}

        self._throttle()
        try:
            response = requests.get(
                _SEARCH_URL, params=params,
                headers={'User-Agent': self._user_agent()}, timeout=_TIMEOUT)
        except Exception as exc:
            logger.debug('MusicBrainz search failed: %s', type(exc).__name__)
            return None
        if response.status_code == 429:
            logger.warning('MusicBrainz rate limited; skipping metadata lookup')
            return None
        if response.status_code != 200:
            logger.warning('MusicBrainz search failed (HTTP %s)', response.status_code)
            return None
        try:
            recordings = (response.json() or {}).get('recordings') or []
        except Exception:
            return None
        best = self._pick_best(recordings, artist, title, duration_ms)
        return self._to_metadata(best) if best else None

    @staticmethod
    def _artist_name(item: Dict) -> Optional[str]:
        credits = item.get('artist-credit') or []
        names = []
        for credit in credits:
            if not isinstance(credit, dict):
                continue
            names.append(str(credit.get('name') or
                             (credit.get('artist') or {}).get('name') or ''))
        return ', '.join(n for n in names if n) or None

    @staticmethod
    def _pick_best(recordings, artist, title, duration_ms):
        def score(item):
            if not isinstance(item, dict):
                return -1
            value = 0
            name = str(item.get('title') or '').lower()
            if title and title.lower() == name:
                value += 4
            elif title and title.lower() in name:
                value += 2
            found_artist = MusicBrainzClient._artist_name(item) or ''
            if artist and artist.lower() in found_artist.lower():
                value += 3
            try:
                if duration_ms is not None and item.get('length'):
                    diff = abs(float(item['length']) - float(duration_ms)) / max(float(duration_ms), 1)
                    if diff <= 0.1:
                        value += 2
            except (TypeError, ValueError):
                pass
            return value

        ranked = sorted(recordings, key=score, reverse=True)
        return ranked[0] if ranked and score(ranked[0]) >= 0 else None

    @staticmethod
    def _to_metadata(item: Dict) -> Dict:
        releases = item.get('releases') or []
        release = releases[0] if releases and isinstance(releases[0], dict) else {}
        date = str(release.get('date') or '')
        recording_id = item.get('id')
        return {
            'name': item.get('title'),
            'artist': MusicBrainzClient._artist_name(item),
            'album': release.get('title'),
            'release_year': date[:4] if date[:4].isdigit() else None,
            'duration_ms': item.get('length'),
            'external_url': ('https://musicbrainz.org/recording/' + recording_id)
                            if recording_id else None,
            'musicbrainz_id': recording_id,
        }

    def build_search_query(self, metadata: Any) -> Optional[str]:
        """Build a high-confidence search query from MusicBrainz metadata."""
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

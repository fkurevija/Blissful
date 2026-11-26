"""AcoustID / Chromaprint verification client for Blissful.

Post-download only: fingerprints an audio file with ``fpcalc`` and looks it
up through the AcoustID web service to verify that the candidate really is
the expected recording. AcoustID has no text-search endpoint, so this client
is never used to refine a pre-download search query.

Keys come from ConfigManager or environment variables and are never logged.
Application key (``client``) is required; a user key becomes mandatory for
lookups from 1 January 2027.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
import unicodedata
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_LOOKUP_URL = 'https://api.acoustid.org/v2/lookup'
_TIMEOUT = 15
_FPCALC_TIMEOUT = 120
_MIN_INTERVAL = 0.4  # AcoustID asks for no more than 3 requests/second.
_DEFAULT_MIN_SCORE = 0.75
_NON_WORD = re.compile(r'[^a-z0-9]+')


def _normalize(value: Any) -> str:
    """Normalize a title/artist for a forgiving comparison."""
    if not value:
        return ''
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')
    return _NON_WORD.sub(' ', text.lower()).strip()


class AcoustIDClient:
    """Identify a downloaded audio file via Chromaprint + AcoustID."""

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

    def _keys(self):
        api_key = self._setting('acoustid_api_key', 'ACOUSTID_API_KEY')
        user_key = self._setting('acoustid_user_key', 'ACOUSTID_USER_KEY')
        return api_key, user_key

    def is_configured(self) -> bool:
        """True when an application key and the fpcalc binary are available."""
        api_key, _ = self._keys()
        return bool(api_key) and bool(self.fpcalc_path())

    def fpcalc_path(self) -> Optional[str]:
        configured = str(self._cfg('acoustid_fpcalc_path') or '').strip()
        candidates = [configured, shutil.which('fpcalc'), '/usr/bin/fpcalc',
                      '/usr/local/bin/fpcalc']
        for path in candidates:
            if path and os.path.isfile(path):
                return path
        return None

    def min_score(self) -> float:
        try:
            value = float(self._cfg('acoustid_min_score', _DEFAULT_MIN_SCORE))
        except (TypeError, ValueError):
            return _DEFAULT_MIN_SCORE
        return min(1.0, max(0.0, value))

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------
    # Fingerprinting
    # ------------------------------------------------------------------
    def fingerprint_file(self, path: str) -> Optional[Dict]:
        """Return ``{'fingerprint': str, 'duration': int}`` for an audio file."""
        binary = self.fpcalc_path()
        if not binary:
            logger.debug('fpcalc is not installed; skipping AcoustID fingerprint')
            return None
        try:
            completed = subprocess.run(
                [binary, '-json', str(path)],
                capture_output=True, text=True, timeout=_FPCALC_TIMEOUT,
                check=False,
            )
            if completed.returncode != 0:
                logger.debug('fpcalc failed for %s', path)
                return None
            payload = json.loads(completed.stdout)
            fingerprint = payload.get('FINGERPRINT')
            duration = payload.get('DURATION')
            if not fingerprint or duration is None:
                return None
            return {'fingerprint': str(fingerprint), 'duration': int(float(duration))}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
            logger.debug('AcoustID fingerprint failed: %s', type(exc).__name__)
            return None

    # ------------------------------------------------------------------
    # Lookup / verification
    # ------------------------------------------------------------------
    def lookup(self, fingerprint: str, duration: int) -> Optional[Dict]:
        """Look up a Chromaprint fingerprint and return the best recording."""
        api_key, user_key = self._keys()
        if not api_key:
            return None

        headers = {'Acoustid-App-Key': api_key}
        if user_key:
            headers['Acoustid-User-Key'] = user_key
        data = {
            'format': 'json',
            'duration': int(duration),
            'fingerprint': fingerprint,
            'meta': 'recordings+releasegroups+compress',
        }

        self._throttle()
        try:
            response = requests.post(
                _LOOKUP_URL, data=data, headers=headers, timeout=_TIMEOUT)
        except Exception as exc:
            logger.debug('AcoustID lookup failed: %s', type(exc).__name__)
            return None
        if response.status_code == 429:
            logger.warning('AcoustID rate limited; skipping verification')
            return None
        if response.status_code != 200:
            logger.warning('AcoustID lookup failed (HTTP %s)', response.status_code)
            return None
        try:
            results = (response.json() or {}).get('results') or []
        except Exception:
            return None
        if not results:
            return None
        best = max(results, key=lambda item: float(item.get('score') or 0))
        return self._to_metadata(best)

    @staticmethod
    def _to_metadata(result: Dict) -> Dict:
        recording = (result.get('recordings') or [{}])[0]
        artists = recording.get('artists') or []
        groups = recording.get('releasegroups') or []
        return {
            'acoustid': result.get('id'),
            'score': float(result.get('score') or 0),
            'recording_id': recording.get('id'),
            'name': recording.get('title'),
            'artist': artists[0].get('name') if artists else None,
            'album': groups[0].get('title') if groups else None,
            'duration': recording.get('duration'),
        }

    def verify_file(
        self,
        path: str,
        artist: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict]:
        """Fingerprint ``path`` and verify it against the expected track.

        Returns AcoustID metadata with a ``verified`` boolean, or ``None``
        when fingerprinting/lookup was unavailable (never a hard failure).
        """
        fingerprint = self.fingerprint_file(path)
        if not fingerprint:
            return None
        metadata = self.lookup(fingerprint['fingerprint'], fingerprint['duration'])
        if not metadata:
            return None

        score_ok = metadata['score'] >= self.min_score()
        artist_ok = not artist or _normalize(metadata.get('artist')) == _normalize(artist)
        title_ok = not title or _normalize(metadata.get('name')) == _normalize(title)
        metadata['verified'] = bool(score_ok and artist_ok and title_ok)
        metadata['fingerprint_duration'] = fingerprint['duration']
        return metadata

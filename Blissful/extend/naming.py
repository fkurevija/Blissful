"""
Filename rendering helpers for Blissful.

Tokens follow either the short form used internally (``{artist}``,
``{track:00}``) or Lidarr's native naming tokens (``{Artist Name}``,
``{Track:00}``).  Sanitization is deliberately left to the caller so this
module never needs to import another manager.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TRACK_FORMAT = "{track:00} - {title}"
DEFAULT_MULTI_DISC_TRACK_FORMAT = "{disc:00}-{track:00} - {title}"

_TOKEN_RE = re.compile(r'\{([^{}]+)\}')
_LEADING_YEAR_RE = re.compile(r'(\d{4})')


def _to_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion of a track/disc number to an integer."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first(context: Dict[str, Any], *keys: str, default: Any = '') -> Any:
    for key in keys:
        if key in context and context[key] not in (None, ''):
            return context[key]
    return default


def _year_value(value: Any) -> str:
    """Return a four-digit year from a year value or an ISO date string."""
    text = str(value).strip() if value is not None else ''
    match = _LEADING_YEAR_RE.match(text)
    return match.group(1) if match else text


def sanitize_filename(filename: str) -> str:
    """Self-contained filesystem-safe fallback sanitizer (no external imports)."""
    for char in '<>:"/\\|?*':
        filename = filename.replace(char, '_')
    return filename.strip('. ')[:200]


def get_naming_config(lidarr_client: Any) -> Optional[Dict]:
    """
    Fetch Lidarr's naming configuration through the supplied client.

    The client exposes ``get_naming_config()`` which issues
    ``GET /api/v1/config/naming`` with the normal headers/timeout.

    Args:
        lidarr_client: An initialized LidarrClient instance

    Returns:
        Naming config dict, or None when unavailable
    """
    if lidarr_client is None:
        return None
    try:
        method = getattr(lidarr_client, 'get_naming_config', None)
        if callable(method):
            config = method()
            return config if isinstance(config, dict) else None

        # Minimal clients may only expose a generic GET helper.
        getter = getattr(lidarr_client, 'get', None)
        if callable(getter):
            config = getter('/api/v1/config/naming')
            return config if isinstance(config, dict) else None
    except Exception as exc:
        logger.debug(f"Could not fetch Lidarr naming configuration: {exc}")
    return None


def get_track_format(naming_config: Optional[Dict], disc_number: Any = None) -> str:
    """
    Pick the appropriate Lidarr track format for a track.

    Multi-disc releases use ``multiDiscTrackFormat`` when present so the disc
    number is not lost (Lidarr's default multi-disc format contains ``{Disc:00}``).

    Args:
        naming_config: Lidarr naming configuration dict (or None)
        disc_number: Disc number, used to select the multi-disc format

    Returns:
        A format string (never empty)
    """
    default = (DEFAULT_MULTI_DISC_TRACK_FORMAT if _to_int(disc_number, 1) > 1
               else DEFAULT_TRACK_FORMAT)
    if not isinstance(naming_config, dict):
        return default

    multi_disc = _to_int(disc_number, 1) > 1
    multi_keys = (
        'multiDiscTrackFormat', 'multi_disc_track_format',
        'multiDiscFormat', 'multi_disc_format', 'multiTrackFormat',
    )
    standard_keys = (
        'standardTrackFormat', 'standard_track_format',
        'trackFormat', 'track_format', 'trackFileFormat', 'track_file_format',
        'format',
    )

    fmt = ''
    if multi_disc:
        for key in multi_keys:
            value = naming_config.get(key)
            if isinstance(value, str) and value.strip():
                fmt = value
                break
    if not fmt:
        for key in standard_keys:
            value = naming_config.get(key)
            if isinstance(value, str) and value.strip():
                fmt = value
                break
    return fmt if fmt else default


def _build_values(context: Dict[str, Any]) -> Dict[str, str]:
    """Build the normalized token -> replacement mapping."""
    artist = _first(context, 'artist', 'Artist Name', 'artist name',
                    'album_artist', 'album artist')
    album_artist = _first(context, 'album_artist', 'album artist', 'artist')
    album = _first(context, 'album', 'Album Title', 'album title',
                   'albumName', 'album_name')
    title = _first(context, 'title', 'Track Title', 'track title', 'trackName')

    track = _to_int(_first(context, 'track', 'trackNumber', 'track_number',
                           'Track', default=0), 0)
    disc = _to_int(_first(context, 'disc', 'discNumber', 'disc_number',
                          'mediumNumber', 'Disc', default=1), 1)
    if disc < 0:
        disc = 0

    year = _year_value(_first(context, 'year', 'release_year', 'releaseYear',
                              'Release Year', 'releaseDate'))
    release_year = _year_value(_first(context, 'release_year', 'releaseYear',
                                      'Release Year', 'year', 'releaseDate'))
    release_year = release_year or year
    year = year or release_year

    values = {
        'artist': str(artist),
        'artist name': str(artist),
        'album artist': str(album_artist),
        'album': str(album),
        'album title': str(album),
        'title': str(title),
        'track title': str(title),
        'track': str(track),
        'disc': str(disc),
        'track:00': f'{track:02d}',
        'disc:00': f'{disc:02d}',
        'year': year,
        'release year': release_year,
    }
    return values


def _has_disc_token(fmt: str) -> bool:
    return any('disc' in token.lower() for token in _TOKEN_RE.findall(fmt))


def render_track_filename(fmt: str, context: Dict[str, Any],
                          sanitize: Any = None, sanitizer: Any = None) -> str:
    """
    Render a Lidarr-style format string into a track filename (no extension).

    Supported tokens (case-insensitive, underscores treated as spaces):
    ``{artist}``, ``{album}``, ``{title}``, ``{track}``, ``{track:00}``,
    ``{disc}``, ``{disc:00}``, ``{year}`` and ``{release_year}``.  Lidarr's
    native spellings (``{Artist Name}``, ``{Album Title}``, ``{Track Title}``,
    ``{Track:00}``, ``{Disc:00}``, ``{Release Year}``) are accepted too.
    ``year`` falls back to ``release_year`` and vice versa.  Unknown tokens are
    left untouched.

    Multi-disc tracks (``disc`` > 1) whose format has no disc token get a disc
    prefix so files from different discs cannot collide.

    Sanitization is optional and supplied by the caller via ``sanitize`` /
    ``sanitizer`` (or a callable ``sanitize`` entry in ``context``).

    Args:
        fmt: Format template; falls back to a sensible default when empty
        context: Token values
        sanitize: Optional callable applied to the rendered filename
        sanitizer: Alias for ``sanitize``

    Returns:
        Rendered filename stem
    """
    context = context or {}
    disc = _to_int(_first(context, 'disc', 'discNumber', 'disc_number',
                          'mediumNumber', 'Disc', default=1), 1)
    if not fmt:
        fmt = (DEFAULT_MULTI_DISC_TRACK_FORMAT if disc > 1
               else DEFAULT_TRACK_FORMAT)
    fmt = str(fmt)
    values = _build_values(context)

    padded_re = re.compile(r'^(track|disc):0+$')

    def substitute(match):
        key = match.group(1).strip().lower().replace('_', ' ')
        if key in values:
            return values[key]
        padded = padded_re.match(key)
        if padded:
            base = padded.group(1)
            width = len(key.split(':', 1)[1])
            return str(_to_int(values.get(base, 0), 0)).zfill(width)
        return match.group(0)

    result = _TOKEN_RE.sub(substitute, fmt)

    if disc > 1 and not _has_disc_token(fmt):
        result = f'{disc:02d} {result}'

    cleaner = sanitize or sanitizer or context.get('sanitize') or context.get('sanitizer')
    if callable(cleaner):
        result = str(cleaner(result))
    return result

import yt_dlp
import os
import json
import threading
import logging
import shutil
from pathlib import Path
from typing import Dict, Optional, Any
import subprocess

try:
    from .bandcamp_resolver import BandcampResolver
except (ImportError, ValueError):  # pragma: no cover - standalone module import
    try:
        from bandcamp_resolver import BandcampResolver
    except ImportError:
        BandcampResolver = None

logger = logging.getLogger(__name__)

# Live download progress for the Wanted tab. One worker processes jobs, so a
# single snapshot is enough; reads from the web thread are guarded.
DOWNLOAD_PROGRESS = {}
_DOWNLOAD_PROGRESS_LOCK = threading.Lock()

_DEFAULT_POT_URL = 'http://blissful-pot:4416'
_DEFAULT_DENO_PATH = '/usr/local/bin/deno'
_IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp', '.avif', '.gif')


class DownloadManager:
    """Manager for downloading tracks using yt-dlp"""

    def __init__(
        self,
        download_dir: str = 'downloads',
        config_manager: Any = None,
        spotify_client: Any = None,
        discogs_client: Any = None,
        acoustid_client: Any = None,
        musicbrainz_client: Any = None,
    ):
        """
        Initialize download manager.

        Args:
            download_dir: Directory to store downloaded files
            config_manager: Optional ConfigManager-compatible object/dict
            spotify_client: Optional metadata-only SpotifyClient
            discogs_client: Optional metadata-only DiscogsClient (query refinement)
            acoustid_client: Optional AcoustIDClient (post-download verification)
            musicbrainz_client: Optional MusicBrainzClient (query refinement)
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Temporary directory for downloads
        self.temp_dir = self.download_dir / 'temp'
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.config_manager = config_manager
        self.spotify_client = spotify_client
        self.discogs_client = discogs_client
        self.acoustid_client = acoustid_client
        self.musicbrainz_client = musicbrainz_client

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        """Read a setting from a ConfigManager, dict, or plain object."""
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

    def _setting(self, key: str, env_names, default: str) -> str:
        """Resolve a setting with environment variables taking precedence."""
        for env_name in env_names:
            value = os.environ.get(env_name)
            if value is not None and str(value).strip():
                return str(value).strip()
        value = self._cfg(key, None)
        if value is not None and str(value).strip():
            return str(value).strip()
        return default

    @staticmethod
    def _as_bool(value: Any, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ('false', '0', 'no', 'off', ''):
            return False
        if text in ('true', '1', 'yes', 'on'):
            return True
        return default

    @staticmethod
    def _parse_js_runtimes(raw: Any) -> Optional[Dict]:
        """Parse YT_DLP_JS_RUNTIMES (JSON object or 'deno:/x,node' list)."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        result: Dict[str, Dict] = {}

        if text.startswith('{'):
            data = None
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                pass
            if isinstance(data, dict):
                for name, value in data.items():
                    name = str(name).strip()
                    if not name:
                        continue
                    if isinstance(value, dict):
                        result[name] = dict(value)
                    elif isinstance(value, str) and value.strip():
                        result[name] = {'path': value.strip()}
                    else:
                        result[name] = {}
                return result or None

        for token in text.split(','):
            token = token.strip()
            if not token:
                continue
            if ':' in token:
                name, path = token.split(':', 1)
                name, path = name.strip(), path.strip()
                if not name:
                    continue
                result[name] = {'path': path} if path else {}
            else:
                result[token] = {}
        return result or None

    # ------------------------------------------------------------------
    # yt-dlp option construction
    # ------------------------------------------------------------------
    def _build_ydl_opts(self, output_template: str) -> Dict:
        """
        Build the shared yt-dlp option dictionary.

        Mirrors the verified live setup: PO-token provider via
        youtubepot-bgutilhttp and a deno JS runtime, both configurable.
        """
        codec = str(self._cfg('output_format', 'mp3') or 'mp3').strip().lower().lstrip('.')
        if codec not in ('mp3', 'flac', 'wav', 'ogg', 'opus', 'm4a', 'aac', 'best'):
            codec = 'mp3'

        quality_raw = str(self._cfg('quality', '320') or '320').strip().lower()
        quality = quality_raw[:-1] if quality_raw.endswith('k') else quality_raw
        if not quality.isdigit():
            quality = '320'

        ydl_opts: Dict[str, Any] = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'writethumbnail': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': codec,
                'preferredquality': quality,
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'noplaylist': True,
            # max_downloads is intentionally omitted: yt-dlp counts search +
            # download as two downloads and raises MaxDownloadsReached.
        }

        # PO token provider (bgutil-ytdlp-pot-provider sidecar). Same options
        # fix 403s for both YouTube and YouTube Music.
        enable_pot = self._as_bool(self._cfg('enable_pot_provider', True), True)
        env_pot = os.environ.get('ENABLE_POT_PROVIDER')
        if env_pot is not None:
            enable_pot = self._as_bool(env_pot, True)
        pot_url = self._setting(
            'pot_provider_url', ('POT_PROVIDER_URL',), _DEFAULT_POT_URL)

        extractor_args: Dict[str, Dict] = {}
        if enable_pot:
            extractor_args['youtubepot-bgutilhttp'] = {'base_url': [pot_url]}

        extra_args: Dict[str, Dict] = {}
        cfg_args = self._cfg('ytdlp_extractor_args', None)
        if isinstance(cfg_args, dict):
            extra_args.update(cfg_args)
        env_args_raw = os.environ.get('YT_DLP_EXTRACTOR_ARGS')
        if env_args_raw and str(env_args_raw).strip():
            try:
                parsed = json.loads(env_args_raw)
                if isinstance(parsed, dict):
                    extra_args.update(parsed)
                else:
                    logger.warning('YT_DLP_EXTRACTOR_ARGS is not a JSON object; ignoring')
            except (ValueError, TypeError):
                logger.warning('YT_DLP_EXTRACTOR_ARGS is not valid JSON; ignoring')

        for key, value in extra_args.items():
            if not key or not isinstance(value, dict):
                continue
            if key == 'youtubepot-bgutilhttp':
                # Never let extra args clobber the configured POT endpoint.
                if enable_pot:
                    merged = dict(value)
                    merged['base_url'] = [pot_url]
                    extractor_args[key] = merged
            elif key in extractor_args and isinstance(extractor_args[key], dict):
                nested = dict(extractor_args[key])
                nested.update(value)
                extractor_args[key] = nested
            else:
                extractor_args[key] = dict(value)

        if extractor_args:
            ydl_opts['extractor_args'] = extractor_args

        # JavaScript runtime needed by current yt-dlp challenge solvers.
        js_runtimes = self._parse_js_runtimes(os.environ.get('YT_DLP_JS_RUNTIMES'))
        if js_runtimes is None:
            deno_path = os.path.expanduser(
                self._setting('deno_path', ('DENO_PATH',), _DEFAULT_DENO_PATH))
            if not os.path.isfile(deno_path):
                found = shutil.which('deno')
                if found:
                    deno_path = found
            if os.path.isfile(deno_path):
                js_runtimes = {'deno': {'path': deno_path}}
        if js_runtimes:
            ydl_opts['js_runtimes'] = js_runtimes

        # Optional explicit yt-dlp config file; leave YT_DLP_HOME alone when
        # unset (no config_paths key added).
        config_file = os.environ.get('YT_DLP_CONFIG_FILE') or self._cfg('ytdlp_config_file', None)
        if config_file:
            ydl_opts['config_paths'] = [os.path.expanduser(str(config_file))]

        return ydl_opts

    # ----------------------------------------------------------- progress
    def get_download_progress(self):
        """Snapshot of the current download attempt (safe cross-thread read)."""
        with _DOWNLOAD_PROGRESS_LOCK:
            return dict(DOWNLOAD_PROGRESS)

    def _set_download_progress(self, **updates):
        with _DOWNLOAD_PROGRESS_LOCK:
            DOWNLOAD_PROGRESS.update(updates)
            return dict(DOWNLOAD_PROGRESS)

    def _add_source_attempt(self, source, status, reason=''):
        with _DOWNLOAD_PROGRESS_LOCK:
            attempts = list(DOWNLOAD_PROGRESS.get('attempts') or [])
            attempts.append({'source': str(source), 'status': status,
                             'reason': str(reason or '')})
            DOWNLOAD_PROGRESS['attempts'] = attempts[-30:]
            return dict(DOWNLOAD_PROGRESS)

    def reset_download_progress(self):
        with _DOWNLOAD_PROGRESS_LOCK:
            DOWNLOAD_PROGRESS.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_ytdlp(self) -> bool:
        """Check if yt-dlp is available"""
        try:
            import yt_dlp  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def is_duration_acceptable(actual, expected, tolerance: float = 0.10) -> bool:
        """
        Return True when ``actual`` is within ``tolerance`` (fraction) of
        ``expected``. An unknown duration cannot prove a mismatch, so it is
        accepted; no expectation at all always accepts.
        """
        if expected is None or actual is None:
            return True
        try:
            actual_value = float(actual)
            expected_value = float(expected)
            tolerance_value = float(tolerance)
        except (TypeError, ValueError):
            return True
        if expected_value <= 0:
            return True
        return abs(actual_value - expected_value) <= tolerance_value * expected_value

    def download_track(
        self,
        artist: str,
        title: str,
        album: str = '',
        output_format: str = 'mp3',
        source_priorities: list = None,
        expected_duration=None,
    ) -> Dict:
        """
        Download a track based on metadata.

        Args:
            artist: Artist name
            title: Track title
            album: Album name (optional)
            output_format: Desired output format
            source_priorities: Optional list of source priorities
            expected_duration: Expected track length in seconds (optional)

        Returns:
            Dict with success status, file path, duration, thumbnail path or error
        """
        try:
            search_query, metadata_source = self._refine_search_query(
                artist, title, album, expected_duration)
            logger.info(f"Searching for: {search_query} (metadata: {metadata_source})")

            if source_priorities:
                sources = self._build_source_list(search_query, source_priorities)
            else:
                sources = [
                    f"{self._search_prefix('ytsearch')}{search_query} site:music.youtube.com",  # YouTube Music search
                    f"{self._search_prefix('ytsearch')}{search_query}",  # YouTube search
                    f"{self._search_prefix('scsearch')}{search_query}",  # SoundCloud search
                ]

            self._set_download_progress(
                artist=artist, album=album or '', title=title,
                source=None, status='searching', attempts=[], pending=len(sources))

            tolerance = self._duration_tolerance()
            downloaded_file = None
            final_duration = None
            final_thumbnail = None
            final_acoustid = None
            acoustid_info = None
            last_error = None

            for index, source in enumerate(sources, 1):
                try:
                    self._set_download_progress(
                        source=source, status='trying',
                        pending=max(0, len(sources) - index))
                    logger.info(f"Trying source: {source}")
                    result = self._download_from_source(
                        source, artist, title, expected_duration=expected_duration)

                    if not result or not result.get('success'):
                        last_error = (result or {}).get('error')
                        self._add_source_attempt(source, 'failed', last_error)
                        continue

                    duration = result.get('duration')
                    if expected_duration is not None and not self.is_duration_acceptable(
                            duration, expected_duration, tolerance):
                        rejected = result.get('file_path')
                        if rejected:
                            self._delete_file(rejected)
                        logger.warning(
                            'Rejected candidate from %s: duration %s outside tolerance of %ss',
                            source, duration, expected_duration)
                        last_error = 'Duration mismatch'
                        self._add_source_attempt(source, 'rejected', last_error)
                        continue

                    acoustid_info = None
                    if self._as_bool(self._cfg('acoustid_verify_enabled', False), False) \
                            and self.acoustid_client is not None:
                        candidate = result.get('file_path')
                        if candidate:
                            try:
                                acoustid_info = self.acoustid_client.verify_file(
                                    candidate, artist=artist, title=title)
                            except Exception:
                                logger.debug('AcoustID verification unavailable')
                            if acoustid_info and not acoustid_info.get('verified'):
                                logger.warning(
                                    'Rejected candidate from %s: AcoustID score %s for %s',
                                    source, acoustid_info.get('score'),
                                    acoustid_info.get('name'))
                                self._delete_file(candidate)
                                last_error = 'AcoustID verification failed'
                                self._add_source_attempt(source, 'rejected', last_error)
                                continue
                            if acoustid_info:
                                self._add_source_attempt(
                                    source, 'verified',
                                    'AcoustID score %s' % acoustid_info.get('score'))

                    downloaded_file = result.get('file_path')
                    final_duration = duration
                    final_thumbnail = result.get('thumbnail_path')
                    final_acoustid = acoustid_info
                    if not acoustid_info:
                        self._add_source_attempt(source, 'success')
                    self._set_download_progress(status='downloaded', source=source,
                                                pending=max(0, len(sources) - index))
                    break

                except Exception as e:
                    logger.warning(f"Failed to download from source {source}: {e}")
                    last_error = str(e)
                    self._add_source_attempt(source, 'failed', last_error)
                    continue

            if downloaded_file:
                return {
                    'success': True,
                    'file_path': downloaded_file,
                    'artist': artist,
                    'title': title,
                    'duration': final_duration,
                    'thumbnail_path': final_thumbnail,
                    'acoustid': final_acoustid,
                }

            attempts = []
            try:
                attempts = self.get_download_progress().get('attempts') or []
            except Exception:
                pass
            return {
                'success': False,
                'error': last_error or 'Could not find track from any source',
                'duration': None,
                'thumbnail_path': None,
                'attempts': attempts[-8:],
            }

        except Exception as e:
            logger.error(f"Error downloading track: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'duration': None,
                'thumbnail_path': None,
            }

    def _metadata_order(self):
        """Configured provider order, sanitized and always complete."""
        known = ['spotify', 'discogs', 'musicbrainz', 'acoustid']
        raw = self._cfg('metadata_provider_order', None)
        order = []
        if isinstance(raw, (list, tuple)):
            for item in raw:
                name = str(item).strip().lower()
                if name in known and name not in order:
                    order.append(name)
        for name in known:
            if name not in order:
                order.append(name)
        return order

    def _refine_search_query(self, artist, title, album, expected_duration=None):
        """Build the query from the first enabled provider that resolves."""
        query = f"{artist} - {album} - {title}" if album else f"{artist} - {title}"
        source = 'plain'

        def spotify():
            nonlocal query, source
            if not self._as_bool(self._cfg('spotify_metadata_enabled', False), False) \
                    or self.spotify_client is None:
                return False
            duration_ms = None
            if expected_duration is not None:
                try:
                    duration_ms = int(float(expected_duration) * 1000)
                except (TypeError, ValueError):
                    pass
            try:
                metadata = self.spotify_client.resolve_track(
                    artist, title, album=album or None, duration_ms=duration_ms)
            except Exception:
                logger.debug('Spotify lookup unavailable; using plain query')
                return False
            try:
                refined = self.spotify_client.build_search_query(metadata) if metadata else None
            except Exception:
                refined = None
            if refined:
                query, source = refined, 'spotify'
                return True
            return False

        def discogs():
            nonlocal query, source
            if not self._as_bool(self._cfg('discogs_metadata_enabled', False), False) \
                    or self.discogs_client is None:
                return False
            try:
                release = self.discogs_client.resolve_track(
                    artist, title, album=album or None)
            except Exception:
                logger.debug('Discogs lookup unavailable; using current query')
                return False
            try:
                refined = self.discogs_client.build_search_query(release) if release else None
            except Exception:
                refined = None
            if refined:
                query, source = refined, 'discogs'
                return True
            return False

        def musicbrainz():
            nonlocal query, source
            if not self._as_bool(self._cfg('musicbrainz_metadata_enabled', False), False):
                return False
            if self.musicbrainz_client is None:
                return False
            try:
                recording = self.musicbrainz_client.resolve_track(
                    artist, title, album=album or None)
            except Exception:
                logger.debug('MusicBrainz lookup unavailable; using current query')
                return False
            try:
                refined = self.musicbrainz_client.build_search_query(recording) if recording else None
            except Exception:
                refined = None
            if refined:
                query, source = refined, 'musicbrainz'
                return True
            return False

        handlers = {'spotify': spotify, 'discogs': discogs,
                    'musicbrainz': musicbrainz}
        for name in self._metadata_order():
            handler = handlers.get(name)
            if handler and handler():
                break
        return query, source

    def _search_prefix(self, name: str) -> str:
        """yt-dlp search prefix with the configured candidate count."""
        try:
            count = int(float(self._cfg('search_results_per_source', 3)))
        except (TypeError, ValueError):
            count = 3
        return f"{name}{min(10, max(1, count))}:"

    def _duration_tolerance(self) -> float:
        raw = self._cfg('max_duration_deviation', 0.10)
        try:
            tolerance = float(raw)
        except (TypeError, ValueError):
            tolerance = 0.10
        if tolerance < 0:
            tolerance = 0.10
        if tolerance > 1:
            tolerance = tolerance / 100.0
        return tolerance

    @staticmethod
    def _delete_file(path):
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.debug('Could not remove rejected file: %s', path)

    # ------------------------------------------------------------------
    # Source construction
    # ------------------------------------------------------------------
    def _build_source_list(self, search_query: str, priorities: list) -> list:
        """
        Build ordered source list based on priorities.

        Spotify is a metadata provider only - it is never a download source
        and never falls back to a YouTube search here.
        """
        sources = []

        for priority in priorities:
            if not priority.get('enabled', True):
                continue

            name = priority.get('name', '').lower()
            search = priority.get('search', '').lower()

            # YouTube and YouTube Music share the same yt-dlp options.
            if 'youtube' in name or 'youtube.com' in search:
                if 'music' in name or 'music.youtube' in search:
                    clean_query = search_query.replace('"', '').replace("'", '').strip()
                    sources.append(f"{self._search_prefix('ytsearch')}{clean_query} site:music.youtube.com")
                else:
                    sources.append(f"{self._search_prefix('ytsearch')}{search_query}")

            # SoundCloud
            elif 'soundcloud' in name or 'soundcloud.com' in search:
                sources.append(f"{self._search_prefix('scsearch')}{search_query}")

            # Bandcamp: resolved to a real track/album URL at download time.
            elif 'bandcamp' in name or 'bandcamp.com' in search:
                sources.append(f"bandcamp:{search_query}")

            # Spotify: metadata only - intentionally no download source here.
            elif 'spotify' in name or 'spotify.com' in search:
                continue

            # Discogs/AcoustID: metadata only - never download sources.
            elif ('discog' in name or 'discogs.com' in search
                  or 'acoustid' in name or 'acoustid.org' in search
                  or 'musicbrainz' in name or 'musicbrainz.org' in search):
                continue

            # Apple Music
            elif 'apple' in name or 'apple.com' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} apple music")

            # Deezer
            elif 'deezer' in name or 'deezer.com' in search:
                sources.append(f"{self._search_prefix('dzsearch')}{search_query}")
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} deezer")

            # Tidal
            elif 'tidal' in name or 'tidal.com' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} tidal")

            # Mixcloud
            elif 'mixcloud' in name or 'mixcloud.com' in search:
                sources.append(f"https://www.mixcloud.com/search/?q={search_query.replace(' ', '+')}")

            # Archive.org
            elif 'archive' in name or 'archive.org' in search:
                sources.append(f"https://archive.org/search.php?query={search_query.replace(' ', '+')}&and[]=mediatype:audio")

            # Jamendo
            elif 'jamendo' in name or 'jamendo.com' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} jamendo")

            # Free Music Archive
            elif 'freemusicarchive' in name or 'freemusicarchive.org' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} free music archive")

            # Audiomack
            elif 'audiomack' in name or 'audiomack.com' in search:
                sources.append(f"https://audiomack.com/search?q={search_query.replace(' ', '+')}")

            # Vimeo
            elif 'vimeo' in name or 'vimeo.com' in search:
                sources.append(f"https://vimeo.com/search?q={search_query.replace(' ', '+')}")

            # Dailymotion
            elif 'dailymotion' in name or 'dailymotion.com' in search:
                sources.append(f"https://www.dailymotion.com/search/{search_query.replace(' ', '+')}")

            # TikTok
            elif 'tiktok' in name or 'tiktok.com' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} tiktok")

            # Reverbnation
            elif 'reverbnation' in name or 'reverbnation.com' in search:
                sources.append(f"{self._search_prefix('ytsearch')}{search_query} reverbnation")

        # If no sources were added, add default fallbacks
        if not sources:
            sources = [
                f"{self._search_prefix('ytsearch')}{search_query}",
                f"{self._search_prefix('scsearch')}{search_query}",
            ]

        return sources

    # ------------------------------------------------------------------
    # Download execution
    # ------------------------------------------------------------------
    def _download_from_source(
        self,
        source: str,
        artist: str,
        title: str,
        expected_duration=None,
    ) -> Dict:
        """Download from a specific source."""
        try:
            # Bandcamp queries are resolved to a concrete track/album URL.
            if source.startswith('bandcamp:'):
                query = source.split(':', 1)[1].strip()
                if BandcampResolver is None:
                    return {'success': False, 'error': 'Bandcamp resolver unavailable'}
                resolved = BandcampResolver().resolve(query)
                if not resolved:
                    return {'success': False, 'error': 'Bandcamp resolver found no track URL'}
                logger.info(f"Resolved Bandcamp source to: {resolved}")
                source = resolved

            # Sanitize filename
            safe_filename = self._sanitize_filename(f"{artist} - {title}")
            output_template = str(self.temp_dir / f"{safe_filename}.%(ext)s")
            ydl_opts = self._build_ydl_opts(output_template)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first to verify there is a result.
                try:
                    info = ydl.extract_info(source, download=False)
                    if not info or ('entries' in info and not info['entries']):
                        return {'success': False, 'error': 'No results found'}

                    info = ydl.extract_info(source, download=True)
                    if isinstance(info, dict) and 'entries' in info:
                        entries = info.get('entries') or []
                        info = entries[0] if entries else None
                except Exception as e:
                    logger.warning(f"Extraction failed for {source}: {e}")
                    return {'success': False, 'error': str(e)}

                duration, thumbnail_path = self._extract_info_fields(info, safe_filename)

                expected_file = self.temp_dir / f"{safe_filename}.mp3"
                downloaded = expected_file if expected_file.exists() else None
                if downloaded is None:
                    for candidate in sorted(self.temp_dir.glob(f"{safe_filename}.*")):
                        if candidate.suffix.lower() in _IMAGE_SUFFIXES:
                            continue
                        downloaded = candidate
                        break

                if downloaded is None:
                    return {
                        'success': False,
                        'error': 'Downloaded file not found',
                        'duration': duration,
                        'thumbnail_path': thumbnail_path,
                    }

                logger.info(f"Successfully downloaded: {downloaded}")
                return {
                    'success': True,
                    'file_path': str(downloaded),
                    'duration': duration,
                    'thumbnail_path': thumbnail_path,
                }

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"Download error: {e}")
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"Unexpected error downloading: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _extract_info_fields(self, info, safe_filename: str):
        """Pull duration and a local thumbnail path from extraction info."""
        duration = None
        thumbnail_path = None
        if not isinstance(info, dict):
            return duration, thumbnail_path

        raw_duration = info.get('duration')
        if raw_duration is not None:
            try:
                parsed = float(raw_duration)
                if parsed > 0:
                    duration = parsed
            except (TypeError, ValueError):
                duration = None

        thumbnails = info.get('thumbnails') or []
        if isinstance(thumbnails, list):
            for thumb in thumbnails:
                if not isinstance(thumb, dict):
                    continue
                local = thumb.get('filepath') or thumb.get('path')
                if local and os.path.isfile(str(local)):
                    thumbnail_path = str(local)
                    break

        if thumbnail_path is None:
            for suffix in _IMAGE_SUFFIXES:
                candidate = self.temp_dir / f"{safe_filename}{suffix}"
                if candidate.is_file():
                    thumbnail_path = str(candidate)
                    break

        if thumbnail_path is None:
            for candidate in sorted(self.temp_dir.glob(f"{safe_filename}.*")):
                if candidate.suffix.lower() in _IMAGE_SUFFIXES:
                    thumbnail_path = str(candidate)
                    break

        return duration, thumbnail_path

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe file system storage"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')

        filename = filename.strip('. ')

        if len(filename) > 200:
            filename = filename[:200]

        return filename

    def move_to_target(
        self,
        source_file: str,
        target_path: str,
        path_mapping: Optional[Dict[str, str]] = None,
    ) -> str:
        """Move file to target location with path mapping"""
        try:
            source = Path(source_file)

            target_path = target_path.replace('\\', '/')

            if path_mapping:
                for micro_path, lidarr_path in path_mapping.items():
                    micro_path_norm = micro_path.replace('\\', '/')
                    lidarr_path_norm = lidarr_path.replace('\\', '/')
                    target_path_norm = target_path.replace('\\', '/')

                    if target_path_norm.startswith(lidarr_path_norm):
                        target_path = target_path_norm.replace(lidarr_path_norm, micro_path_norm, 1)
                        logger.info(f"Path mapping applied: {lidarr_path_norm} -> {micro_path_norm}")
                        break

            target = Path(target_path)
            target.parent.mkdir(parents=True, exist_ok=True)

            logger.info(f"Moving file from {source} to {target}")
            shutil.move(str(source), str(target))

            logger.info(f"✅ Successfully moved file to: {target}")
            return str(target)

        except Exception as e:
            logger.error(f"❌ Error moving file to target: {e}", exc_info=True)
            return source_file

    def cleanup_temp(self):
        """Clean up temporary download directory"""
        try:
            for file in self.temp_dir.glob('*'):
                if file.is_file():
                    file.unlink()
            logger.info("Cleaned up temporary downloads")
        except Exception as e:
            logger.error(f"Error cleaning up temp directory: {e}")

    def get_supported_sources(self) -> list:
        """
        Get list of supported download sources.

        Spotify is listed as a metadata provider only, never as a download
        source.
        """
        return [
            'YouTube',
            'YouTube Music',
            'SoundCloud',
            'Bandcamp',
            'And many more supported by yt-dlp',
            'Spotify (metadata provider via SpotifyClient; not a download source)',
        ]

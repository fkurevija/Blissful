"""
Track Download Manager for Blissful
Handles individual track downloads with Lidarr integration
"""

import inspect
import logging
from pathlib import Path
import shutil

try:
    from . import naming
except ImportError:  # pragma: no cover - supports direct module import
    import naming

logger = logging.getLogger(__name__)


class TrackManager:
    """Manages track download operations"""

    def __init__(self, config_manager, lidarr_client_class, download_manager, audio_converter):
        self.config_manager = config_manager
        self.LidarrClient = lidarr_client_class
        self.download_manager = download_manager
        self.audio_converter = audio_converter

    @staticmethod
    def _is_enabled(config, key, default=True):
        """Feature flags default to on; only an explicit False disables them."""
        return config.get(key, default) is not False

    def _download(self, artist, title, album, config, expected_duration):
        """Download a track, passing the expected duration when supported."""
        kwargs = {
            'artist': artist,
            'title': title,
            'album': album,
            'output_format': config.get('output_format', 'mp3'),
            'source_priorities': config.get('source_priorities', []),
        }
        try:
            return self.download_manager.download_track(
                expected_duration=expected_duration, **kwargs
            )
        except TypeError as exc:
            if 'expected_duration' not in str(exc):
                raise
            # Older download managers may not know about duration hints yet.
            logger.debug("Download manager does not accept expected_duration; retrying")
            return self.download_manager.download_track(**kwargs)

    def _check_duration(self, file_path, expected_duration):
        """
        Validate a converted file against the expected duration.

        Returns:
            (acceptable, measured_duration_or_None)
        """
        if expected_duration is None:
            return True, None

        validator = getattr(self.download_manager, 'is_duration_acceptable', None)
        if not callable(validator):
            return True, None

        first_name = ''
        try:
            params = list(inspect.signature(validator).parameters.values())
            first_name = params[0].name.lower() if params else ''
        except (TypeError, ValueError):
            pass
        path_first = any(word in first_name for word in ('path', 'file'))

        measured = None
        order = (True, False) if path_first else (False, True)
        for use_path in order:
            try:
                if use_path:
                    accepted = validator(file_path, expected_duration)
                else:
                    if measured is None:
                        measured = self.audio_converter.get_duration(file_path)
                    accepted = validator(measured, expected_duration)
                return bool(accepted), measured
            except (TypeError, ArithmeticError):
                continue
            except Exception as exc:
                logger.warning(f"Duration validation failed, accepting file: {exc}")
                return True, measured
        return True, measured

    def download_track(
        self,
        artist,
        title,
        album='',
        album_id=None,
        track_number=1,
        expected_duration=None,
        disc_number=None,
        year=None,
        genre=None
    ):
        """
        Download a track based on metadata

        Args:
            artist: Artist name
            title: Track title
            album: Album name (optional)
            album_id: Lidarr album ID for organization (optional)
            track_number: Track number for filename (default: 1)
            expected_duration: Expected track length in seconds
            disc_number: Disc number for tags and multi-disc naming
            year: Release year for tags and naming
            genre: Genre for tags

        Returns:
            dict: Download result with file path and rescan status
        """
        try:
            logger.info(f"Downloading track: {artist} - {title}")

            config = self.config_manager.get_config()

            # Search and download track (duration hint helps pick the right result)
            download_result = self._download(
                artist, title, album, config, expected_duration
            )

            if not download_result['success']:
                return download_result

            # Convert to desired format
            output_format = config.get('output_format', 'mp3')
            converted_file = self.audio_converter.convert(
                input_file=download_result['file_path'],
                output_format=output_format,
                quality=config.get('quality', '320k')
            )

            # Reject obviously wrong matches before tagging/organizing them.
            acceptable, measured = self._check_duration(converted_file, expected_duration)
            if not acceptable:
                try:
                    Path(converted_file).unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning(f"Could not remove bad file {converted_file}: {exc}")
                actual = measured if measured is not None else self.audio_converter.get_duration(converted_file)
                logger.warning(
                    f"Rejected {artist} - {title}: duration {actual} does not match {expected_duration}s"
                )
                return {
                    'success': False,
                    'error': (
                        f"Downloaded audio for {artist} - {title} has duration {actual}s, "
                        f"which does not match the expected duration {expected_duration}s"
                    ),
                    'actual_duration': actual,
                    'expected_duration': expected_duration,
                }

            # Embed metadata before the file is moved into Lidarr's library.
            if self._is_enabled(config, 'embed_metadata'):
                thumbnail = None
                if self._is_enabled(config, 'embed_thumbnail'):
                    thumbnail = download_result.get('thumbnail_path')
                self.audio_converter.add_metadata(
                    converted_file,
                    artist=artist,
                    album_artist=artist,
                    title=title,
                    album=album,
                    year=year,
                    track_number=track_number,
                    disc=disc_number,
                    genre=genre,
                    thumbnail_path=thumbnail,
                )

            # Organize file if album_id is provided
            final_path = converted_file
            if album_id and config.get('lidarr_url') and config.get('lidarr_api_key'):
                final_path = self._organize_track_file(
                    converted_file,
                    album_id,
                    title,
                    album,
                    track_number,
                    output_format,
                    disc_number=disc_number,
                    year=year
                )

            # Trigger Lidarr rescan
            rescan_triggered = False
            if album_id and config.get('lidarr_url') and config.get('lidarr_api_key'):
                rescan_triggered = self._trigger_lidarr_rescan(album_id)

            return {
                'success': True,
                'message': 'Track downloaded and converted successfully',
                'file_path': final_path,
                'rescan_triggered': rescan_triggered,
                'album_id': album_id
            }

        except Exception as e:
            logger.error(f"Error downloading track: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    def _organize_track_file(
        self, converted_file, album_id, title, album, track_number, output_format,
        disc_number=None, year=None
    ):
        """
        Organize track file into Lidarr directory structure
        
        Args:
            converted_file: Path to converted audio file
            album_id: Lidarr album ID
            title: Track title
            album: Album name
            track_number: Track number
            output_format: Audio format extension
            disc_number: Disc number (used for multi-disc naming)
            year: Release year (used as a naming token fallback)
            
        Returns:
            str: Final file path
        """
        try:
            config = self.config_manager.get_config()
            
            # Get album details from Lidarr
            lidarr_client = self.LidarrClient(
                url=config.get('lidarr_url'),
                api_key=config.get('lidarr_api_key')
            )
            
            album_data = lidarr_client.get_album(int(album_id))
            if not album_data:
                logger.warning(f"Album {album_id} not found in Lidarr, keeping file in downloads")
                return converted_file
            
            # Get artist path and album title
            artist_data = album_data.get('artist', {}) or {}
            artist_path = artist_data.get('path', '')
            album_title = album_data.get('title', album)
            release_year = year or str(album_data.get('releaseDate') or '')[:4] or album_data.get('year')

            if not artist_path:
                logger.warning("No artist path found, keeping file in downloads")
                return converted_file
            
            # Normalize artist path to use forward slashes
            artist_path = artist_path.replace('\\', '/')
            
            safe_album = self.download_manager._sanitize_filename(album_title)
            safe_title = self.download_manager._sanitize_filename(title)

            filename = None
            if self._is_enabled(config, 'use_lidarr_naming'):
                naming_config = naming.get_naming_config(lidarr_client)
                if naming_config:
                    fmt = naming.get_track_format(naming_config, disc_number or 1)
                    context = {
                        'artist': artist_data.get('artistName', '') or artist_data.get('name', ''),
                        'album': album_title,
                        'title': title,
                        'track': track_number,
                        'disc': disc_number or 1,
                        'year': release_year,
                        'release_year': release_year,
                    }
                    stem = naming.render_track_filename(
                        fmt, context, sanitize=self.download_manager._sanitize_filename
                    )
                    filename = f"{stem}.{output_format}"

            if not filename:
                track_num_str = str(track_number).zfill(2)
                filename = f"{track_num_str} - {safe_title}.{output_format}"
            
            # Construct path using forward slashes
            target_path = f"{artist_path}/{safe_album}/{filename}"
            
            logger.info(f"Target path (before mapping): {target_path}")
            
            # Move file to target location with path mapping
            if config.get('lidarr_path_mapping'):
                final_path = self.download_manager.move_to_target(
                    source_file=converted_file,
                    target_path=target_path,
                    path_mapping=config.get('lidarr_path_mapping')
                )
            else:
                # Direct move (no path mapping) - use Path for platform compatibility
                target = Path(target_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(converted_file, str(target))
                final_path = str(target)
                logger.info(f"Moved file to: {final_path}")
            
            return final_path
            
        except Exception as e:
            logger.warning(f"Failed to organize file to Lidarr path: {e}", exc_info=True)
            return converted_file
    
    def _trigger_lidarr_rescan(self, album_id):
        """
        Trigger Lidarr to rescan an album
        
        Args:
            album_id: Lidarr album ID
            
        Returns:
            bool: True if rescan triggered successfully
        """
        try:
            config = self.config_manager.get_config()
            
            lidarr_client = self.LidarrClient(
                url=config.get('lidarr_url'),
                api_key=config.get('lidarr_api_key')
            )
            
            rescan_triggered = lidarr_client.rescan_album(int(album_id))
            
            if rescan_triggered:
                logger.info(f"✅ Triggered Lidarr rescan for album {album_id}")
            else:
                logger.warning(f"⚠️ Failed to trigger Lidarr rescan for album {album_id}")
            
            return rescan_triggered
            
        except Exception as e:
            logger.warning(f"Failed to trigger Lidarr rescan: {e}")
            return False

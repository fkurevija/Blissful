"""
Album Management Module for Blissful
Handles album information, tracks, and bulk album downloads
"""

import logging
import random
import time

logger = logging.getLogger(__name__)


class AlbumManager:
    """Manages album-related operations"""
    
    def __init__(self, config_manager, lidarr_client_class, download_manager, audio_converter):
        self.config_manager = config_manager
        self.LidarrClient = lidarr_client_class
        self.download_manager = download_manager
        self.audio_converter = audio_converter

    @staticmethod
    def _is_enabled(config, key, default=True):
        """Feature flags default to on; only an explicit False disables them."""
        return config.get(key, default) is not False

    @staticmethod
    def _duration_seconds(value):
        """Convert a Lidarr track duration (milliseconds) into seconds."""
        if value is None or value == '':
            return None
        try:
            seconds = float(value) / 1000.0
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    @staticmethod
    def _first_value(data, *keys):
        for key in keys:
            value = data.get(key)
            if value not in (None, ''):
                return value
        return None

    def get_album_info(self, album_id):
        """
        Fetch album information from Lidarr API
        
        Args:
            album_id: The foreign album ID (GUID) from Lidarr URL
            
        Returns:
            dict: Album information including title, artist, path
        """
        try:
            # Get Lidarr configuration
            config = self.config_manager.get_config()
            lidarr_url = config.get('lidarr_url')
            lidarr_api_key = config.get('lidarr_api_key')
            
            if not lidarr_url or not lidarr_api_key:
                return {
                    'success': False,
                    'error': 'Lidarr not configured'
                }
            
            # Create Lidarr client
            lidarr_client = self.LidarrClient(url=lidarr_url, api_key=lidarr_api_key)
            
            # Fetch album data
            album_data = lidarr_client.get_album_by_foreign_id(album_id)
            
            if not album_data:
                return {
                    'success': False,
                    'error': f'Album not found: {album_id}'
                }
            
            # Extract relevant information
            result = {
                'success': True,
                'title': album_data.get('title', 'Unknown Album'),
                'artist': album_data.get('artist', {}).get('artistName', 'Unknown Artist'),
                'foreignAlbumId': album_data.get('foreignAlbumId'),
                'lidarrAlbumId': album_data.get('id'),
                'path': album_data.get('artist', {}).get('path', ''),
                'releaseDate': album_data.get('releaseDate'),
                'trackCount': album_data.get('statistics', {}).get('trackCount', 0)
            }
            
            logger.info(f"Fetched album info: {result['artist']} - {result['title']} (Path: {result['path']})")
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching album info for {album_id}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_album_tracks(self, album_id):
        """
        Fetch album tracks with their file status from Lidarr
        
        Args:
            album_id: The Lidarr album ID (numeric)
            
        Returns:
            dict: Track list with file status
        """
        try:
            # Get Lidarr configuration
            config = self.config_manager.get_config()
            lidarr_url = config.get('lidarr_url')
            lidarr_api_key = config.get('lidarr_api_key')
            
            if not lidarr_url or not lidarr_api_key:
                return {
                    'success': False,
                    'error': 'Lidarr not configured'
                }
            
            # Create Lidarr client
            lidarr_client = self.LidarrClient(url=lidarr_url, api_key=lidarr_api_key)
            
            # Fetch tracks
            tracks = lidarr_client.get_album_tracks(int(album_id))
            
            # BLISS-9: an empty list is a valid (successful) result, e.g. an
            # album whose tracks are all unmonitored. Only a non-list response
            # is a genuine failure; exceptions are handled below.
            if tracks is None or not isinstance(tracks, list):
                return {
                    'success': False,
                    'error': f'No tracks found for album {album_id}'
                }
            if not tracks:
                logger.info(f"Album {album_id} has no tracks")
                return {
                    'success': True,
                    'tracks': [],
                    'total': 0
                }
            
            # Format track data
            track_list = []
            for track in tracks:
                track_list.append({
                    'id': track.get('id'),
                    'trackNumber': track.get('trackNumber'),
                    'title': track.get('title'),
                    'duration': track.get('duration', 0),
                    'hasFile': track.get('hasFile', False),
                    'trackFileId': track.get('trackFileId'),
                })
            
            logger.info(f"Fetched {len(track_list)} tracks for album {album_id}")
            
            return {
                'success': True,
                'tracks': track_list,
                'total': len(track_list)
            }
            
        except Exception as e:
            logger.error(f"Error fetching tracks for album {album_id}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    def download_album(self, artist, album, tracks, target_path='',
                       should_cancel=None, retry_delay=None, on_progress=None,
                       resume_state=None):
        """Download every track, retrying only the failures in later rounds.

        A failed track never blocks the rest of the album: it is left pending
        and returned in ``pending_tracks`` for the next round. Job-managed
        calls run one round per worker pass so other jobs (including retries)
        are not blocked; ``should_cancel`` stops a round immediately.
        """
        try:
            logger.info(f"Downloading album: {artist} - {album} ({len(tracks)} tracks)")
            total = len(tracks)
            managed = callable(should_cancel)
            resume_state = resume_state if isinstance(resume_state, dict) else {}
            rounds_done = int(resume_state.get('rounds', 0))
            completed_before = int(resume_state.get('completed_tracks', 0))
            results = {
                'success': True,
                'cancelled': False,
                'album': album,
                'artist': artist,
                'total_tracks': total,
                'completed_tracks': completed_before,
                'successful': completed_before,
                'failed': 0,
                'rounds': rounds_done,
                'tracks': [],
            }
            config = self.config_manager.get_config()
            pending = list(tracks)
            completed = []
            failures = {}

            def cancelled():
                return bool(managed and should_cancel())

            def progress(round_no, phase='track'):
                details = {
                    'phase': phase,
                    'artist': artist,
                    'album': album,
                    'current_track': results['completed_tracks'],
                    'total_tracks': total,
                    'completed_tracks': results['completed_tracks'],
                    'failed_tracks': len(pending),
                    'round': round_no,
                }
                try:
                    self.download_manager._set_download_progress(
                        download_index=results['completed_tracks'],
                        total_tracks=total,
                        completed_tracks=results['completed_tracks'],
                        failed_tracks=len(pending),
                        round=round_no,
                    )
                except Exception:
                    pass
                if callable(on_progress):
                    try:
                        on_progress(**details)
                    except Exception:
                        logger.debug('Album progress callback failed')

            while pending:
                if cancelled():
                    results['cancelled'] = True
                    break
                results['rounds'] += 1
                round_no = results['rounds']
                next_pending = []
                for track in pending:
                    if cancelled():
                        break
                    progress(round_no)
                    track_result = {
                        'title': track.get('title'),
                        'success': False,
                        'error': None,
                    }
                    try:
                        expected_duration = self._duration_seconds(track.get('duration'))
                        download_kwargs = {
                            'artist': artist,
                            'title': track.get('title'),
                            'album': album,
                            'output_format': config.get('output_format', 'mp3'),
                            'source_priorities': config.get('source_priorities', []),
                            'expected_duration': expected_duration,
                        }
                        try:
                            download_result = self.download_manager.download_track(**download_kwargs)
                        except TypeError as exc:
                            if 'expected_duration' not in str(exc):
                                raise
                            download_kwargs.pop('expected_duration')
                            download_result = self.download_manager.download_track(**download_kwargs)

                        if download_result['success']:
                            converted_file = self.audio_converter.convert(
                                input_file=download_result['file_path'],
                                output_format=config.get('output_format', 'mp3'),
                                quality=config.get('quality', '320k'),
                            )
                            if self._is_enabled(config, 'embed_metadata'):
                                thumbnail = None
                                if self._is_enabled(config, 'embed_thumbnail'):
                                    thumbnail = download_result.get('thumbnail_path')
                                self.audio_converter.add_metadata(
                                    converted_file,
                                    artist=artist,
                                    album_artist=artist,
                                    title=track.get('title'),
                                    album=album,
                                    year=self._first_value(track, 'year', 'releaseYear', 'release_year'),
                                    track_number=track.get('trackNumber'),
                                    disc=self._first_value(track, 'mediumNumber', 'discNumber', 'disc_number'),
                                    genre=track.get('genre'),
                                    thumbnail_path=thumbnail,
                                )
                            exact_target = track.get('target_path') or target_path
                            if exact_target:
                                final_path = self.download_manager.move_to_target(
                                    source_file=converted_file,
                                    target_path=exact_target,
                                    path_mapping=config.get('lidarr_path_mapping') or None,
                                )
                                track_result['file_path'] = final_path
                            else:
                                track_result['file_path'] = converted_file
                            track_result['success'] = True
                            results['successful'] += 1
                            results['completed_tracks'] += 1
                            completed.append(track_result)
                        else:
                            track_result['error'] = download_result.get('error')
                            track_result['attempts'] = download_result.get('attempts') or []
                            failures[id(track)] = track_result
                    except Exception as e:
                        logger.error(f"Error downloading track {track.get('title')}: {e}")
                        track_result['error'] = str(e)
                        failures[id(track)] = track_result
                    if not track_result['success']:
                        next_pending.append(track)

                pending = next_pending
                results['failed'] = len(pending)
                progress(results['rounds'],
                         'retry-round' if pending else 'complete')
                if pending and not cancelled():
                    logger.info(
                        'Album %s - %s: %s/%s tracks complete, %s left; next retry round',
                        artist, album, results['completed_tracks'], total,
                        len(pending))
                break  # one round per worker pass; the manager reschedules failures

            results['tracks'] = completed + [
                failures[id(t)] for t in pending if id(t) in failures]
            results['failed'] = len(pending)
            results['success'] = not pending and not results['cancelled']
            results['pending_tracks'] = pending
            results['resume_state'] = {
                'rounds': results['rounds'],
                'completed_tracks': results['completed_tracks'],
            }
            return results
        except Exception as e:
            logger.error(f"Error downloading album: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'total_tracks': len(tracks),
                'completed_tracks': 0,
                'tracks': [],
            }

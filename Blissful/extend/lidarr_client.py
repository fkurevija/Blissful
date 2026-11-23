import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class LidarrClient:
    """Client for interacting with Lidarr API"""
    
    def __init__(self, url: str, api_key: str):
        """
        Initialize Lidarr client
        
        Args:
            url: Lidarr base URL (e.g., http://localhost:8686)
            api_key: Lidarr API key
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }
    
    def test_connection(self) -> Dict:
        """
        Test connection to Lidarr
        
        Returns:
            Dict with success status and message
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/system/status",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'message': f"Connected to Lidarr v{data.get('version', 'unknown')}",
                    'version': data.get('version')
                }
            elif response.status_code == 401:
                return {
                    'success': False,
                    'error': 'Invalid API key'
                }
            else:
                return {
                    'success': False,
                    'error': f'Connection failed with status code: {response.status_code}'
                }
        except requests.exceptions.ConnectionError:
            return {
                'success': False,
                'error': 'Could not connect to Lidarr. Please check the URL.'
            }
        except Exception as e:
            logger.error(f"Error testing Lidarr connection: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_artist(self, artist_id: int) -> Optional[Dict]:
        """
        Get artist by ID
        
        Args:
            artist_id: Lidarr artist ID
            
        Returns:
            Artist data or None
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/artist/{artist_id}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get artist {artist_id}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting artist: {e}")
            return None
    
    def get_album(self, album_id: int) -> Optional[Dict]:
        """
        Get album by ID
        
        Args:
            album_id: Lidarr album ID
            
        Returns:
            Album data or None
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/album/{album_id}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get album {album_id}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting album: {e}")
            return None
    
    def get_album_by_foreign_id(self, foreign_album_id: str) -> Optional[Dict]:
        """
        Get album by foreign album ID (MusicBrainz GUID)
        
        Args:
            foreign_album_id: Foreign album ID (GUID format)
            
        Returns:
            Album data or None
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/album",
                headers=self.headers,
                params={'foreignAlbumId': foreign_album_id},
                timeout=10
            )
            
            if response.status_code == 200:
                albums = response.json()
                if albums and len(albums) > 0:
                    return albums[0]  # Return first match
                else:
                    logger.warning(f"No album found with foreign ID: {foreign_album_id}")
                    return None
            else:
                logger.error(f"Failed to get album by foreign ID {foreign_album_id}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting album by foreign ID: {e}")
            return None
    
    def get_album_tracks(self, album_id: int) -> List[Dict]:
        """
        Get all tracks for an album
        
        Args:
            album_id: Lidarr album ID
            
        Returns:
            List of track data
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/track",
                headers=self.headers,
                params={'albumId': album_id},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get tracks for album {album_id}: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting album tracks: {e}")
            return []
    
    def get_naming_config(self) -> Optional[Dict]:
        """
        Get Lidarr's naming configuration.

        Returns:
            Naming configuration dict (e.g. standardTrackFormat /
            multiDiscTrackFormat), or None if unavailable. The API key is
            never included in log messages.
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/config/naming",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, dict) else None
            logger.error(f"Failed to get naming config: {response.status_code}")
            return None
        except Exception as e:
            # Do not log the request/headers: they contain the API key.
            logger.error(f"Error getting naming config: {e}")
            return None

    def get_missing_tracks(self, artist_id: Optional[int] = None) -> List[Dict]:
        """
        Get missing tracks, optionally filtered by artist
        
        Args:
            artist_id: Optional artist ID to filter by
            
        Returns:
            List of missing track data
        """
        try:
            params = {'monitored': 'true'}
            if artist_id:
                params['artistId'] = artist_id
            
            response = requests.get(
                f"{self.url}/api/v1/wanted/missing",
                headers=self.headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('records', [])
            else:
                logger.error(f"Failed to get missing tracks: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting missing tracks: {e}")
            return []
    
    def get_missing_albums(self, artist_id: Optional[int] = None) -> List[Dict]:
        """
        Get missing albums, optionally filtered by artist
        
        Args:
            artist_id: Optional artist ID to filter by
            
        Returns:
            List of missing album data
        """
        try:
            # Get all albums
            response = requests.get(
                f"{self.url}/api/v1/album",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get albums: {response.status_code}")
                return []
            
            albums = response.json()
            
            # Filter for missing albums
            missing_albums = []
            for album in albums:
                # Check if album is monitored and has missing tracks
                if album.get('monitored', False):
                    stats = album.get('statistics', {})
                    if stats.get('trackCount', 0) > stats.get('trackFileCount', 0):
                        # Album has missing tracks
                        if artist_id is None or album.get('artistId') == artist_id:
                            missing_albums.append(album)
            
            return missing_albums
        except Exception as e:
            logger.error(f"Error getting missing albums: {e}")
            return []
    
    def search_artist(self, artist_name: str) -> List[Dict]:
        """
        Search for artist by name
        
        Args:
            artist_name: Artist name to search for
            
        Returns:
            List of matching artists
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/artist",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                artists = response.json()
                # Filter by name (case-insensitive)
                search_lower = artist_name.lower()
                return [
                    artist for artist in artists
                    if search_lower in artist.get('artistName', '').lower()
                ]
            else:
                logger.error(f"Failed to search artists: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error searching artists: {e}")
            return []
    
    def refresh_artist(self, artist_id: int) -> bool:
        """
        Trigger a refresh for an artist
        
        Args:
            artist_id: Artist ID to refresh
            
        Returns:
            True if successful
        """
        try:
            response = requests.post(
                f"{self.url}/api/v1/command",
                headers=self.headers,
                json={
                    'name': 'RefreshArtist',
                    'artistId': artist_id
                },
                timeout=10
            )
            
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error refreshing artist: {e}")
            return False
    
    def rescan_artist(self, artist_id: int) -> bool:
        """
        Trigger a rescan for an artist
        
        Args:
            artist_id: Artist ID to rescan
            
        Returns:
            True if successful
        """
        try:
            response = requests.post(
                f"{self.url}/api/v1/command",
                headers=self.headers,
                json={
                    'name': 'RescanFolders',
                    'folders': []
                },
                timeout=10
            )
            
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error rescanning artist: {e}")
            return False
    
    def rescan_album(self, album_id: int) -> bool:
        """
        Trigger a rescan/refresh for a specific album
        
        Args:
            album_id: Album ID to rescan
            
        Returns:
            True if successful
        """
        try:
            # Get album to find artist ID
            album = self.get_album(album_id)
            if not album:
                logger.error(f"Album {album_id} not found")
                return False
            
            artist_id = album.get('artistId')
            if not artist_id:
                logger.error(f"No artist ID found for album {album_id}")
                return False
            
            # Trigger artist rescan which will pick up new files
            response = requests.post(
                f"{self.url}/api/v1/command",
                headers=self.headers,
                json={
                    'name': 'RefreshArtist',
                    'artistId': artist_id
                },
                timeout=10
            )
            
            logger.info(f"Triggered rescan for artist {artist_id} (album {album_id})")
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error rescanning album: {e}")
            return False
    
    def get_track_files_by_album(self, album_id: int) -> List[Dict]:
        """
        Get track files for a specific album
        
        Args:
            album_id: Album ID
            
        Returns:
            List of track file data
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/trackfile",
                headers=self.headers,
                params={'albumId': album_id},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get track files for album {album_id}: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting track files: {e}")
            return []
    
    def get_root_folders(self) -> List[Dict]:
        """
        Get root folders configured in Lidarr
        
        Returns:
            List of root folder paths
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/rootfolder",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                folders = response.json()
                result = []
                
                for folder in folders:
                    path = folder.get('path', '')
                    if path:
                        result.append({
                            'lidarr_path': path,
                            'suggested_local_path': path,  # Can be customized later
                            'free_space': folder.get('freeSpace', 0),
                            'total_space': folder.get('totalSpace', 0)
                        })
                
                logger.info(f"Found {len(result)} root folder(s) in Lidarr")
                return result
            else:
                logger.error(f"Failed to get root folders: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting root folders: {e}")
            return []
    
    def search_artist_lidarr(self, term: str) -> List[Dict]:
        """
        Search for artists using Lidarr's lookup API
        
        Args:
            term: Search term (artist name)
            
        Returns:
            List of artist search results from MusicBrainz via Lidarr
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/artist/lookup",
                headers=self.headers,
                params={'term': term},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to search artists: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error searching artists via Lidarr: {e}")
            return []
    
    def get_quality_profiles(self) -> List[Dict]:
        """
        Get available quality profiles
        
        Returns:
            List of quality profiles
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/qualityprofile",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get quality profiles: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting quality profiles: {e}")
            return []
    
    def get_metadata_profiles(self) -> List[Dict]:
        """
        Get available metadata profiles
        
        Returns:
            List of metadata profiles
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/metadataprofile",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get metadata profiles: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting metadata profiles: {e}")
            return []
    
    def get_artist_by_foreign_id(self, foreign_artist_id: str) -> Optional[Dict]:
        """
        Get artist by foreign artist ID (MusicBrainz ID)
        
        Args:
            foreign_artist_id: MusicBrainz artist ID
            
        Returns:
            Artist data if exists, None otherwise
        """
        try:
            # Search through all artists for matching foreign ID
            response = requests.get(
                f"{self.url}/api/v1/artist",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                artists = response.json()
                for artist in artists:
                    if artist.get('foreignArtistId') == foreign_artist_id:
                        return artist
                return None
            else:
                logger.error(f"Failed to check existing artist: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error checking existing artist: {e}")
            return None
    
    def add_artist(self, artist_data: Dict, monitored: bool = True, search_for_missing: bool = True) -> Dict:
        """
        Add an artist to Lidarr
        
        Args:
            artist_data: Artist metadata from search
            monitored: Whether to monitor the artist
            search_for_missing: Whether to search for missing albums
            
        Returns:
            Dict with success status and message
        """
        try:
            # Check if artist already exists
            foreign_artist_id = artist_data.get('foreignArtistId')
            if foreign_artist_id:
                existing = self.get_artist_by_foreign_id(foreign_artist_id)
                if existing:
                    return {
                        'success': False,
                        'error': 'Artist already exists in Lidarr',
                        'artist_id': existing.get('id')
                    }
            
            # Get quality and metadata profiles
            quality_profiles = self.get_quality_profiles()
            metadata_profiles = self.get_metadata_profiles()
            root_folders = self.get_root_folders()
            
            if not quality_profiles or not metadata_profiles or not root_folders:
                return {
                    'success': False,
                    'error': 'Failed to get Lidarr profiles or root folders'
                }
            
            # Build payload
            payload = {
                **artist_data,
                'qualityProfileId': quality_profiles[0]['id'],
                'metadataProfileId': metadata_profiles[0]['id'],
                'rootFolderPath': root_folders[0]['lidarr_path'],
                'monitored': monitored,
                'addOptions': {
                    'monitor': 'all',
                    'monitored': monitored,
                    'searchForMissingAlbums': search_for_missing
                }
            }
            
            # Add artist
            response = requests.post(
                f"{self.url}/api/v1/artist",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                artist_response = response.json()
                logger.info(f"Added artist: {artist_response.get('artistName')} (ID: {artist_response.get('id')})")
                
                return {
                    'success': True,
                    'message': 'Artist added successfully',
                    'artist_id': artist_response.get('id'),
                    'artist_name': artist_response.get('artistName')
                }
            else:
                logger.error(f"Failed to add artist: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f'Failed to add artist: {response.status_code}'
                }
                
        except Exception as e:
            logger.error(f"Error adding artist: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_queue(self, page: int = 1, page_size: int = 200) -> Dict:
        """Return one page of the Lidarr queue (default page is only 10)."""
        try:
            response = requests.get(
                f"{self.url}/api/v1/queue",
                headers=self.headers,
                params={'page': page, 'pageSize': page_size},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            logger.error(f"Failed to get Lidarr queue: {response.status_code}")
            return {'records': [], 'totalRecords': 0}
        except Exception as exc:
            logger.error(f"Error getting Lidarr queue: {exc}")
            return {'records': [], 'totalRecords': 0}

    def get_all_queue_records(self, page_size: int = 200) -> List[Dict]:
        """Read every queue page until all records are collected."""
        records: List[Dict] = []
        page = 1
        total = 1
        while len(records) < total:
            data = self.get_queue(page=page, page_size=page_size)
            page_records = data.get('records', []) if isinstance(data, dict) else []
            total = data.get('totalRecords', len(records)) if isinstance(data, dict) else len(records)
            if not page_records:
                break
            records.extend(page_records)
            page += 1
            if page > 100:
                logger.warning("Stopped paginating Lidarr queue after 100 pages")
                break
        return records

    def post_command(self, name: str, **body) -> Dict:
        """POST a Lidarr command (ManualImport, RescanFolders, etc.)."""
        try:
            payload = {'name': name, **body}
            response = requests.post(
                f"{self.url}/api/v1/command",
                headers=self.headers,
                json=payload,
                timeout=60
            )
            if response.status_code in (200, 201):
                return response.json()
            logger.error(f"Lidarr command {name} failed: {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as exc:
            logger.error(f"Error posting Lidarr command {name}: {exc}")
            return {'success': False, 'error': str(exc)}

    def get_command(self, command_id: int) -> Dict:
        """Poll a Lidarr command by id."""
        try:
            response = requests.get(
                f"{self.url}/api/v1/command/{command_id}",
                headers=self.headers,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            return {'status': 'failed', 'message': f'HTTP {response.status_code}'}
        except Exception as exc:
            logger.error(f"Error polling Lidarr command {command_id}: {exc}")
            return {'status': 'failed', 'message': str(exc)}

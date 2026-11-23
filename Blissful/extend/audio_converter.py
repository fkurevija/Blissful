import subprocess
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class AudioConverter:
    """Audio converter using ffmpeg"""
    
    def __init__(self):
        """Initialize audio converter"""
        self.supported_formats = ['mp3', 'flac', 'wav', 'ogg', 'opus', 'm4a', 'aac']
    
    def check_ffmpeg(self) -> bool:
        """
        Check if ffmpeg is available
        
        Returns:
            True if ffmpeg is available
        """
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    def convert(
        self,
        input_file: str,
        output_format: str = 'mp3',
        quality: str = '320k',
        output_file: Optional[str] = None
    ) -> str:
        """
        Convert audio file to specified format
        
        Args:
            input_file: Path to input audio file
            output_format: Target format (mp3, flac, etc.)
            quality: Audio quality (bitrate for lossy, compression level for lossless)
            output_file: Optional output file path
            
        Returns:
            Path to converted file
        """
        try:
            input_path = Path(input_file)
            
            # If input is already in the correct format, return it
            if input_path.suffix[1:].lower() == output_format.lower():
                logger.info(f"File already in {output_format} format: {input_file}")
                return input_file
            
            # Determine output file path
            if output_file:
                output_path = Path(output_file)
            else:
                output_path = input_path.with_suffix(f'.{output_format}')
            
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Build ffmpeg command
            cmd = ['ffmpeg', '-i', str(input_path), '-y']  # -y to overwrite
            
            # Add format-specific options
            if output_format.lower() == 'mp3':
                cmd.extend([
                    '-codec:a', 'libmp3lame',
                    '-b:a', quality,
                    '-q:a', '0'  # Highest quality VBR
                ])
            elif output_format.lower() == 'flac':
                cmd.extend([
                    '-codec:a', 'flac',
                    '-compression_level', '8'  # Max compression
                ])
            elif output_format.lower() == 'wav':
                cmd.extend([
                    '-codec:a', 'pcm_s16le'
                ])
            elif output_format.lower() == 'ogg':
                cmd.extend([
                    '-codec:a', 'libvorbis',
                    '-q:a', '8'  # High quality
                ])
            elif output_format.lower() == 'opus':
                cmd.extend([
                    '-codec:a', 'libopus',
                    '-b:a', quality
                ])
            elif output_format.lower() in ['m4a', 'aac']:
                cmd.extend([
                    '-codec:a', 'aac',
                    '-b:a', quality
                ])
            else:
                # Generic conversion
                cmd.extend(['-b:a', quality])
            
            # Add output file
            cmd.append(str(output_path))
            
            logger.info(f"Converting {input_file} to {output_format}")
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            # Run ffmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                raise Exception(f"FFmpeg conversion failed: {result.stderr}")
            
            # Remove input file if conversion was successful and it's different
            if output_path != input_path and input_path.exists():
                input_path.unlink()
                logger.debug(f"Removed original file: {input_path}")
            
            logger.info(f"Successfully converted to: {output_path}")
            return str(output_path)
            
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg conversion timed out")
            raise Exception("Audio conversion timed out")
        except Exception as e:
            logger.error(f"Error converting audio: {e}", exc_info=True)
            # Return original file if conversion failed
            return input_file
    
    def extract_metadata(self, file_path: str) -> dict:
        """
        Extract metadata from audio file using ffprobe
        
        Args:
            file_path: Path to audio file
            
        Returns:
            Dict with metadata
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(file_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
            else:
                logger.warning(f"Could not extract metadata from {file_path}")
                return {}
                
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            return {}
    
    def add_metadata(
        self,
        file_path: str,
        artist: Optional[str] = None,
        title: Optional[str] = None,
        album: Optional[str] = None,
        year: Optional[str] = None,
        track_number: Optional[str] = None,
        album_artist: Optional[str] = None,
        disc: Optional[str] = None,
        genre: Optional[str] = None,
        thumbnail_path: Optional[str] = None
    ) -> bool:
        """
        Add metadata to an audio file using a stream copy.

        ``-map 0`` keeps every input stream (including existing cover art).
        A local image passed as ``thumbnail_path`` is attached as an
        ``attached_pic`` stream.  If the muxer rejects the attachment the tag
        write is retried without it so metadata is still applied.

        Args:
            file_path: Path to audio file
            artist: Artist name
            title: Track title
            album: Album name
            year: Release year (written as the ``date`` tag)
            track_number: Track number (written as the ``track`` tag)
            album_artist: Album artist name
            disc: Disc number
            genre: Genre
            thumbnail_path: Optional local image to embed as cover art

        Returns:
            True if successful
        """
        try:
            input_path = Path(file_path)
            if not input_path.is_file():
                logger.warning(f"Cannot add metadata, file not found: {file_path}")
                return False
            temp_path = input_path.with_suffix('.temp' + input_path.suffix)

            tags = (
                ('artist', artist),
                ('album_artist', album_artist),
                ('title', title),
                ('album', album),
                ('disc', disc),
                ('track', track_number),
                ('date', year),
                ('genre', genre),
            )
            metadata_args = []
            for name, value in tags:
                if value is not None and str(value) != '':
                    metadata_args.extend(['-metadata', f'{name}={value}'])

            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-y',
                '-map', '0',      # preserve all streams, including existing artwork
                '-codec', 'copy'
            ] + metadata_args

            # Optional embedded cover art, guarded so a bad image never
            # prevents the rest of the tags from being written.
            thumb = None
            if thumbnail_path:
                candidate = Path(str(thumbnail_path))
                if candidate.is_file():
                    thumb = candidate
                else:
                    logger.debug(f"Thumbnail not found locally, skipping: {thumbnail_path}")

            def run(command):
                return subprocess.run(command, capture_output=True, text=True, timeout=60)

            cover_name = 'cover' + (thumb.suffix.lower() or '.jpg') if thumb is not None else ''
            attempts = []
            if thumb is not None:
                # Preferred: ffmpeg attachment with the attached_pic disposition.
                attach_cmd = list(cmd)
                attach_cmd.extend([
                    '-attach', str(thumb),
                    '-metadata:s:t:0', f'filename={cover_name}',
                    '-disposition:t:0', 'attached_pic',
                ])
                attempts.append(attach_cmd)

                # Some muxers (notably MP3) reject data attachments but accept
                # the same image as an attached picture video stream.
                pic_cmd = [
                    'ffmpeg', '-i', str(input_path), '-i', str(thumb), '-y',
                    '-map', '0', '-map', '1', '-codec', 'copy'
                ] + metadata_args + [
                    '-disposition:v:0', 'attached_pic',
                    '-metadata:s:v:0', f'filename={cover_name}',
                ]
                attempts.append(pic_cmd)
            attempts.append(cmd)

            result = None
            for attempt in attempts:
                try:
                    candidate = run(attempt + [str(temp_path)])
                except Exception as exc:
                    logger.warning(f"FFmpeg tag write attempt failed: {exc}")
                    continue
                if candidate.returncode == 0:
                    result = candidate
                    break
                logger.warning(
                    "FFmpeg tag write attempt failed, trying fallback: %s",
                    str(getattr(candidate, 'stderr', '') or '').strip()[-200:]
                )
                if temp_path.exists():
                    temp_path.unlink()

            if result is None:
                logger.error("All metadata write attempts failed")
                return False

            if result.returncode == 0 and temp_path.exists():
                temp_path.replace(input_path)
                logger.info(f"Added metadata to {file_path}")
                return True

            logger.error(f"Failed to add metadata: {str(getattr(result, 'stderr', '') or '').strip()}")
            if temp_path.exists():
                temp_path.unlink()
            return False

        except Exception as e:
            logger.error(f"Error adding metadata: {e}", exc_info=True)
            return False

    def get_duration(self, file_path: str) -> float:
        """
        Get the duration of a media file in seconds.

        Uses the ffprobe ``format.duration`` value and falls back to the
        longest stream duration when the format duration is unavailable.

        Args:
            file_path: Path to the media file

        Returns:
            Duration in seconds, or 0.0 if it cannot be determined
        """
        try:
            data = self.extract_metadata(file_path) or {}
            duration = data.get('format', {}).get('duration')
            if duration is not None:
                return float(duration)

            durations = []
            for stream in data.get('streams', []) or []:
                stream_duration = stream.get('duration')
                if stream_duration is None:
                    continue
                try:
                    durations.append(float(stream_duration))
                except (TypeError, ValueError):
                    continue
            return max(durations) if durations else 0.0
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not parse duration for {file_path}: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Error getting duration for {file_path}: {e}")
            return 0.0
    
    def normalize_audio(self, file_path: str, target_level: str = '-14.0') -> bool:
        """
        Normalize audio levels
        
        Args:
            file_path: Path to audio file
            target_level: Target loudness level in LUFS
            
        Returns:
            True if successful
        """
        try:
            input_path = Path(file_path)
            temp_path = input_path.with_suffix('.temp' + input_path.suffix)
            
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-af', f'loudnorm=I={target_level}:TP=-1.5:LRA=11',
                '-y',
                str(temp_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                temp_path.replace(input_path)
                logger.info(f"Normalized audio: {file_path}")
                return True
            else:
                logger.error(f"Failed to normalize audio: {result.stderr}")
                if temp_path.exists():
                    temp_path.unlink()
                return False
                
        except Exception as e:
            logger.error(f"Error normalizing audio: {e}")
            return False
    
    def get_supported_formats(self) -> list:
        """
        Get list of supported output formats
        
        Returns:
            List of format names
        """
        return self.supported_formats

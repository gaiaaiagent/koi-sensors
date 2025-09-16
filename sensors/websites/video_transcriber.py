#!/usr/bin/env python3
"""
Video Transcription Module for Website Sensor
Handles downloading and transcribing videos found on websites
"""

import os
import asyncio
import logging
import tempfile
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime
import subprocess
import json

logger = logging.getLogger(__name__)


class VideoTranscriber:
    """Handles video downloading and transcription"""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="koi_videos_")
        self.transcribed_videos: Dict[str, str] = {}  # URL hash -> transcript

    async def process_video(self, video_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a video: download and transcribe"""
        try:
            video_url = video_info['url']
            video_type = video_info['type']

            # Create unique filename based on URL hash
            url_hash = hashlib.sha256(video_url.encode()).hexdigest()[:16]

            # Check if already transcribed
            if url_hash in self.transcribed_videos:
                logger.info(f"Video already transcribed: {video_url}")
                return {
                    'transcript': self.transcribed_videos[url_hash],
                    'cached': True,
                    **video_info
                }

            # Download video
            video_path = await self.download_video(video_url, video_type, url_hash)
            if not video_path:
                logger.warning(f"Failed to download video: {video_url}")
                return None

            # Extract audio
            audio_path = await self.extract_audio(video_path, url_hash)
            if not audio_path:
                logger.warning(f"Failed to extract audio from: {video_path}")
                return None

            # Transcribe audio
            transcript = await self.transcribe_audio(audio_path)
            if transcript:
                self.transcribed_videos[url_hash] = transcript

                # Clean up files
                try:
                    os.remove(video_path)
                    os.remove(audio_path)
                except Exception as e:
                    logger.debug(f"Cleanup error: {e}")

                return {
                    'transcript': transcript,
                    'transcribed_at': datetime.now().isoformat(),
                    'cached': False,
                    **video_info
                }

        except Exception as e:
            logger.error(f"Error processing video {video_info.get('url')}: {e}")
            return None

    async def download_video(self, url: str, video_type: str, url_hash: str) -> Optional[str]:
        """Download video from URL"""
        try:
            output_path = os.path.join(self.temp_dir, f"{url_hash}.mp4")

            if video_type in ['youtube', 'vimeo']:
                # Use yt-dlp for YouTube/Vimeo
                cmd = [
                    'yt-dlp',
                    '-f', 'best[ext=mp4]/best',
                    '-o', output_path,
                    '--no-playlist',
                    '--quiet',
                    url
                ]
            else:
                # Use wget for direct downloads
                cmd = ['wget', '-q', '-O', output_path, url]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await result.communicate()

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Downloaded video to {output_path}")
                return output_path
            else:
                return None

        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

    async def extract_audio(self, video_path: str, url_hash: str) -> Optional[str]:
        """Extract audio from video using ffmpeg"""
        try:
            audio_path = os.path.join(self.temp_dir, f"{url_hash}.wav")

            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-ar', '16000',  # 16kHz for whisper
                '-ac', '1',      # mono
                '-y',            # overwrite
                audio_path
            ]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await result.communicate()

            if os.path.exists(audio_path):
                logger.info(f"Extracted audio to {audio_path}")
                return audio_path
            else:
                return None

        except Exception as e:
            logger.error(f"Audio extraction error: {e}")
            return None

    async def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """Transcribe audio using whisper"""
        try:
            # Try to use whisper if available
            try:
                import whisper

                # Load model (base is a good balance of speed/quality)
                model = whisper.load_model("base")

                # Transcribe
                result = model.transcribe(audio_path)

                return result['text']

            except ImportError:
                logger.warning("Whisper not installed, using placeholder transcription")
                # For now, return a placeholder
                return f"[Video transcription pending - whisper not installed. Audio file: {audio_path}]"

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    def cleanup(self):
        """Clean up temporary files"""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
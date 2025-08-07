#!/usr/bin/env python3
"""
Audio transcription processor using OpenAI Whisper.
Handles podcast episodes and other audio content.
"""

import os
import asyncio
from pathlib import Path
from typing import Dict, Optional, List
import tempfile
import aiohttp
from loguru import logger

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("Whisper not installed. Audio transcription disabled.")

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("pydub not installed. Audio format conversion disabled.")


class AudioTranscriber:
    """Transcribe audio files to text using Whisper."""
    
    def __init__(self, model_name: str = "base", device: str = "cpu"):
        """
        Initialize the transcriber.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (cpu or cuda)
        """
        self.model_name = model_name
        self.device = device
        self.model = None
        
        if WHISPER_AVAILABLE:
            logger.info(f"Loading Whisper model: {model_name}")
            self.model = whisper.load_model(model_name, device=device)
            logger.info("Whisper model loaded successfully")
        else:
            logger.error("Whisper not available. Install with: pip install openai-whisper")
            
    async def download_audio(self, url: str, output_path: Path) -> bool:
        """Download audio file from URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        output_path.write_bytes(content)
                        return True
                    else:
                        logger.error(f"Failed to download audio: HTTP {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error downloading audio from {url}: {e}")
            return False
            
    def convert_to_wav(self, input_path: Path, output_path: Path) -> bool:
        """Convert audio file to WAV format for Whisper."""
        if not PYDUB_AVAILABLE:
            logger.error("pydub not available for audio conversion")
            return False
            
        try:
            audio = AudioSegment.from_file(str(input_path))
            audio.export(str(output_path), format="wav")
            return True
        except Exception as e:
            logger.error(f"Error converting audio: {e}")
            return False
            
    def transcribe_file(self, audio_path: Path, language: str = "en") -> Optional[Dict]:
        """
        Transcribe an audio file.
        
        Returns:
            Dict with 'text' and 'segments' or None if failed
        """
        if not self.model:
            logger.error("Whisper model not loaded")
            return None
            
        try:
            logger.info(f"Transcribing: {audio_path}")
            
            # Transcribe with Whisper
            result = self.model.transcribe(
                str(audio_path),
                language=language,
                verbose=False,
                fp16=False  # Disable for CPU
            )
            
            logger.info(f"Transcription complete. Length: {len(result['text'])} chars")
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None
            
    async def transcribe_url(self, audio_url: str, language: str = "en") -> Optional[Dict]:
        """
        Download and transcribe audio from URL.
        
        Returns:
            Dict with transcription results or None if failed
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Download audio
            audio_file = temp_path / "audio.mp3"
            success = await self.download_audio(audio_url, audio_file)
            
            if not success:
                return None
                
            # Convert to WAV if needed
            wav_file = temp_path / "audio.wav"
            if not self.convert_to_wav(audio_file, wav_file):
                # Try transcribing original format
                wav_file = audio_file
                
            # Transcribe
            return self.transcribe_file(wav_file, language)
            
    def format_transcript(self, result: Dict, include_timestamps: bool = True) -> str:
        """
        Format transcription results as readable text.
        
        Args:
            result: Whisper transcription result
            include_timestamps: Whether to include segment timestamps
            
        Returns:
            Formatted transcript text
        """
        if not result:
            return ""
            
        lines = []
        
        # Add full text first
        lines.append("## Full Transcript\n")
        lines.append(result.get('text', '').strip())
        lines.append("")
        
        # Add timestamped segments if requested
        if include_timestamps and 'segments' in result:
            lines.append("## Timestamped Segments\n")
            
            for segment in result['segments']:
                start = self._format_timestamp(segment['start'])
                end = self._format_timestamp(segment['end'])
                text = segment['text'].strip()
                
                lines.append(f"[{start} - {end}] {text}")
                
        return "\n".join(lines)
        
    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as MM:SS timestamp."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
        
    async def process_soundcloud_document(self, document: Dict) -> Dict:
        """
        Process a SoundCloud document by adding transcription.
        
        Args:
            document: Document dict with metadata containing audio_url
            
        Returns:
            Updated document with transcription
        """
        metadata = document.get('metadata', {})
        audio_url = metadata.get('audio_url')
        
        if not audio_url:
            logger.warning(f"No audio URL for document: {document.get('id')}")
            return document
            
        # Transcribe audio
        result = await self.transcribe_url(audio_url)
        
        if result:
            # Format transcript
            transcript = self.format_transcript(result)
            
            # Update document content
            content = document.get('content', '')
            content = content.replace(
                "*Note: Audio transcription not yet implemented. This document contains metadata only.*",
                transcript
            )
            document['content'] = content
            
            # Update metadata
            metadata['has_transcription'] = True
            metadata['transcript_model'] = self.model_name
            metadata['transcript_length'] = len(result['text'])
            document['metadata'] = metadata
            
            logger.info(f"Added transcription to document: {document.get('id')}")
        else:
            logger.warning(f"Failed to transcribe: {document.get('id')}")
            
        return document


class MockTranscriber:
    """Mock transcriber for testing without Whisper."""
    
    def __init__(self, *args, **kwargs):
        logger.info("Using mock transcriber (Whisper not installed)")
        
    async def process_soundcloud_document(self, document: Dict) -> Dict:
        """Return document unchanged."""
        logger.info(f"Mock transcription for: {document.get('id')}")
        return document
        
    def transcribe_file(self, *args, **kwargs) -> Optional[Dict]:
        """Return mock transcription."""
        return {
            'text': 'This is a mock transcription. Install Whisper for real transcription.',
            'segments': []
        }


def get_transcriber(model_name: str = "base", device: str = "cpu") -> AudioTranscriber:
    """
    Get appropriate transcriber based on availability.
    
    Returns:
        AudioTranscriber or MockTranscriber
    """
    if WHISPER_AVAILABLE:
        return AudioTranscriber(model_name, device)
    else:
        return MockTranscriber(model_name, device)
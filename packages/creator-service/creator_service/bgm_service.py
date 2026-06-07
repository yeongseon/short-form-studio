"""BGM generation and audio mixing service.

Generates ambient background music using FFmpeg's built-in audio generators
and mixes it with narration audio for YouTube Shorts.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# FFmpeg lavfi filter presets for different moods
_MOOD_FILTERS: dict[str, str] = {
    "warm": "anoisesrc=d={duration}:c=pink:r=44100,lowpass=f=300,volume=0.4",
    "tense": "anoisesrc=d={duration}:c=brown:r=44100,lowpass=f=200,highpass=f=60,volume=0.5",
    "calm": "sine=frequency=174:duration={duration},lowpass=f=200,volume=0.3",
    "emotional": "anoisesrc=d={duration}:c=pink:r=44100,lowpass=f=250,highpass=f=80,volume=0.6",
    "dramatic": "anoisesrc=d={duration}:c=pink:r=44100,lowpass=f=400,highpass=f=100,volume=0.7,aecho=0.8:0.88:60:0.4",
    "suspense": "anoisesrc=d={duration}:c=brown:r=44100,lowpass=f=150,highpass=f=40,volume=0.5,aecho=0.8:0.9:1000:0.3",
}


class BgmService:
    """Service for generating and mixing background music."""

    def generate_ambient_bgm(
        self,
        duration_seconds: float,
        output_path: str,
        mood: str = "emotional",
    ) -> str:
        """Generate ambient BGM using FFmpeg lavfi filters.

        Args:
            duration_seconds: Length of BGM in seconds.
            output_path: Where to save the generated audio file.
            mood: One of 'warm', 'tense', 'calm', 'emotional'.

        Returns:
            The output path.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Validate duration to prevent resource exhaustion
        duration_seconds = max(1.0, min(float(duration_seconds), 600.0))

        filter_template = _MOOD_FILTERS.get(mood, _MOOD_FILTERS["emotional"])
        audio_filter = filter_template.format(duration=int(duration_seconds) + 1)

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            audio_filter,
            "-t",
            str(duration_seconds),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(out),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, start_new_session=True
        )
        if result.returncode != 0:
            logger.error("BGM generation failed: %s", result.stderr[-500:])
            raise RuntimeError(f"BGM generation failed: {result.stderr}")

        return str(out)

    def mix_audio_with_bgm(
        self,
        narration_path: str,
        bgm_path: str,
        output_path: str,
        bgm_volume: float = 0.25,
    ) -> str:
        """Mix narration audio with BGM using sidechain-style ducking.

        BGM volume ducks when narration is present (dynamic mixing).
        This creates a more professional sound where BGM fills pauses
        but stays quiet during speech.

        Args:
            narration_path: Path to narration audio file.
            bgm_path: Path to BGM audio file.
            output_path: Where to save mixed audio.
            bgm_volume: Base volume of BGM (0.0-1.0). BGM will duck below this during speech.

        Returns:
            The output path.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Validate bgm_volume to prevent filter injection
        bgm_volume = max(0.0, min(1.0, float(bgm_volume)))

        # Sidechain ducking: use sidechaincompress to duck BGM when narration is present
        # This gives a professional "radio" feel where BGM fills pauses naturally
        filter_complex = (
            f"[1:a]volume={bgm_volume}[bgm];"
            f"[bgm][0:a]sidechaincompress=threshold=0.02:ratio=6:attack=200:release=1000[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            narration_path,
            "-i",
            bgm_path,
            "-filter_complex",
            filter_complex,
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, start_new_session=True
        )
        if result.returncode != 0:
            # Fallback: try simpler mix without sidechain (older FFmpeg may lack it)
            logger.warning("Sidechain ducking failed, falling back to simple mix: %s", result.stderr[-200:])
            filter_complex_simple = (
                f"[1:a]volume={bgm_volume}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2"
            )
            cmd_simple = [
                "ffmpeg",
                "-y",
                "-i",
                narration_path,
                "-i",
                bgm_path,
                "-filter_complex",
                filter_complex_simple,
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(out),
            ]
            result = subprocess.run(
                cmd_simple, capture_output=True, text=True, timeout=120, start_new_session=True
            )
            if result.returncode != 0:
                logger.error("Audio mixing failed: %s", result.stderr[-500:])
                raise RuntimeError(f"Audio mixing failed: {result.stderr}")

        return str(out)


# Module-level singleton
bgm_service = BgmService()

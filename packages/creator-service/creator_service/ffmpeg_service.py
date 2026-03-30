import subprocess
from pathlib import Path
from dataclasses import dataclass

from .render_profile import RenderProfile


@dataclass
class RenderInput:
    image_paths: list[Path]       # ordered scene images
    audio_path: Path | None       # narration audio
    subtitle_path: Path | None    # SRT subtitle file
    scene_durations: list[float]  # duration per scene in seconds


class FFmpegService:
    def __init__(self, profile: RenderProfile | None = None):
        self.profile = profile or RenderProfile.default()

    def build_command(self, input_data: RenderInput, output_path: Path) -> list[str]:
        """Build FFmpeg command for rendering video from scenes."""
        # This builds the actual FFmpeg command
        # Ken Burns effect: use zoompan filter
        # Subtitle burn-in: use subtitles filter
        cmd = ["ffmpeg", "-y"]  # overwrite output
        
        # Build filter complex for image sequence with ken burns
        filter_parts = []
        for i, (img, dur) in enumerate(zip(input_data.image_paths, input_data.scene_durations)):
            cmd.extend(["-loop", "1", "-t", str(dur), "-i", str(img)])
            # Scale + Ken Burns zoom
            filter_parts.append(
                f"[{i}:v]scale={self.profile.width}:{self.profile.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.profile.width}:{self.profile.height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1[v{i}]"
            )
        
        # Concat all scenes
        concat_inputs = "".join(f"[v{i}]" for i in range(len(input_data.image_paths)))
        filter_parts.append(f"{concat_inputs}concat=n={len(input_data.image_paths)}:v=1:a=0[vout]")
        
        cmd.extend(["-filter_complex", ";".join(filter_parts)])
        
        # Add audio if present
        if input_data.audio_path:
            cmd.extend(["-i", str(input_data.audio_path)])
            cmd.extend(["-map", "[vout]", "-map", f"{len(input_data.image_paths)}:a"])
        else:
            cmd.extend(["-map", "[vout]"])
        
        # Codec settings
        cmd.extend([
            "-c:v", self.profile.video_codec.value,
            "-crf", str(self.profile.crf),
            "-preset", self.profile.preset,
            "-r", str(self.profile.fps),
        ])
        
        if input_data.audio_path:
            cmd.extend(["-c:a", self.profile.audio_codec.value])
        
        # Subtitle burn-in
        if self.profile.burn_subtitles and input_data.subtitle_path:
            cmd.extend(["-vf", f"subtitles={input_data.subtitle_path}:force_style='FontSize={self.profile.subtitle_font_size}'"])
        
        cmd.append(str(output_path))
        return cmd

    def render(self, input_data: RenderInput, output_path: Path) -> Path:
        """Execute FFmpeg render. Returns output path on success."""
        cmd = self.build_command(input_data, output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed: {result.stderr}")
        return output_path

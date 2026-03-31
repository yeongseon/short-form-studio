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


def _escape_subtitle_path(path: Path) -> str:
    """Escape special characters in subtitle path for FFmpeg filter syntax.

    FFmpeg filter strings treat ``\\``, ``:``, ``'``, ``;``, ``,``, ``[``,
    and ``]`` as syntax characters.  They must be escaped with a backslash so
    the path is interpreted literally.
    """
    s = str(path)
    # Order matters: escape backslashes first, then the rest.
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    s = s.replace(";", "\\;")
    s = s.replace(",", "\\,")
    s = s.replace("[", "\\[")
    s = s.replace("]", "\\]")
    return s


class FFmpegService:
    def __init__(self, profile: RenderProfile | None = None):
        self.profile = profile or RenderProfile.default()

    def build_command(self, input_data: RenderInput, output_path: Path) -> list[str]:
        """Build FFmpeg command for rendering video from scenes.

        All video filtering — scale/pad, concat, and optional subtitle
        burn-in — is merged into a single ``-filter_complex`` graph so that
        FFmpeg never receives conflicting ``-filter_complex`` and ``-vf``
        flags.
        """
        cmd = ["ffmpeg", "-y"]  # overwrite output

        # --- inputs --------------------------------------------------------
        filter_parts: list[str] = []
        for i, (img, dur) in enumerate(
            zip(input_data.image_paths, input_data.scene_durations),
        ):
            cmd.extend(["-loop", "1", "-t", str(dur), "-i", str(img)])
            # Scale + pad each input to target resolution
            filter_parts.append(
                f"[{i}:v]scale={self.profile.width}:{self.profile.height}"
                f":force_original_aspect_ratio=decrease,"
                f"pad={self.profile.width}:{self.profile.height}"
                f":(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1[v{i}]"
            )

        # --- concat --------------------------------------------------------
        concat_inputs = "".join(
            f"[v{i}]" for i in range(len(input_data.image_paths))
        )

        # Determine whether we need a subtitle stage after concat.
        need_subs = (
            self.profile.burn_subtitles
            and input_data.subtitle_path is not None
        )

        if need_subs:
            # Concat → [vcat], then subtitle burn-in → [vout]
            filter_parts.append(
                f"{concat_inputs}concat="
                f"n={len(input_data.image_paths)}:v=1:a=0[vcat]"
            )
            escaped = _escape_subtitle_path(input_data.subtitle_path)  # type: ignore[arg-type]
            filter_parts.append(
                f"[vcat]subtitles={escaped}"
                f":force_style='FontSize={self.profile.subtitle_font_size}'[vout]"
            )
        else:
            filter_parts.append(
                f"{concat_inputs}concat="
                f"n={len(input_data.image_paths)}:v=1:a=0[vout]"
            )

        cmd.extend(["-filter_complex", ";".join(filter_parts)])

        # --- stream mapping ------------------------------------------------
        if input_data.audio_path:
            cmd.extend(["-i", str(input_data.audio_path)])
            cmd.extend(
                ["-map", "[vout]", "-map", f"{len(input_data.image_paths)}:a"]
            )
        else:
            cmd.extend(["-map", "[vout]"])

        # --- codec settings ------------------------------------------------
        cmd.extend([
            "-c:v", self.profile.video_codec.value,
            "-crf", str(self.profile.crf),
            "-preset", self.profile.preset,
            "-r", str(self.profile.fps),
        ])

        if input_data.audio_path:
            cmd.extend(["-c:a", self.profile.audio_codec.value])

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

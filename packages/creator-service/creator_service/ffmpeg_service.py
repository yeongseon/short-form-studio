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

    # -- Per-paragraph helper methods -----------------------------------------

    def get_audio_duration(self, audio_path: str) -> float:
        """Probe audio file duration in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {audio_path}: {result.stderr}")
        return float(result.stdout.strip())

    def concatenate_audio(self, audio_paths: list[str], output_path: str) -> Path:
        """Concatenate multiple audio files using FFmpeg concat demuxer.

        Creates a temporary concat list file, runs FFmpeg, and returns the
        output path.  The caller is responsible for ensuring input files exist.
        """
        import tempfile

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Build concat list file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            for p in audio_paths:
                # FFmpeg concat requires single-quoted paths with inner quotes escaped
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
            concat_list = f.name

        try:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                str(out),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")
        finally:
            Path(concat_list).unlink(missing_ok=True)

        return out

    def merge_subtitles(
        self,
        subtitle_paths: list[str],
        durations: list[float],
        output_path: str,
    ) -> Path:
        """Merge multiple SRT files into one, adjusting timestamps.

        Each subtitle file's timestamps are offset by the cumulative duration
        of all preceding paragraphs.  This produces a single SRT file suitable
        for rendering onto the concatenated audio track.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        merged_entries: list[str] = []
        entry_index = 1
        cumulative_offset = 0.0

        for srt_path, dur in zip(subtitle_paths, durations):
            path = Path(srt_path)
            if not path.exists():
                cumulative_offset += dur
                continue

            content = path.read_text(encoding="utf-8")
            blocks = content.strip().split("\n\n")

            for block in blocks:
                lines = block.strip().split("\n")
                if len(lines) < 3:
                    continue  # skip malformed blocks

                # Parse timestamp line: "00:00:01,000 --> 00:00:03,500"
                ts_line = lines[1]
                parts = ts_line.split(" --> ")
                if len(parts) != 2:
                    continue

                start = _parse_srt_ts(parts[0].strip()) + cumulative_offset
                end = _parse_srt_ts(parts[1].strip()) + cumulative_offset
                text = "\n".join(lines[2:])

                merged_entries.append(
                    f"{entry_index}\n{_format_srt_ts(start)} --> {_format_srt_ts(end)}\n{text}"
                )
                entry_index += 1

            cumulative_offset += dur

        out.write_text("\n\n".join(merged_entries) + "\n", encoding="utf-8")
        return out


def _parse_srt_ts(ts: str) -> float:
    """Parse SRT timestamp 'HH:MM:SS,mmm' to seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def _format_srt_ts(seconds: float) -> str:
    """Format seconds as SRT timestamp 'HH:MM:SS,mmm'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .render_profile import RenderProfile

logger = logging.getLogger(__name__)
@dataclass
class RenderInput:
    image_paths: list[Path]  # ordered scene images
    audio_path: Path | None  # narration audio
    subtitle_path: Path | None  # SRT subtitle file
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
        cmd = ["ffmpeg", "-y", "-threads", "1", "-filter_threads", "1"]

        if len(input_data.image_paths) != len(input_data.scene_durations):
            raise ValueError(
                f"image_paths ({len(input_data.image_paths)}) and "
                f"scene_durations ({len(input_data.scene_durations)}) must have equal length"
            )
        if not input_data.image_paths:
            raise ValueError("image_paths must not be empty")

        # --- inputs --------------------------------------------------------
        filter_parts: list[str] = []
        for i, (img, dur) in enumerate(
            zip(input_data.image_paths, input_data.scene_durations, strict=False),
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
        concat_inputs = "".join(f"[v{i}]" for i in range(len(input_data.image_paths)))

        # Determine whether we need a subtitle stage after concat.
        need_subs = self.profile.burn_subtitles and input_data.subtitle_path is not None

        if need_subs:
            # Concat → [vcat], then subtitle burn-in → [vout]
            filter_parts.append(
                f"{concat_inputs}concat=n={len(input_data.image_paths)}:v=1:a=0[vcat]"
            )
            assert input_data.subtitle_path is not None  # guaranteed by need_subs check
            escaped = _escape_subtitle_path(input_data.subtitle_path)
            if str(input_data.subtitle_path).endswith(".ass"):
                # ASS format with embedded styling
                filter_parts.append(f"[vcat]ass={escaped}[vout]")
            else:
                # SRT with inline force_style
                filter_parts.append(
                    f"[vcat]subtitles={escaped}"
                    f":force_style='FontSize={self.profile.subtitle_font_size}'[vout]"
                )
        else:
            filter_parts.append(
                f"{concat_inputs}concat=n={len(input_data.image_paths)}:v=1:a=0[vout]"
            )

        cmd.extend(["-filter_complex", ";".join(filter_parts)])

        # --- stream mapping ------------------------------------------------
        if input_data.audio_path:
            cmd.extend(["-i", str(input_data.audio_path)])
            cmd.extend(["-map", "[vout]", "-map", f"{len(input_data.image_paths)}:a"])
        else:
            cmd.extend(["-map", "[vout]"])

        # --- codec settings ------------------------------------------------
        cmd.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                self.profile.video_codec.value,
                "-crf",
                str(self.profile.crf),
                "-preset",
                self.profile.preset,
                "-r",
                str(self.profile.fps),
            ]
        )

        if input_data.audio_path:
            cmd.extend(["-c:a", self.profile.audio_codec.value, "-shortest"])

        cmd.append(str(output_path))
        return cmd

    # Minimum output file size to consider valid (10KB — any real video exceeds this)
    _MIN_VALID_SIZE = 10 * 1024

    def _probe_output_valid(self, output_path: Path) -> bool:
        """Validate output file with ffprobe. Returns True if it's a playable video."""
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output_path),
            ]
            probe = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=15
            )
            if probe.returncode != 0:
                logger.warning("ffprobe failed on %s: %s", output_path, probe.stderr[:200])
                return False
            duration = float(probe.stdout.strip())
            if duration <= 0:
                logger.warning("ffprobe reports zero/negative duration for %s", output_path)
                return False
            logger.info("ffprobe validated %s: duration=%.2fs", output_path, duration)
            return True
        except (ValueError, subprocess.TimeoutExpired) as exc:
            logger.warning("ffprobe validation error for %s: %s", output_path, exc)
            return False

    def render(self, input_data: RenderInput, output_path: Path) -> Path:
        """Execute FFmpeg render. Returns output path on success.

        Renders to a unique temporary file, then atomically renames on
        success. If FFmpeg exits with a non-zero code but the temp file is a
        valid video (verified by ffprobe with duration > 0 and size >= 10KB),
        we accept the result. This handles the known case where FFmpeg
        encounters ENOMEM during filter graph teardown in memory-constrained
        containers but has already flushed a valid file.
        """
        import gc
        import os
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Use a unique temp filename (PID + random) to prevent collision on
        # concurrent renders or Celery retries targeting the same output_path.
        unique_suffix = f".tmp.{os.getpid()}.{os.urandom(4).hex()}.mp4"
        tmp_path = output_path.with_suffix(unique_suffix)
        cmd = self.build_command(input_data, tmp_path)
        logger.debug("FFmpeg command: %s", ' '.join(str(c) for c in cmd))
        # Force GC to reduce virtual memory before fork (prevents ENOMEM in containers)
        gc.collect()
        try:
            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            # Clean up temp file on timeout before propagating
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        if result.returncode != 0:
            # Check if temp output is a valid video despite non-zero exit
            try:
                file_size = tmp_path.stat().st_size
            except FileNotFoundError:
                file_size = 0
            if file_size >= self._MIN_VALID_SIZE and self._probe_output_valid(tmp_path):
                logger.warning(
                    "FFmpeg returned %d but output is valid (%d bytes), accepting",
                    result.returncode,
                    file_size,
                )
                if result.stderr:
                    logger.debug("FFmpeg stderr (accepted): %s", result.stderr[-500:])
                tmp_path.rename(output_path)
                return output_path
            # Truly failed — clean up temp file
            if tmp_path.exists():
                tmp_path.unlink()
            logger.error("FFmpeg stderr: %s", result.stderr[-2000:] if result.stderr else 'empty')
            raise RuntimeError(f"FFmpeg render failed (rc={result.returncode}): {result.stderr}")
        # Success — atomic rename from temp to final
        tmp_path.rename(output_path)
        return output_path

    # -- Per-paragraph helper methods -----------------------------------------

    def get_audio_duration(self, audio_path: str) -> float:
        """Probe audio file duration in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for p in audio_paths:
                # FFmpeg concat requires single-quoted paths with inner quotes escaped
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
            concat_list = f.name

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
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

        for srt_path, dur in zip(subtitle_paths, durations, strict=False):
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

    def convert_srt_to_ass(
        self,
        srt_path: str | Path,
        ass_path: str | Path,
        width: int | None = None,
        height: int | None = None,
        font_size: int | None = None,
    ) -> Path:
        """Convert SRT subtitle to ASS format with styled rendering.

        Produces bottom-center subtitles with:
        - White bold text
        - Black outline (2px)
        - Semi-transparent black background box (BorderStyle=3)
        - Large font for mobile readability
        """
        w = width or self.profile.width
        h = height or self.profile.height
        fs = font_size or self.profile.subtitle_font_size
        out = Path(ass_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Parse SRT
        srt_content = Path(srt_path).read_text(encoding="utf-8")
        blocks = srt_content.strip().split("\n\n")

        # ASS header
        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {w}",
            f"PlayResY: {h}",
            "WrapStyle: 0",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,NanumGothic,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,3,2,0,2,10,10,30,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            ts_line = lines[1]
            parts = ts_line.split(" --> ")
            if len(parts) != 2:
                continue
            start = _srt_ts_to_ass(parts[0].strip())
            end = _srt_ts_to_ass(parts[1].strip())
            text = "\\N".join(lines[2:])  # ASS newline
            # Escape braces to prevent ASS override injection
            text = text.replace("{", "\uff5b").replace("}", "\uff5d")
            ass_lines.append(
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
            )

        out.write_text("\n".join(ass_lines) + "\n", encoding="utf-8")
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


def _srt_ts_to_ass(ts: str) -> str:
    """Convert SRT timestamp 'HH:MM:SS,mmm' to ASS format 'H:MM:SS.cc'."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h = int(parts[0])
    m = int(parts[1])
    s_parts = parts[2].split(".")
    s = int(s_parts[0])
    # ASS uses centiseconds (2 digits)
    ms = int(s_parts[1]) if len(s_parts) > 1 else 0
    cs = ms // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

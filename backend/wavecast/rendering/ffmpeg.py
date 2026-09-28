from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.rendering.errors import MixRenderError, MixRendererUnavailableError


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    duration_seconds: float


@dataclass(frozen=True)
class HlsRenderedSegment:
    output_path: Path
    duration_seconds: float


@dataclass(frozen=True)
class HlsRenderResult:
    playlist_path: Path
    segments: tuple[HlsRenderedSegment, ...]
    duration_seconds: float


def _number(value: float) -> str:
    rendered = f"{value:.12g}"
    return "0" if rendered == "-0" else rendered


def _gain_expression(clip: AudioClip) -> str:
    points = list(clip.gain_automation)
    if not points:
        return _number(clip.gain)

    tail = _number(points[-1].gain)
    for left, right in reversed(list(zip(points, points[1:]))):
        span = right.offset_seconds - left.offset_seconds
        if span <= 0:
            continue
        slope = (right.gain - left.gain) / span
        interpolated = (
            f"({_number(left.gain)}+({_number(slope)})"
            f"*(t-{_number(left.offset_seconds)}))"
        )
        tail = f"if(lt(t,{_number(right.offset_seconds)}),{interpolated},{tail})"
    return (
        f"{_number(clip.gain)}*if(lt(t,{_number(points[0].offset_seconds)}),"
        f"{_number(points[0].gain)},{tail})"
    )


def build_filter_graph(plan: MixPlan) -> str:
    """Compile canonical clip timing and gain automation into ffmpeg filters."""
    chains: list[str] = []
    labels: list[str] = []
    for index, clip in enumerate(plan.clips):
        label = f"clip{index}"
        labels.append(f"[{label}]")
        delay_ms = round(clip.timeline_start_seconds * 1000)
        chains.append(
            f"[{index}:a]"
            f"atrim=start={_number(clip.source_offset_seconds)}:"
            f"duration={_number(clip.playable_duration_seconds)},"
            "asetpts=PTS-STARTPTS,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"volume=eval=frame:volume='{_gain_expression(clip)}',"
            f"adelay={delay_ms}:all=1"
            f"[{label}]"
        )
    chains.append(
        "".join(labels)
        + f"amix=inputs={len(plan.clips)}:duration=longest:normalize=0:"
        + "dropout_transition=0,"
        + f"atrim=duration={_number(plan.duration_seconds)},"
        + "asetpts=PTS-STARTPTS[mixout]"
    )
    return ";".join(chains)


def _stderr_summary(stderr: bytes | None) -> str:
    if not stderr:
        return "no ffmpeg stderr"
    text = stderr.decode("utf-8", errors="replace").strip()
    if not text:
        return "empty ffmpeg stderr"
    # Keep diagnostics compact and avoid dumping full command/source context.
    return text.splitlines()[-1][-320:]


def _ffmpeg_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise MixRendererUnavailableError("ffmpeg is unavailable")
    return resolved


def _base_input_command(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    binary: str,
) -> list[str]:
    command = [_ffmpeg_binary(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for clip in plan.clips:
        source = inputs.get(clip.id)
        if source is None or not source.is_file():
            raise MixRenderError("resolved mix input is missing")
        command.extend(["-i", str(source)])
    return command


def _command(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_path: Path,
    binary: str,
) -> list[str]:
    command = _base_input_command(plan, inputs, binary)
    command.extend(
        [
            "-filter_complex",
            build_filter_graph(plan),
            "-map",
            "[mixout]",
            "-map_metadata",
            "-1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            _number(plan.duration_seconds),
            str(output_path),
        ]
    )
    return command


def _transport_command(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_path: Path,
    binary: str,
    *,
    timeline_offset_seconds: float,
) -> list[str]:
    command = _base_input_command(plan, inputs, binary)
    command.extend(
        [
            "-filter_complex",
            build_filter_graph(plan),
            "-map",
            "[mixout]",
            "-map_metadata",
            "-1",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-f",
            "mpegts",
            "-mpegts_flags",
            "+resend_headers",
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-output_ts_offset",
            _number(timeline_offset_seconds),
            "-t",
            _number(plan.duration_seconds),
            str(output_path),
        ]
    )
    return command


def _hls_command(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_directory: Path,
    binary: str,
    *,
    segment_time_seconds: float,
) -> tuple[list[str], Path]:
    if segment_time_seconds <= 0:
        raise ValueError("HLS segment duration must be positive")
    playlist_path = output_directory / "render.m3u8"
    segment_pattern = output_directory / "segment-%06d.ts"
    command = _base_input_command(plan, inputs, binary)
    command.extend(
        [
            "-filter_complex",
            build_filter_graph(plan),
            "-map",
            "[mixout]",
            "-map_metadata",
            "-1",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            _number(plan.duration_seconds),
            "-f",
            "hls",
            "-hls_time",
            _number(segment_time_seconds),
            "-hls_segment_type",
            "mpegts",
            "-hls_flags",
            "independent_segments+omit_endlist",
            "-hls_playlist_type",
            "event",
            "-start_number",
            "0",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist_path),
        ]
    )
    return command, playlist_path


def _parse_hls_segments(playlist_path: Path) -> tuple[HlsRenderedSegment, ...]:
    try:
        lines = playlist_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MixRenderError("ffmpeg did not produce an HLS playlist") from error

    parsed: list[HlsRenderedSegment] = []
    pending_duration: float | None = None
    root = playlist_path.parent.resolve()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError as error:
                raise MixRenderError("ffmpeg produced an invalid HLS duration") from error
            continue
        if line.startswith("#"):
            continue
        if pending_duration is None:
            raise MixRenderError("ffmpeg HLS playlist is missing segment duration")
        path = (playlist_path.parent / line).resolve()
        if root != path.parent or not path.is_file() or path.stat().st_size == 0:
            raise MixRenderError("ffmpeg HLS segment is missing")
        parsed.append(
            HlsRenderedSegment(
                output_path=path,
                duration_seconds=pending_duration,
            )
        )
        pending_duration = None

    if not parsed:
        raise MixRenderError("ffmpeg did not produce HLS segments")

    # The native AAC encoder can flush one final frame after the requested
    # programme duration. Publishing that frame would create a synthetic
    # 20ms programme segment and make future prefix comparisons unstable.
    if len(parsed) > 1 and parsed[-1].duration_seconds <= 0.05:
        parsed = parsed[:-1]
    if not parsed:
        raise MixRenderError("ffmpeg produced only encoder padding")
    return tuple(parsed)


def render_mix_hls_prefix(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_directory: Path,
    *,
    segment_time_seconds: float = 6.0,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float | None = None,
) -> HlsRenderResult:
    """Render one continuous canonical prefix and let ffmpeg cut HLS segments.

    The whole ready prefix is encoded in one ffmpeg process. Re-rendering a
    longer immutable prefix therefore reproduces byte-identical earlier
    transport segments instead of starting a fresh AAC encoder for every chunk.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    command, playlist_path = _hls_command(
        plan,
        inputs,
        output_directory,
        ffmpeg_binary,
        segment_time_seconds=segment_time_seconds,
    )
    timeout = timeout_seconds or max(30.0, plan.duration_seconds * 2)
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise MixRenderError("ffmpeg HLS render timed out") from error
    except OSError as error:
        raise MixRenderError("ffmpeg could not be started") from error
    if completed.returncode != 0:
        raise MixRenderError(
            "ffmpeg did not produce a valid HLS prefix: "
            + _stderr_summary(completed.stderr)
        )

    segments = _parse_hls_segments(playlist_path)
    duration = sum(segment.duration_seconds for segment in segments)
    if abs(duration - plan.duration_seconds) > 0.15:
        raise MixRenderError("ffmpeg HLS duration diverges from the canonical plan")
    return HlsRenderResult(
        playlist_path=playlist_path,
        segments=segments,
        duration_seconds=duration,
    )


def render_mix_transport_segment(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_path: Path,
    *,
    timeline_offset_seconds: float,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float | None = None,
) -> RenderResult:
    """Legacy bounded transport render retained for compatibility tests."""

    if timeline_offset_seconds < 0:
        raise ValueError("timeline offset cannot be negative")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _transport_command(
        plan,
        inputs,
        output_path,
        ffmpeg_binary,
        timeline_offset_seconds=timeline_offset_seconds,
    )
    timeout = timeout_seconds or max(30.0, plan.duration_seconds * 2)
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise MixRenderError("ffmpeg transport render timed out") from error
    except OSError as error:
        raise MixRenderError("ffmpeg could not be started") from error
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        raise MixRenderError("ffmpeg did not produce a valid transport segment")
    return RenderResult(output_path=output_path, duration_seconds=plan.duration_seconds)


def render_mix(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float | None = None,
) -> RenderResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _command(plan, inputs, output_path, ffmpeg_binary)
    timeout = timeout_seconds or max(30.0, plan.duration_seconds * 2)
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise MixRenderError("ffmpeg render timed out") from error
    except OSError as error:
        raise MixRenderError("ffmpeg could not be started") from error
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        raise MixRenderError("ffmpeg did not produce a valid mixdown")
    return RenderResult(output_path=output_path, duration_seconds=plan.duration_seconds)


__all__ = [
    "HlsRenderedSegment",
    "HlsRenderResult",
    "RenderResult",
    "build_filter_graph",
    "render_mix",
    "render_mix_hls_prefix",
    "render_mix_transport_segment",
]

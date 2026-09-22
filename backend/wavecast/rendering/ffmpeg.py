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


def _ffmpeg_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise MixRendererUnavailableError("ffmpeg is unavailable")
    return resolved


def _command(
    plan: MixPlan,
    inputs: Mapping[str, Path],
    output_path: Path,
    binary: str,
) -> list[str]:
    command = [_ffmpeg_binary(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for clip in plan.clips:
        source = inputs.get(clip.id)
        if source is None or not source.is_file():
            raise MixRenderError("resolved mix input is missing")
        command.extend(["-i", str(source)])
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


__all__ = ["RenderResult", "build_filter_graph", "render_mix"]

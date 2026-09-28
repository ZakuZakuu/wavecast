from __future__ import annotations

import asyncio
import hashlib
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wavecast.arrangement.models import AudioClip, GainPoint, MixPlan
from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.rendering.errors import MixRenderError
from wavecast.rendering.ffmpeg import HlsRenderedSegment, render_mix_hls_prefix
from wavecast.rendering.fingerprint import mix_plan_fingerprint
from wavecast.rendering.sources import resolve_mix_sources


DEFAULT_PROGRAM_CHUNK_SECONDS = 6.0
DEFAULT_RENDER_HOLDBACK_SECONDS = 30.0
_MEDIA_TIMELINE_TOLERANCE_SECONDS = 0.15


class ProgramImmutabilityError(RuntimeError):
    """A newer plan or renderer attempted to rewrite audio behind the frontier."""


class ProgramRenderChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0, serialization_alias="startSeconds")
    duration_seconds: float = Field(gt=0, serialization_alias="durationSeconds")
    plan_fingerprint: str = Field(min_length=1, serialization_alias="planFingerprint")
    content_sha256: str = Field(min_length=64, max_length=64, serialization_alias="contentSha256")
    asset_key: str = Field(min_length=1, serialization_alias="assetKey")
    audio_url: str = Field(min_length=1, serialization_alias="audioUrl")

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds


class ProgramRenderManifest(BaseModel):
    """Append-only publication state for one listener-facing programme feed."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = Field(default=1, serialization_alias="schemaVersion")
    episode_id: str = Field(min_length=1, serialization_alias="episodeId")
    revision: str = Field(default="r1", min_length=1)
    chunk_duration_seconds: float = Field(gt=0, serialization_alias="chunkDurationSeconds")
    holdback_seconds: float = Field(ge=0, serialization_alias="holdbackSeconds")
    rendered_frontier_seconds: float = Field(ge=0, serialization_alias="renderedFrontierSeconds")
    complete: bool = False
    chunks: tuple[ProgramRenderChunk, ...] = ()
    stream_url: str = Field(min_length=1, serialization_alias="streamUrl")

    @model_validator(mode="after")
    def validate_append_only_shape(self) -> "ProgramRenderManifest":
        expected_start = 0.0
        for index, chunk in enumerate(self.chunks):
            if chunk.index != index:
                raise ValueError("program chunks must have contiguous indices")
            if abs(chunk.start_seconds - expected_start) > 1e-5:
                raise ValueError("program chunks must be contiguous")
            expected_start = chunk.end_seconds
        if abs(expected_start - self.rendered_frontier_seconds) > 1e-5:
            raise ValueError("rendered frontier must equal the end of the final chunk")
        return self


def _automation_gain(clip: AudioClip, offset_seconds: float) -> float:
    points = list(clip.gain_automation)
    if not points:
        return 1.0
    if offset_seconds <= points[0].offset_seconds:
        return points[0].gain
    for left, right in zip(points, points[1:]):
        if offset_seconds <= right.offset_seconds:
            span = right.offset_seconds - left.offset_seconds
            if span <= 0:
                return right.gain
            progress = (offset_seconds - left.offset_seconds) / span
            return left.gain + (right.gain - left.gain) * progress
    return points[-1].gain


def _slice_gain_automation(
    clip: AudioClip,
    source_clip_start_offset: float,
    duration_seconds: float,
) -> tuple[GainPoint, ...]:
    if not clip.gain_automation:
        return ()
    source_end = source_clip_start_offset + duration_seconds
    points: list[GainPoint] = [
        GainPoint(
            offset_seconds=0,
            gain=_automation_gain(clip, source_clip_start_offset),
        )
    ]
    for point in clip.gain_automation:
        if source_clip_start_offset < point.offset_seconds < source_end:
            points.append(
                GainPoint(
                    offset_seconds=point.offset_seconds - source_clip_start_offset,
                    gain=point.gain,
                )
            )
    points.append(
        GainPoint(
            offset_seconds=duration_seconds,
            gain=_automation_gain(clip, source_end),
        )
    )

    deduped: list[GainPoint] = []
    for point in points:
        if deduped and abs(deduped[-1].offset_seconds - point.offset_seconds) <= 1e-9:
            deduped[-1] = point
        else:
            deduped.append(point)
    return tuple(deduped)


def slice_mix_plan(plan: MixPlan, start_seconds: float, end_seconds: float) -> MixPlan:
    """Project one absolute programme interval into a standalone canonical MixPlan."""

    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError("invalid mix slice")
    if end_seconds > plan.duration_seconds + 1e-6:
        raise ValueError("mix slice exceeds plan duration")

    duration = end_seconds - start_seconds
    clips: list[AudioClip] = []
    for clip in plan.clips:
        absolute_start = max(start_seconds, clip.timeline_start_seconds)
        absolute_end = min(end_seconds, clip.timeline_end_seconds)
        if absolute_end <= absolute_start + 1e-9:
            continue

        clip_local_start = absolute_start - clip.timeline_start_seconds
        clipped_duration = absolute_end - absolute_start
        clips.append(
            clip.model_copy(
                update={
                    "timeline_start_seconds": absolute_start - start_seconds,
                    "source_offset_seconds": clip.source_offset_seconds + clip_local_start,
                    "playable_duration_seconds": clipped_duration,
                    "fade_in_seconds": 0.0,
                    "fade_out_seconds": 0.0,
                    "gain_automation": _slice_gain_automation(
                        clip,
                        clip_local_start,
                        clipped_duration,
                    ),
                }
            )
        )

    if not clips:
        raise ValueError("mix slice contains no audio")

    segment_starts = {
        segment_id: absolute_start - start_seconds
        for segment_id, absolute_start in plan.segment_starts.items()
        if start_seconds <= absolute_start < end_seconds
    }
    return MixPlan(
        episode_id=plan.episode_id,
        duration_seconds=duration,
        clips=tuple(clips),
        segment_starts=segment_starts,
    )


def committable_frontier(
    plan: MixPlan,
    *,
    complete: bool,
    chunk_duration_seconds: float = DEFAULT_PROGRAM_CHUNK_SECONDS,
    holdback_seconds: float = DEFAULT_RENDER_HOLDBACK_SECONDS,
) -> float:
    """Return the latest source-timeline point allowed to become immutable."""

    del chunk_duration_seconds
    if complete:
        return plan.duration_seconds
    return max(0.0, plan.duration_seconds - holdback_seconds)


def _safe_episode_id(episode_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", episode_id)


def manifest_key(episode_id: str) -> str:
    return f"program-renders/{_safe_episode_id(episode_id)}/manifest.json"


def stream_url(episode_id: str) -> str:
    return f"/api/program-streams/{_safe_episode_id(episode_id)}.m3u8"


async def load_program_manifest(
    storage: ObjectStorageProvider,
    episode_id: str,
) -> ProgramRenderManifest | None:
    stored = await storage.get(manifest_key(episode_id))
    if stored is None:
        return None
    try:
        return ProgramRenderManifest.model_validate_json(stored.content)
    except (ValueError, TypeError) as error:
        raise ProgramImmutabilityError("stored program manifest is invalid") from error


async def _store_manifest(
    storage: ObjectStorageProvider,
    manifest: ProgramRenderManifest,
) -> None:
    await storage.put(
        manifest_key(manifest.episode_id),
        manifest.model_dump_json().encode("utf-8"),
        "application/json",
        {
            "episode_id": manifest.episode_id,
            "rendered_frontier_seconds": manifest.rendered_frontier_seconds,
            "complete": manifest.complete,
        },
    )


def _new_manifest(
    episode_id: str,
    *,
    chunk_duration_seconds: float,
    holdback_seconds: float,
) -> ProgramRenderManifest:
    return ProgramRenderManifest(
        episode_id=episode_id,
        chunk_duration_seconds=chunk_duration_seconds,
        holdback_seconds=holdback_seconds,
        rendered_frontier_seconds=0,
        complete=False,
        chunks=(),
        stream_url=stream_url(episode_id),
    )


def _fingerprint_interval(
    plan: MixPlan,
    start_seconds: float,
    media_end_seconds: float,
) -> str:
    source_end = min(media_end_seconds, plan.duration_seconds)
    if source_end <= start_seconds + 1e-9:
        raise ProgramImmutabilityError("rendered media extends beyond the canonical programme")
    return mix_plan_fingerprint(slice_mix_plan(plan, start_seconds, source_end))


def _verify_frozen_prefix(plan: MixPlan, manifest: ProgramRenderManifest) -> None:
    for chunk in manifest.chunks:
        if chunk.start_seconds >= plan.duration_seconds + _MEDIA_TIMELINE_TOLERANCE_SECONDS:
            raise ProgramImmutabilityError("new plan is shorter than the frozen programme")
        fingerprint = _fingerprint_interval(
            plan,
            chunk.start_seconds,
            chunk.end_seconds,
        )
        if fingerprint != chunk.plan_fingerprint:
            raise ProgramImmutabilityError("new plan rewrites frozen programme audio")


def _candidate_prefix(
    segments: tuple[HlsRenderedSegment, ...],
    *,
    safe_frontier_seconds: float,
    complete: bool,
) -> list[tuple[float, HlsRenderedSegment]]:
    candidates: list[tuple[float, HlsRenderedSegment]] = []
    cursor = 0.0
    for segment in segments:
        end = cursor + segment.duration_seconds
        if not complete and end > safe_frontier_seconds + 1e-6:
            break
        candidates.append((cursor, segment))
        cursor = end
    return candidates


async def render_program_prefix(
    plan: MixPlan,
    storage: ObjectStorageProvider,
    *,
    complete: bool = False,
    chunk_duration_seconds: float = DEFAULT_PROGRAM_CHUNK_SECONDS,
    holdback_seconds: float = DEFAULT_RENDER_HOLDBACK_SECONDS,
) -> ProgramRenderManifest:
    """Append immutable HLS chunks from a continuously encoded canonical prefix.

    Each extension re-renders the ready prefix from time zero in one ffmpeg
    process. Existing transport chunks must reproduce byte-for-byte before any
    new chunk is published. That costs extra CPU today, but it gives the first
    production transport a strong immutability guarantee and avoids AAC encoder
    resets between chunks.
    """

    if chunk_duration_seconds <= 0:
        raise ValueError("chunk duration must be positive")
    if holdback_seconds < 0:
        raise ValueError("render holdback cannot be negative")

    manifest = await load_program_manifest(storage, plan.episode_id)
    if manifest is None:
        manifest = _new_manifest(
            plan.episode_id,
            chunk_duration_seconds=chunk_duration_seconds,
            holdback_seconds=holdback_seconds,
        )
    elif (
        abs(manifest.chunk_duration_seconds - chunk_duration_seconds) > 1e-9
        or abs(manifest.holdback_seconds - holdback_seconds) > 1e-9
    ):
        raise ProgramImmutabilityError("render policy changed after programme publication")

    _verify_frozen_prefix(plan, manifest)
    if manifest.complete:
        return manifest

    safe_frontier = committable_frontier(
        plan,
        complete=complete,
        chunk_duration_seconds=chunk_duration_seconds,
        holdback_seconds=holdback_seconds,
    )

    with TemporaryDirectory(prefix="wavecast-program-render-") as temporary:
        root = Path(temporary)
        sources = await resolve_mix_sources(plan, storage, root / "inputs")
        rendered = await asyncio.to_thread(
            render_mix_hls_prefix,
            plan,
            sources,
            root / "hls",
            segment_time_seconds=chunk_duration_seconds,
        )
        candidates = _candidate_prefix(
            rendered.segments,
            safe_frontier_seconds=safe_frontier,
            complete=complete,
        )

        if len(candidates) < len(manifest.chunks):
            raise ProgramImmutabilityError("rendered prefix moved behind the frozen frontier")

        # Re-rendering from zero must reproduce every previously published
        # transport segment byte-for-byte. This also protects against an ffmpeg
        # configuration/version change silently altering a live programme.
        for existing, (start, rendered_segment) in zip(manifest.chunks, candidates):
            if (
                abs(existing.start_seconds - start) > 1e-5
                or abs(existing.duration_seconds - rendered_segment.duration_seconds) > 1e-5
            ):
                raise ProgramImmutabilityError("renderer changed a frozen segment boundary")
            digest = hashlib.sha256(rendered_segment.output_path.read_bytes()).hexdigest()
            if digest != existing.content_sha256:
                raise ProgramImmutabilityError("renderer changed frozen programme bytes")

        chunks = list(manifest.chunks)
        for index in range(len(chunks), len(candidates)):
            start, rendered_segment = candidates[index]
            end = start + rendered_segment.duration_seconds
            if start >= plan.duration_seconds + _MEDIA_TIMELINE_TOLERANCE_SECONDS:
                break
            content = rendered_segment.output_path.read_bytes()
            if not content:
                raise MixRenderError("program renderer produced an empty chunk")
            digest = hashlib.sha256(content).hexdigest()
            fingerprint = _fingerprint_interval(plan, start, end)
            key = (
                f"program-renders/{_safe_episode_id(plan.episode_id)}/r1/"
                f"{index:06d}-{digest[:20]}.ts"
            )
            url = await storage.put(
                key,
                content,
                "video/mp2t",
                {
                    "episode_id": plan.episode_id,
                    "chunk_index": index,
                    "start_seconds": start,
                    "duration_seconds": rendered_segment.duration_seconds,
                    "plan_fingerprint": fingerprint,
                    "content_sha256": digest,
                },
            )
            chunks.append(
                ProgramRenderChunk(
                    index=index,
                    start_seconds=start,
                    duration_seconds=rendered_segment.duration_seconds,
                    plan_fingerprint=fingerprint,
                    content_sha256=digest,
                    asset_key=key,
                    audio_url=url,
                )
            )

    frontier = chunks[-1].end_seconds if chunks else 0.0
    is_complete = bool(
        complete
        and chunks
        and frontier >= plan.duration_seconds - _MEDIA_TIMELINE_TOLERANCE_SECONDS
    )
    manifest = manifest.model_copy(
        update={
            "chunks": tuple(chunks),
            "rendered_frontier_seconds": frontier,
            "complete": is_complete,
        }
    )
    await _store_manifest(storage, manifest)
    return manifest


def hls_playlist(manifest: ProgramRenderManifest) -> str:
    """Build the mutable EVENT playlist over immutable programme chunks."""

    target = max(
        1,
        math.ceil(max((chunk.duration_seconds for chunk in manifest.chunks), default=1)),
    )
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:EVENT",
        "#EXT-X-START:TIME-OFFSET=0.000,PRECISE=YES",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    for chunk in manifest.chunks:
        lines.append(f"#EXTINF:{chunk.duration_seconds:.6f},")
        lines.append(chunk.audio_url)
    if manifest.complete:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_PROGRAM_CHUNK_SECONDS",
    "DEFAULT_RENDER_HOLDBACK_SECONDS",
    "ProgramImmutabilityError",
    "ProgramRenderChunk",
    "ProgramRenderManifest",
    "committable_frontier",
    "hls_playlist",
    "load_program_manifest",
    "manifest_key",
    "render_program_prefix",
    "slice_mix_plan",
    "stream_url",
]

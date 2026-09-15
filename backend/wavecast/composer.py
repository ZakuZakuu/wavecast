"""Deterministic composition of resolved music and structured radio narration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import cast

from wavecast.intelligence.models import (
    NarrationScript,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
    ResolvedTrackCandidate,
    UnresolvedTrackError,
)
from wavecast.models.episode import (
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.providers.contracts import AudioAsset, AudioAssetType, MusicProvider


class EpisodeComposer:
    """Compose an ordered timeline without allowing proposals into playback."""

    def __init__(self, music_provider: MusicProvider) -> None:
        self.music_provider = music_provider

    async def compose(
        self,
        tracks: Sequence[ResolvedTrack | ResolvedTrackCandidate | object],
        script: RadioScript | NarrationScript | Sequence[RadioScriptBlock],
    ) -> PlayableEpisode:
        blocks = _script_blocks(script)
        resolved_assets: list[tuple[ResolvedTrack, AudioAsset]] = []
        for candidate in tracks:
            resolved = _resolved_identity(candidate)
            asset = await _playback_asset(self.music_provider, resolved)
            if asset.asset_type is not AudioAssetType.MUSIC:
                raise ValueError("music provider returned a non-music asset")
            resolved_assets.append((resolved, asset))

        segments: list[MusicSegment | NarrationSegment] = []
        order = 0
        unassigned_transition = [
            block for block in blocks if block.kind is RadioScriptBlockKind.TRANSITION and block.track_index is None
        ]
        used_blocks: set[int] = set()

        for track_index, (track, asset) in enumerate(resolved_assets):
            for block_index, block in enumerate(blocks):
                if block.kind is RadioScriptBlockKind.TRACK_INTRO and (
                    block.track_index == track_index
                    or (block.track_index is None and track_index == 0)
                ):
                    segments.append(_narration_segment(block, order, track_index + 1))
                    order += 1
                    used_blocks.add(block_index)

            segments.append(
                MusicSegment(
                    id=f"segment-music-{track_index}",
                    chapter_id=f"chapter-{track_index + 1}",
                    order=order,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=asset.duration,
                    actual_duration_seconds=asset.duration,
                    track_ref=track.track_ref,
                    audio_source_url=asset.playback_url,
                    title=track.canonical_title,
                    artist=track.canonical_artist,
                    asset_ref=asset.asset_id,
                )
            )
            order += 1

            for block_index, block in enumerate(blocks):
                if block_index in used_blocks:
                    continue
                if block.kind is RadioScriptBlockKind.INTRO and (
                    block.track_index == track_index
                    or (block.track_index is None and track_index == 0)
                ):
                    segments.append(_narration_segment(block, order, track_index + 1))
                    order += 1
                    used_blocks.add(block_index)
                elif block.kind is RadioScriptBlockKind.TRANSITION and (
                    block.track_index == track_index
                    or (
                        block.track_index is None
                        and track_index > 0
                        and block
                        is (
                            unassigned_transition[track_index - 1]
                            if track_index - 1 < len(unassigned_transition)
                            else None
                        )
                    )
                ):
                    segments.append(_narration_segment(block, order, track_index + 1))
                    order += 1
                    used_blocks.add(block_index)

        for block_index, block in enumerate(blocks):
            if block_index not in used_blocks and block.kind is RadioScriptBlockKind.OUTRO:
                segments.append(_narration_segment(block, order, len(resolved_assets) + 1))
                order += 1
                used_blocks.add(block_index)

        # Keep malformed-but-structured scripts observable instead of silently dropping text.
        for block_index, block in enumerate(blocks):
            if block_index not in used_blocks:
                segments.append(_narration_segment(block, order, len(resolved_assets) + 1))
                order += 1

        return PlayableEpisode(segments=segments)


def _resolved_identity(candidate: object) -> ResolvedTrack:
    if isinstance(candidate, ResolvedTrack):
        return candidate
    if isinstance(candidate, ResolvedTrackCandidate):
        return candidate.resolved_track()
    raise UnresolvedTrackError("unresolved track proposal cannot enter a playable episode")


async def _playback_asset(provider: MusicProvider, track: ResolvedTrack) -> AudioAsset:
    resolver = cast(
        Callable[[ResolvedTrack], Awaitable[AudioAsset]],
        getattr(provider, "get_playback_asset", None) or getattr(provider, "playback_asset"),
    )
    return await resolver(track)


def _script_blocks(
    script: RadioScript | NarrationScript | Sequence[RadioScriptBlock],
) -> list[RadioScriptBlock]:
    if isinstance(script, RadioScript):
        return list(script.blocks)
    if isinstance(script, NarrationScript):
        return [
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRANSITION,
                text=script.text,
                duration_seconds=script.intended_duration_seconds,
                tts_cues=list(script.tts_cues),
                evidence_ids=list(script.evidence_ids),
            )
        ]
    return list(script)


def _narration_segment(block: RadioScriptBlock, order: int, chapter_number: int) -> NarrationSegment:
    return NarrationSegment(
        id=f"segment-narration-{order}",
        chapter_id=f"chapter-{chapter_number}",
        order=order,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=block.intended_duration_seconds,
        title=block.kind.value.replace("_", " ").title(),
        narration_text=block.text,
    )

"""Deterministic composition of resolved music and structured radio narration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from wavecast.audio_timing import TrackTimingProfile
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
    NarrationRole,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.providers.contracts import AudioAsset, AudioAssetType


class PlaybackAssetProvider(Protocol):
    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset: ...


@dataclass(frozen=True)
class PreparedMusicAsset:
    track: ResolvedTrack
    asset: AudioAsset


class EpisodeComposer:
    """Compose an ordered timeline without allowing proposals into playback."""

    def __init__(self, music_provider: PlaybackAssetProvider) -> None:
        self.music_provider = music_provider

    async def compose(
        self,
        tracks: Sequence[ResolvedTrack | ResolvedTrackCandidate | None],
        script: RadioScript | NarrationScript | Sequence[RadioScriptBlock],
    ) -> PlayableEpisode:
        prepared_tracks = await self.prepare_tracks(tracks)
        return self.compose_prepared(prepared_tracks, script)

    async def prepare_tracks(
        self,
        tracks: Sequence[ResolvedTrack | ResolvedTrackCandidate | None],
    ) -> list[PreparedMusicAsset | None]:
        """Resolve each playable track to exactly one provider asset."""

        prepared: list[PreparedMusicAsset | None] = []
        for candidate in tracks:
            if candidate is None:
                prepared.append(None)
                continue
            resolved = _resolved_identity(candidate)
            asset = await self.music_provider.get_playback_asset(resolved)
            if asset.asset_type is not AudioAssetType.MUSIC:
                raise ValueError("music provider returned a non-music asset")
            prepared.append(PreparedMusicAsset(track=resolved, asset=asset))
        return prepared

    def compose_prepared(
        self,
        prepared_tracks: Sequence[PreparedMusicAsset | None],
        script: RadioScript | NarrationScript | Sequence[RadioScriptBlock],
    ) -> PlayableEpisode:
        """Compose from already prepared assets without another provider fetch."""

        blocks = _script_blocks(script)
        resolved_assets = [(item.track, item.asset) for item in prepared_tracks if item is not None]
        segments: list[MusicSegment | NarrationSegment] = []
        order = 0
        used_blocks: set[int] = set()

        # Radio block placement is deliberately explicit:
        # - track intros sit immediately before their indexed track;
        # - opening music is emitted before an unindexed INTRO;
        # - INTRO(i) and TRANSITION(i) sit in the gap after track i;
        # - unindexed transitions are compatibility syntax assigned to gaps in
        #   order, starting with the first gap;
        # - OUTRO follows the final track.
        unindexed_track_intros = [
            index
            for index, block in enumerate(blocks)
            if block.kind is RadioScriptBlockKind.TRACK_INTRO and block.track_index is None
        ]
        unindexed_transitions = [
            index
            for index, block in enumerate(blocks)
            if block.kind is RadioScriptBlockKind.TRANSITION and block.track_index is None
        ]
        explicit_intro_targets = {
            block.track_index
            for block in blocks
            if block.kind is RadioScriptBlockKind.TRACK_INTRO and block.track_index is not None
        }
        unindexed_intro_targets = iter(
            index for index in range(len(resolved_assets)) if index not in explicit_intro_targets
        )
        unindexed_intro_by_block = {
            block_index: next(unindexed_intro_targets, None)
            for block_index in unindexed_track_intros
        }
        explicit_transition_targets = {
            block.track_index
            for block in blocks
            if block.kind is RadioScriptBlockKind.TRANSITION
            and block.track_index is not None
            and block.track_index < len(resolved_assets) - 1
        }
        fallback_gap_targets = [
            index
            for index in range(max(0, len(resolved_assets) - 1))
            if index not in explicit_transition_targets
        ]
        if not fallback_gap_targets:
            # If every gap already has an indexed transition, additional
            # narrative beats still belong to the final available gap rather
            # than being pushed after the episode.
            fallback_gap_targets = list(range(max(0, len(resolved_assets) - 1)))
        unindexed_transition_by_block = {
            block_index: (
                fallback_gap_targets[min(position, len(fallback_gap_targets) - 1)]
                if fallback_gap_targets
                else None
            )
            for position, block_index in enumerate(unindexed_transitions)
        }

        for track_index, (track, asset) in enumerate(resolved_assets):
            for block_index, block in enumerate(blocks):
                is_indexed_intro = (
                    block.kind is RadioScriptBlockKind.TRACK_INTRO
                    and block.track_index == track_index
                )
                is_sequential_intro = (
                    block.kind is RadioScriptBlockKind.TRACK_INTRO
                    and block.track_index is None
                    and unindexed_intro_by_block.get(block_index) == track_index
                )
                if is_indexed_intro or is_sequential_intro:
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
                    timing_profile=_asset_timing_profile(asset),
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
                        and unindexed_transition_by_block.get(block_index) == track_index
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


def _resolved_identity(candidate: ResolvedTrack | ResolvedTrackCandidate) -> ResolvedTrack:
    if isinstance(candidate, ResolvedTrack):
        return candidate
    if isinstance(candidate, ResolvedTrackCandidate):
        return candidate.resolved_track()
    raise UnresolvedTrackError("unresolved track proposal cannot enter a playable episode")


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
                tts_text=script.tts_text,
                duration_seconds=script.intended_duration_seconds,
                tts_cues=list(script.tts_cues),
                evidence_ids=list(script.evidence_ids),
            )
        ]
    return list(script)


def _narration_segment(
    block: RadioScriptBlock, order: int, chapter_number: int
) -> NarrationSegment:
    return NarrationSegment(
        id=f"segment-narration-{order}",
        chapter_id=f"chapter-{chapter_number}",
        order=order,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=block.intended_duration_seconds,
        title=block.kind.value.replace("_", " ").title(),
        narration_text=block.text,
        tts_text=block.tts_text,
        tts_cues=list(block.tts_cues),
        narration_role=_narration_role(block.kind),
    )


def _narration_role(kind: RadioScriptBlockKind) -> NarrationRole:
    return {
        RadioScriptBlockKind.INTRO: NarrationRole.INTRO,
        RadioScriptBlockKind.TRACK_INTRO: NarrationRole.TRACK_INTRO,
        RadioScriptBlockKind.TRANSITION: NarrationRole.TRANSITION,
        RadioScriptBlockKind.OUTRO: NarrationRole.OUTRO,
    }[kind]


def _asset_timing_profile(asset: AudioAsset) -> TrackTimingProfile | None:
    raw = asset.metadata.get("timing_profile")
    if isinstance(raw, TrackTimingProfile):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return TrackTimingProfile.model_validate(raw)
    except ValueError:
        return None

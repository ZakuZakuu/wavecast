import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
import wavecast.assembly as assembly_module
from pydantic import ValidationError
from wavecast.assembly import (
    EpisodeAssemblyError,
    LiveEpisodeAssemblyRequest,
    LiveEpisodeAssemblyService,
    MockEpisodeAssemblyLLM,
    NarrationPlacementError,
    _apply_host_mode_to_slot_contexts,
    _assemble_radio_script,
    _assemble_writer_scripts,
    _bound_progressive_resolved_route,
    _build_narration_slot_contexts,
    _dedupe_progressive_song_route,
    _lock_successor_after_opening,
    _mock_writer_chapter_index,
    _mock_writer_slot_contexts,
    _normalize_opening_resolved_route,
    _reindex_resolved_chapters,
    _ResolvedChapter,
    _same_song_identity,
    create_episode_assembly_service,
)
from wavecast.composer import EpisodeComposer
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import (
    ChapterPlan,
    EditorialConnection,
    EditorialRelationType,
    FastStartPlan,
    NarrativeRole,
    NoveltyDistance,
    OutputLanguage,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.intelligence.research import BackgroundResearchService, FastResearchService
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import MusicSegment, NarrationSegment, SegmentState
from wavecast.presentation import HostMode, PresentationIntent
from wavecast.providers.fakes import FakeSearchProvider, MockMusicProvider, MockTTSProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.usage import UsageLedger
from wavecast.storage.assets import LocalObjectStorageProvider


def block(
    kind: RadioScriptBlockKind,
    text: str,
    *,
    track_index: int | None = None,
    cue: str = "",
    evidence: str = "",
    tts_text: str | None = None,
) -> RadioScriptBlock:
    return RadioScriptBlock(
        kind=kind,
        text=text,
        tts_text=tts_text,
        duration_seconds=3,
        track_index=track_index,
        tts_cues=[cue] if cue else [],
        evidence_ids=[evidence] if evidence else [],
    )


def slot_blocks(prompt: str, prefix: str) -> list[RadioScriptBlock]:
    marker = "Narration slot contexts: "
    contexts = json.loads(prompt.split(marker, 1)[1].split(
        "\nThe following legacy field", 1
    )[0])
    chapter = json.loads(prompt.split("Chapter: ", 1)[1].split(
        "\nEvidence:", 1
    )[0])
    blocks: list[RadioScriptBlock] = []
    for context in contexts:
        allowed = set(context["allowed_block_kinds"])
        if "track_intro" in allowed:
            kind = RadioScriptBlockKind.TRACK_INTRO
        elif "outro" in allowed:
            kind = RadioScriptBlockKind.OUTRO
        elif "intro" in allowed and (chapter["index"] == 0 or context["is_opening"]):
            kind = RadioScriptBlockKind.INTRO
        elif "transition" in allowed:
            kind = RadioScriptBlockKind.TRANSITION
        else:
            continue
        blocks.append(block(kind, f"{prefix}{chapter['index']}"))
    return blocks


class RecordingAssemblyLLM(MockEpisodeAssemblyLLM):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
        return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]


def service(tmp_path, llm: RecordingAssemblyLLM | None = None) -> LiveEpisodeAssemblyService:
    ledger = UsageLedger()
    llm = llm or RecordingAssemblyLLM()
    discovery = FakeSearchProvider()
    research = FakeSearchProvider()
    fast_path = FastPathCoordinator(
        research=FastResearchService(discovery=discovery, research=research, ledger=ledger),
        planner=FastStartPlanner(llm),
    )
    background = BackgroundIntelligencePipeline(
        research=BackgroundResearchService(
            discovery=discovery, research=research, ledger=ledger
        ),
        curator=CuratorService(llm),
        writer=WriterService(llm),
    )
    music = MockMusicProvider()
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    return LiveEpisodeAssemblyService(
        fast_path=fast_path,
        background_pipeline=background,
        retrieval=MusicRetrievalService(MusicProviderRegistry({"mock": music})),
        composer=EpisodeComposer(music),
        materializer=NarrationMaterializer(MockTTSProvider(storage), storage),
        ledger=ledger,
    )


def test_fast_successor_is_locked_into_full_progressive_route(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    llm = RecordingAssemblyLLM()
    assembly = service(tmp_path, llm)
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )
    request = LiveEpisodeAssemblyRequest(
        topic="night textures",
        anchor_tracks=["Neon First Light"],
        desired_duration_seconds=900,
        max_tracks=4,
        max_chapters=8,
    )

    bootstrap = asyncio.run(
        assembly.prepare_fast_successor(
            request,
            opening_track=opening,
        )
    )

    assert bootstrap is not None
    assert bootstrap.chapter_id == "chapter-2"
    assert len(bootstrap.segments) == 2
    placeholder, successor = bootstrap.segments
    assert isinstance(placeholder, NarrationSegment)
    assert placeholder.state is SegmentState.PLANNED
    assert isinstance(successor, MusicSegment)
    assert successor.track_ref == "mock:bridge"
    assert successor.title == "Midnight Transfer"
    assert successor.artist == "Signal Garden"
    assert successor.is_audio_ready

    locked = ResolvedTrack(
        track_ref=successor.track_ref,
        canonical_artist=successor.artist or "",
        canonical_title=successor.title,
    )
    session = asyncio.run(
        assembly.prepare_progressive_session(
            request,
            opening_track=opening,
            locked_successor=locked,
        )
    )

    assert session.chapters[0].chapter_id == "chapter-2"
    assert session.chapters[0].resolved_track == locked
    resolved_refs = [
        chapter.resolved_track.track_ref
        for chapter in session.chapters
        if chapter.resolved_track is not None
    ]
    assert resolved_refs.count("mock:bridge") == 1
    fast_start_calls = [
        call
        for call in llm.calls
        if call["output_type"] is FastStartPlan
    ]
    assert len(fast_start_calls) == 1


def test_music_only_fast_successor_has_no_narration_segment(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assembly = service(tmp_path)
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )
    request = LiveEpisodeAssemblyRequest(
        topic="只放歌，不要旁白",
        anchor_tracks=["Neon First Light"],
        desired_duration_seconds=900,
        max_tracks=4,
        max_chapters=8,
        presentation_intent=PresentationIntent(host_mode=HostMode.NONE),
    )

    bootstrap = asyncio.run(
        assembly.prepare_fast_successor(
            request,
            opening_track=opening,
        )
    )

    assert bootstrap is not None
    assert len(bootstrap.segments) == 1
    assert isinstance(bootstrap.segments[0], MusicSegment)
    assert bootstrap.segments[0].is_audio_ready


def test_default_light_fast_successor_reserves_pending_host_seam(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assembly = service(tmp_path)
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    bootstrap = asyncio.run(
        assembly.prepare_fast_successor(
            LiveEpisodeAssemblyRequest(
                topic="guided listening",
                anchor_tracks=["Neon First Light"],
            ),
            opening_track=opening,
        )
    )

    assert bootstrap is not None
    assert len(bootstrap.segments) == 2
    placeholder, music = bootstrap.segments
    assert isinstance(placeholder, NarrationSegment)
    assert placeholder.state is SegmentState.PLANNED
    assert placeholder.audio_source_url is None
    assert isinstance(music, MusicSegment)
    assert music.is_audio_ready


def test_song_identity_collapses_catalog_aliases_without_merging_unrelated_covers() -> None:
    bill_evans = ResolvedTrack(
        track_ref="netease:one",
        canonical_artist="Bill Evans",
        canonical_title="Waltz for Debby",
    )
    bill_evans_trio = ResolvedTrack(
        track_ref="netease:two",
        canonical_artist="Bill Evans Trio",
        canonical_title="Waltz for Debby",
    )
    unrelated_cover = ResolvedTrack(
        track_ref="netease:three",
        canonical_artist="Oscar Peterson Trio",
        canonical_title="Waltz for Debby",
    )

    assert _same_song_identity(bill_evans, bill_evans_trio) is True
    assert _same_song_identity(bill_evans_trio, bill_evans) is True
    assert _same_song_identity(bill_evans, unrelated_cover) is False


def test_progressive_route_drops_later_semantic_song_repeat_after_locked_prefix() -> None:
    opening = ResolvedTrack(
        track_ref="netease:opening",
        canonical_artist="Bill Evans Trio",
        canonical_title="Waltz for Debby",
    )
    locked = ResolvedTrack(
        track_ref="netease:locked",
        canonical_artist="Bill Evans Trio",
        canonical_title="My Foolish Heart",
    )
    repeated = ResolvedTrack(
        track_ref="netease:variant",
        canonical_artist="Bill Evans",
        canonical_title="Waltz for Debby",
    )
    later = ResolvedTrack(
        track_ref="netease:later",
        canonical_artist="Jerry Thomas Trio",
        canonical_title="Late Night Jam",
    )

    def item(index: int, track: ResolvedTrack) -> _ResolvedChapter:
        plan = ChapterPlan(
            index=index,
            track=TrackProposal(
                artist=track.canonical_artist,
                title=track.canonical_title,
                confidence=1.0,
            ),
            narrative_role=NarrativeRole.BRIDGE,
            reason="fixture",
            narration_goal="fixture",
        )
        return _ResolvedChapter(
            chapter=plan,
            writer_chapter=plan,
            track=track,
            music_index=index,
        )

    deduped = _dedupe_progressive_song_route(
        [
            item(0, opening),
            item(1, locked),
            item(2, repeated),
            item(3, later),
        ],
        protected_prefix=2,
    )

    assert [entry.track.track_ref for entry in deduped if entry.track] == [
        "netease:opening",
        "netease:locked",
        "netease:later",
    ]


def test_locked_successor_is_inserted_when_curator_route_does_not_contain_it() -> None:
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Opening Artist",
        canonical_title="Opening Track",
    )
    locked = ResolvedTrack(
        track_ref="mock:fast",
        canonical_artist="Fast Artist",
        canonical_title="Fast Successor",
    )
    later = ResolvedTrack(
        track_ref="mock:later",
        canonical_artist="Later Artist",
        canonical_title="Later Track",
    )
    opening_plan = ChapterPlan(
        index=0,
        track=TrackProposal(
            artist=opening.canonical_artist,
            title=opening.canonical_title,
            confidence=1.0,
        ),
        narrative_role=NarrativeRole.ANCHOR,
        reason="Opening.",
        narration_goal="Open.",
    )
    later_plan = ChapterPlan(
        index=1,
        track=TrackProposal(
            artist=later.canonical_artist,
            title=later.canonical_title,
            confidence=0.9,
        ),
        connection_from_previous_track=EditorialConnection(
            relation_type=EditorialRelationType.CONTRAST,
            rationale="This relation belongs to the old opening-to-later adjacency.",
        ),
        narrative_role=NarrativeRole.DISCOVERY,
        reason="Continue.",
        narration_goal="Continue.",
    )
    route = [
        _ResolvedChapter(
            chapter=opening_plan,
            writer_chapter=opening_plan,
            track=opening,
            music_index=0,
        ),
        _ResolvedChapter(
            chapter=later_plan,
            writer_chapter=later_plan,
            track=later,
            music_index=1,
        ),
    ]

    locked_route = _lock_successor_after_opening(route, locked)

    assert [item.track.track_ref if item.track else None for item in locked_route] == [
        "mock:opening",
        "mock:fast",
        "mock:later",
    ]
    assert locked_route[1].writer_chapter.track is not None
    assert locked_route[1].writer_chapter.track.artist == "Fast Artist"
    assert locked_route[1].writer_chapter.track.title == "Fast Successor"
    reindexed = _reindex_resolved_chapters(locked_route)
    assert reindexed[1].writer_chapter.connection_from_previous_track is None
    assert reindexed[2].writer_chapter.connection_from_previous_track is None

def test_mock_factory_assembles_real_music_and_narration_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assembly = create_episode_assembly_service()

    result = asyncio.run(
        assembly.assemble(
            LiveEpisodeAssemblyRequest(
                topic="night textures", anchor_tracks=["Neon First Light"], max_tracks=4
            )
        )
    )

    assert len(result.resolved_tracks) == 4
    assert result.unresolved_proposals == []
    assert result.playable_episode.segments[0].kind.value == "MUSIC"
    assert all(segment.is_audio_ready for segment in result.playable_episode.segments)
    assert result.duration_summary.total_seconds == result.playable_episode.duration_seconds
    assert result.duration_summary.music_seconds > result.duration_summary.narration_seconds
    assert [track.canonical_title for track in result.resolved_tracks] == [
        "Neon First Light",
        "Midnight Transfer",
        "Daybreak in Stereo",
        "Afterimage Avenue",
    ]
    assert [chapter.track.title for chapter in result.skeleton.chapters] == [
        "Neon First Light",
        "Midnight Transfer",
        "Daybreak in Stereo",
        "Afterimage Avenue",
    ]
    asyncio.run(assembly.aclose())


def test_writer_runs_only_after_resolution_and_receives_next_track_context(tmp_path) -> None:
    llm = RecordingAssemblyLLM()
    assembly = service(tmp_path, llm)

    result = asyncio.run(
        assembly.assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", anchor_tracks=["Neon First Light"])
        )
    )

    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    assert writer_calls
    assert "\"canonical_title\": \"Midnight Transfer\"" in writer_calls[0]["prompt"]
    assert any("Previous context:" in call["prompt"] for call in writer_calls[1:])
    assert sum(block.kind is RadioScriptBlockKind.INTRO for block in result.radio_script.blocks) == 0
    assert sum(block.kind is RadioScriptBlockKind.OUTRO for block in result.radio_script.blocks) == 1
    assert all(
        not (
            block.kind is RadioScriptBlockKind.TRANSITION
            and block.track_index == len(result.resolved_tracks) - 1
        )
        for block in result.radio_script.blocks
    )


def test_progressive_preparation_stops_before_writer_tts_and_playback_assets(tmp_path) -> None:
    llm = RecordingAssemblyLLM()
    assembly = service(tmp_path, llm)
    music_assets = assembly.composer.music_provider.get_playback_asset
    assembly.composer.music_provider.get_playback_asset = AsyncMock(wraps=music_assets)
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                anchor_tracks=["Neon First Light"],
                max_tracks=4,
            ),
            opening_track=opening,
        )
    )

    assert session.opening_track_ref == "mock:opening"
    assert [chapter.chapter_id for chapter in session.chapters] == [
        "chapter-2",
        "chapter-3",
        "chapter-4",
    ]
    assert all(chapter.resolved_track is not None for chapter in session.chapters)
    assert [call["output_type"] for call in llm.calls if call["output_type"] is RadioScript] == []
    assert assembly.materializer.tts_provider.calls == 0
    assert assembly.composer.music_provider.get_playback_asset.await_count == 0


def test_progressive_preparation_counts_application_opening_as_first_resolved_track(tmp_path) -> None:
    class OneFutureTrackLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                item = self._tracks[1]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(item),
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="one future track is enough when opening is already known",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="connect the opening to the next playable track",
                        )
                    ],
                    estimated_duration_seconds=900,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, OneFutureTrackLLM())
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                desired_duration_seconds=5 * 60,
                max_tracks=4,
            ),
            opening_track=opening,
        )
    )

    assert [chapter.resolved_track.canonical_title for chapter in session.chapters if chapter.resolved_track] == [
        "Midnight Transfer"
    ]


def test_progressive_route_rejects_severely_underfilled_duration(tmp_path) -> None:
    class OneFutureTrackLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                item = self._tracks[1]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(item),
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="only one future track resolved",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="fixture",
                        )
                    ],
                    estimated_duration_seconds=22 * 60,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, OneFutureTrackLLM())
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    with pytest.raises(
        EpisodeAssemblyError,
        match="duration coverage is too short",
    ) as failure:
        asyncio.run(
            assembly.prepare_progressive_session(
                LiveEpisodeAssemblyRequest(
                    topic="fixture",
                    desired_duration_seconds=22 * 60,
                    max_tracks=5,
                ),
                opening_track=opening,
            )
        )

    assert failure.value.reason_code == "insufficient_progressive_duration_coverage"
    assert failure.value.diagnostics["estimated_resolved_music_seconds"] == 360
    assert failure.value.diagnostics["required_resolved_music_seconds"] > 360


def test_progressive_route_allows_two_tracks_when_duration_target_is_short(
    tmp_path,
) -> None:
    class OneFutureTrackLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                item = self._tracks[1]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(item),
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="one future track is enough for a short target",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="fixture",
                        )
                    ],
                    estimated_duration_seconds=5 * 60,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, OneFutureTrackLLM())
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                desired_duration_seconds=5 * 60,
                max_tracks=5,
            ),
            opening_track=opening,
        )
    )

    assert len([chapter for chapter in session.chapters if chapter.resolved_track]) == 1


def test_progressive_resolution_uses_alternate_when_primary_repeats_opening_song(
    tmp_path,
) -> None:
    class DuplicatePrimaryLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                repeated = self._tracks[1]
                alternate = self._tracks[2]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(repeated),
                            track_alternates=[self._proposal(alternate)],
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="avoid repeating the opening song",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="move to a distinct next song",
                        )
                    ],
                    estimated_duration_seconds=900,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, DuplicatePrimaryLLM())
    opening = ResolvedTrack(
        track_ref="external:opening-version",
        canonical_artist="Signal Garden Trio",
        canonical_title="Midnight Transfer",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
            ),
            opening_track=opening,
        )
    )

    assert len(session.chapters) == 1
    chapter = session.chapters[0]
    assert chapter.resolved_track is not None
    assert chapter.resolved_track.canonical_title == "Daybreak in Stereo"
    assert chapter.chapter.track is not None
    assert chapter.chapter.track.title == "Daybreak in Stereo"


def test_progressive_preparation_uses_ranked_alternate_before_skipping_slot(tmp_path) -> None:
    class AlternateResolutionLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                primary = (
                    "Missing Artist",
                    "Definitely Not In Catalog",
                    NoveltyDistance.CLOSE,
                )
                alternate = self._tracks[1]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(primary),
                            track_alternates=[self._proposal(alternate)],
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="same editorial slot with a playable fallback",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="connect the opening to the resolved fallback",
                        )
                    ],
                    estimated_duration_seconds=900,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, AlternateResolutionLLM())
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
            ),
            opening_track=opening,
        )
    )

    assert len(session.chapters) == 1
    chapter = session.chapters[0]
    assert chapter.resolved_track is not None
    assert chapter.resolved_track.canonical_title == "Midnight Transfer"
    assert chapter.chapter.track is not None
    assert chapter.chapter.track.title == "Midnight Transfer"
    assert chapter.chapter.track_alternates == []
    assert session.skeleton.chapters[-1].track is not None
    assert session.skeleton.chapters[-1].track.title == "Midnight Transfer"
    assert not any(
        diagnostic.code == "unresolved_track"
        for diagnostic in session.diagnostics
    )


def test_progressive_preparation_skips_unresolved_selected_music_slot(tmp_path) -> None:
    class MixedResolutionLLM(RecordingAssemblyLLM):
        async def structured(
            self,
            prompt: str,
            output_type: type[object],
            **kwargs: object,
        ) -> object:
            if output_type is ProgramSkeleton:
                known_opening = self._tracks[0]
                missing = (
                    "Missing Artist",
                    "Definitely Not In Catalog",
                    NoveltyDistance.CLOSE,
                )
                known_future = self._tracks[1]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=index,
                            track=self._proposal(item),
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="fixture",
                            novelty_distance=item[2],
                            narration_goal="fixture",
                        )
                        for index, item in enumerate(
                            (known_opening, missing, known_future)
                        )
                    ],
                    estimated_duration_seconds=900,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    assembly = service(tmp_path, MixedResolutionLLM())
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
            ),
            opening_track=opening,
        )
    )

    assert [chapter.resolved_track.canonical_title for chapter in session.chapters if chapter.resolved_track] == [
        "Midnight Transfer"
    ]
    assert all(
        chapter.chapter.track is None
        or chapter.chapter.track.title != "Definitely Not In Catalog"
        for chapter in session.chapters
    )
    assert any(
        diagnostic.code == "unresolved_track"
        and diagnostic.chapter_index == 1
        for diagnostic in session.diagnostics
    )


def test_progressive_opening_dedupes_exact_identity_and_keeps_other_tracks() -> None:
    def chapter(index: int, track: ResolvedTrack) -> _ResolvedChapter:
        plan = ChapterPlan(
            index=index,
            track=TrackProposal(
                artist=track.canonical_artist,
                title=track.canonical_title,
                reasons=["fixture"],
                similarity_dimensions=["groove"],
                confidence=0.9,
            ),
            narrative_role=NarrativeRole.BRIDGE,
            reason="fixture",
            narration_goal="fixture",
        )
        return _ResolvedChapter(
            chapter=plan,
            writer_chapter=plan,
            track=track,
            music_index=None,
        )

    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )
    different = ResolvedTrack(
        track_ref="mock:bridge",
        canonical_artist="Signal Garden",
        canonical_title="Midnight Transfer",
    )
    normalized = _reindex_resolved_chapters(
        _normalize_opening_resolved_route(
            [chapter(0, opening), chapter(1, opening), chapter(2, different)],
            opening,
        )
    )

    assert [item.track.track_ref for item in normalized if item.track is not None] == [
        "mock:opening",
        "mock:bridge",
    ]
    assert [item.chapter.index for item in normalized] == [0, 1]
    assert normalized[1].track == different

def test_progressive_opening_insertion_reapplies_track_and_chapter_bounds() -> None:
    def chapter(index: int, track: ResolvedTrack) -> _ResolvedChapter:
        plan = ChapterPlan(
            index=index,
            track=TrackProposal(
                artist=track.canonical_artist,
                title=track.canonical_title,
                reasons=["fixture"],
                confidence=0.9,
            ),
            narrative_role=NarrativeRole.BRIDGE,
            reason="fixture",
            narration_goal="fixture",
        )
        return _ResolvedChapter(
            chapter=plan,
            writer_chapter=plan,
            track=track,
            music_index=None,
        )

    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
    )
    route = [
        chapter(
            index,
            ResolvedTrack(
                track_ref=f"mock:track-{index}",
                canonical_artist=f"Artist {index}",
                canonical_title=f"Track {index}",
            ),
        )
        for index in range(3)
    ]

    bounded = _bound_progressive_resolved_route(
        _normalize_opening_resolved_route(route, opening),
        max_tracks=2,
        max_chapters=2,
    )

    assert [item.track.track_ref for item in bounded if item.track is not None] == [
        "mock:opening",
        "mock:track-0",
    ]
    assert len(bounded) == 2


def test_writer_skips_chapters_without_owned_slots(tmp_path) -> None:
    class TrailingNarrativeLLM(RecordingAssemblyLLM):
        async def structured(
            self, prompt: str, output_type: type[object], **kwargs: object
        ) -> object:
            if output_type is ProgramSkeleton:
                tracks = self._tracks[:2]
                chapters = [
                    ChapterPlan(
                        index=index,
                        track=self._proposal(item),
                        narrative_role=(
                            NarrativeRole.ANCHOR if index == 0 else NarrativeRole.RESOLUTION
                        ),
                        reason="fixture",
                        novelty_distance=item[2],
                        narration_goal="fixture",
                    )
                    for index, item in enumerate(tracks)
                ]
                chapters.extend(
                    [
                        ChapterPlan(
                            index=2,
                            track=None,
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="trailing context",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="fixture",
                        ),
                        ChapterPlan(
                            index=3,
                            track=None,
                            narrative_role=NarrativeRole.RESOLUTION,
                            reason="trailing outro",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="fixture",
                        ),
                    ]
                )
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=chapters,
                    estimated_duration_seconds=900,
                )
            if output_type is RadioScript and not _mock_writer_slot_contexts(prompt):
                raise AssertionError("Writer must not be called for an unowned chapter")
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = TrailingNarrativeLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=2, max_chapters=4)
        )
    )

    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    called_indices = [
        json.loads(call["prompt"].split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0])["index"]
        for call in writer_calls
    ]
    assert called_indices == [1, 3]
    assert result.writer_chapters[2].available_slots == []
    assert result.writer_chapters[2].normalized_blocks == []
    assert any(block.kind is RadioScriptBlockKind.OUTRO for block in result.radio_script.blocks)
    previous_context = writer_calls[-1]["prompt"].split("Previous context:", 1)[1]
    assert previous_context.split("\nNext track metadata:", 1)[0].strip()
    assert all(chapter.slot_contexts for chapter in result.progressive_session.chapters)


def test_assembly_passes_request_limits_to_curator_prompt(tmp_path) -> None:
    llm = RecordingAssemblyLLM()
    assembly = service(tmp_path, llm)

    asyncio.run(
        assembly.assemble(
            LiveEpisodeAssemblyRequest(
                topic="bounded fixture",
                max_tracks=4,
                max_chapters=6,
            )
        )
    )

    curator_calls = [call for call in llm.calls if call["output_type"] is ProgramSkeleton]
    assert len(curator_calls) == 1
    prompt = curator_calls[0]["prompt"]
    assert "Return no more than 6 chapters total" in prompt
    assert "no more than 4 chapters with a TrackProposal" in prompt
    asyncio.run(assembly.aclose())


def test_radio_script_normalization_keeps_episode_anchors_in_their_owners() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.INTRO, "opening", cue="open", evidence="e0"),
                    block(
                        RadioScriptBlockKind.TRACK_INTRO,
                        "track one intro",
                        track_index=1,
                        cue="track-first",
                        evidence="e1",
                    ),
                    block(
                        RadioScriptBlockKind.TRACK_INTRO,
                        "duplicate track one intro",
                        track_index=1,
                        cue="track-duplicate",
                    ),
                    block(
                        RadioScriptBlockKind.TRANSITION,
                        "first gap",
                        track_index=0,
                        cue="gap-first",
                        evidence="e2",
                    ),
                    block(
                        RadioScriptBlockKind.TRANSITION,
                        "duplicate first gap",
                        track_index=0,
                        cue="gap-duplicate",
                    ),
                ]
            ),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.INTRO, "late chapter intro", cue="late"),
                    block(RadioScriptBlockKind.TRACK_INTRO, "duplicate by chapter"),
                    block(RadioScriptBlockKind.TRANSITION, "second gap", cue="gap-second"),
                ]
            ),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.OUTRO, "final outro", cue="outro", evidence="e3"),
                ]
            ),
        ],
        track_count=3,
    )

    assert [item.text for item in script.blocks if item.kind is RadioScriptBlockKind.INTRO] == [
        "opening"
    ]
    track_intros = [item for item in script.blocks if item.kind is RadioScriptBlockKind.TRACK_INTRO]
    assert [(item.track_index, item.text, item.tts_cues, item.evidence_ids) for item in track_intros] == [
        (1, "track one intro", ["track-first"], ["e1"])
    ]
    transitions = [item for item in script.blocks if item.kind is RadioScriptBlockKind.TRANSITION]
    assert [(item.track_index, item.text, item.tts_cues) for item in transitions] == [
        (0, "first gap", ["gap-first"]),
        (1, "second gap", ["gap-second"]),
    ]
    assert [item.text for item in script.blocks if item.kind is RadioScriptBlockKind.OUTRO] == [
        "final outro"
    ]
    assert "late chapter intro" not in script.text


def test_radio_script_normalization_rejects_duplicate_final_outros() -> None:
    with pytest.raises(NarrationPlacementError, match="multiple OUTRO"):
        _assemble_radio_script(
            [
                RadioScript(blocks=[]),
                RadioScript(
                    blocks=[
                        block(RadioScriptBlockKind.OUTRO, "first outro"),
                        block(RadioScriptBlockKind.OUTRO, "second outro"),
                    ]
                ),
            ],
            track_count=1,
            chapter_music_indices=[0, None],
        )


def _resolved_chapter(index: int, music_index: int | None) -> _ResolvedChapter:
    chapter = ChapterPlan(
        index=index,
        track=None,
        narrative_role=NarrativeRole.RESOLUTION,
        reason="fixture",
        novelty_distance=NoveltyDistance.BRIDGE,
        narration_goal="fixture",
    )
    track = (
        ResolvedTrack(
            track_ref=f"mock:{index}",
            canonical_artist="Fixture Artist",
            canonical_title=f"Fixture Track {index}",
        )
        if music_index is not None
        else None
    )
    return _ResolvedChapter(
        chapter=chapter,
        writer_chapter=chapter,
        track=track,
        music_index=music_index,
    )


def _assemble_writer_fixture(
    chapter_music_indices: list[int | None],
    scripts: list[RadioScript],
) -> tuple[RadioScript, list[object]]:
    chapters = [
        _resolved_chapter(index, music_index)
        for index, music_index in enumerate(chapter_music_indices)
    ]
    slot_contexts = _build_narration_slot_contexts(chapters)
    return _assemble_writer_scripts(
        scripts,
        track_count=max(
            (music_index for music_index in chapter_music_indices if music_index is not None),
            default=-1,
        )
        + 1,
        chapter_music_indices=chapter_music_indices,
        slot_contexts=slot_contexts,
    )


def test_final_narrative_slot_requires_exactly_one_outro() -> None:
    with pytest.raises(
        NarrationPlacementError,
        match="final narration slot must return exactly one OUTRO",
    ):
        _assemble_writer_fixture(
            [0, 1, None],
            [RadioScript(blocks=[]), RadioScript(blocks=[]), RadioScript(blocks=[])],
        )


def test_final_slot_canonicalizes_writer_kinds_and_merges() -> None:
    script, _ = _assemble_writer_fixture(
        [0, 1, None],
        [
            RadioScript(blocks=[]),
            RadioScript(blocks=[]),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.TRANSITION, "tail transition"),
                    block(RadioScriptBlockKind.OUTRO, "final outro"),
                ]
            ),
        ],
    )

    assert [item.kind for item in script.blocks] == [RadioScriptBlockKind.OUTRO]
    assert script.blocks[0].text == "tail transition final outro"


def test_final_playable_slot_allows_before_track_and_exactly_one_outro() -> None:
    script, _ = _assemble_writer_fixture(
        [0, 1],
        [
            RadioScript(blocks=[]),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.TRACK_INTRO, "before final track"),
                    block(RadioScriptBlockKind.OUTRO, "final outro"),
                ]
            ),
        ],
    )

    assert [item.kind for item in script.blocks] == [
        RadioScriptBlockKind.TRACK_INTRO,
        RadioScriptBlockKind.OUTRO,
    ]


def test_final_playable_slot_with_one_block_keeps_required_outro() -> None:
    script, _ = _assemble_writer_fixture(
        [0, 1],
        [
            RadioScript(blocks=[]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "final narration")]),
        ],
    )

    assert [item.kind for item in script.blocks] == [RadioScriptBlockKind.OUTRO]


def test_duplicate_before_track_intro_blocks_collapse_into_final_slots() -> None:
    script, _ = _assemble_writer_fixture(
        [0, 1],
        [
            RadioScript(blocks=[]),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.TRACK_INTRO, "first intro"),
                    block(RadioScriptBlockKind.TRACK_INTRO, "duplicate intro"),
                    block(RadioScriptBlockKind.OUTRO, "final outro"),
                ]
            ),
        ],
    )

    assert [item.kind for item in script.blocks] == [
        RadioScriptBlockKind.TRACK_INTRO,
        RadioScriptBlockKind.OUTRO,
    ]
    assert script.blocks[1].text == "duplicate intro final outro"


def test_host_mode_filters_narration_density_after_gap_ownership() -> None:
    full = _build_narration_slot_contexts(
        [
            _resolved_chapter(0, 0),
            _resolved_chapter(1, 1),
            _resolved_chapter(2, 2),
            _resolved_chapter(3, 3),
        ]
    )

    light = _apply_host_mode_to_slot_contexts(full, HostMode.LIGHT)
    none = _apply_host_mode_to_slot_contexts(full, HostMode.NONE)
    kept_light_slots = [
        context.slot_id for contexts in light for context in contexts
    ]

    assert "chapter-1:before-track" in kept_light_slots
    assert "chapter-2:before-track" not in kept_light_slots
    assert "chapter-3:before-track" in kept_light_slots
    assert "chapter-3:after-final" in kept_light_slots
    assert all(not contexts for contexts in none)
    assert sum(len(contexts) for contexts in light) < sum(
        len(contexts) for contexts in full
    )


def test_direct_music_gap_has_one_slot_owner() -> None:
    contexts = _build_narration_slot_contexts(
        [_resolved_chapter(0, 0), _resolved_chapter(1, 1)]
    )

    assert contexts[0] == []
    assert [context.slot_id for context in contexts[1]] == [
        "chapter-1:before-track",
        "chapter-1:after-final",
    ]
    assert contexts[1][0].allowed_block_kinds == [RadioScriptBlockKind.TRACK_INTRO]
    assert contexts[1][1].allowed_block_kinds == [RadioScriptBlockKind.OUTRO]


def test_single_track_episode_keeps_final_outro_slot() -> None:
    contexts = _build_narration_slot_contexts([_resolved_chapter(0, 0)])

    assert [context.allowed_block_kinds for context in contexts[0]] == [
        [RadioScriptBlockKind.OUTRO]
    ]


def test_duplicate_narrative_middle_transitions_collapse_to_one_slot() -> None:
    script, _ = _assemble_writer_fixture(
        [0, None, 1],
        [
            RadioScript(blocks=[]),
            RadioScript(
                blocks=[
                    block(RadioScriptBlockKind.TRANSITION, "middle one"),
                    block(RadioScriptBlockKind.TRANSITION, "middle two"),
                ]
            ),
            RadioScript(blocks=[block(RadioScriptBlockKind.OUTRO, "final outro")]),
        ],
    )

    assert [item.kind for item in script.blocks] == [
        RadioScriptBlockKind.TRANSITION,
        RadioScriptBlockKind.OUTRO,
    ]
    assert script.blocks[0].text == "middle one middle two"


def test_multiple_middle_narrative_chapters_collapse_to_one_physical_gap() -> None:
    contexts = _build_narration_slot_contexts(
        [
            _resolved_chapter(0, 0),
            _resolved_chapter(1, None),
            _resolved_chapter(2, None),
            _resolved_chapter(3, 1),
        ]
    )

    assert [context.slot_id for context in contexts[1]] == [
        "chapter-1:after-previous"
    ]
    assert contexts[2] == []
    assert [context.slot_id for context in contexts[3]] == [
        "chapter-3:after-final"
    ]


def test_multiple_leading_narrative_chapters_collapse_to_one_opening_gap() -> None:
    contexts = _build_narration_slot_contexts(
        [
            _resolved_chapter(0, None),
            _resolved_chapter(1, None),
            _resolved_chapter(2, 0),
            _resolved_chapter(3, 1),
        ]
    )

    assert [context.slot_id for context in contexts[0]] == [
        "chapter-0:after-opening"
    ]
    assert contexts[1] == []
    assert contexts[2] == []
    assert [context.slot_id for context in contexts[3]] == [
        "chapter-3:before-track",
        "chapter-3:after-final",
    ]


def test_assembly_wraps_narration_placement_failure_at_writer_boundary(tmp_path, monkeypatch) -> None:
    assembly = service(tmp_path)

    def fail_slot_derivation(chapters: list[_ResolvedChapter]) -> list[list[object]]:
        raise NarrationPlacementError(
            "physical playback gap has multiple narration owners (fixture)"
        )

    monkeypatch.setattr(
        assembly_module,
        "_build_narration_slot_contexts",
        fail_slot_derivation,
    )

    with pytest.raises(EpisodeAssemblyError, match="physical playback gap") as failure:
        asyncio.run(
            assembly.assemble(
                LiveEpisodeAssemblyRequest(topic="fixture", anchor_tracks=["Neon First Light"])
            )
        )

    assert failure.value.stage == "writer_normalization"
    assert failure.value.reason_code == "narration_slot_derivation_failed"
    assert failure.value.diagnostics == {"narration_failure_boundary": "slot_derivation"}
    assert isinstance(failure.value.__cause__, NarrationPlacementError)


def test_assembly_wraps_writer_slot_normalization_failure_with_safe_reason(tmp_path, monkeypatch) -> None:
    assembly = service(tmp_path)

    def fail_writer_normalization(*args: object, **kwargs: object) -> tuple[object, object]:
        raise NarrationPlacementError("writer slot cardinality failed (fixture)")

    monkeypatch.setattr(assembly_module, "_assemble_writer_scripts", fail_writer_normalization)

    with pytest.raises(EpisodeAssemblyError, match="writer slot cardinality") as failure:
        asyncio.run(
            assembly.assemble(
                LiveEpisodeAssemblyRequest(topic="fixture", anchor_tracks=["Neon First Light"])
            )
        )

    assert failure.value.stage == "writer_normalization"
    assert failure.value.reason_code == "narration_slot_normalization_failed"
    assert failure.value.diagnostics == {
        "narration_failure_boundary": "writer_slot_normalization"
    }
    assert isinstance(failure.value.__cause__, NarrationPlacementError)


def test_only_last_trailing_narrative_chapter_owns_final_tail() -> None:
    chapters = [
        _resolved_chapter(0, 0),
        _resolved_chapter(1, 1),
        _resolved_chapter(2, None),
        _resolved_chapter(3, None),
    ]
    contexts = _build_narration_slot_contexts(chapters)

    assert contexts[2] == []
    assert [context.allowed_block_kinds for context in contexts[3]] == [
        [RadioScriptBlockKind.OUTRO]
    ]

    script, _ = _assemble_writer_scripts(
        [RadioScript(blocks=[]), RadioScript(blocks=[]), RadioScript(blocks=[]), RadioScript(
            blocks=[block(RadioScriptBlockKind.OUTRO, "final outro")]
        )],
        track_count=2,
        chapter_music_indices=[0, 1, None, None],
        slot_contexts=contexts,
    )
    assert [item.kind for item in script.blocks] == [RadioScriptBlockKind.OUTRO]


def test_trackless_chapter_intro_is_not_promoted_to_episode_opening() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(
                blocks=[block(RadioScriptBlockKind.INTRO, "opening")]
            ),
            RadioScript(
                blocks=[block(RadioScriptBlockKind.INTRO, "trackless story beat")]
            ),
        ],
        track_count=1,
        chapter_music_indices=[0, None],
    )

    assert [item.kind for item in script.blocks] == [
        RadioScriptBlockKind.INTRO,
        RadioScriptBlockKind.TRANSITION,
    ]
    assert script.blocks[1].text == "trackless story beat"
    # With one playable track, a later narration-only INTRO belongs after the
    # final track rather than remaining unanchored or moving into the opening.
    assert script.blocks[1].track_index == 0


def test_registry_closes_each_unique_provider_once() -> None:
    class ClosableProvider:
        def __init__(self) -> None:
            self.close_calls = 0

        async def search(self, query: str, *, limit: int = 5) -> list[Any]:
            del query, limit
            return []

        async def resolve_track(self, track_ref: str) -> Any:
            del track_ref
            raise AssertionError("not used")

        async def get_playback_asset(self, resolved_track: Any) -> Any:
            del resolved_track
            raise AssertionError("not used")

        async def aclose(self) -> None:
            self.close_calls += 1

    provider = ClosableProvider()
    registry = MusicProviderRegistry({"one": provider, "alias": provider})

    asyncio.run(registry.aclose())

    assert provider.close_calls == 1


def test_request_requires_two_tracks_and_mock_repeats_deterministically(tmp_path) -> None:
    with pytest.raises(ValidationError):
        LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=1)

    assembly = service(tmp_path)
    first = asyncio.run(assembly.assemble(LiveEpisodeAssemblyRequest(topic="fixture")))
    second = asyncio.run(assembly.assemble(LiveEpisodeAssemblyRequest(topic="fixture")))

    first_blocks = [
        (item.kind, item.text, item.track_index, item.tts_cues)
        for item in first.radio_script.blocks
    ]
    second_blocks = [
        (item.kind, item.text, item.track_index, item.tts_cues)
        for item in second.radio_script.blocks
    ]
    assert first_blocks == second_blocks
    assert [item.canonical_title for item in first.resolved_tracks] == [
        item.canonical_title for item in second.resolved_tracks
    ]


def test_probe_asset_url_redacts_external_tokens() -> None:
    from scripts.live_episode_probe import _safe_asset_url

    assert _safe_asset_url("/api/assets/audio/abc.mp3?token=local") == "/api/assets/audio/abc.mp3?token=local"
    assert _safe_asset_url("https://cdn.example.test/audio.mp3?token=secret") == (
        "https://cdn.example.test/[external-redacted]"
    )


def test_unresolved_proposal_is_reported_but_narrative_is_still_written(tmp_path) -> None:
    class MixedLLM(RecordingAssemblyLLM):
        async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
            if output_type is ProgramSkeleton:
                known = self._tracks[0]
                unknown = ("Event Listing", "Festival doors 8-9-2026", NoveltyDistance.CLOSE)
                chapters = [
                    ChapterPlan(
                        index=index,
                        track=self._proposal(item),
                        narrative_role=NarrativeRole.ANCHOR,
                        reason="fixture",
                        novelty_distance=item[2],
                        narration_goal="fixture",
                    )
                    for index, item in enumerate((known, unknown, self._tracks[1]))
                ]
                return ProgramSkeleton(thesis="fixture", chapters=chapters, estimated_duration_seconds=900)
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = MixedLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=3))
    )

    assert len(result.resolved_tracks) == 2
    assert [track.canonical_title for track in result.resolved_tracks] == [
        "Neon First Light",
        "Midnight Transfer",
    ]
    assert len(result.unresolved_proposals) == 1
    assert result.skeleton.chapters[1].track is not None
    assert result.skeleton.chapters[1].track.artist == "Event Listing"
    assert result.unresolved_proposals[0].proposal.artist == "Event Listing"
    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    assert len(writer_calls) == 2
    unresolved_writer_chapter = json.loads(
        writer_calls[0]["prompt"].split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0]
    )
    assert unresolved_writer_chapter["track"] is None
    assert any(
        segment.narration_text == "现在进入第 2 首。"
        for segment in result.playable_episode.segments
    )
    assert any(
        item.kind is RadioScriptBlockKind.OUTRO for item in result.radio_script.blocks
    )


def test_explicit_track_index_for_trackless_chapter_has_no_music_anchor() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(
                blocks=[
                    block(
                        RadioScriptBlockKind.TRACK_INTRO,
                        "opening context",
                        track_index=0,
                    )
                ]
            ),
            RadioScript(
                blocks=[
                    block(
                        RadioScriptBlockKind.TRACK_INTRO,
                        "narrative context",
                        track_index=1,
                    )
                ]
            ),
            RadioScript(blocks=[]),
        ],
        track_count=2,
        chapter_music_indices=[0, None, 1],
    )

    narrative = next(item for item in script.blocks if item.text == "narrative context")
    assert narrative.track_index is None
    assert narrative.kind is RadioScriptBlockKind.TRANSITION


def test_two_consecutive_narrative_chapters_share_one_music_gap() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(blocks=[]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "Narration A")]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "Narration B")]),
            RadioScript(blocks=[]),
        ],
        track_count=2,
        chapter_music_indices=[0, None, None, 1],
    )
    tracks = [
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        ResolvedTrack(
            track_ref="mock:bridge",
            canonical_artist="Signal Garden",
            canonical_title="Midnight Transfer",
        ),
    ]

    episode = asyncio.run(EpisodeComposer(MockMusicProvider()).compose(tracks, script))

    assert [segment.narration_text or segment.track_ref for segment in episode.segments] == [
        "mock:opening",
        "Narration A",
        "Narration B",
        "mock:bridge",
    ]


def test_final_narrative_chapter_anchors_after_final_music_track() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(blocks=[]),
            RadioScript(blocks=[]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "Final beat")]),
        ],
        track_count=2,
        chapter_music_indices=[0, 1, None],
    )
    tracks = [
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        ResolvedTrack(
            track_ref="mock:bridge",
            canonical_artist="Signal Garden",
            canonical_title="Midnight Transfer",
        ),
    ]

    episode = asyncio.run(EpisodeComposer(MockMusicProvider()).compose(tracks, script))

    assert [segment.narration_text or segment.track_ref for segment in episode.segments] == [
        "mock:opening",
        "mock:bridge",
        "Final beat",
    ]


def test_final_narrative_chapters_preserve_order_after_final_music_track() -> None:
    script = _assemble_radio_script(
        [
            RadioScript(blocks=[]),
            RadioScript(blocks=[]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "Ending A")]),
            RadioScript(blocks=[block(RadioScriptBlockKind.TRANSITION, "Ending B")]),
        ],
        track_count=2,
        chapter_music_indices=[0, 1, None, None],
    )
    tracks = [
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        ResolvedTrack(
            track_ref="mock:bridge",
            canonical_artist="Signal Garden",
            canonical_title="Midnight Transfer",
        ),
    ]

    episode = asyncio.run(EpisodeComposer(MockMusicProvider()).compose(tracks, script))

    assert [segment.narration_text or segment.track_ref for segment in episode.segments] == [
        "mock:opening",
        "mock:bridge",
        "Ending A",
        "Ending B",
    ]


def test_max_tracks_limits_music_but_preserves_narrative_only_chapters(tmp_path) -> None:
    class MusicLimitLLM(RecordingAssemblyLLM):
        async def structured(
            self, prompt: str, output_type: type[object], **kwargs: object
        ) -> object:
            if output_type is ProgramSkeleton:
                chapters: list[ChapterPlan] = []
                for index, item in enumerate(
                    [
                        self._tracks[0],
                        None,
                        self._tracks[1],
                        None,
                        self._tracks[2],
                        self._tracks[3],
                    ]
                ):
                    chapters.append(
                        ChapterPlan(
                            index=index,
                            track=self._proposal(item) if item is not None else None,
                            narrative_role=NarrativeRole.BRIDGE,
                            reason=f"beat {index}",
                            novelty_distance=(
                                NoveltyDistance.VERY_CLOSE
                                if index == 0
                                else NoveltyDistance.CLOSE
                                if index <= 2
                                else NoveltyDistance.BRIDGE
                                if index <= 4
                                else NoveltyDistance.DISCOVERY
                            ),
                            narration_goal=f"explain beat {index}",
                        )
                    )
                return ProgramSkeleton(
                    thesis="four music beats and two narrative-only beats",
                    chapters=chapters,
                    estimated_duration_seconds=900,
                )
            if output_type is RadioScript:
                self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                return RadioScript(blocks=slot_blocks(prompt, "narrative beat "))
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = MusicLimitLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=4)
        )
    )

    assert len(result.resolved_tracks) == 4
    assert [chapter.index for chapter in result.skeleton.chapters] == [0, 1, 2, 3, 4, 5]
    assert len([call for call in llm.calls if call["output_type"] is RadioScript]) == 3
    assert {"narrative beat 1", "narrative beat 3"}.issubset(
        {segment.narration_text for segment in result.playable_episode.segments}
    )


def test_narrative_only_chapter_survives_writer_and_assembly(tmp_path) -> None:
    class NarrativeOnlyLLM(RecordingAssemblyLLM):
        async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
            if output_type is ProgramSkeleton:
                self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                first = self._proposal(self._tracks[0])
                last = self._proposal(self._tracks[1])
                return ProgramSkeleton(
                    thesis="A story with a beat between songs.",
                    estimated_duration_seconds=900,
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=first,
                            narrative_role=NarrativeRole.ANCHOR,
                            reason="open",
                            novelty_distance=NoveltyDistance.VERY_CLOSE,
                            narration_goal="open",
                        ),
                        ChapterPlan(
                            index=1,
                            track=None,
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="explain the context",
                            novelty_distance=NoveltyDistance.CLOSE,
                            narration_goal="tell a context beat",
                        ),
                        ChapterPlan(
                            index=2,
                            track=last,
                            narrative_role=NarrativeRole.RESOLUTION,
                            reason="resolve",
                            novelty_distance=NoveltyDistance.BRIDGE,
                            narration_goal="close",
                        ),
                    ],
                )
            if output_type is RadioScript:
                index = _mock_writer_chapter_index(prompt)
                if index == 1:
                    self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                    return RadioScript(
                        blocks=[
                            block(
                                RadioScriptBlockKind.TRANSITION,
                                "A narrative beat without a song.",
                            )
                        ]
                    )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = NarrativeOnlyLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=3)
        )
    )

    assert len([call for call in llm.calls if call["output_type"] is RadioScript]) == 2
    assert [chapter.track is None for chapter in result.skeleton.chapters] == [False, True, False]
    assert len(result.resolved_tracks) == 2
    assert any(
        segment.narration_text == "A narrative beat without a song."
        for segment in result.playable_episode.segments
    )


def test_writer_uses_resolved_narration_slots_for_sparse_playback_sequence(tmp_path) -> None:
    class SlotFixtureLLM(RecordingAssemblyLLM):
        async def structured(
            self, prompt: str, output_type: type[object], **kwargs: object
        ) -> object:
            if output_type is ProgramSkeleton:
                known = [self._tracks[0], self._tracks[1], self._tracks[2]]
                unknown = ("Event Listing", "STAY piano cover", NoveltyDistance.CLOSE)
                chapters = [
                    ChapterPlan(
                        index=index,
                        track=self._proposal(item) if item is not None else None,
                        narrative_role=(
                            NarrativeRole.ANCHOR
                            if index == 0
                            else NarrativeRole.RESOLUTION
                            if index == 4
                            else NarrativeRole.BRIDGE
                        ),
                        reason=f"beat {index}",
                        novelty_distance=(
                            item[2] if item is not None else NoveltyDistance.CLOSE
                        ),
                        narration_goal=f"explain beat {index}",
                    )
                    for index, item in enumerate(
                        (known[0], known[1], unknown, known[2], None)
                    )
                ]
                chapters[-1] = chapters[-1].model_copy(
                    update={"index": 6, "novelty_distance": NoveltyDistance.DISCOVERY}
                )
                # Deliberately sparse Curator identity; application code must
                # normalize it before returning the skeleton and calling Writer.
                return ProgramSkeleton(
                    thesis="resolved tracks with a narrative-only middle and ending",
                    chapters=chapters,
                    estimated_duration_seconds=900,
                )
            if output_type is RadioScript:
                self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                return RadioScript(blocks=slot_blocks(prompt, "slot "))
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = SlotFixtureLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=4)
        )
    )

    assert [chapter.index for chapter in result.skeleton.chapters] == [0, 1, 2, 3, 4]
    assert result.skeleton.chapters[2].track is not None
    assert result.unresolved_proposals[0].chapter_index == 2
    assert [track.canonical_title for track in result.resolved_tracks] == [
        "Neon First Light",
        "Midnight Transfer",
        "Daybreak in Stereo",
    ]
    assert len([call for call in llm.calls if call["output_type"] is RadioScript]) == 3

    middle_prompt = next(
        call["prompt"]
        for call in llm.calls
        if call["output_type"] is RadioScript and '"index":2' in call["prompt"]
    )
    assert '"track":null' in middle_prompt
    assert "Midnight Transfer" in middle_prompt
    assert "Daybreak in Stereo" in middle_prompt
    final_prompt = next(
        call["prompt"]
        for call in llm.calls
        if call["output_type"] is RadioScript and '"index":4' in call["prompt"]
    )
    assert "Daybreak in Stereo" in final_prompt
    assert '"upcoming_track": null' in final_prompt

    assert len(result.writer_chapters) == 5
    middle_context = result.writer_chapters[2]
    assert len(middle_context.available_slots) == 1
    middle_slot = middle_context.available_slots[0]
    assert middle_slot.chapter_track is None
    assert middle_slot.just_played_track is not None
    assert middle_slot.just_played_track.canonical_title == "Midnight Transfer"
    assert middle_slot.upcoming_track is not None
    assert middle_slot.upcoming_track.canonical_title == "Daybreak in Stereo"
    final_context = result.writer_chapters[4]
    final_slot = final_context.available_slots[0]
    assert final_slot.just_played_track is not None
    assert final_slot.just_played_track.canonical_title == "Daybreak in Stereo"
    assert final_slot.upcoming_track is None
    assert sum(len(item.parsed_blocks) for item in result.writer_chapters) == 3
    assert sum(len(item.normalized_blocks) for item in result.writer_chapters) == 3
    assert sum(segment.kind.value == "NARRATION" for segment in result.playable_episode.segments) == 3
    assert [segment.narration_text for segment in result.playable_episode.segments if segment.narration_text] == [
        "slot 1",
        "slot 2",
        "slot 4",
    ]


def test_writer_slots_match_each_final_playback_adjacency_and_preserve_blocks(tmp_path) -> None:
    class AdjacencyLLM(RecordingAssemblyLLM):
        async def structured(
            self, prompt: str, output_type: type[object], **kwargs: object
        ) -> object:
            if output_type is ProgramSkeleton:
                known = [self._tracks[0], self._tracks[1], self._tracks[2]]
                unknown = ("Event Listing", "unresolved beat", NoveltyDistance.CLOSE)
                chapters = [
                    ChapterPlan(
                        index=index,
                        track=self._proposal(item) if item is not None else None,
                        narrative_role=(
                            NarrativeRole.ANCHOR if index == 0 else NarrativeRole.RESOLUTION
                        ),
                        reason=f"beat {index}",
                        novelty_distance=(
                            item[2] if item is not None else NoveltyDistance.BRIDGE
                        ),
                        narration_goal=f"explain beat {index}",
                    )
                    for index, item in enumerate((known[0], known[1], unknown, known[2]))
                ]
                return ProgramSkeleton(thesis="adjacency", chapters=chapters, estimated_duration_seconds=900)
            if output_type is RadioScript:
                chapter = json.loads(prompt.split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0])
                self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                index = chapter["index"]
                if index == 0:
                    blocks = [block(RadioScriptBlockKind.INTRO, "after A")]
                elif index == 1:
                    blocks = [block(RadioScriptBlockKind.TRACK_INTRO, "before B")]
                elif index == 2:
                    blocks = [block(RadioScriptBlockKind.TRANSITION, "unresolved middle")]
                else:
                    blocks = [block(RadioScriptBlockKind.OUTRO, "after C")]
                return RadioScript(blocks=blocks, intended_duration_seconds=6)
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = AdjacencyLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=4)
        )
    )

    diagnostics = result.writer_chapters
    middle_prompt = next(
        call["prompt"]
        for call in llm.calls
        if call["output_type"] is RadioScript and '"index":1' in call["prompt"]
    )
    assert 'chapter-1:before-track' in middle_prompt
    assert 'chapter-1:after-track' not in middle_prompt
    assert diagnostics[0].available_slots == []

    middle = diagnostics[1]
    before_b = middle.normalized_slot_contexts[0]
    assert before_b.just_played_track is not None
    assert before_b.just_played_track.canonical_title == "Neon First Light"
    assert before_b.upcoming_track is not None
    assert before_b.upcoming_track.canonical_title == "Midnight Transfer"

    unresolved = diagnostics[2].normalized_slot_contexts[0]
    assert unresolved.just_played_track is not None
    assert unresolved.just_played_track.canonical_title == "Midnight Transfer"
    assert unresolved.upcoming_track is not None
    assert unresolved.upcoming_track.canonical_title == "Daybreak in Stereo"

    final = diagnostics[3].normalized_slot_contexts[0]
    assert final.just_played_track is not None
    assert final.just_played_track.canonical_title == "Daybreak in Stereo"
    assert final.upcoming_track is None
    assert result.radio_script.blocks[-1].kind is RadioScriptBlockKind.OUTRO

    narration = [
        segment.narration_text
        for segment in result.playable_episode.segments
        if segment.narration_text is not None
    ]
    assert narration == ["before B", "unresolved middle", "after C"]
    assert len(narration) == sum(len(item.parsed_blocks) for item in diagnostics)


def test_leading_narrative_slot_uses_opening_music_as_just_played(tmp_path) -> None:
    class LeadingNarrativeLLM(RecordingAssemblyLLM):
        async def structured(
            self, prompt: str, output_type: type[object], **kwargs: object
        ) -> object:
            if output_type is ProgramSkeleton:
                return ProgramSkeleton(
                    thesis="opening narrative",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=None,
                            narrative_role=NarrativeRole.BRIDGE,
                            reason="opening setup",
                            narration_goal="set the scene",
                        ),
                        ChapterPlan(
                            index=1,
                            track=self._proposal(self._tracks[0]),
                            narrative_role=NarrativeRole.ANCHOR,
                            reason="first song",
                            narration_goal="introduce the song",
                        ),
                        ChapterPlan(
                            index=2,
                            track=self._proposal(self._tracks[1]),
                            narrative_role=NarrativeRole.RESOLUTION,
                            reason="close",
                            narration_goal="close the route",
                        ),
                    ],
                    estimated_duration_seconds=900,
                )
            if output_type is RadioScript:
                chapter = json.loads(prompt.split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0])
                if chapter["track"] is None:
                    kind, text = RadioScriptBlockKind.INTRO, "lead"
                elif chapter["index"] == 1:
                    return RadioScript(blocks=[], intended_duration_seconds=1)
                else:
                    kind, text = RadioScriptBlockKind.OUTRO, "outro"
                return RadioScript(blocks=[block(kind, text)], intended_duration_seconds=3)
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = LeadingNarrativeLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=2)
        )
    )

    opening = result.writer_chapters[0].normalized_slot_contexts[0]
    assert opening.just_played_track is not None
    assert opening.just_played_track.canonical_title == "Neon First Light"
    assert opening.upcoming_track is not None
    assert opening.upcoming_track.canonical_title == "Midnight Transfer"
    assert result.playable_episode.segments[0].track_ref == result.resolved_tracks[0].track_ref
    assert result.playable_episode.segments[1].narration_text == "lead"


def test_assembly_preserves_auto_language_and_duration_budget(tmp_path) -> None:
    llm = RecordingAssemblyLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(
                topic="藤井风的音乐背景",
                anchor_tracks=["Neon First Light"],
                desired_duration_seconds=600,
                output_language=OutputLanguage.AUTO,
            )
        )
    )
    writer_prompts = [call["prompt"] for call in llm.calls if call["output_type"] is RadioScript]
    assert writer_prompts
    assert all("output language zh-CN" in prompt for prompt in writer_prompts)
    writer_budgets = [
        budget
        for budget, chapter in zip(
            result.timing_plan.chapter_budgets,
            result.writer_chapters,
            strict=True,
        )
        if chapter.available_slots
    ]
    assert all(
        f"Target narration duration seconds: {budget.target_narration_seconds}" in prompt
        for prompt, budget in zip(writer_prompts, writer_budgets, strict=True)
    )
    assert result.duration_summary.narration_seconds >= 0


def test_assembly_explicit_english_overrides_chinese_topic(tmp_path) -> None:
    llm = RecordingAssemblyLLM()
    asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(
                topic="藤井风的音乐背景",
                output_language=OutputLanguage.EN_US,
            )
        )
    )
    writer_prompts = [call["prompt"] for call in llm.calls if call["output_type"] is RadioScript]
    assert writer_prompts
    assert all("output language en-US" in prompt for prompt in writer_prompts)


def test_middle_unresolved_chapter_keeps_narrative_writer_order(tmp_path) -> None:
    class ExplicitIndexLLM(RecordingAssemblyLLM):
        async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
            self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
            if output_type is ProgramSkeleton:
                known = self._tracks[0]
                unknown = ("Event Listing", "Festival doors 8-9-2026", NoveltyDistance.CLOSE)
                surviving = self._tracks[2]
                chapters = [
                    ChapterPlan(
                        index=index,
                        track=self._proposal(item),
                        narrative_role=NarrativeRole.ANCHOR,
                        reason="fixture",
                        novelty_distance=item[2],
                        connection_from_previous_track=(
                            EditorialConnection(
                                relation_type=EditorialRelationType.SCENE_OR_LINEAGE,
                                rationale="fixture selected-route connection",
                            )
                            if index > 0
                            else None
                        ),
                        narration_goal="fixture",
                    )
                    for index, item in enumerate((known, unknown, surviving))
                ]
                return ProgramSkeleton(
                    thesis="fixture", chapters=chapters, estimated_duration_seconds=900
                )
            if output_type is RadioScript:
                payload = json.loads(prompt.split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0])
                writer_index = payload["index"]
                if payload["track"] is None:
                    kind = RadioScriptBlockKind.TRANSITION
                elif writer_index == 0:
                    kind = RadioScriptBlockKind.INTRO
                elif writer_index == 2:
                    kind = RadioScriptBlockKind.OUTRO
                else:
                    kind = RadioScriptBlockKind.TRACK_INTRO
                return RadioScript(
                    blocks=[
                        RadioScriptBlock(
                            kind=kind,
                            text=f"writer track {writer_index}",
                            duration_seconds=3,
                            track_index=writer_index,
                        )
                    ]
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = ExplicitIndexLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=3))
    )

    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    assert '"index":1' in writer_calls[0]["prompt"]
    assert '"index":2' in writer_calls[1]["prompt"]
    assert [chapter.index for chapter in result.skeleton.chapters] == [0, 1, 2]
    assert [
        chapter.connection_from_previous_track for chapter in result.writer_chapters
    ] == [None, None, None]
    assert [track.canonical_title for track in result.resolved_tracks] == [
        "Neon First Light",
        "Daybreak in Stereo",
    ]

    second_track_ref = result.resolved_tracks[1].track_ref
    second_music_index = next(
        index
        for index, segment in enumerate(result.playable_episode.segments)
        if segment.track_ref == second_track_ref
    )
    assert result.playable_episode.segments[second_music_index - 1].narration_text == "writer track 1"


def test_fewer_than_two_resolved_tracks_is_a_typed_assembly_failure(tmp_path) -> None:
    class OneTrackLLM(RecordingAssemblyLLM):
        async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
            if output_type is ProgramSkeleton:
                item = self._tracks[0]
                return ProgramSkeleton(
                    thesis="fixture",
                    chapters=[
                        ChapterPlan(
                            index=0,
                            track=self._proposal(item),
                            narrative_role=NarrativeRole.ANCHOR,
                            reason="fixture",
                            novelty_distance=NoveltyDistance.VERY_CLOSE,
                            narration_goal="fixture",
                        )
                    ],
                    estimated_duration_seconds=900,
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(EpisodeAssemblyError, match="at least two resolved tracks") as failure:
        asyncio.run(service(tmp_path, OneTrackLLM()).assemble(LiveEpisodeAssemblyRequest(topic="fixture")))
    assert failure.value.stage == "resolution"
    assert failure.value.reason_code == "insufficient_resolved_tracks"
    assert failure.value.diagnostics == {
        "resolved_track_count": 1,
        "unresolved_track_count": 0,
        "required_resolved_track_count": 2,
    }


def test_live_factory_requires_a_real_music_provider(monkeypatch) -> None:
    from wavecast.providers.config import ProviderSettings
    from wavecast.providers.errors import ProviderConfigurationError

    with pytest.raises(ProviderConfigurationError, match="real music provider"):
        create_episode_assembly_service(ProviderSettings(mode="live"))

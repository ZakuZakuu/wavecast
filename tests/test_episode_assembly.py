import asyncio

import pytest
from wavecast.assembly import (
    EpisodeAssemblyError,
    LiveEpisodeAssemblyRequest,
    LiveEpisodeAssemblyService,
    MockEpisodeAssemblyLLM,
    create_episode_assembly_service,
)
from wavecast.composer import EpisodeComposer
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlockKind,
)
from wavecast.intelligence.research import BackgroundResearchService, FastResearchService
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
from wavecast.providers.fakes import FakeSearchProvider, MockMusicProvider, MockTTSProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.usage import UsageLedger
from wavecast.storage.assets import LocalObjectStorageProvider


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
    assert len(writer_calls) == 4
    assert "Next track metadata: Signal Garden — Midnight Transfer" in writer_calls[0]["prompt"]
    assert "Previous context:" in writer_calls[1]["prompt"]
    assert sum(block.kind is RadioScriptBlockKind.INTRO for block in result.radio_script.blocks) == 1
    assert sum(block.kind is RadioScriptBlockKind.OUTRO for block in result.radio_script.blocks) == 1
    assert all(
        not (
            block.kind is RadioScriptBlockKind.TRANSITION
            and block.track_index == len(result.resolved_tracks) - 1
        )
        for block in result.radio_script.blocks
    )


def test_unresolved_proposal_is_reported_and_skipped_before_writing(tmp_path) -> None:
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
    assert len(result.unresolved_proposals) == 1
    assert result.unresolved_proposals[0].proposal.artist == "Event Listing"
    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    assert len(writer_calls) == 2


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


def test_live_factory_requires_a_real_music_provider(monkeypatch) -> None:
    from wavecast.providers.config import ProviderSettings
    from wavecast.providers.errors import ProviderConfigurationError

    with pytest.raises(ProviderConfigurationError, match="real music provider"):
        create_episode_assembly_service(ProviderSettings(mode="live"))

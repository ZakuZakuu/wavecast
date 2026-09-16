import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError
from wavecast.assembly import (
    EpisodeAssemblyError,
    LiveEpisodeAssemblyRequest,
    LiveEpisodeAssemblyService,
    MockEpisodeAssemblyLLM,
    _assemble_radio_script,
    _mock_writer_chapter_index,
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
    OutputLanguage,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
)
from wavecast.intelligence.research import BackgroundResearchService, FastResearchService
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
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
                    block(RadioScriptBlockKind.OUTRO, "duplicate outro", cue="outro-duplicate"),
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
    assert script.blocks[1].track_index is None


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
    assert len(result.unresolved_proposals) == 1
    assert result.skeleton.chapters[1].track is not None
    assert result.skeleton.chapters[1].track.artist == "Event Listing"
    assert result.unresolved_proposals[0].proposal.artist == "Event Listing"
    writer_calls = [call for call in llm.calls if call["output_type"] is RadioScript]
    assert len(writer_calls) == 3
    unresolved_writer_chapter = json.loads(
        writer_calls[1]["prompt"].split("Chapter: ", 1)[1].split("\nEvidence:", 1)[0]
    )
    assert unresolved_writer_chapter["track"] is None
    assert any(
        segment.narration_text == "现在进入第 2 首。"
        for segment in result.playable_episode.segments
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
                index = _mock_writer_chapter_index(prompt)
                self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
                return RadioScript(
                    blocks=[
                        block(
                            RadioScriptBlockKind.TRANSITION,
                            f"narrative beat {index}",
                        )
                    ]
                )
            return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    llm = MusicLimitLLM()
    result = asyncio.run(
        service(tmp_path, llm).assemble(
            LiveEpisodeAssemblyRequest(topic="fixture", max_tracks=4)
        )
    )

    assert len(result.resolved_tracks) == 4
    assert [chapter.index for chapter in result.skeleton.chapters] == [0, 1, 2, 3, 4, 5]
    assert len([call for call in llm.calls if call["output_type"] is RadioScript]) == 6
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

    assert len([call for call in llm.calls if call["output_type"] is RadioScript]) == 3
    assert [chapter.track is None for chapter in result.skeleton.chapters] == [False, True, False]
    assert len(result.resolved_tracks) == 2
    assert any(
        segment.narration_text == "A narrative beat without a song."
        for segment in result.playable_episode.segments
    )


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
    assert all("Target narration duration seconds: 22" in prompt for prompt in writer_prompts)
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
                return RadioScript(
                    blocks=[
                        RadioScriptBlock(
                            kind=RadioScriptBlockKind.TRACK_INTRO,
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
    assert '"index":1' in writer_calls[1]["prompt"]
    assert '"index":2' not in writer_calls[1]["prompt"]
    assert [chapter.index for chapter in result.skeleton.chapters] == [0, 1, 2]
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
    assert result.playable_episode.segments[second_music_index - 1].narration_text == "writer track 2"


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

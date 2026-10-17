"""The researched two-host passage inside live authoring, voicing and the real HLS render.

Everything is offline: the model answers are the fixed ones in ``tests/dialogue_fixtures.py``,
the audio is the credential-free fake (silent WAV of a fixed length), and the render is the
real program-render endpoint with the real arrangement and ffmpeg path.  What this does not
show: how a real model words a passage, or how the real Doubao service behaves (ADR 0027).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from wavecast.assembly import StagedProgressiveChapterGenerator, create_episode_assembly_service
from wavecast.composer import EpisodeComposer
from wavecast.intelligence.dialogue_budget import story_slot_ids
from wavecast.intelligence.dialogue_pipeline import DialoguePipeline
from wavecast.intelligence.dialogue_writer import DialogueWriter
from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrationSlotContext,
    NarrationSlotPlacement,
    NarrativeRole,
    OutputLanguage,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResearchBundle,
    ResolvedTrack,
)
from wavecast.intelligence.story_material import StoryMaterialService, verify_material
from wavecast.intelligence.track_research import TrackResearch
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueDraft, DraftTurn
from wavecast.models.episode import (
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.models.story_usage import StoryUseState
from wavecast.orchestration import EpisodeOrchestrator, InlineGenerationScheduler
from wavecast.orchestration.dialogue_runtime import DialogueRuntime, block_id_for, story_id_for
from wavecast.orchestration.dialogue_timeline import DialogueSeamService
from wavecast.orchestration.episode import InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.orchestration.staged import ProgressiveAssemblyChapter, ProgressiveAssemblySession
from wavecast.providers.config import ProviderSettings
from wavecast.providers.dialogue_speech import MockDialogueSpeechProvider
from wavecast.providers.dialogue_voicing import build_dialogue_voicing
from wavecast.providers.doubao_podcast import DoubaoPodcastSpeechProvider
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.fakes import MockMusicProvider, MockTTSProvider
from wavecast.providers.usage import UsageLedger
from wavecast.stations import StationId
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore
from wavecast.storage.story_usage import StoryUsageStore
from wavecast.timing import build_program_timing_plan

import services.api.main as api_module
from tests.dialogue_fixtures import (
    TRACK_REF,
    ScriptedLLM,
    clean_draft,
    evidence,
    material_draft,
)
from tests.test_program_stream_api import EventLoopRejectingEpisodeRepository, _wav_bytes

EPISODE_ID = "dialogue-runtime-episode"
TRACK = ResolvedTrack(track_ref=TRACK_REF, canonical_artist="方大同", canonical_title="爱爱爱")
OPENING = ResolvedTrack(track_ref="mock:opening", canonical_artist="Opening Artist", canonical_title="Opening Track")
FIRST_SLOT, SECOND_SLOT = "chapter-2:before-track", "chapter-3:before-track"


def _seed_choosing(slot: str, other: str, station: StationId = StationId.PORTRAIT) -> str:
    return next(
        seed for seed in (f"seed-{n}" for n in range(500)) if story_slot_ids(station, [slot, other], seed) == [slot]
    )


def _slot(slot_id: str, chapter_index: int, **changes: Any) -> NarrationSlotContext:
    base: dict[str, Any] = dict(
        slot_id=slot_id,
        chapter_index=chapter_index,
        placement=NarrationSlotPlacement.BEFORE_TRACK,
        allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
        chapter_track=TRACK,
        just_played_track=OPENING,
        upcoming_track=TRACK,
    )
    return NarrationSlotContext(**{**base, **changes})


def _session(station: StationId | None = StationId.PORTRAIT, first_slot: NarrationSlotContext | None = None) -> ProgressiveAssemblySession:
    plan = ChapterPlan(index=0, track=None, narrative_role=NarrativeRole.BRIDGE, reason="x", narration_goal="x")
    chapters = [
        ProgressiveAssemblyChapter(
            chapter_id=chapter_id,
            chapter=plan.model_copy(update={"evidence_ids": ["E1", "E2", "E3", "E4"]}),
            resolved_track=TRACK,
            slot_contexts=[slot],
            target_narration_seconds=40,
        )
        for chapter_id, slot in (
            ("chapter-2", first_slot or _slot(FIRST_SLOT, 1)),
            ("chapter-3", _slot(SECOND_SLOT, 2)),
        )
    ]
    return ProgressiveAssemblySession(
        topic="方大同",
        desired_duration_seconds=900,
        max_tracks=3,
        max_chapters=3,
        output_language=OutputLanguage.ZH_CN,
        opening_track_ref="mock:opening",
        station=station,
        fast_plan=FastStartPlan(
            anchor_understanding=["opening"],
            immediate_taste_hypotheses=[],
            next_candidates=[],
            first_narration=NarrationScript(text="Start here.", intended_duration_seconds=1),
        ),
        research=ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]),
        skeleton=ProgramSkeleton(thesis="x", chapters=[plan], estimated_duration_seconds=900),
        chapters=chapters,
        timing_plan=build_program_timing_plan(
            desired_total_seconds=900,
            target_narration_ratio=0.15,
            resolved_music_seconds=180,
            chapter_slot_counts=[1, 1],
        ),
    )


def _episode(session: ProgressiveAssemblySession, *, seed: str, music_seconds: int = 2) -> LiveEpisode:
    return LiveEpisode(
        id=EPISODE_ID,
        seed_id=seed,
        title="Dialogue runtime",
        topic="方大同",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=900,
        progressive_session=session,
        current_segment_id="opening",
        last_activity_at=datetime.now(UTC),
        last_heartbeat_at=datetime.now(UTC),
        segments=[
            MusicSegment(
                id="opening",
                chapter_id="chapter-1",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=music_seconds,
                actual_duration_seconds=music_seconds,
                track_ref="mock:opening",
                audio_source_url="/api/assets/audio/music-a.wav",
                title="Opening Track",
                artist="Opening Artist",
            ),
            NarrationSegment(
                id="chapter-2:narration:pending",
                chapter_id="chapter-2",
                order=1,
                state=SegmentState.PLANNED,
                planned_duration_seconds=40,
                title="Pending host bridge",
            ),
            MusicSegment(
                id="chapter-2:music:0",
                chapter_id="chapter-2",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=music_seconds,
                actual_duration_seconds=music_seconds,
                track_ref=TRACK_REF,
                audio_source_url="/api/assets/audio/music-b.wav",
                title="爱爱爱",
                artist="方大同",
            ),
        ],
    )


class _Researcher:
    async def prepare(self, **kwargs: object) -> TrackResearch:
        return TrackResearch(evidence=evidence(), evidence_ids=["E1", "E2", "E3", "E4"], points=[])


class _Writer:
    """The one-voice Writer the dialogue path must leave alone."""

    def __init__(self) -> None:
        self.calls = 0

    async def write(self, *args: object, **kwargs: object) -> RadioScript:
        self.calls += 1
        return RadioScript(
            blocks=[RadioScriptBlock(kind=RadioScriptBlockKind.TRACK_INTRO, text="一个人说的下一首。", duration_seconds=5)],
            intended_duration_seconds=5,
        )


def _material_for_runtime() -> Any:
    story = story_id_for(TRACK_REF)
    material = verify_material(material_draft(), evidence(), story_id=story, recording_refs=[TRACK_REF])
    assert material is not None
    return material


def _retag(draft: Any) -> Any:
    """The shared fixture cites facts as ``fdt-Fn``; the runtime names its story after the song."""
    story = story_id_for(TRACK_REF)
    text = draft.model_dump_json().replace("fdt-", f"{story}-")
    return type(draft).model_validate_json(text)


class _HookedLLM(ScriptedLLM):
    """A model whose answer arrives only after something else happened (a late passage)."""

    def __init__(self, *responses: Any) -> None:
        super().__init__(*responses)
        self.before_answer: Any = None

    async def structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        if self.before_answer is not None:
            hook, self.before_answer = self.before_answer, None
            await hook()
        return await super().structured(prompt, output_type, **kwargs)


class Rig:
    def __init__(
        self,
        tmp_path: Any,
        *,
        station: StationId | None = StationId.PORTRAIT,
        first_slot: NarrationSlotContext | None = None,
        fail_writer: BaseException | None = None,
        seed: str | None = None,
        voices: Any = VOICE_COMBINATION_B,
        scripted: bool = True,
        music_seconds: int = 2,
        plain_repository: bool = False,
        doubao_transport: Any = None,
    ) -> None:
        self.storage = LocalObjectStorageProvider(tmp_path / "audio")
        self.ledger_of_calls = UsageLedger()
        draft = _retag(clean_draft())
        self.material_llm = ScriptedLLM(material_draft()) if scripted else ScriptedLLM()
        self.writer_llm = (
            _HookedLLM(fail_writer) if fail_writer is not None else _HookedLLM(draft) if scripted else _HookedLLM()
        )
        pipeline = DialoguePipeline(writer=DialogueWriter(self.writer_llm))  # type: ignore[arg-type]
        self.usage = StoryUsageStore(self.storage)
        self.artifacts = DialogueArtifactStore(self.storage)
        self.runtime = DialogueRuntime(
            material=StoryMaterialService(self.material_llm),  # type: ignore[arg-type]
            seam=DialogueSeamService(pipeline=pipeline, artifacts=self.artifacts, usage=self.usage),
            usage=self.usage,
            artifacts=self.artifacts,
        )
        self.speech: Any = (
            DoubaoPodcastSpeechProvider(doubao_transport, self.storage, ledger=self.ledger_of_calls)
            if doubao_transport is not None
            else MockDialogueSpeechProvider(self.storage, fixed_duration_seconds=3)
        )
        self.materializer = NarrationMaterializer(
            MockTTSProvider(self.storage),
            self.storage,
            dialogue_speech=self.speech,
            dialogue_voices=voices,
            dialogue_speed=float(SPEECH_RATE_B),
            dialogue_format="wav" if doubao_transport is not None else None,
        )
        self.session = _session(station, first_slot)
        self.seed = seed or (
            _seed_choosing(FIRST_SLOT, SECOND_SLOT, station)
            if station not in (None, StationId.NIGHT)
            else "seed"
        )
        self.writer = _Writer()
        self.generator = StagedProgressiveChapterGenerator(
            session=self.session,
            writer=self.writer,  # type: ignore[arg-type]
            composer=EpisodeComposer(MockMusicProvider()),
            materializer=self.materializer,
            track_research=_Researcher(),  # type: ignore[arg-type]
            dialogue=self.runtime,
        )
        assembly = SimpleNamespace(
            create_progressive_chapter_generator=lambda session: self.generator,
            materializer=self.materializer,
            dialogue_runtime=self.runtime,
            ledger=self.ledger_of_calls,
        )
        self.assembly = assembly
        self.repository: InMemoryEpisodeRepository = (
            InMemoryEpisodeRepository() if plain_repository else EventLoopRejectingEpisodeRepository()
        )
        self.orchestrator = EpisodeOrchestrator(
            self.repository,
            progressive_runtime=StagedProgressiveRuntimeAdapter(assembly),  # type: ignore[arg-type]
        )
        self.repository.save(_episode(self.session, seed=self.seed, music_seconds=music_seconds))

    def author(self) -> LiveEpisode:
        return asyncio.run(self.orchestrator.author_pending_narration_async(EPISODE_ID, max_chapters=1))

    def voice(self) -> LiveEpisode:
        return asyncio.run(self.orchestrator.materialize_pending_narration_async(EPISODE_ID))

    def narration(self) -> list[NarrationSegment]:
        return [
            segment
            for segment in self.repository.get(EPISODE_ID).ordered_segments
            if isinstance(segment, NarrationSegment) and segment.chapter_id == "chapter-2"
        ]

    def ledger(self) -> Any:
        return asyncio.run(self.usage.load(EPISODE_ID))


def test_a_chosen_slot_gets_a_checked_passage_and_the_writer_is_not_asked(tmp_path) -> None:
    rig = Rig(tmp_path)

    rig.author()

    (segment,) = rig.narration()
    assert segment.state is SegmentState.SCRIPT_READY
    assert segment.dialogue is not None and segment.dialogue.block_id == block_id_for(FIRST_SLOT)
    assert segment.dialogue.story_id == story_id_for(TRACK_REF)
    assert segment.narration_text == segment.dialogue.text
    assert rig.writer.calls == 0
    # The passage was saved, checked and its story reserved before it reached the timeline.
    assert asyncio.run(rig.artifacts.load(EPISODE_ID, segment.dialogue.block_id)) is not None
    assert rig.ledger().entries[story_id_for(TRACK_REF)].state is StoryUseState.RESERVED
    assert rig.speech.calls == 0  # authoring never makes audio


def test_voicing_keeps_the_hosts_voices_and_the_real_audio_length(tmp_path) -> None:
    rig = Rig(tmp_path)
    rig.author()

    rig.voice()

    (segment,) = rig.narration()
    assert segment.state is SegmentState.AUDIO_READY
    assert segment.actual_duration_seconds == 3  # the audio's length, not the 40 s estimate
    assert segment.dialogue_audio is not None  # the record of the request travels with the audio
    assert [(v.speaker.value, v.voice_id) for v in segment.dialogue_audio.voices] == [
        (v.speaker.value, v.voice_id) for v in VOICE_COMBINATION_B
    ]
    (request,) = rig.speech.requests
    assert [turn.speaker.value for turn in request.turns][:2] == ["A", "B"]
    assert request.speed == float(SPEECH_RATE_B)
    # What was persisted in the episode is enough to restore it with no synthesis.
    saved = rig.repository.get(EPISODE_ID)
    restored = [s for s in saved.ordered_segments if isinstance(s, NarrationSegment) and s.dialogue][0]
    assert restored.dialogue_audio == segment.dialogue_audio


def test_a_foreign_track_title_survives_authoring_storage_and_voicing(tmp_path) -> None:
    played = OPENING.model_copy(update={"canonical_title": "夢のあと", "spoken_title": "梦之后"})
    rig = Rig(tmp_path, first_slot=_slot(FIRST_SLOT, 0, just_played_track=played))
    text = "刚才的《夢のあと》留下了一个问题，我们沿着它继续听。"
    draft = _retag(DialogueDraft(turns=[DraftTurn(speaker="A", text=text, fact_refs=["fdt-F1"])]))  # type: ignore[arg-type]
    rig.writer_llm.queues[DialogueDraft] = [draft]

    rig.author()
    (authored,) = rig.narration()
    assert authored.dialogue is not None
    assert authored.dialogue.turns[0].tts_text == "刚才的梦之后留下了一个问题，我们沿着它继续听。"
    saved = asyncio.run(rig.artifacts.load(EPISODE_ID, authored.dialogue.block_id))
    assert saved is not None and saved.block == authored.dialogue

    rig.voice()

    (voiced,) = rig.narration()
    assert voiced.state is SegmentState.AUDIO_READY and voiced.dialogue_audio is not None
    assert voiced.narration_text == text
    assert rig.writer.calls == 0 and rig.writer_llm.calls == [("DialogueDraft", "dialogue_writer")]


def test_an_unreadable_tour_name_falls_back_before_audio_not_after_it(tmp_path) -> None:
    rig = Rig(tmp_path)
    draft = _retag(DialogueDraft(turns=[DraftTurn(speaker="A", text="她的“雙六エクスタシー”巡演聚集了这些乐手。", fact_refs=["fdt-F1"])]))  # type: ignore[arg-type]
    rig.writer_llm.queues[DialogueDraft] = [draft]

    rig.author()
    rig.voice()

    (segment,) = rig.narration()
    assert segment.state is SegmentState.AUDIO_READY and segment.dialogue is None
    assert rig.writer.calls == 1
    assert not rig.ledger().entries


def test_a_failing_dialogue_writer_leaves_the_chapter_to_the_writer_and_gives_the_story_back(tmp_path) -> None:
    from tests.dialogue_fixtures import unavailable

    rig = Rig(tmp_path, fail_writer=unavailable())

    rig.author()

    (segment,) = rig.narration()
    assert segment.dialogue is None and segment.narration_text == "一个人说的下一首。"
    assert rig.writer.calls == 1
    assert story_id_for(TRACK_REF) not in rig.ledger().entries


def test_an_unchosen_slot_makes_no_model_call_at_all(tmp_path) -> None:
    rig = Rig(tmp_path, seed=_seed_choosing(SECOND_SLOT, FIRST_SLOT))

    rig.author()

    (segment,) = rig.narration()
    assert segment.dialogue is None and rig.writer.calls == 1
    assert rig.material_llm.calls == [] and rig.writer_llm.calls == []


@pytest.mark.parametrize(
    "changes",
    [{"is_opening": True}, {"is_final": True}],
    ids=["opening-slot", "final-slot"],
)
def test_the_opening_and_the_sign_off_stay_with_the_writer(tmp_path, changes) -> None:
    rig = Rig(tmp_path, first_slot=_slot(FIRST_SLOT, 1, **changes))
    # An opening/closing slot has its own kind rules; only the offer's eligibility is under test.
    assert rig.runtime.eligible_slot_ids(StationId.PORTRAIT, [[s] for s in [_slot(FIRST_SLOT, 1, **changes)]], rig.seed) == set()


def test_night_has_no_passages(tmp_path) -> None:
    rig = Rig(tmp_path, station=StationId.NIGHT)

    rig.author()

    (segment,) = rig.narration()
    assert segment.dialogue is None and rig.writer_llm.calls == []


def test_settle_publishes_what_was_reached_and_releases_what_never_arrived(tmp_path) -> None:
    rig = Rig(tmp_path)
    rig.author()
    rig.voice()
    story = story_id_for(TRACK_REF)

    episode = rig.repository.get(EPISODE_ID)
    asyncio.run(rig.runtime.settle(EPISODE_ID, episode.segments))
    assert rig.ledger().entries[story].state is StoryUseState.RESERVED  # reached by nobody yet

    for segment in episode.segments:
        if isinstance(segment, NarrationSegment) and segment.dialogue is not None:
            segment.state = SegmentState.COMMITTED
    asyncio.run(rig.runtime.settle(EPISODE_ID, episode.segments))
    assert rig.ledger().entries[story].state is StoryUseState.PUBLISHED

    # A reservation whose passage is not in the programme is given back.
    asyncio.run(rig.usage.reserve(EPISODE_ID, "st-lost", "dlg-lost"))
    asyncio.run(rig.runtime.settle(EPISODE_ID, episode.segments))
    assert "st-lost" not in rig.ledger().entries and story in rig.ledger().entries


def test_a_passage_that_loses_the_race_to_playback_is_dropped_and_its_story_returned(tmp_path) -> None:
    rig = Rig(tmp_path)
    episode = rig.repository.get(EPISODE_ID)
    for segment in episode.segments:
        if segment.chapter_id == "chapter-2" and isinstance(segment, MusicSegment):
            segment.state = SegmentState.COMMITTED  # playback reached the chapter first
    rig.repository.save(episode)

    rig.author()

    assert all(segment.dialogue is None for segment in rig.narration())
    assert story_id_for(TRACK_REF) not in rig.ledger().entries


def _storage_with_music(tmp_path: Any) -> LocalObjectStorageProvider:
    storage = LocalObjectStorageProvider(tmp_path / "audio")

    async def put() -> None:
        await storage.put("music-a.wav", _wav_bytes(2.5, 220), "audio/wav")
        await storage.put("music-b.wav", _wav_bytes(2.5, 330), "audio/wav")

    asyncio.run(put())
    return storage


def _close_programme(rig: Rig) -> None:
    """The programme is complete (nothing more is coming), so the whole of it can be published."""
    episode = rig.repository.get(EPISODE_ID)
    episode.state = EpisodeState.MATERIALIZED
    episode.progressive_session = None
    rig.repository.save(episode)


def _render(client: TestClient) -> dict[str, Any]:
    response = client.post(f"/api/episodes/{EPISODE_ID}/program-render", headers={"X-Wavecast-Listener": "listener-a"})
    assert response.status_code == 200, response.text
    manifest = response.json()
    playlist = client.get(manifest["streamUrl"])
    assert playlist.status_code == 200, playlist.text
    for chunk in manifest["chunks"]:
        assert chunk["audioUrl"] in playlist.text
        asset = client.get(chunk["audioUrl"])
        assert asset.status_code == 200 and asset.content
    return manifest  # type: ignore[no-any-return]


def test_the_voiced_passage_renders_through_the_real_hls_path_without_touching_the_episode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path)
    rig.storage = _storage_with_music(tmp_path)  # same directory: the music sits beside the fake speech
    rig.author()
    rig.voice()
    (segment,) = rig.narration()
    assert segment.state is SegmentState.AUDIO_READY

    _close_programme(rig)
    monkeypatch.setattr(api_module, "repository", rig.repository)
    monkeypatch.setattr(api_module, "orchestrator", rig.orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(rig.orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", rig.storage)
    client = TestClient(api_module.app)
    before = rig.repository.get(EPISODE_ID).model_dump(mode="json")

    with_passage = _render(client)

    assert with_passage["chunks"] and with_passage["renderedFrontierSeconds"] > 0
    assert rig.repository.get(EPISODE_ID).model_dump(mode="json") == before
    assert _render(client) == with_passage  # asking again publishes the same programme

    # The same programme with the passage skipped is shorter by about the passage's length.
    other = Rig(tmp_path / "other")
    other.storage = _storage_with_music(tmp_path / "other")
    episode = other.repository.get(EPISODE_ID)
    episode.segments = [
        s.model_copy(update={"state": SegmentState.SKIPPED}) if isinstance(s, NarrationSegment) else s
        for s in episode.segments
    ]
    other.repository.save(episode)
    _close_programme(other)
    monkeypatch.setattr(api_module, "repository", other.repository)
    monkeypatch.setattr(api_module, "orchestrator", other.orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(other.orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", other.storage)
    without_passage = _render(TestClient(api_module.app))
    gap = with_passage["renderedFrontierSeconds"] - without_passage["renderedFrontierSeconds"]
    assert 2.0 <= gap <= 3.5, gap


# --- off by default, and the factory ----------------------------------------------------------


def test_the_feature_is_off_by_default(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")

    assert build_dialogue_voicing(ProviderSettings(), storage) is None
    service = create_episode_assembly_service(ProviderSettings(), storage=storage)
    assert service.dialogue_runtime is None
    assert service.materializer.dialogue_speech is None


def test_the_mock_voicing_is_wired_when_the_feature_is_on(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    settings = ProviderSettings(dialogue_radio=True)

    service = create_episode_assembly_service(settings, storage=storage)

    assert service.dialogue_runtime is not None
    assert isinstance(service.materializer.dialogue_speech, MockDialogueSpeechProvider)
    assert tuple(service.materializer.dialogue_voices) == VOICE_COMBINATION_B
    generator = service.create_progressive_chapter_generator(_session())
    assert generator.dialogue is service.dialogue_runtime


def test_doubao_selection_needs_its_own_api_key_and_wires_the_real_transport(tmp_path) -> None:
    from wavecast.providers.doubao_podcast import (
        DoubaoPodcastSpeechProvider,
        DoubaoPodcastWebSocketTransport,
    )

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    base = ProviderSettings(dialogue_radio=True, dialogue_speech_provider="doubao")

    with pytest.raises(ProviderConfigurationError, match="DOUBAO_PODCAST_API_KEY"):
        build_dialogue_voicing(base, storage)
    with pytest.raises(ProviderConfigurationError, match="DOUBAO_PODCAST_API_KEY"):
        create_episode_assembly_service(base, storage=storage)

    keyed = ProviderSettings(
        dialogue_radio=True, dialogue_speech_provider="doubao", doubao_podcast_api_key="k-secret"
    )
    voicing = build_dialogue_voicing(keyed, storage)
    assert voicing is not None and isinstance(voicing.speech, DoubaoPodcastSpeechProvider)
    assert voicing.audio_format == "wav" and voicing.speed == 0.0
    assert isinstance(voicing.speech._transport, DoubaoPodcastWebSocketTransport)  # type: ignore[attr-defined]
    assert "k-secret" not in repr(voicing.speech._transport) and "k-secret" not in repr(keyed)  # type: ignore[attr-defined]
    service = create_episode_assembly_service(keyed, storage=storage)
    assert service.materializer.dialogue_speech is not None
    assert service.materializer.dialogue_format == "wav"


def test_settings_read_the_dialogue_switches_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAVECAST_DIALOGUE_RADIO", raising=False)
    monkeypatch.delenv("WAVECAST_DIALOGUE_SPEECH_PROVIDER", raising=False)
    assert ProviderSettings.from_env().dialogue_radio is False
    assert ProviderSettings.from_env().dialogue_speech_provider == "mock"

    monkeypatch.setenv("WAVECAST_DIALOGUE_RADIO", "on")
    monkeypatch.setenv("WAVECAST_DIALOGUE_SPEECH_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_PODCAST_API_KEY", "secret-token")
    settings = ProviderSettings.from_env()
    assert settings.dialogue_radio is True and settings.dialogue_speech_provider == "doubao"
    assert settings.doubao_podcast_api_key == "secret-token"
    assert settings.doubao_podcast_resource_id == "volc.service_type.10050"
    assert "secret-token" not in repr(settings)

    monkeypatch.setenv("WAVECAST_DIALOGUE_SPEECH_PROVIDER", "minimax")
    with pytest.raises(ProviderConfigurationError):
        ProviderSettings.from_env()


def test_a_checked_passage_is_placed_as_it_is_in_either_kind_of_gap() -> None:
    from wavecast.assembly import _assemble_writer_scripts
    from wavecast.intelligence.models import RadioScriptBlockKind as Kind
    from wavecast.models.dialogue import (
        DialogueBlock,
        DialoguePurpose,
        DialogueSpeaker,
        DialogueTurn,
    )

    block = DialogueBlock(
        block_id="dlg-x",
        slot_id="x",
        story_id="st-x",
        purpose=DialoguePurpose.STORY,
        turns=[DialogueTurn(speaker=DialogueSpeaker.A, text="一句话。", tts_text=None, fact_refs=[])],
        duration_seconds=5,
    )
    script = RadioScript(
        blocks=[
            RadioScriptBlock(
                kind=Kind.TRANSITION, text=block.text, tts_text=block.tts_text, duration_seconds=5, dialogue=block
            )
        ],
        intended_duration_seconds=5,
    )
    for placement, allowed, expected in (
        (NarrationSlotPlacement.BEFORE_TRACK, [Kind.TRACK_INTRO], Kind.TRACK_INTRO),
        (NarrationSlotPlacement.AFTER_TRACK, [Kind.TRANSITION], Kind.TRANSITION),
    ):
        context = _slot("x", 1, placement=placement, allowed_block_kinds=allowed)
        placed, _ = _assemble_writer_scripts(
            [script],
            1,
            chapter_music_indices=[0],
            slot_contexts=[[context]],
            previous_music_indices=[0],
            require_final_slot=False,
        )
        (only,) = placed.blocks
        assert only.kind is expected and only.dialogue == block and only.track_index == 0


# --- a dialogue that cannot be placed: the Writer gets one try, unless it is too late ---------


def _break_dialogue_placement(rig: Rig, *, before: Any = None, failure: BaseException | None = None) -> None:
    from wavecast.assembly import NarrationPlacementError

    original = rig.generator.composer.compose_prepared

    def compose(tracks: Any, script: Any) -> Any:
        if any(block.dialogue is not None for block in getattr(script, "blocks", [])):
            if before is not None:
                before()
            raise failure or NarrationPlacementError("this passage cannot be placed")
        return original(tracks, script)

    rig.generator.composer.compose_prepared = compose  # type: ignore[method-assign]


def _chapter_two_music_reached(rig: Rig) -> None:
    episode = rig.repository.get(EPISODE_ID)
    for segment in episode.segments:
        if segment.chapter_id == "chapter-2" and isinstance(segment, MusicSegment):
            segment.state = SegmentState.COMMITTED
    rig.repository.save(episode)


def _chapter_two_seam_skipped(rig: Rig) -> None:
    episode = rig.repository.get(EPISODE_ID)
    for segment in episode.segments:
        if segment.chapter_id == "chapter-2" and isinstance(segment, NarrationSegment):
            segment.state = SegmentState.SKIPPED
    rig.repository.save(episode)


def test_a_passage_that_cannot_be_placed_falls_back_to_the_writer_once(tmp_path) -> None:
    rig = Rig(tmp_path)
    _break_dialogue_placement(rig)

    rig.author()

    (segment,) = rig.narration()
    assert segment.dialogue is None and segment.narration_text == "一个人说的下一首。"
    assert segment.state is SegmentState.SCRIPT_READY
    assert rig.writer.calls == 1  # once; the passage is neither retried nor redrawn
    assert [name for name, _ in rig.writer_llm.calls].count("DialogueDraft") == 1
    assert story_id_for(TRACK_REF) not in rig.ledger().entries  # given back before the Writer ran


@pytest.mark.parametrize(
    "happens",
    [_chapter_two_music_reached, _chapter_two_seam_skipped],
    ids=["playback-reached-the-chapter", "seam-skipped-for-continuity"],
)
def test_no_writer_fallback_once_the_chapter_is_exposed_or_its_seam_given_up(tmp_path, happens) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, plain_repository=True)
    _break_dialogue_placement(rig, before=lambda: happens(rig))

    rig.author()

    assert rig.writer.calls == 0  # no money spent on a chapter nobody will hear
    assert all(segment.dialogue is None and segment.state is not SegmentState.SCRIPT_READY for segment in rig.narration())
    assert story_id_for(TRACK_REF) not in rig.ledger().entries


def test_cancellation_never_reaches_the_writer(tmp_path) -> None:
    rig = Rig(tmp_path)
    _break_dialogue_placement(rig, failure=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        rig.author()

    assert rig.writer.calls == 0


def test_when_the_writer_fails_too_the_music_carries_on(tmp_path) -> None:
    from wavecast.providers.errors import ProviderTimeoutError

    rig = Rig(tmp_path)
    _break_dialogue_placement(rig)

    async def broken(*args: object, **kwargs: object) -> RadioScript:
        raise ProviderTimeoutError("writer timeout")

    rig.writer.write = broken  # type: ignore[method-assign]

    rig.author()

    (segment,) = rig.narration()
    assert segment.state is SegmentState.SKIPPED and segment.dialogue is None
    assert story_id_for(TRACK_REF) not in rig.ledger().entries


# --- coming back to a passage: the ledger and the store are asked before any model ------------


def _offer_args(rig: Rig) -> dict[str, Any]:
    return dict(
        episode_id=EPISODE_ID,
        station=StationId.PORTRAIT,
        context=_slot(FIRST_SLOT, 1),
        chosen_slot_ids={FIRST_SLOT},
        chapter_id="chapter-2",
        order=1,
        evidence=evidence(),
        subject="方大同",
        track_ref=TRACK_REF,
        track_label="方大同 - 爱爱爱",
    )


def _quiet(rig: Rig) -> bool:
    return rig.material_llm.calls == [] and rig.writer_llm.calls == []


def test_asking_again_for_a_saved_passage_costs_no_model_call(tmp_path) -> None:
    rig = Rig(tmp_path)
    rig.author()
    before = (len(rig.material_llm.calls), len(rig.writer_llm.calls))
    assert before == (1, 1)  # material and the draft: nothing else is asked

    again = asyncio.run(rig.runtime.offer(**_offer_args(rig)))

    assert again is not None and again.restored
    assert again.block == rig.narration()[0].dialogue
    assert (len(rig.material_llm.calls), len(rig.writer_llm.calls)) == before


def test_a_fresh_process_resumes_the_saved_passage_with_no_model_at_all(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()
    saved = first.narration()[0].dialogue

    second = Rig(tmp_path, scripted=False)  # any model call would fail
    second.author()

    (segment,) = second.narration()
    assert segment.dialogue == saved and segment.state is SegmentState.SCRIPT_READY
    assert _quiet(second) and second.writer.calls == 0


def test_the_audio_it_was_voiced_with_survives_resuming_whatever_is_configured_now(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()
    first.voice()
    voiced = first.narration()[0]
    assert voiced.dialogue_audio is not None
    assert asyncio.run(first.artifacts.load_audio(EPISODE_ID, voiced.dialogue.block_id)) == voiced.dialogue_audio  # type: ignore[union-attr]

    other_voices = [
        VOICE_COMBINATION_B[0].model_copy(update={"voice_id": "some_other_voice_a"}),
        VOICE_COMBINATION_B[1].model_copy(update={"voice_id": "some_other_voice_b"}),
    ]
    second = Rig(tmp_path, scripted=False, voices=other_voices)
    second.author()

    (resumed,) = second.narration()
    assert resumed.state is SegmentState.SCRIPT_READY
    assert resumed.dialogue_audio == voiced.dialogue_audio  # the old request travels with it

    second.voice()

    (restored,) = second.narration()
    assert restored.state is SegmentState.AUDIO_READY
    assert second.speech.calls == 0  # nothing synthesized
    assert restored.asset_ref == voiced.asset_ref and restored.actual_duration_seconds == 3
    assert [v.voice_id for v in restored.dialogue_audio.voices] == [v.voice_id for v in VOICE_COMBINATION_B]  # type: ignore[union-attr]
    assert _quiet(second)


def test_a_story_held_by_another_passage_is_skipped_without_a_request(tmp_path) -> None:
    rig = Rig(tmp_path, scripted=False)
    asyncio.run(rig.usage.reserve(EPISODE_ID, story_id_for(TRACK_REF), "dlg-somewhere-else"))

    rig.author()

    (segment,) = rig.narration()
    assert segment.dialogue is None and rig.writer.calls == 1  # the Writer path, as before
    assert _quiet(rig)


def test_a_passage_being_made_elsewhere_is_not_started_twice(tmp_path) -> None:
    rig = Rig(tmp_path, scripted=False)
    asyncio.run(rig.usage.reserve(EPISODE_ID, story_id_for(TRACK_REF), block_id_for(FIRST_SLOT)))

    rig.author()  # reserved by this very block, nothing saved yet: someone is on it

    assert rig.narration()[0].dialogue is None and _quiet(rig)


def test_a_told_passage_is_never_entered_again(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()
    episode = first.repository.get(EPISODE_ID)
    for segment in episode.segments:
        if isinstance(segment, NarrationSegment) and segment.dialogue is not None:
            segment.state = SegmentState.COMMITTED
    asyncio.run(first.runtime.settle(EPISODE_ID, episode.segments))
    assert first.ledger().entries[story_id_for(TRACK_REF)].state is StoryUseState.PUBLISHED

    second = Rig(tmp_path, scripted=False)
    second.author()

    assert second.narration()[0].dialogue is None and _quiet(second)
    assert first.ledger().entries[story_id_for(TRACK_REF)].state is StoryUseState.PUBLISHED


def test_a_saved_passage_whose_story_went_back_to_the_pool_is_taken_again_not_rewritten(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()
    asyncio.run(first.usage.release(EPISODE_ID, story_id_for(TRACK_REF), block_id_for(FIRST_SLOT)))
    assert story_id_for(TRACK_REF) not in first.ledger().entries

    second = Rig(tmp_path, scripted=False)
    second.author()

    assert second.narration()[0].dialogue is not None and _quiet(second)
    assert second.ledger().entries[story_id_for(TRACK_REF)].state is StoryUseState.RESERVED


# --- the progressive path: a prefix is published first, the passage arrives late -----------------


def _long_music(tmp_path: Any, seconds: int = 70) -> LocalObjectStorageProvider:
    storage = LocalObjectStorageProvider(tmp_path / "audio")

    async def put() -> None:
        await storage.put("music-a.wav", _wav_bytes(seconds, 220), "audio/wav")
        await storage.put("music-b.wav", _wav_bytes(seconds, 330), "audio/wav")

    asyncio.run(put())
    return storage


def test_a_passage_that_arrives_after_the_prefix_was_published_changes_nothing_that_was_published(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, music_seconds=70, plain_repository=True)
    rig.storage = _long_music(tmp_path)
    monkeypatch.setattr(api_module, "repository", rig.repository)
    monkeypatch.setattr(api_module, "orchestrator", rig.orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(rig.orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", rig.storage)
    client = TestClient(api_module.app)
    published: dict[str, Any] = {}

    async def while_the_passage_is_being_written() -> None:
        def publish() -> None:
            # Continuity gives the pending seam up, and the programme prefix goes out past it.
            _chapter_two_seam_skipped(rig)
            manifest = _render(client)
            published["manifest"] = manifest
            published["bytes"] = {chunk["audioUrl"]: client.get(chunk["audioUrl"]).content for chunk in manifest["chunks"]}

        await asyncio.to_thread(publish)

    rig.writer_llm.before_answer = while_the_passage_is_being_written

    rig.author()  # the passage is written, checked and saved - and then finds the seam gone

    manifest = published["manifest"]
    assert manifest["renderedFrontierSeconds"] > 70, "the published prefix must reach past the host seam"
    # the late passage was not inserted anywhere, and its story went back
    assert all(segment.dialogue is None for segment in rig.narration())
    assert [segment.state for segment in rig.narration()] == [SegmentState.SKIPPED]
    assert story_id_for(TRACK_REF) not in rig.ledger().entries
    assert asyncio.run(rig.artifacts.load(EPISODE_ID, block_id_for(FIRST_SLOT))) is not None  # made, not used
    rig.voice()
    assert rig.speech.calls == 0  # and never voiced

    # Everything already published is byte-for-byte what it was; the feed only ever grows.
    again = _render(client)
    assert again["chunks"][: len(manifest["chunks"])] == manifest["chunks"]
    for chunk in manifest["chunks"]:
        content = client.get(chunk["audioUrl"]).content
        assert content == published["bytes"][chunk["audioUrl"]] and len(content) == len(published["bytes"][chunk["audioUrl"]])


# --- the same place, another song ------------------------------------------------------------

OTHER_TRACK = "netease:another-song"


def test_a_slot_that_now_holds_another_song_never_gets_the_old_passage_or_its_reservation(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()
    first.voice()
    old = asyncio.run(first.artifacts.load(EPISODE_ID, block_id_for(FIRST_SLOT)))
    old_audio = asyncio.run(first.artifacts.load_audio(EPISODE_ID, block_id_for(FIRST_SLOT)))
    assert old is not None and old_audio is not None
    ledger_before = first.ledger()

    second = Rig(tmp_path, scripted=False)
    offered = asyncio.run(second.runtime.offer(**{**_offer_args(second), "track_ref": OTHER_TRACK}))

    assert offered is None  # neither the old text nor the old audio comes back
    assert _quiet(second)  # and nothing was asked of a model
    assert second.ledger() == ledger_before  # no reservation for the new song, the old one untouched
    assert story_id_for(OTHER_TRACK) not in second.ledger().entries
    assert asyncio.run(second.artifacts.load(EPISODE_ID, block_id_for(FIRST_SLOT))) == old  # not replaced
    assert asyncio.run(second.artifacts.load_audio(EPISODE_ID, block_id_for(FIRST_SLOT))) == old_audio


def test_the_other_song_is_authored_by_the_writer_path_through_the_whole_chain(tmp_path) -> None:
    first = Rig(tmp_path)
    first.author()

    second = Rig(tmp_path, scripted=False)
    other = ResolvedTrack(track_ref=OTHER_TRACK, canonical_artist="方大同", canonical_title="另一首")
    second.session.chapters[0] = second.session.chapters[0].model_copy(update={"resolved_track": other})
    episode = second.repository.get(EPISODE_ID)
    episode.segments = [
        s.model_copy(update={"track_ref": OTHER_TRACK, "title": "另一首"}) if isinstance(s, MusicSegment) and s.chapter_id == "chapter-2" else s
        for s in episode.segments
    ]
    episode.progressive_session = second.session
    second.repository.save(episode)

    second.author()

    (segment,) = second.narration()
    assert segment.dialogue is None and second.writer.calls == 1  # the Writer, as before
    assert _quiet(second)
    assert story_id_for(OTHER_TRACK) not in second.ledger().entries


def test_a_saved_passage_for_another_station_or_slot_is_not_taken_either(tmp_path) -> None:
    from wavecast.intelligence.dialogue_writer import DialogueSlot
    from wavecast.models.dialogue import DialoguePurpose

    first = Rig(tmp_path)
    first.author()
    story = story_id_for(TRACK_REF)
    block = block_id_for(FIRST_SLOT)

    def ask(slot_id: str, station: StationId):  # type: ignore[no-untyped-def]
        slot = DialogueSlot(slot_id=slot_id, block_id=block, purpose=DialoguePurpose.STORY, station=station)
        return asyncio.run(first.runtime._seam.resume(EPISODE_ID, story, slot, chapter_id="chapter-2", order=1))

    right = ask(FIRST_SLOT, StationId.PORTRAIT)
    assert right is not None and right.segment is not None and right.restored
    for slot_id, station in ((FIRST_SLOT, StationId.CRATE), ("chapter-9:before-track", StationId.PORTRAIT)):
        refused = ask(slot_id, station)
        assert refused is not None and refused.segment is None
        assert refused.reason == "saved_passage_is_for_another_story"


# --- whose voicing it was ----------------------------------------------------------------------


def _doubao_rig(tmp_path: Any, *outcomes: Any, **options: Any) -> tuple[Rig, Any]:
    """A rig voiced by the Doubao adapter over a fake transport: one outcome per attempt.

    ``None`` is a success (one second of audio per line, 403 audio tokens reported); an
    exception is raised after the service has already reported its usage.
    """

    from wavecast.providers.doubao_podcast import PodcastAudio

    queue = list(outcomes) or [None]

    class Sequenced:
        def __init__(self) -> None:
            self.attempts = 0

        async def synthesize(self, script: Any, attempt: Any) -> Any:
            self.attempts += 1
            outcome = queue.pop(0) if len(queue) > 1 else queue[0]
            attempt.request_id = f"req-{self.attempts}"
            attempt.add_usage({"input_text_tokens": 0, "output_audio_tokens": 403})
            if outcome is not None:
                raise outcome
            second = b"\x01\x00" * 24000
            attempt.session_finished = True
            return PodcastAudio(
                pcm=second * len(script.lines),
                sample_rate=24000,
                line_byte_lengths=(len(second),) * len(script.lines),
            )

    transport = Sequenced()
    return Rig(tmp_path, doubao_transport=transport, **options), transport


def _events(rig: Rig, scope: str) -> list[Any]:
    return [event for event in rig.ledger_of_calls.events if event.scope == scope]


def test_voicing_through_the_orchestrator_is_charged_to_the_episode(tmp_path) -> None:
    from wavecast.providers.usage import usage_diagnostics

    rig, _ = _doubao_rig(tmp_path)
    rig.author()

    rig.voice()

    (event,) = rig.ledger_of_calls.events
    assert event.scope == EPISODE_ID and event.metadata["output_audio_tokens"] == 403
    report = usage_diagnostics(rig.ledger_of_calls, scope=EPISODE_ID)
    assert report["usage"]["output_audio_tokens"] == 403  # type: ignore[index]
    assert usage_diagnostics(rig.ledger_of_calls, scope="another-episode")["usage"]["output_audio_tokens"] == 0  # type: ignore[index]


def test_a_failed_and_a_cancelled_voicing_are_charged_to_the_episode_too(tmp_path) -> None:
    from wavecast.providers.errors import ProviderTimeoutError

    rig, _ = _doubao_rig(tmp_path, ProviderTimeoutError("slow"), asyncio.CancelledError())
    rig.author()

    rig.voice()  # the first attempt fails: the seam is given up, the episode carries on
    assert rig.narration()[0].state is SegmentState.SKIPPED
    (failed,) = _events(rig, EPISODE_ID)
    assert failed.metadata["outcome"] == "ProviderTimeoutError" and failed.metadata["output_audio_tokens"] == 403

    # a second attempt on another passage that is cancelled midway
    episode = rig.repository.get(EPISODE_ID)
    for segment in episode.segments:
        if isinstance(segment, NarrationSegment) and segment.dialogue is not None:
            segment.state = SegmentState.SCRIPT_READY
    rig.repository.save(episode)
    with pytest.raises(asyncio.CancelledError):
        rig.voice()
    failed, cancelled = _events(rig, EPISODE_ID)
    assert cancelled.metadata["outcome"] == "cancelled" and cancelled.scope == EPISODE_ID
    assert [event.scope for event in rig.ledger_of_calls.events] == [EPISODE_ID, EPISODE_ID]  # none unattributed


def test_the_single_segment_endpoint_charges_the_episode_and_never_another(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wavecast.providers.errors import ProviderTimeoutError
    from wavecast.providers.usage import UsageLedger

    rig, _ = _doubao_rig(tmp_path, ProviderTimeoutError("slow"), None, plain_repository=True)
    rig.author()
    runtime = StagedProgressiveRuntimeAdapter(rig.assembly)  # type: ignore[arg-type]
    monkeypatch.setattr(api_module, "repository", rig.repository)
    monkeypatch.setattr(api_module, "orchestrator", EpisodeOrchestrator(rig.repository, progressive_runtime=runtime))
    monkeypatch.setattr(api_module, "progressive_runtime", runtime)
    monkeypatch.setattr(api_module, "narration_materializer", rig.materializer)
    monkeypatch.setattr(api_module, "audio_storage", rig.storage)
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "listener-a"}
    assert isinstance(rig.ledger_of_calls, UsageLedger) and api_module._usage_ledger() is rig.ledger_of_calls

    other = rig.repository.get(EPISODE_ID).model_copy(deep=True)
    other.id = "other-episode"
    rig.repository.save(other)

    segment_id = rig.narration()[0].id
    failed = client.post(f"/api/episodes/{EPISODE_ID}/segments/{segment_id}/materialize", headers=headers)
    assert failed.status_code == 502
    done = client.post(f"/api/episodes/{EPISODE_ID}/segments/{segment_id}/materialize", headers=headers)
    assert done.status_code == 200, done.text

    usage = client.get(f"/api/episodes/{EPISODE_ID}/usage", headers=headers).json()["providers"]
    assert usage["usage"]["event_count"] == 2
    assert usage["usage"]["output_audio_tokens"] == 806  # the failed attempt reported 403 too
    outcomes = [event["outcome"] if "outcome" in event else None for event in usage["provider_events"]]
    assert all(event["provider"] == "doubao_podcast" for event in usage["provider_events"]) and len(outcomes) == 2
    elsewhere = client.get("/api/episodes/other-episode/usage", headers=headers).json()["providers"]
    assert elsewhere["usage"]["event_count"] == 0 and elsewhere["usage"]["output_audio_tokens"] == 0
    assert "刚听完" not in str(usage)


def test_the_api_materializer_records_into_the_runtime_ledger(tmp_path) -> None:
    from tests.test_doubao_podcast import FakeTransport

    ledger = UsageLedger()
    settings = ProviderSettings(dialogue_radio=True, dialogue_speech_provider="doubao", doubao_podcast_api_key="k")
    storage = LocalObjectStorageProvider(tmp_path / "audio")

    materializer = api_module._build_narration_materializer(
        settings, MockTTSProvider(storage), storage, ledger, transport=FakeTransport()
    )

    assert materializer.dialogue_speech is not None and materializer.dialogue_speech._ledger is ledger  # type: ignore[attr-defined]
    assert api_module._build_narration_materializer(ProviderSettings(), MockTTSProvider(storage), storage, ledger).dialogue_speech is None


def test_planned_discussion_gets_the_editorial_goal_and_original_earlier_context(
    tmp_path, monkeypatch
):
    from wavecast.hosting import DiscussionPlan

    rig = Rig(tmp_path, seed=_seed_choosing(SECOND_SLOT, FIRST_SLOT))
    # The old hash would select the other slot. The durable heavy-station plan wins.
    rig.session.discussion_plan = DiscussionPlan(target=3, minimum=2, chapter_ids=["chapter-2"])
    rig.session.chapters[0].chapter.narration_goal = "用这首歌比较靠近与退让"
    episode = rig.repository.get(EPISODE_ID)
    episode.editorial_brief = "爱情表达里的不同选择"
    episode.segments.append(
        NarrationSegment(
            id="later-host",
            chapter_id="chapter-3",
            order=100,
            state=SegmentState.SCRIPT_READY,
            title="Future",
            planned_duration_seconds=10,
            narration_text="DO_NOT_INCLUDE_LATER_HOST",
        )
    )
    prompts = []
    original = rig.writer_llm.structured

    async def capture(prompt, output_type, **kwargs):
        prompts.append(prompt)
        return await original(prompt, output_type, **kwargs)

    monkeypatch.setattr(rig.writer_llm, "structured", capture)
    rig.author()
    assert rig.narration()[0].dialogue is not None
    prompt = prompts[-1]
    assert "用这首歌比较靠近与退让" in prompt
    assert "爱情表达里的不同选择" in prompt
    assert "DO_NOT_INCLUDE_LATER_HOST" not in prompt


def test_next_available_discussion_takes_up_a_failed_opening(tmp_path, monkeypatch):
    from wavecast.hosting import DiscussionPlan

    rig = Rig(tmp_path)
    episode = rig.repository.get(EPISODE_ID)
    # Move the fixture's available discussion after an earlier failed opening.
    rig.session.chapters[1].chapter_id = "chapter-4"
    rig.session.chapters[0].chapter_id = "chapter-3"
    for segment in episode.segments:
        if segment.chapter_id == "chapter-2":
            segment.chapter_id = "chapter-3"
            segment.order += 1
    episode.segments.append(
        NarrationSegment(
            id="missed-opening",
            chapter_id="chapter-2",
            order=1,
            state=SegmentState.SKIPPED,
            title="Missed",
            planned_duration_seconds=30,
        )
    )
    rig.session.narration_authored_chapter_ids = ["chapter-2"]
    rig.session.discussion_plan = DiscussionPlan(target=3, minimum=2, chapter_ids=["chapter-3"])
    prompts = []
    original = rig.writer_llm.structured

    async def capture(prompt, output_type, **kwargs):
        prompts.append(prompt)
        return await original(prompt, output_type, **kwargs)

    monkeypatch.setattr(rig.writer_llm, "structured", capture)
    rig.author()
    assert len(prompts) == 1
    assert "The first opening could not air" in prompts[0]


@pytest.mark.parametrize("station", [None, StationId.PORTRAIT])
def test_researched_title_is_used_now_and_saved_for_later_host_passages(tmp_path, station):
    rig = Rig(tmp_path, station=station)
    named = TRACK.model_copy(
        update={"spoken_title": "爱，爱，爱", "spoken_title_evidence_id": "E1"}
    )

    class NamedResearcher(_Researcher):
        async def prepare(self, **kwargs):
            result = await super().prepare(**kwargs)
            result.spoken_title = named.spoken_title
            result.spoken_title_evidence_id = named.spoken_title_evidence_id
            return result

    rig.generator.track_research = NamedResearcher()
    prompts = []
    if station is None:
        original = rig.writer.write

        async def capture(*args, **kwargs):
            prompts.append(kwargs)
            return await original(*args, **kwargs)

        rig.writer.write = capture
    else:
        original = rig.writer_llm.structured

        async def capture(prompt, *args, **kwargs):
            prompts.append(prompt)
            return await original(prompt, *args, **kwargs)

        rig.writer_llm.structured = capture

    episode = rig.author()
    assert len(prompts) == 1
    if station is None:
        assert prompts[0]["slot_contexts"][0].chapter_track.spoken_title == named.spoken_title
    else:
        assert '"spoken_title": "爱，爱，爱"' in prompts[0]
    # Reload persisted state: another seam can name the same recording without re-extracting it.
    assert episode.progressive_session is not None
    saved = ProgressiveAssemblySession.model_validate_json(episode.progressive_session.model_dump_json())
    for chapter in saved.chapters:
        assert chapter.resolved_track.spoken_title == named.spoken_title
        assert chapter.resolved_track.spoken_title_evidence_id == "E1"
        assert chapter.slot_contexts[0].upcoming_track.spoken_title == named.spoken_title
    music = next(
        s for s in episode.segments if isinstance(s, MusicSegment) and s.chapter_id == "chapter-2"
    )
    assert music.spoken_title == named.spoken_title
    assert music.track_ref == TRACK.track_ref

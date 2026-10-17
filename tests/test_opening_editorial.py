"""Offline checks for the opening's context, placement and compatibility."""

import asyncio

import pytest
from wavecast.assembly import create_episode_assembly_service
from wavecast.intelligence.models import (
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
)
from wavecast.intelligence.writer import WriterService
from wavecast.models.episode import LiveEpisode, NarrationRole, NarrationSegment, SegmentState
from wavecast.narration_quality import estimate_seconds
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.presentation import HostMode, PresentationIntent
from wavecast.proposals import (
    OpeningTrackCandidate,
    ProgramProposal,
    ProgramProposalDraft,
    ProgramProposalDraftBatch,
    ProposalGenerationRequest,
    shared_copy,
)
from wavecast.providers.config import ProviderSettings
from wavecast.providers.profiles import InferenceProfile
from wavecast.stations import StationId

from tests.test_intelligence_services import StructuredFixture
from tests.test_program_proposals import _live_generator
from tests.test_staged_runtime import _PlaceholderBootstrapRuntime, _seed


def test_topic_lead_survives_candidate_rotation_and_sharing_without_research(monkeypatch) -> None:
    note = "爱情里的靠近和退让，可以从不同的歌里慢慢听。"
    generator, llm = _live_generator(
        ProgramProposalDraftBatch(
            proposals=[
                ProgramProposalDraft(
                    title="靠近与退让",
                    short_description="从爱情的不同处境出发听歌。",
                    editorial_route=["靠近", "退让"],
                    opening_host_note=note,
                    opening_track_candidates=[
                        OpeningTrackCandidate(artist="Mira Fields", title="Neon First Light"),
                        OpeningTrackCandidate(artist="Signal Garden", title="Midnight Transfer"),
                    ],
                )
            ]
        )
    )
    # Exercise each catalog outcome without depending on UUID-generated rotations.
    from wavecast import proposals as module

    calls = 0
    original_draft = generator._draft

    async def draft_once(prompt):
        nonlocal calls
        calls += 1
        return await original_draft(prompt)

    monkeypatch.setattr(generator, "_draft", draft_once)
    proposals = []
    for reverse in (False, True):
        monkeypatch.setattr(
            module,
            "_rotated",
            lambda items, seed, reverse=reverse: list(reversed(items)) if reverse else items,
        )
        proposal = asyncio.run(
            generator.generate(
                ProposalGenerationRequest(
                    prompt="爱情里的不同处境",
                    station=StationId.PORTRAIT,
                    output_language=OutputLanguage.ZH_CN,
                )
            )
        )[0]
        proposals.append(proposal)
        assert proposal.opening_narration_text.startswith(note)
        assert "FM九七四，人物志" in proposal.opening_narration_text
        assert estimate_seconds(proposal.opening_narration_text) <= 12
        assert proposal.to_episode_seed().opening_narration_text == proposal.opening_narration_text
        # Persisted copies reuse the lead, with no request parsing or model call.
        saved = ProgramProposal.model_validate_json(proposal.model_dump_json())
        copy = shared_copy(saved, new_id="shared")
        assert copy.opening_narration_text == proposal.opening_narration_text
        assert copy.opening_host_note == note
    assert {p.opening_track_ref for p in proposals} == {"mock:opening", "mock:bridge"}
    assert calls == 2


@pytest.mark.parametrize(
    ("station", "mode", "topic", "brief", "expected_window"),
    [
        (StationId.PORTRAIT, HostMode.FULL, "方大同的爱情观", "听爱情里的靠近、迟疑和退让。", 75),
        (StationId.PORTRAIT, HostMode.FULL, "椎名林檎", "从个人作品到乐队，尝试不同的听法。", 75),
        (
            StationId.LINEAGE,
            HostMode.FULL,
            "灵魂乐的变化",
            "听不同年代如何处理相近的音乐想法。",
            75,
        ),
        (StationId.CRATE, HostMode.LIGHT, "想挖一些歌", "从喜欢的选择向外多听一点。", 12),
        (StationId.CASUAL, HostMode.LIGHT, "随便听一会儿", "几首适合连续听的选择。", 12),
        (StationId.PORTRAIT, HostMode.LIGHT, "少讲两句", "从不同作品认识一个人。", 12),
    ],
)
def test_first_passage_uses_durable_intention_and_only_available_prior_speech(
    tmp_path,
    monkeypatch,
    station,
    mode,
    topic,
    brief,
    expected_window,
) -> None:
    monkeypatch.chdir(tmp_path)
    seed = _seed().model_copy(
        update={
            "topic": topic,
            "short_description": brief,
            "station": station,
            "output_language": OutputLanguage.ZH_CN,
            "presentation_intent": PresentationIntent(host_mode=mode),
        }
    )
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(
        repository, progressive_runtime=_PlaceholderBootstrapRuntime()
    )
    episode = orchestrator.start(seed)
    opening = "爱情未必只有一种答案，这次一起听听。"
    orchestrator.attach_opening_narration(
        episode.id,
        NarrationSegment(
            chapter_id="chapter-1",
            order=1,
            state=SegmentState.AUDIO_READY,
            planned_duration_seconds=8,
            actual_duration_seconds=8,
            title="Opening",
            narration_text=opening,
            narration_role=NarrationRole.INTRO,
            audio_source_url="/api/audio/mock/opening",
        ),
    )
    episode = asyncio.run(orchestrator.ensure_fast_start_async(episode.id))
    # Equivalent JSON boundary to the durable repository/worker, with no proposal lookup.
    episode = LiveEpisode.model_validate_json(episode.model_dump_json())
    assert episode.editorial_brief == brief
    prefix = [
        s.model_dump(mode="json") for s in episode.ordered_segments if s.chapter_id == "chapter-1"
    ]
    # Drafts and discarded speech must not become context just because text exists.
    for offset, state in enumerate((SegmentState.SCRIPT_READY, SegmentState.SKIPPED)):
        episode.segments.append(
            NarrationSegment(
                id=f"discarded-{offset}",
                chapter_id="chapter-1",
                order=1,
                state=state,
                planned_duration_seconds=8,
                title="Not airing",
                narration_text=f"DO_NOT_INCLUDE_{offset}",
            )
        )
    episode.segments.append(
        NarrationSegment(
            id="future",
            chapter_id="chapter-3",
            order=100,
            state=SegmentState.AUDIO_READY,
            planned_duration_seconds=8,
            title="Future",
            narration_text="DO_NOT_INCLUDE_FUTURE",
        )
    )
    text = "这次想听听爱情里不同的选择，下一首也放在这个问题里听。"
    fixture = StructuredFixture(
        RadioScript(
            blocks=[
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.TRACK_INTRO,
                    text=text,
                    duration_seconds=12,
                )
            ]
        )
    )
    assembly = create_episode_assembly_service(ProviderSettings(mode="mock"))
    assembly.background_pipeline.writer = WriterService(fixture)
    generated = asyncio.run(
        StagedProgressiveRuntimeAdapter(assembly).author_fast_successor_narration(episode)
    )
    assert generated is not None
    assert len(fixture.prompts) == 1
    prompt = fixture.prompts[0]
    assert brief in prompt and topic in prompt
    assert opening in prompt
    assert "DO_NOT_INCLUDE" not in prompt
    assert "not evidence" in prompt and "unconfirmed songs" in prompt
    assert '"is_opening": false' in prompt
    assert '"placement": "before_track"' in prompt
    assert "This block's move" not in prompt
    assert "Register samples" not in prompt
    assert "Length: between" not in prompt
    assert f"Target narration duration seconds: {expected_window}" in prompt
    assert fixture.calls[0]["profile"] is InferenceProfile.FAST
    assert [s.narration_text for s in generated.segments if isinstance(s, NarrationSegment)] == [
        text
    ]
    assert [
        s.model_dump(mode="json")
        for s in episode.ordered_segments
        if s.chapter_id == "chapter-1" and not s.id.startswith("discarded")
    ] == prefix


@pytest.mark.parametrize("mode", [HostMode.NONE, HostMode.LIGHT])
def test_missing_short_opening_and_legacy_brief_do_not_require_waiting(
    tmp_path, monkeypatch, mode
) -> None:
    monkeypatch.chdir(tmp_path)
    orchestrator = EpisodeOrchestrator(
        InMemoryEpisodeRepository(), progressive_runtime=_PlaceholderBootstrapRuntime()
    )
    episode = orchestrator.start(
        _seed().model_copy(
            update={
                "presentation_intent": PresentationIntent(host_mode=mode),
            }
        )
    )
    episode = asyncio.run(orchestrator.ensure_fast_start_async(episode.id))
    payload = episode.model_dump(mode="json")
    payload.pop("editorial_brief")
    episode = LiveEpisode.model_validate(payload)
    assert episode.editorial_brief is None
    fixture = StructuredFixture(RadioScript(blocks=[]))
    assembly = create_episode_assembly_service(ProviderSettings(mode="mock"))
    assembly.background_pipeline.writer = WriterService(fixture)
    result = asyncio.run(
        StagedProgressiveRuntimeAdapter(assembly).author_fast_successor_narration(episode)
    )
    assert result is None  # Missing/empty host never removes ready music.
    assert len(fixture.prompts) == (0 if mode is HostMode.NONE else 1)
    if fixture.prompts:
        assert episode.topic in fixture.prompts[0]
        assert "none yet: the programme has just begun" in fixture.prompts[0]
        assert "if that short opening was absent or skipped" in fixture.prompts[0]


def test_fast_opening_reuses_existing_research_without_exposing_it_in_episode_json(tmp_path):
    from tests.dialogue_fixtures import evidence

    orchestrator = EpisodeOrchestrator(
        InMemoryEpisodeRepository(), progressive_runtime=_PlaceholderBootstrapRuntime()
    )
    episode = orchestrator.start(_seed())
    episode = asyncio.run(orchestrator.ensure_fast_start_async(episode.id))
    episode.opening_evidence = evidence()
    fixture = StructuredFixture(
        RadioScript(
            blocks=[
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.TRACK_INTRO,
                    text="从这两首歌出发，听听不同的表达。",
                    duration_seconds=10,
                )
            ]
        )
    )
    assembly = create_episode_assembly_service(ProviderSettings(mode="mock"))
    assembly.background_pipeline.writer = WriterService(fixture)
    generated = asyncio.run(
        StagedProgressiveRuntimeAdapter(assembly).author_fast_successor_narration(episode)
    )
    assert generated is not None
    assert len(fixture.prompts) == 1
    assert episode.opening_evidence[0].claim_or_excerpt in fixture.prompts[0]
    assert "opening_evidence" not in episode.model_dump(mode="json")


def test_catalog_spoken_title_survives_saved_proposal_and_fast_opening():
    from wavecast.models.episode import MusicSegment

    seed = _seed().model_copy(
        update={
            "opening_track_artist": "椎名林檎",
            "opening_track_title": "丸ノ内サディスティック",
            "opening_track_spoken_title": "丸之内虐待狂",
            "output_language": OutputLanguage.ZH_CN,
        }
    )
    proposal = ProgramProposal.from_episode_seed(seed)
    copied = shared_copy(
        ProgramProposal.model_validate_json(proposal.model_dump_json()), new_id="copy"
    )
    assert copied.to_episode_seed().opening_track_spoken_title == "丸之内虐待狂"
    orchestrator = EpisodeOrchestrator(
        InMemoryEpisodeRepository(), progressive_runtime=_PlaceholderBootstrapRuntime()
    )
    episode = orchestrator.start(copied.to_episode_seed())
    episode = asyncio.run(orchestrator.ensure_fast_start_async(episode.id))
    episode = LiveEpisode.model_validate_json(episode.model_dump_json())
    music = next(
        s for s in episode.segments if isinstance(s, MusicSegment) and s.chapter_id == "chapter-1"
    )
    assert music.spoken_title == "丸之内虐待狂"
    prefix = music.model_dump()
    fixture = StructuredFixture(
        RadioScript(
            blocks=[
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.TRACK_INTRO,
                    text="刚才这首《丸ノ内サディスティック》留下的律动，我们继续听。",
                    duration_seconds=10,
                )
            ]
        )
    )
    assembly = create_episode_assembly_service(ProviderSettings(mode="mock"))
    assembly.background_pipeline.writer = WriterService(fixture)
    generated = asyncio.run(
        StagedProgressiveRuntimeAdapter(assembly).author_fast_successor_narration(episode)
    )
    assert generated is not None
    assert '"spoken_title": "丸之内虐待狂"' in fixture.prompts[0]
    narration = next(s for s in generated.segments if isinstance(s, NarrationSegment))
    assert "丸之内虐待狂" in narration.tts_text
    assert music.model_dump() == prefix


@pytest.mark.parametrize("available", [True, False])
def test_fast_opening_prefers_real_dialogue_and_reuses_the_single_writer_fallback(
    tmp_path, available
):
    from wavecast.models.dialogue import DialoguePurpose
    from wavecast.models.episode import MusicSegment

    from tests.test_dialogue_runtime import TRACK, Rig, evidence

    rig = Rig(tmp_path)
    bootstrap = _PlaceholderBootstrapRuntime()
    bootstrap.fast_track = TRACK
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository, progressive_runtime=bootstrap)
    episode = orchestrator.start(
        _seed().model_copy(
            update={
                "station": StationId.PORTRAIT,
                "output_language": OutputLanguage.ZH_CN,
                "presentation_intent": PresentationIntent(host_mode=HostMode.FULL),
            }
        )
    )
    episode = asyncio.run(orchestrator.ensure_fast_start_async(episode.id))
    episode.opening_evidence = evidence() if available else []
    assembly = create_episode_assembly_service(ProviderSettings(mode="mock"))
    assembly.dialogue_runtime = rig.runtime
    assembly.background_pipeline.writer = rig.writer
    adapter = StagedProgressiveRuntimeAdapter(assembly)
    prefix = next(
        s for s in episode.segments if isinstance(s, MusicSegment) and s.chapter_id == "chapter-1"
    ).model_dump()
    generated = asyncio.run(adapter.author_fast_successor_narration(episode))
    assert generated is not None
    speech = next(s for s in generated.segments if isinstance(s, NarrationSegment))
    assert speech.hosting_role == "opening"
    assert (
        speech.narration_role is not NarrationRole.INTRO
    )  # editorial role never changes placement
    if available:
        assert speech.dialogue.purpose is DialoguePurpose.OPENING
        assert rig.writer.calls == 0
        assert len(rig.writer_llm.calls) == 1
    else:
        assert speech.dialogue is None
        assert rig.writer.calls == 1
        assert not rig.writer_llm.calls
    assert (
        next(
            s
            for s in episode.segments
            if isinstance(s, MusicSegment) and s.chapter_id == "chapter-1"
        ).model_dump()
        == prefix
    )


def test_closing_has_room_to_answer_the_opening_without_random_moves_or_new_research():
    from wavecast.intelligence.models import ChapterPlan, NarrationSlotContext

    text = (
        "开头我们问这些歌怎样表达靠近。听到这里，热烈与克制并不总在两端，有时会在同一首歌里相遇。"
    )
    fixture = StructuredFixture(
        RadioScript(
            blocks=[
                RadioScriptBlock(kind=RadioScriptBlockKind.OUTRO, text=text, duration_seconds=32)
            ]
        )
    )
    script = asyncio.run(
        WriterService(fixture).write(
            ChapterPlan(
                index=5,
                track=None,
                narrative_role="resolution",
                reason="Close",
                narration_goal="Close",
            ),
            [],
            station=StationId.PORTRAIT,
            host_mode=HostMode.FULL,
            output_language=OutputLanguage.ZH_CN,
            target_duration_seconds=45,
            closing_brief="靠近与退让",
            previous_committed_context="开头的问题与已经播出的讨论。",
            route_tracks=["方大同 - 爱爱爱", "方大同 - 特别的人"],
            slot_contexts=[
                NarrationSlotContext(
                    slot_id="final",
                    chapter_index=5,
                    placement="after_final_track",
                    allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
                    is_final=True,
                )
            ],
        )
    )
    assert len(fixture.prompts) == 1
    prompt = fixture.prompts[0]
    assert "Target narration duration seconds: 45" in prompt
    assert "Return to the opening's listening question" in prompt
    assert "开头的问题与已经播出的讨论。" in prompt
    assert "one or two plain sentences" not in prompt
    assert "This block's move" not in prompt and "Register samples" not in prompt
    assert script.blocks[-1].text.startswith(text)
    assert len(script.blocks[-1].text) > len(text)  # existing sign-off is still appended

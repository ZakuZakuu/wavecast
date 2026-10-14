"""A checked two-host passage → an ordinary timeline segment → one voiced asset → the arrangement.

Offline: the passage comes from fixed model responses (tests/dialogue_fixtures.py), the audio
from a fake speech provider.  What this does not show: that a real vendor's voices, timings or
failures behave like the fake (ADR 0026).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from wavecast.arrangement.planner import plan_episode_mix
from wavecast.composer import _narration_segment
from wavecast.intelligence.dialogue_pipeline import DialogueStatus
from wavecast.intelligence.dialogue_writer import DialogueRepair, DialogueSlot
from wavecast.intelligence.models import RadioScriptBlock, RadioScriptBlockKind
from wavecast.materialization.narration import NarrationMaterializer
from wavecast.models.dialogue import DialogueSpeaker, VoiceRoleSnapshot
from wavecast.models.episode import (
    LiveEpisode,
    MusicSegment,
    NarrationRole,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.models.story_usage import StoryUsageLedger, StoryUseState
from wavecast.orchestration.dialogue_timeline import (
    DialogueSeamService,
    narration_segment_from_record,
    restore_narration_segment,
)
from wavecast.orchestration.episode import InMemoryEpisodeRepository
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.narration_enrichment import _finish_authoring
from wavecast.providers.dialogue_speech import MockDialogueSpeechProvider
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderTimeoutError,
)
from wavecast.providers.fakes import MockTTSProvider
from wavecast.rendering.fingerprint import mix_plan_fingerprint
from wavecast.rendering.programme import slice_mix_plan
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore
from wavecast.storage.episodes import EpisodeConcurrencyError
from wavecast.storage.story_usage import StoryUsageError, StoryUsageStore, usage_key

from tests.dialogue_fixtures import STORY_ID, ScriptedLLM, clean_draft
from tests.test_dialogue_pipeline import SLOT, build, material
from tests.test_narration_authoring import _authored_chapter, _episode, _Host

EPISODE = "episode-1"


def record():  # type: ignore[no-untyped-def]
    pipeline, _, _ = build(clean_draft())
    outcome = asyncio.run(pipeline.produce(material(), SLOT))
    assert outcome.status is DialogueStatus.READY
    return outcome.to_record()


def materializer(
    storage: LocalObjectStorageProvider, speech: MockDialogueSpeechProvider | None, **kwargs
):  # type: ignore[no-untyped-def]
    return NarrationMaterializer(
        MockTTSProvider(storage),
        storage,
        dialogue_speech=speech,
        dialogue_voices=kwargs.pop("voices", VOICE_COMBINATION_B),
        dialogue_speed=kwargs.pop("speed", SPEECH_RATE_B),
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalObjectStorageProvider:
    return LocalObjectStorageProvider(tmp_path / "store")


# --- the segment ----------------------------------------------------------------------------------------


def test_the_segment_keeps_the_turns_speakers_and_references_and_derives_its_text() -> None:
    checked = record()

    segment = narration_segment_from_record(checked, chapter_id="chapter-2", order=1)

    assert segment.state is SegmentState.SCRIPT_READY and segment.dialogue == checked.block
    assert segment.narration_text == checked.block.text and segment.tts_text is None
    assert [t.speaker for t in segment.dialogue.turns] == [t.speaker for t in checked.block.turns]  # type: ignore[union-attr]
    assert segment.dialogue.story_id == STORY_ID  # type: ignore[union-attr]
    assert segment.narration_role is NarrationRole.TRANSITION
    assert segment.planned_duration_seconds == checked.block.duration_seconds


def test_a_dialogue_segment_cannot_drift_from_its_dialogue() -> None:
    block = record().block
    base = dict(id="s", chapter_id="c", order=0, planned_duration_seconds=5, title="t", dialogue=block)

    with pytest.raises(ValidationError, match="derived from the dialogue"):
        NarrationSegment(**base, narration_text="另一段话")
    with pytest.raises(ValidationError, match="voiced from its dialogue"):
        NarrationSegment(**base, tts_text="朗读")
    with pytest.raises(ValidationError, match="belong to a dialogue"):
        NarrationSegment(
            id="s", chapter_id="c", order=0, planned_duration_seconds=5, title="t",
            narration_text="x", dialogue_voices=list(VOICE_COMBINATION_B),
        )  # fmt: skip
    # The one-voice segment is exactly as before.
    plain = NarrationSegment(
        id="s", chapter_id="c", order=0, planned_duration_seconds=5, title="t", narration_text="接下来。"
    )
    assert plain.dialogue is None and plain.dialogue_voices == [] and plain.tts_text is None


def test_the_composer_now_builds_a_segment_from_a_dialogue_block_without_flattening_it() -> None:
    block = RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, dialogue=record().block)

    segment = _narration_segment(block, 3, 2)

    assert segment.dialogue == block.dialogue and segment.narration_text == block.text
    assert segment.tts_text is None and segment.tts_cues == []


def test_the_segment_survives_the_json_round_trip_the_repository_uses() -> None:
    episode = _episode()
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    segment.dialogue_voices = list(VOICE_COMBINATION_B)
    episode.segments.append(segment)

    restored = LiveEpisode.model_validate_json(episode.model_dump_json())

    again = restored.segment(segment.id)
    assert isinstance(again, NarrationSegment)
    assert again.dialogue == segment.dialogue and again.dialogue_voices == segment.dialogue_voices


# --- voicing: turns and the B voices ----------------------------------------------------------------------


def test_the_request_keeps_turn_order_and_the_chosen_b_voices(storage: LocalObjectStorageProvider) -> None:
    speech = MockDialogueSpeechProvider(storage)
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)

    asyncio.run(materializer(storage, speech).materialize(segment))

    (request,) = speech.requests
    assert [t.speaker for t in request.turns] == [t.speaker for t in segment.dialogue.turns]  # type: ignore[union-attr]
    assert [t.text for t in request.turns] == [t.text for t in segment.dialogue.turns]  # type: ignore[union-attr]
    assert {r.speaker: r.voice_id for r in request.roles} == {
        DialogueSpeaker.A: "zh_male_liufei_v2_saturn_bigtts",
        DialogueSpeaker.B: "zh_male_xiaolei_v2_saturn_bigtts",
    }
    assert request.speed == 0  # Doubao's chosen rate, not MiniMax's 0.9
    assert segment.dialogue_voices == list(VOICE_COMBINATION_B)
    assert "voice" not in json.dumps(segment.dialogue.model_dump())  # type: ignore[union-attr]


def test_the_voiced_asset_records_who_spoke_when(storage: LocalObjectStorageProvider) -> None:
    speech = MockDialogueSpeechProvider(storage)
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)

    asyncio.run(materializer(storage, speech).materialize(segment))

    stored = asyncio.run(storage.get(segment.asset_ref))  # type: ignore[arg-type]
    assert stored is not None
    assert [t["speaker"] for t in stored.metadata["turn_timings"]] == [
        t.speaker.value for t in segment.dialogue.turns  # type: ignore[union-attr]
    ]
    assert {v["speaker"]: v["voice_id"] for v in stored.metadata["voices"]}["B"].startswith("zh_male_xiaolei")
    assert segment.state is SegmentState.AUDIO_READY and segment.audio_source_url


def test_changing_a_voice_or_a_word_does_not_reuse_old_audio(storage: LocalObjectStorageProvider) -> None:
    speech = MockDialogueSpeechProvider(storage)
    checked = record()

    def key(voices, text_change: bool = False) -> str:  # type: ignore[no-untyped-def]
        segment = narration_segment_from_record(checked, chapter_id="c", order=1)
        asyncio.run(materializer(storage, speech, voices=voices).materialize(segment))
        return segment.asset_ref  # type: ignore[return-value]

    swapped = (
        VoiceRoleSnapshot(speaker=DialogueSpeaker.A, voice_id="zh_male_xiaolei_v2_saturn_bigtts"),
        VoiceRoleSnapshot(speaker=DialogueSpeaker.B, voice_id="zh_male_liufei_v2_saturn_bigtts"),
    )
    first, second = key(VOICE_COMBINATION_B), key(swapped)

    assert first != second and speech.calls == 2
    assert key(VOICE_COMBINATION_B) == first and speech.calls == 2  # same mapping: a cache hit


# --- the arrangement uses the real audio length -------------------------------------------------------------


def _timeline(dialogue: NarrationSegment | None) -> PlayableEpisode:
    segments: list[MusicSegment | NarrationSegment] = [
        MusicSegment(
            id="a", chapter_id="c1", order=0, track_ref="track:a", state=SegmentState.AUDIO_READY,
            planned_duration_seconds=270, actual_duration_seconds=270, audio_source_url="/a.mp3",
            title="A", artist="A",
        ),
    ]  # fmt: skip
    if dialogue is not None:
        segments.append(dialogue)
    segments.append(
        MusicSegment(
            id="b", chapter_id="c2", order=2, track_ref="track:b", state=SegmentState.AUDIO_READY,
            planned_duration_seconds=292, actual_duration_seconds=292, audio_source_url="/b.mp3",
            title="B", artist="B",
        )
    )  # fmt: skip
    return PlayableEpisode(id="e", segments=segments)


def test_the_actual_audio_length_not_the_estimate_is_what_the_timeline_plans_with(
    storage: LocalObjectStorageProvider,
) -> None:
    speech = MockDialogueSpeechProvider(storage, fixed_duration_seconds=88)  # an existing 88 s recording
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    estimate = segment.planned_duration_seconds
    assert estimate != 88

    asyncio.run(materializer(storage, speech).materialize(segment))
    plan = plan_episode_mix(_timeline(segment))

    voice = next(clip for clip in plan.clips if clip.segment_id == segment.id)
    assert segment.actual_duration_seconds == 88 and segment.duration_seconds == 88
    assert voice.playable_duration_seconds == pytest.approx(88)
    assert voice.source_url == segment.audio_source_url
    b = next(clip for clip in plan.clips if clip.segment_id == "b")
    assert b.timeline_start_seconds >= voice.timeline_start_seconds + 88 - 10  # B follows the real length


def test_adding_the_passage_later_leaves_the_published_part_of_the_programme_alone(
    storage: LocalObjectStorageProvider,
) -> None:
    speech = MockDialogueSpeechProvider(storage, fixed_duration_seconds=88)
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    asyncio.run(materializer(storage, speech).materialize(segment))
    published = plan_episode_mix(PlayableEpisode(id="e", segments=_timeline(None).segments[:1]))
    without = plan_episode_mix(_timeline(None))
    with_passage = plan_episode_mix(_timeline(segment))

    def fingerprint(plan, end: float) -> str:  # type: ignore[no-untyped-def]
        return mix_plan_fingerprint(slice_mix_plan(plan, 0, end))

    assert fingerprint(without, 240) == fingerprint(published, 240)
    assert fingerprint(with_passage, 240) == fingerprint(published, 240)


# --- restoring without rewriting or re-voicing -------------------------------------------------------------------


def test_a_saved_passage_comes_back_without_a_model_call_or_new_audio(
    storage: LocalObjectStorageProvider,
) -> None:
    pipeline, writer, judge = build(clean_draft())
    outcome = asyncio.run(pipeline.produce(material(), SLOT))
    artifacts = DialogueArtifactStore(storage)
    asyncio.run(artifacts.save(EPISODE, outcome.to_record()))
    first_speech = MockDialogueSpeechProvider(storage)
    original = narration_segment_from_record(outcome.to_record(), chapter_id="chapter-2", order=1)
    asyncio.run(materializer(storage, first_speech).materialize(original))
    model_calls = (list(writer.calls), list(judge.calls))

    # "A restart": new store, new provider, new materializer - only the storage is shared.
    restored = asyncio.run(
        restore_narration_segment(
            DialogueArtifactStore(storage), EPISODE, SLOT.block_id, chapter_id="chapter-2", order=1
        )
    )
    second_speech = MockDialogueSpeechProvider(storage)
    assert restored is not None
    asyncio.run(materializer(storage, second_speech).materialize(restored))

    assert second_speech.calls == 0 and first_speech.calls == 1
    assert (list(writer.calls), list(judge.calls)) == model_calls  # nothing was written or checked again
    assert restored.dialogue == original.dialogue
    assert restored.asset_ref == original.asset_ref
    assert restored.actual_duration_seconds == original.actual_duration_seconds
    assert restored.state is SegmentState.AUDIO_READY
    assert asyncio.run(
        restore_narration_segment(artifacts, EPISODE, "nothing", chapter_id="c", order=1)
    ) is None


# --- failure, cancellation, lateness -------------------------------------------------------------------------------


def test_a_failed_synthesis_leaves_the_segment_unpublished_and_retryable(
    storage: LocalObjectStorageProvider,
) -> None:
    speech = MockDialogueSpeechProvider(storage)
    speech.fail_with = ProviderTimeoutError("slow")
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    materialize = materializer(storage, speech)

    with pytest.raises(ProviderTimeoutError):
        asyncio.run(materialize.materialize(segment))

    assert segment.state is SegmentState.SCRIPT_READY
    assert segment.asset_ref is None and segment.audio_source_url is None
    assert segment.actual_duration_seconds is None and segment.dialogue_voices == []
    speech.fail_with = None
    asyncio.run(materialize.materialize(segment))
    assert segment.state is SegmentState.AUDIO_READY


def test_cancelling_synthesis_resets_the_segment(storage: LocalObjectStorageProvider) -> None:
    speech = MockDialogueSpeechProvider(storage, delay_seconds=30)
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)

    async def scenario() -> None:
        task = asyncio.create_task(materializer(storage, speech).materialize(segment))
        while speech.calls == 0:
            await asyncio.sleep(0)
        assert segment.state is SegmentState.AUDIO_GENERATING
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert segment.state is SegmentState.SCRIPT_READY and segment.asset_ref is None


def test_dialogue_without_configured_voices_is_a_configuration_error_not_a_one_voice_reading(
    storage: LocalObjectStorageProvider,
) -> None:
    segment = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    tts = MockTTSProvider(storage)

    with pytest.raises(ProviderConfigurationError):
        asyncio.run(NarrationMaterializer(tts, storage).materialize(segment))
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(
            materializer(storage, MockDialogueSpeechProvider(storage), voices=VOICE_COMBINATION_B[:1]).materialize(
                segment
            )
        )

    assert tts.calls == 0 and segment.state is SegmentState.SCRIPT_READY


def test_an_exposed_chapter_never_receives_the_late_passage() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode(music_state=SegmentState.COMMITTED)
    repository.save(episode)
    dialogue = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    generated = GeneratedChapter(
        chapter_id="chapter-2", segments=[dialogue, _authored_chapter().segments[1]]
    )

    updated = _finish_authoring(_Host(repository), episode.id, "chapter-2", generated)

    chapter = [s for s in updated.ordered_segments if s.chapter_id == "chapter-2"]
    assert [s.id for s in chapter] == ["chapter-2:music:0"]
    assert chapter[0].state is SegmentState.COMMITTED
    assert not any(isinstance(s, NarrationSegment) and s.dialogue for s in updated.ordered_segments)


def test_an_unexposed_chapter_takes_the_passage_with_turns_and_ids_intact() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode()
    repository.save(episode)
    checked = record()
    dialogue = narration_segment_from_record(checked, chapter_id="chapter-2", order=1)
    generated = GeneratedChapter(
        chapter_id="chapter-2", segments=[dialogue, _authored_chapter().segments[1]]
    )

    updated = _finish_authoring(_Host(repository), episode.id, "chapter-2", generated)

    stored = repository.get(episode.id).segment(dialogue.id)
    assert isinstance(stored, NarrationSegment) and stored.state is SegmentState.SCRIPT_READY
    assert stored.dialogue == checked.block
    assert updated.segment("chapter-3:music:0").order == 3  # later music moved by one place, as before


def test_a_late_voicing_cannot_overwrite_a_seam_that_was_given_up() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode()
    repository.save(episode)
    dialogue = narration_segment_from_record(record(), chapter_id="chapter-2", order=1)
    generated = GeneratedChapter(
        chapter_id="chapter-2", segments=[dialogue, _authored_chapter().segments[1]]
    )
    _finish_authoring(_Host(repository), episode.id, "chapter-2", generated)
    stale = repository.get(episode.id).model_copy(deep=True)  # what the voicing worker loaded
    other = repository.get(episode.id).model_copy(deep=True)  # the continuity guard gives the seam up
    seam = other.segment(dialogue.id)
    assert isinstance(seam, NarrationSegment)
    seam.state = SegmentState.SKIPPED
    repository.save(other)

    async def late_voicing() -> None:
        storage_dir = Path(__import__("tempfile").mkdtemp())
        local = LocalObjectStorageProvider(storage_dir)
        late = stale.segment(dialogue.id)
        assert isinstance(late, NarrationSegment)
        await materializer(local, MockDialogueSpeechProvider(local)).materialize(late)
        assert late.state is SegmentState.AUDIO_READY  # in the stale copy only
        repository.save(stale)

    with pytest.raises(EpisodeConcurrencyError):
        asyncio.run(late_voicing())

    now = repository.get(episode.id).segment(dialogue.id)
    assert isinstance(now, NarrationSegment)
    assert now.state is SegmentState.SKIPPED and now.asset_ref is None


# --- stories are told once ---------------------------------------------------------------------------------------------


def seam_service(storage: LocalObjectStorageProvider, draft=None):  # type: ignore[no-untyped-def]
    pipeline, writer, judge = build(draft or clean_draft())
    service = DialogueSeamService(
        pipeline=pipeline, artifacts=DialogueArtifactStore(storage), usage=StoryUsageStore(storage)
    )
    return service, StoryUsageStore(storage), writer


def other_slot(block_id: str) -> DialogueSlot:
    return DialogueSlot(**{**SLOT.__dict__, "block_id": block_id, "slot_id": f"slot-{block_id}"})


def test_a_story_is_reserved_while_made_and_a_second_passage_cannot_tell_it(
    storage: LocalObjectStorageProvider,
) -> None:
    service, usage, writer = seam_service(storage)

    first = asyncio.run(service.author(EPISODE, material(), SLOT, chapter_id="chapter-2", order=1))
    second = asyncio.run(service.author(EPISODE, material(), other_slot("block-2"), chapter_id="chapter-3", order=2))

    assert first.segment is not None and first.artifact_key
    assert second.segment is None and second.reason == "story_already_used"
    assert second.outcome.status is DialogueStatus.SKIPPED
    assert len(writer.calls) == 1  # the second passage cost no model call
    ledger = asyncio.run(usage.load(EPISODE))
    assert ledger.entries[STORY_ID].state is StoryUseState.RESERVED
    assert ledger.entries[STORY_ID].block_id == SLOT.block_id


def test_a_rejected_passage_gives_the_story_back(storage: LocalObjectStorageProvider) -> None:
    from tests.dialogue_fixtures import draft_with_two_problems

    service, usage, writer = seam_service(storage, draft_with_two_problems())
    writer.queue(DialogueRepair, ProviderTimeoutError("repair model is down"))

    result = asyncio.run(service.author(EPISODE, material(), SLOT, chapter_id="c", order=1))

    assert result.segment is None and result.outcome.status is DialogueStatus.REJECTED
    assert result.reason == "provider_failed:ProviderTimeoutError"
    assert asyncio.run(usage.load(EPISODE)).entries == {}
    # Available again: another passage may take it.
    assert asyncio.run(usage.reserve(EPISODE, STORY_ID, "block-9")) is True


def test_cancellation_while_making_a_passage_releases_the_story(
    storage: LocalObjectStorageProvider,
) -> None:
    started = asyncio.Event()

    class Hangs:
        async def structured(self, *args, **kwargs):  # type: ignore[no-untyped-def]  # noqa: ANN002, ANN003
            started.set()
            await asyncio.sleep(30)

    from wavecast.intelligence.dialogue_check import DialogueFactChecker
    from wavecast.intelligence.dialogue_pipeline import DialoguePipeline
    from wavecast.intelligence.dialogue_writer import DialogueRepairer, DialogueWriter

    service = DialogueSeamService(
        pipeline=DialoguePipeline(
            writer=DialogueWriter(Hangs()),  # type: ignore[arg-type]
            checker=DialogueFactChecker(ScriptedLLM()),
            repairer=DialogueRepairer(ScriptedLLM()),
        ),
        artifacts=DialogueArtifactStore(storage),
        usage=StoryUsageStore(storage),
    )
    usage = StoryUsageStore(storage)

    async def scenario() -> None:
        task = asyncio.create_task(service.author(EPISODE, material(), SLOT, chapter_id="c", order=1))
        await started.wait()
        assert (await usage.load(EPISODE)).state_of(STORY_ID) is StoryUseState.RESERVED
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert asyncio.run(usage.load(EPISODE)).entries == {}


def test_reconcile_publishes_what_reached_the_listener_and_releases_what_was_skipped(
    storage: LocalObjectStorageProvider,
) -> None:
    service, usage, _ = seam_service(storage)
    result = asyncio.run(service.author(EPISODE, material(), SLOT, chapter_id="chapter-2", order=1))
    segment = result.segment
    assert segment is not None

    segment.state = SegmentState.COMMITTED
    ledger = asyncio.run(usage.reconcile(EPISODE, [segment]))
    assert ledger.state_of(STORY_ID) is StoryUseState.PUBLISHED
    # Told for good: cannot be reserved by another passage, nor released, even if later skipped.
    assert asyncio.run(usage.reserve(EPISODE, STORY_ID, "block-2")) is False
    segment.state = SegmentState.SKIPPED
    assert asyncio.run(usage.reconcile(EPISODE, [segment])).state_of(STORY_ID) is StoryUseState.PUBLISHED

    # A different story, reserved and then skipped before it reached anyone, is given back.
    assert asyncio.run(usage.reserve(EPISODE, "other-story", "block-x")) is True
    skipped = segment.model_copy(
        update={
            "state": SegmentState.SKIPPED,
            "dialogue": segment.dialogue.model_copy(update={"story_id": "other-story", "block_id": "block-x"}),  # type: ignore[union-attr]
        }
    )
    assert asyncio.run(usage.reconcile(EPISODE, [skipped])).state_of("other-story") is None


def test_the_ledger_survives_a_restart_and_will_not_guess_a_missing_version(
    storage: LocalObjectStorageProvider,
) -> None:
    asyncio.run(StoryUsageStore(storage).reserve(EPISODE, STORY_ID, "block-1"))

    again = asyncio.run(StoryUsageStore(storage).load(EPISODE))
    assert again.state_of(STORY_ID) is StoryUseState.RESERVED

    raw = again.model_dump(mode="json")
    del raw["schema_version"]
    asyncio.run(storage.put(usage_key(EPISODE), json.dumps(raw).encode(), "application/json"))
    with pytest.raises(StoryUsageError, match="does not declare a schema_version"):
        asyncio.run(StoryUsageStore(storage).load(EPISODE))
    with pytest.raises(ValidationError):
        StoryUsageLedger.model_validate(raw)


def test_ledger_rules() -> None:
    ledger = StoryUsageLedger.empty()

    assert ledger.reserve("s", "b1") and ledger.reserve("s", "b1")  # the same passage may ask again
    assert not ledger.reserve("s", "b2")
    assert not ledger.release("s", "b2")  # not its holder
    ledger.publish("s", "b1")
    with pytest.raises(ValueError, match="already told"):
        ledger.release("s", "b1")
    with pytest.raises(ValueError, match="another passage"):
        ledger.publish("s", "b2")


def test_a_reservation_whose_passage_never_arrived_can_be_given_back(
    storage: LocalObjectStorageProvider,
) -> None:
    usage = StoryUsageStore(storage)
    asyncio.run(usage.reserve(EPISODE, "lost-story", "block-lost"))  # a crash before the insert
    asyncio.run(usage.reserve(EPISODE, "inserted-story", "block-live"))
    asyncio.run(usage.reserve(EPISODE, "told-story", "block-told"))
    ledger = asyncio.run(usage.load(EPISODE))
    ledger.publish("told-story", "block-told")
    asyncio.run(storage.put(usage_key(EPISODE), ledger.model_dump_json().encode(), "application/json"))

    released = asyncio.run(usage.release_orphans(EPISODE, ["block-live"]))

    assert released == ["lost-story"]
    after = asyncio.run(usage.load(EPISODE))
    assert set(after.entries) == {"inserted-story", "told-story"}
    assert after.state_of("told-story") is StoryUseState.PUBLISHED  # told stories are never touched

"""Two-host dialogue contract: structure, derived text, fact references, explicit limits."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from wavecast.assembly import _merge_writer_blocks
from wavecast.composer import _narration_segment
from wavecast.intelligence.dialogue import (
    DialogueValidationError,
    block_from_draft,
    validate_dialogue_block,
)
from wavecast.intelligence.models import (
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
)
from wavecast.models.dialogue import (
    DialogueBlock,
    DialogueDraft,
    DialogueNotSupportedError,
    DialoguePurpose,
    DialogueSpeaker,
    DialogueTurn,
)
from wavecast.providers.speech import SpeechRequest, VoiceRoleSnapshot
from wavecast.providers.strict_schema import to_strict_schema

FACTS = {"C-F1", "C-F2", "C-F3"}


def turn(speaker: str, text: str, refs: list[str] | None = None, tts: str | None = None) -> dict:
    return {"speaker": speaker, "text": text, "tts_text": tts, "fact_refs": refs or []}


def draft(*turns: dict) -> DialogueDraft:
    # A model-written turn has no tts_text.
    return DialogueDraft.model_validate(
        {"turns": [{k: v for k, v in item.items() if k != "tts_text"} for item in turns]}
    )


def story_block(**overrides: object) -> DialogueBlock:
    base = dict(
        block_id="b1",
        slot_id="slot-1",
        purpose=DialoguePurpose.STORY,
        turns=[
            DialogueTurn.model_validate(turn("A", "刚听完这首。", ["C-F1"])),
            DialogueTurn.model_validate(turn("B", "你有没有好奇过为什么？", [])),
            DialogueTurn.model_validate(turn("A", "他自己解释过。", ["C-F2", "C-F1"])),
        ],
        duration_seconds=30,
    )
    return DialogueBlock(**{**base, **overrides})  # type: ignore[arg-type]


# --- turns and drafts -------------------------------------------------------------------------


def test_fact_refs_is_required_but_may_be_empty() -> None:
    assert DialogueTurn.model_validate(turn("A", "你好。")).fact_refs == []
    with pytest.raises(ValidationError):
        DialogueTurn.model_validate({"speaker": "A", "text": "你好。"})


def test_a_turn_rejects_unknown_fields_and_unknown_speakers() -> None:
    with pytest.raises(ValidationError):
        DialogueTurn.model_validate({**turn("A", "x"), "subject_note": "extra"})
    with pytest.raises(ValidationError):
        DialogueTurn.model_validate(turn("C", "x"))
    with pytest.raises(ValidationError):
        DialogueTurn.model_validate(turn("A", ""))


def test_a_draft_needs_turns_and_stays_within_the_turn_limit() -> None:
    with pytest.raises(ValidationError):
        DialogueDraft.model_validate({"turns": []})
    with pytest.raises(ValidationError):
        draft(*[turn("A", "x")] * 21)


def test_the_draft_schema_asks_the_model_for_exactly_the_experiment_shape() -> None:
    strict = to_strict_schema(DialogueDraft.model_json_schema())
    item = strict["$defs"]["DraftTurn"]
    # No tts_text: a model never supplies what is spoken beyond the checked text.
    assert item["required"] == ["speaker", "text", "fact_refs"]
    assert strict["$defs"]["DialogueSpeaker"]["enum"] == ["A", "B"]


# --- block ----------------------------------------------------------------------------------


def test_text_is_derived_from_the_turns_without_speaker_labels() -> None:
    block = story_block()

    assert block.text == "刚听完这首。\n你有没有好奇过为什么？\n他自己解释过。"
    for label in ("A：", "B：", "主持 A", "A:", "B:"):
        assert label not in block.text
    assert block.tts_text is None  # no turn needs its own rendering


def test_tts_text_falls_back_turn_by_turn() -> None:
    block = story_block(
        turns=[
            DialogueTurn.model_validate(turn("A", "3rd Coast", [], tts="第三海岸")),
            DialogueTurn.model_validate(turn("B", "好的。")),
        ]
    )

    assert block.tts_text == "第三海岸\n好的。"
    assert block.text == "3rd Coast\n好的。"


def test_fact_refs_are_unique_and_in_first_use_order() -> None:
    assert story_block().fact_refs == ["C-F1", "C-F2"]


def test_the_block_round_trips_through_json() -> None:
    block = story_block()

    assert DialogueBlock.model_validate_json(block.model_dump_json()) == block


# --- application validation ---------------------------------------------------------------------


def test_a_valid_block_is_returned_unchanged() -> None:
    block = story_block()

    assert validate_dialogue_block(block, allowed_fact_refs=FACTS, expected_slot_id="slot-1") is block


def test_unknown_fact_refs_fail_with_the_turn_and_the_ids() -> None:
    block = story_block(
        turns=[DialogueTurn.model_validate(turn("A", "x", ["C-F1", "C-F9"]))]
    )

    with pytest.raises(DialogueValidationError) as caught:
        validate_dialogue_block(block, allowed_fact_refs=FACTS)

    assert "turn 0" in str(caught.value) and "C-F9" in str(caught.value)
    assert "C-F1" not in "".join(p for p in caught.value.problems if "unknown" in p)


def test_a_story_without_any_reference_fails_and_is_never_filled_in() -> None:
    block = story_block(turns=[DialogueTurn.model_validate(turn("A", "一段没有出处的话。"))])

    with pytest.raises(DialogueValidationError, match="at least one fact_ref"):
        validate_dialogue_block(block, allowed_fact_refs=FACTS)
    assert block.fact_refs == []


@pytest.mark.parametrize(
    "purpose", [DialoguePurpose.OPENING, DialoguePurpose.TRANSITION, DialoguePurpose.OUTRO]
)
def test_openings_transitions_and_outros_may_cite_nothing(purpose: DialoguePurpose) -> None:
    block = story_block(purpose=purpose, turns=[DialogueTurn.model_validate(turn("A", "接下来。"))])

    validate_dialogue_block(block, allowed_fact_refs=FACTS)


def test_a_block_for_another_slot_fails() -> None:
    with pytest.raises(DialogueValidationError, match="slot"):
        validate_dialogue_block(story_block(), allowed_fact_refs=FACTS, expected_slot_id="slot-2")


def test_all_problems_are_reported_together() -> None:
    block = story_block(turns=[DialogueTurn.model_validate(turn("A", "x", ["nope"]))])

    with pytest.raises(DialogueValidationError) as caught:
        validate_dialogue_block(block, allowed_fact_refs=FACTS, expected_slot_id="other")

    assert len(caught.value.problems) == 2


def test_block_from_draft_assigns_identity_and_validates() -> None:
    block = block_from_draft(
        draft(turn("A", "一。", ["C-F1"]), turn("B", "二。")),
        block_id="b9",
        slot_id="s9",
        purpose=DialoguePurpose.STORY,
        duration_seconds=20,
        allowed_fact_refs=FACTS,
    )
    assert (block.block_id, block.slot_id, block.duration_seconds) == ("b9", "s9", 20)
    with pytest.raises(DialogueValidationError):
        block_from_draft(
            draft(turn("A", "一。", ["zzz"])),
            block_id="b",
            slot_id="s",
            purpose=DialoguePurpose.STORY,
            duration_seconds=20,
            allowed_fact_refs=FACTS,
        )


# --- compatibility with the one-voice path ------------------------------------------------------


def plain_block() -> RadioScriptBlock:
    return RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, text="接下来。", duration_seconds=5)


def test_one_voice_blocks_are_unchanged() -> None:
    block = plain_block()

    assert block.dialogue is None
    assert (block.text, block.tts_text, block.duration_seconds) == ("接下来。", None, 5)


def test_the_one_voice_writer_schema_does_not_mention_dialogue() -> None:
    schema = json.dumps(RadioScript.model_json_schema())

    assert "dialogue" not in schema and "fact_refs" not in schema


def test_a_dialogue_is_the_source_of_the_blocks_text_and_duration() -> None:
    dialogue = story_block()

    block = RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, dialogue=dialogue)

    assert block.text == dialogue.text
    assert block.tts_text == dialogue.tts_text
    assert block.duration_seconds == 30
    assert block.dialogue == dialogue


def test_a_dialogue_given_as_plain_data_is_accepted() -> None:
    block = RadioScriptBlock.model_validate(
        {"kind": "transition", "dialogue": story_block().model_dump(mode="json")}
    )

    assert block.dialogue == story_block()


def test_text_that_differs_from_the_dialogue_is_refused() -> None:
    with pytest.raises(ValidationError, match="derived from the dialogue"):
        RadioScriptBlock(
            kind=RadioScriptBlockKind.TRANSITION, text="另一段话", dialogue=story_block()
        )
    # The same text is fine: nothing can drift.
    RadioScriptBlock(
        kind=RadioScriptBlockKind.TRANSITION, text=story_block().text, dialogue=story_block()
    )


def test_the_dialogue_survives_serialization_instead_of_being_dropped() -> None:
    block = RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, dialogue=story_block())

    restored = RadioScriptBlock.model_validate_json(block.model_dump_json())

    assert restored.dialogue == block.dialogue
    assert restored == block


# --- paths that cannot carry a dialogue refuse it ------------------------------------------------


def test_a_narration_segment_is_never_made_from_a_dialogue_by_flattening() -> None:
    block = RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, dialogue=story_block())

    with pytest.raises(DialogueNotSupportedError, match="b1"):
        _narration_segment(block, 0, 1)
    assert _narration_segment(plain_block(), 0, 1).narration_text == "接下来。"


def test_merging_writer_blocks_refuses_a_dialogue() -> None:
    dialogue_block = RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, dialogue=story_block())

    with pytest.raises(DialogueNotSupportedError):
        _merge_writer_blocks([plain_block(), dialogue_block], kind=RadioScriptBlockKind.TRANSITION)
    merged = _merge_writer_blocks([plain_block(), plain_block()], kind=RadioScriptBlockKind.TRANSITION)
    assert merged is not None and merged.text == "接下来。 接下来。"


# --- speech request ---------------------------------------------------------------------------------


ROLES = [
    VoiceRoleSnapshot(speaker=DialogueSpeaker.A, voice_id="voice-one"),
    VoiceRoleSnapshot(speaker=DialogueSpeaker.B, voice_id="voice-two"),
]


def test_a_single_voice_request_is_just_text() -> None:
    request = SpeechRequest.single("你好。", cues=["warm"], speed=0.9)

    assert not request.is_dialogue and request.text == "你好。" and request.roles == []


def test_a_dialogue_request_keeps_speakers_and_a_voice_snapshot() -> None:
    request = SpeechRequest.dialogue(story_block(), ROLES, audio_format="mp3")

    assert request.is_dialogue and request.text is None
    assert [t.speaker for t in request.turns] == [DialogueSpeaker.A, DialogueSpeaker.B, DialogueSpeaker.A]
    assert {r.speaker: r.voice_id for r in request.roles} == {
        DialogueSpeaker.A: "voice-one",
        DialogueSpeaker.B: "voice-two",
    }


def test_a_dialogue_request_speaks_the_tts_rendering_when_there_is_one() -> None:
    block = story_block(turns=[DialogueTurn.model_validate(turn("A", "3rd Coast", [], tts="第三海岸"))])

    request = SpeechRequest.dialogue(block, ROLES[:1])

    assert request.turns[0].text == "第三海岸"


def test_a_request_is_one_shape_and_every_speaker_has_a_voice() -> None:
    with pytest.raises(ValidationError):
        SpeechRequest()
    with pytest.raises(ValidationError):
        SpeechRequest(text="x", turns=[{"speaker": "A", "text": "y"}], roles=ROLES)
    with pytest.raises(ValidationError, match="no voice role"):
        SpeechRequest.dialogue(story_block(), ROLES[:1])
    with pytest.raises(ValidationError, match="more than one voice"):
        SpeechRequest.dialogue(story_block(), [*ROLES, ROLES[0]])
    with pytest.raises(ValidationError, match="belong to a dialogue"):
        SpeechRequest(text="x", roles=ROLES)


def test_the_dialogue_types_name_no_vendor_voice() -> None:
    fields = set(DialogueTurn.model_fields) | set(DialogueBlock.model_fields)

    assert not {f for f in fields if "voice" in f}


def test_speed_zero_is_a_valid_neutral_setting_for_a_dialogue_request() -> None:
    # Doubao's chosen speech rate is 0; the neutral contract must not reject it.
    request = SpeechRequest.dialogue(story_block(), ROLES, speed=0, audio_format="mp3")

    assert request.speed == 0 and request.is_dialogue
    assert SpeechRequest.single("你好。", speed=0).speed == 0
    assert SpeechRequest.single("你好。", speed=-1.5).speed == -1.5  # the adapter checks its range


def test_speed_must_still_be_a_finite_number() -> None:
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            SpeechRequest.single("你好。", speed=bad)

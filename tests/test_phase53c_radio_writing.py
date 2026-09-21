import pytest
from wavecast.evals import (
    PHASE53C_RADIO_WRITING_REVIEW_EXAMPLES,
    Phase53CRadioWritingReviewBundle,
    RadioWritingCriterion,
    RadioWritingReviewExample,
    build_phase53c_radio_writing_review_bundle,
)
from wavecast.intelligence.models import (
    NarrationSlotContext,
    NarrationSlotPlacement,
    RadioScriptBlockKind,
)


def test_phase53c_bundle_is_typed_slot_aware_and_human_review_only() -> None:
    bundle = build_phase53c_radio_writing_review_bundle(
        PHASE53C_RADIO_WRITING_REVIEW_EXAMPLES
    )

    assert isinstance(bundle, Phase53CRadioWritingReviewBundle)
    assert bundle.language == "zh-CN"
    assert bundle.review_status == "human_review_required"
    assert len(bundle.examples) == 5
    assert all(example.weak_text != example.stronger_text for example in bundle.examples)
    assert all(
        example.block_kind in example.slot_context.allowed_block_kinds
        for example in bundle.examples
    )


def test_phase53c_examples_cover_real_adjacency_shapes() -> None:
    examples = {
        example.example_id: example
        for example in PHASE53C_RADIO_WRITING_REVIEW_EXAMPLES
    }

    opening = examples["opening-supported"].slot_context
    assert opening.is_opening is True
    assert opening.placement is NarrationSlotPlacement.AFTER_TRACK
    assert opening.chapter_track is not None
    assert opening.just_played_track is not None
    assert opening.just_played_track.canonical_title == "Anchor Song"
    assert opening.upcoming_track is not None

    direct = examples["direct-track-intro"].slot_context
    assert direct.placement is NarrationSlotPlacement.BEFORE_TRACK
    assert direct.just_played_track is not None
    assert direct.upcoming_track is not None
    assert direct.chapter_track is not None

    middle = examples["narrative-only-transition"].slot_context
    assert middle.placement is NarrationSlotPlacement.AFTER_TRACK
    assert middle.chapter_track is None
    assert middle.just_played_track is not None
    assert middle.upcoming_track is not None

    outro = examples["final-outro"].slot_context
    assert outro.placement is NarrationSlotPlacement.AFTER_FINAL_TRACK
    assert outro.is_final is True
    assert outro.just_played_track is not None
    assert outro.upcoming_track is None


def test_phase53c_empty_evidence_case_is_explicitly_conservative() -> None:
    example = next(
        item
        for item in PHASE53C_RADIO_WRITING_REVIEW_EXAMPLES
        if item.example_id == "opening-empty-evidence"
    )

    assert example.evidence_mode.value == "empty"
    assert "不够" in example.stronger_text
    assert "下结论" in example.stronger_text


def test_phase53c_rejects_block_kind_outside_slot_contract() -> None:
    with pytest.raises(ValueError, match="not allowed by slot"):
        RadioWritingReviewExample(
            example_id="invalid-slot-kind",
            slot_context=NarrationSlotContext(
                slot_id="intro-only",
                chapter_index=0,
                placement=NarrationSlotPlacement.BEFORE_TRACK,
                allowed_block_kinds=[RadioScriptBlockKind.INTRO],
                is_opening=True,
            ),
            block_kind=RadioScriptBlockKind.OUTRO,
            weak_text="weak",
            stronger_text="strong",
            criteria=[RadioWritingCriterion.ONE_SPOKEN_BEAT],
            evidence_mode="empty",
            reviewer_note="invalid fixture",
        )

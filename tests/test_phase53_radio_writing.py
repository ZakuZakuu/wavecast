import pytest
from pydantic import ValidationError
from wavecast.evals import (
    PHASE53_RADIO_WRITING_FIXTURES,
    PHASE53_RADIO_WRITING_RUBRIC,
    RadioWritingCriterion,
    RadioWritingRubric,
)


def test_phase53_rubric_is_typed_and_language_scoped() -> None:
    rubric = PHASE53_RADIO_WRITING_RUBRIC

    assert rubric.language == "zh-CN"
    assert len(rubric.items) == len(RadioWritingCriterion)
    assert len({item.criterion for item in rubric.items}) == len(rubric.items)
    assert {item.criterion for item in rubric.items} == set(RadioWritingCriterion)
    assert rubric.human_review_questions


def test_phase53_rubric_rejects_non_chinese_language_scope() -> None:
    with pytest.raises(ValidationError):
        RadioWritingRubric(
            language="en-US",
            items=PHASE53_RADIO_WRITING_RUBRIC.items,
            human_review_questions=PHASE53_RADIO_WRITING_RUBRIC.human_review_questions,
        )


def test_phase53_fixtures_are_self_authored_contrasts() -> None:
    assert len(PHASE53_RADIO_WRITING_FIXTURES) >= 4
    fixture_criteria = {fixture.criterion for fixture in PHASE53_RADIO_WRITING_FIXTURES}
    assert RadioWritingCriterion.CULTURAL_PRECISION in fixture_criteria
    assert RadioWritingCriterion.LISTEN_FOR_CUE in fixture_criteria
    assert RadioWritingCriterion.OUTRO_CALLBACK in fixture_criteria

    for fixture in PHASE53_RADIO_WRITING_FIXTURES:
        assert fixture.weak_text != fixture.stronger_text
        assert fixture.rationale

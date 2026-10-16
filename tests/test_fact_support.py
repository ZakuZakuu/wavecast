"""Source checks run before writing; finished scripts are not reviewed sentence by sentence."""

import pytest
from wavecast.intelligence.fact_support import (
    credited_people,
    people_missing_from_quote,
    qualifiers_missing,
    quote_backs_roles,
    quote_in_source,
    roles_in,
    similar_claim,
)


def test_a_quote_must_be_contiguous_in_its_named_source() -> None:
    source = "方大同說，他理解的愛不只是男女之間的愛情。"
    assert quote_in_source("他理解的爱不只是男女之间的爱情", source)
    assert not quote_in_source("他理解的爱只是男女之间的爱情", source)
    assert not quote_in_source("爱", source)


@pytest.mark.parametrize(("statement", "quote", "backed"), [
    ("木村弓作曲并演唱", "木村 弓が作曲および歌唱を担当", True),
    ("久石让作曲", "由久石让编曲", False),
    ("周耀辉作词", "同名单曲由方大同作曲，周耀辉作词", True),
])
def test_creative_roles_cannot_be_substituted(statement, quote, backed) -> None:
    assert quote_backs_roles(quote, roles_in(statement)) is backed


def test_a_credit_needs_the_right_person_as_well_as_the_right_role() -> None:
    people = credited_people(["久石譲, 木村弓"])
    assert people_missing_from_quote("久石让作曲", "木村弓作曲并演唱", people) == ["久石让"]
    assert people_missing_from_quote("木村弓作曲", "木村弓作曲并演唱", people) == []


def test_material_cannot_add_a_qualifier_or_instrument_absent_from_its_quote() -> None:
    assert "first" in qualifiers_missing("这是他第一次合作", "两人展开合作")
    assert "钢琴" in qualifiers_missing("他用钢琴演奏", "由他演奏")
    assert qualifiers_missing("他用钢琴演奏", "他用钢琴演奏") == []


def test_duplicate_material_is_recognized_without_a_model_call() -> None:
    assert similar_claim("他在工作室认识了这位导演", "这位导演和他在工作室认识")
    assert not similar_claim("他们在工作室见面", "这首歌是电影的片尾曲")

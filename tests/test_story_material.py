"""The ``material`` role: what survives verification, and how the facts are bound to evidence."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError
from wavecast.intelligence.story_material import (
    StoryMaterialDraft,
    StoryMaterialService,
    verify_material,
)
from wavecast.models.story_material import MaterialFact, StoryMaterial, StoryScope
from wavecast.providers.errors import ProviderTimeoutError
from wavecast.providers.strict_schema import to_strict_schema

from tests.dialogue_fixtures import (
    STORY_ID,
    TRACK_REF,
    ScriptedLLM,
    _fact,
    evidence,
    material_draft,
)


def verified(draft: StoryMaterialDraft | None = None, **kwargs) -> StoryMaterial | None:
    return verify_material(
        draft or material_draft(),
        evidence(),
        story_id=STORY_ID,
        recording_refs=kwargs.pop("recording_refs", [TRACK_REF]),
    )


def test_a_clean_draft_keeps_every_fact_with_application_assigned_ids() -> None:
    material = verified()

    assert material is not None
    assert material.fact_ids == [f"{STORY_ID}-F{n}" for n in range(1, 8)]
    assert all(fact.evidence_id in {"E1", "E2", "E3", "E4"} for fact in material.facts)
    assert material.editorial_angle and material.do_not_infer and material.backstage == ["资料来自网页摘录"]


def test_the_material_carries_no_dialogue_lines() -> None:
    fields = set(StoryMaterial.model_fields) | set(MaterialFact.model_fields)

    assert not {name for name in fields if name in {"turns", "lines", "script", "dialogue", "text"}}


def test_recording_facts_get_the_matching_version_and_object() -> None:
    material = verified()

    assert material is not None
    single = material.fact(f"{STORY_ID}-F6")
    assert single is not None
    assert single.scope is StoryScope.RECORDING and single.version_scope == TRACK_REF
    album = material.fact(f"{STORY_ID}-F5")
    assert album is not None and album.scope is StoryScope.ALBUM


def _draft_with(*facts) -> StoryMaterialDraft:
    base = material_draft()
    return base.model_copy(update={"facts": list(facts)})


@pytest.mark.parametrize(
    ("bad", "label"),
    [
        (_fact("x。", "E-NOPE", "把“爱”的边界拉到了更宽的地方", "recording"), "unknown evidence id"),
        (_fact("爱的边界更宽。", "E1", "把“爱”的边界拉到了很宽的地方", "recording"), "quote not verbatim"),
        (_fact("他第一次合作是《春风吹》。", "E4", "方大同与周耀辉的合作是《春风吹》", "album"), "qualifier missing"),
        (_fact("这张专辑由他编曲。", "E3", "方大同说，他理解的爱不只是男女之间的爱情", "album"), "role not in quote"),
        (_fact("他的歌是曲目编号 7。", "E4", "同名单曲《爱爱爱》由方大同作曲，周耀辉作词", "recording"), "catalogue housekeeping"),
    ],
)
def test_unverifiable_facts_are_dropped_not_repaired(bad, label: str) -> None:
    keep = material_draft().facts[:2]

    material = verified(_draft_with(bad, *keep))

    assert material is not None, label
    assert len(material.facts) == 2, label
    assert bad.statement not in [fact.statement for fact in material.facts], label


def test_a_catalogue_remark_is_moved_to_backstage_never_kept_as_a_fact() -> None:
    trivia = _fact("曲目编号 7。", "E4", "同名单曲《爱爱爱》由方大同作曲，周耀辉作词", "recording")
    material = verified(_draft_with(trivia, *material_draft().facts[:2]))

    assert material is not None and "曲目编号 7。" in material.backstage


def test_a_recording_fact_from_another_recording_is_dropped() -> None:
    material = verified(recording_refs=["netease:somebody-else"])

    assert material is not None
    assert material.fact(f"{STORY_ID}-F6") is None or all(
        fact.statement != "同名单曲《爱爱爱》由方大同作曲，周耀辉作词。" for fact in material.facts
    )


def test_too_few_verified_facts_yield_no_material() -> None:
    only_one = _draft_with(material_draft().facts[0])

    assert verified(only_one) is None
    assert verified(_draft_with(_fact("x。", "E-NOPE", "不在资料里的话语啊啊", "background"))) is None


def test_the_model_cannot_choose_fact_ids_and_the_input_is_not_mutated() -> None:
    draft = material_draft()
    before = draft.model_dump()

    material = verified(draft)

    assert draft.model_dump() == before
    assert material is not None and set(material.fact_ids) == {f"{STORY_ID}-F{n}" for n in range(1, 8)}
    assert "fact_id" not in StoryMaterialDraft.model_json_schema()["$defs"]["DraftFact"]["properties"]


def test_material_bounds() -> None:
    fact = material_draft().facts[0]
    base = verified()
    assert base is not None
    dump = base.model_dump(mode="json")
    with pytest.raises(ValidationError):
        StoryMaterial.model_validate({**dump, "facts": dump["facts"] + [dump["facts"][0]]})  # duplicate id
    with pytest.raises(ValidationError):
        StoryMaterial.model_validate({**dump, "facts": []})
    with pytest.raises(ValidationError):
        StoryMaterial.model_validate({**dump, "facts": dump["facts"] * 3})
    assert fact


def test_the_draft_schema_is_strict_compatible() -> None:
    strict = to_strict_schema(StoryMaterialDraft.model_json_schema())

    assert strict["required"] == list(strict["properties"])


def test_extract_runs_one_call_and_verifies() -> None:
    llm = ScriptedLLM(material_draft())
    service = StoryMaterialService(llm)

    material = asyncio.run(
        service.extract(evidence(), story_id=STORY_ID, subject="方大同", recording_refs=[TRACK_REF])
    )

    assert material is not None and len(material.facts) == 7
    assert llm.calls == [("StoryMaterialDraft", "story_material")]


def test_extract_with_no_evidence_makes_no_call() -> None:
    llm = ScriptedLLM()
    service = StoryMaterialService(llm)

    assert asyncio.run(service.extract([], story_id=STORY_ID, subject="x")) is None
    assert llm.calls == []


def test_provider_failure_propagates_for_the_caller_to_decide() -> None:
    service = StoryMaterialService(ScriptedLLM(ProviderTimeoutError("slow")))

    with pytest.raises(ProviderTimeoutError):
        asyncio.run(service.extract(evidence(), story_id=STORY_ID, subject="方大同"))

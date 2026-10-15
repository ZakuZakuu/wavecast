"""Shared material → Lite two-host draft → fact check (→ bounded repair) → a saved, checked passage.

Everything runs on fixed responses.  Which statements a real model would make, and whether Ark
accepts these schemas, are not tested here (see ADR 0025).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from wavecast.intelligence.dialogue_check import DialogueFactChecker
from wavecast.intelligence.dialogue_pipeline import (
    DialogueOutcome,
    DialoguePipeline,
    DialogueStatus,
    create_dialogue_stack,
)
from wavecast.intelligence.dialogue_writer import (
    DialogueRepair,
    DialogueRepairer,
    DialogueSlot,
    DialogueWriter,
    TurnFix,
)
from wavecast.intelligence.story_material import StoryMaterialService
from wavecast.models.dialogue import DialogueDraft, DialoguePurpose, DraftTurn
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderTimeoutError
from wavecast.providers.usage import UsageLedger
from wavecast.stations import StationId
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import (
    CheckedDialogueRecord,
    DialogueArtifactError,
    DialogueArtifactStore,
    artifact_key,
)

from tests.dialogue_fixtures import (
    STORY_ID,
    TRACK_REF,
    JudgingLLM,
    ScriptedLLM,
    clean_draft,
    draft_with_two_problems,
    evidence,
    f,
    good_repair,
    material_draft,
    unavailable,
)

SLOT = DialogueSlot(
    slot_id="slot-1",
    block_id="block-1",
    purpose=DialoguePurpose.STORY,
    station=StationId.PORTRAIT,
    just_played="我们能不能",
    upcoming="爱爱爱",
)


def material() -> StoryMaterial:
    from wavecast.intelligence.story_material import verify_material

    result = verify_material(material_draft(), evidence(), story_id=STORY_ID, recording_refs=[TRACK_REF])
    assert result is not None
    return result


def build(
    draft: DialogueDraft,
    *,
    repair: DialogueRepair | None = None,
    insufficient: tuple[str, ...] = ("更成熟", "一直坚持"),
    max_calls: int = 4,
    checker_llm: JudgingLLM | None = None,
    writer_llm: ScriptedLLM | None = None,
) -> tuple[DialoguePipeline, ScriptedLLM, JudgingLLM]:
    mat = material()
    known: list = [draft, clean_draft()]
    if repair is not None:
        known.append(repair)
    writer_llm = writer_llm or ScriptedLLM(draft)
    if repair is not None:
        writer_llm.queue(DialogueRepair, repair)
    judge = checker_llm or JudgingLLM(mat, known, insufficient=insufficient)
    pipeline = DialoguePipeline(
        writer=DialogueWriter(writer_llm),
        checker=DialogueFactChecker(judge),
        repairer=DialogueRepairer(writer_llm),
        max_calls=max_calls,
    )
    return pipeline, writer_llm, judge


def run(pipeline: DialoguePipeline, slot: DialogueSlot = SLOT) -> DialogueOutcome:
    return asyncio.run(pipeline.produce(material(), slot))


# --- the path through ---------------------------------------------------------------------------


def test_a_passage_that_passes_the_first_check_is_returned_untouched() -> None:
    draft = clean_draft()
    pipeline, writer, judge = build(draft)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.speakable
    assert outcome.calls == 2  # draft + check; no repair, no re-check
    assert [(t.speaker, t.text, t.fact_refs, t.tts_text) for t in outcome.block.turns] == [  # type: ignore[union-attr]
        (t.speaker, t.text, t.fact_refs, None) for t in draft.turns
    ]
    assert writer.calls == [("DialogueDraft", "dialogue_writer")]
    assert judge.calls == [("DialogueCheck", "dialogue_fact_check")]
    assert outcome.first_check_issues == [] and outcome.repaired_turns == []


def test_the_two_problems_in_the_accepted_style_draft_are_found_and_only_those_turns_repaired() -> None:
    draft = draft_with_two_problems()
    pipeline, writer, _ = build(draft, repair=good_repair())

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REPAIRED and outcome.calls == 4
    assert outcome.repaired_turns == [1, 4]
    # What was wrong - 一直坚持 and 更成熟 - is what the Pro check says; code only structures it.
    codes = {(i.turn, i.code) for i in outcome.first_check_issues}
    assert codes == {(1, "insufficient"), (4, "insufficient")}
    block = outcome.block
    assert block is not None
    # Roles, turn count and ids are kept; untouched turns are exactly as written.
    assert [t.speaker for t in block.turns] == [t.speaker for t in draft.turns]
    assert (block.block_id, block.slot_id) == ("block-1", "slot-1")
    for index in (0, 2, 3, 5, 6):
        assert (block.turns[index].speaker, block.turns[index].text, block.turns[index].fact_refs) == (
            draft.turns[index].speaker,
            draft.turns[index].text,
            draft.turns[index].fact_refs,
        )
    assert "一直" not in block.text and "更成熟" not in block.text
    assert all(t.tts_text is None for t in block.turns)
    assert [name for name, _ in writer.calls] == ["DialogueDraft", "DialogueRepair"]


def test_pattern_hints_alone_never_send_a_passage_to_repair() -> None:
    # The draft says 一直坚持 / 更成熟; the Pro check, which decides meaning, finds them supported.
    pipeline, writer, _ = build(draft_with_two_problems(), insufficient=())

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.calls == 2
    assert outcome.first_check_issues == [] and outcome.repaired_turns == []
    assert [name for name, _ in writer.calls] == ["DialogueDraft"]  # no repair call was made


def test_the_first_telling_is_the_writers_the_material_holds_no_lines() -> None:
    pipeline, writer, _ = build(clean_draft())
    run(pipeline)
    # The writer was called once with the material; nothing pre-wrote the turns.
    assert writer.calls[0][0] == "DialogueDraft"
    assert not hasattr(material(), "turns")


# --- failure paths ----------------------------------------------------------------------------------


def test_a_repair_that_does_not_clear_the_check_rejects_the_passage() -> None:
    same = DialogueRepair(
        fixes=[
            TurnFix(turn=1, text=draft_with_two_problems().turns[1].text, fact_refs=[f(4), f(2)]),
            TurnFix(turn=4, text=draft_with_two_problems().turns[4].text, fact_refs=[f(5)]),
        ]
    )
    pipeline, _, _ = build(draft_with_two_problems(), repair=same)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED and outcome.reason == "unresolved_after_repair"
    assert outcome.calls == 4 and outcome.final_issues and not outcome.speakable
    with pytest.raises(ValueError):
        outcome.to_record()


def test_unknown_fact_refs_reject_the_draft_before_any_check() -> None:
    bad = DialogueDraft(turns=[DraftTurn(speaker="A", text="一句话。", fact_refs=["nope-F9"])])  # type: ignore[arg-type]
    pipeline, _, judge = build(bad)

    outcome = run(pipeline)

    assert outcome.reason == "invalid_draft" and outcome.calls == 1 and judge.calls == []
    assert "nope-F9" in outcome.final_issues[0].message


def test_a_story_without_any_reference_is_rejected_and_never_filled_in() -> None:
    bare = DialogueDraft(turns=[DraftTurn(speaker="A", text="一段没有出处的话。", fact_refs=[])])  # type: ignore[arg-type]
    pipeline, _, _ = build(bare)

    outcome = run(pipeline)

    assert outcome.reason == "invalid_draft" and outcome.block is None


def test_a_short_passage_is_fine_there_is_no_minimum() -> None:
    short = DialogueDraft(turns=[DraftTurn(speaker="A", text="方大同说，他理解的爱不只是男女之间的爱情。", fact_refs=[f(4)])])  # type: ignore[arg-type]
    pipeline, _, _ = build(short)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.block.duration_seconds < 10  # type: ignore[union-attr]


def test_a_runaway_draft_over_the_stations_hard_ceiling_is_rejected() -> None:
    long = DialogueDraft(
        turns=[
            DraftTurn(speaker="A" if i % 2 == 0 else "B", text="方大同说，他理解的爱不只是男女之间的爱情。" * 6, fact_refs=[f(4)])  # type: ignore[arg-type]
            for i in range(10)
        ]
    )
    pipeline, _, judge = build(long)

    outcome = run(pipeline, SLOT.__class__(**{**SLOT.__dict__, "station": StationId.CASUAL}))

    assert outcome.reason == "too_long" and outcome.calls == 1 and judge.calls == []


def test_too_many_flagged_turns_are_not_patched() -> None:
    pipeline, _, _ = build(draft_with_two_problems(), insufficient=("爱", "国语", "创作", "专辑", "合作", "角度"))

    outcome = run(pipeline)

    assert outcome.reason == "too_many_flagged_turns" and outcome.calls == 2


def test_the_call_budget_bounds_the_passage() -> None:
    pipeline, _, _ = build(draft_with_two_problems(), repair=good_repair(), max_calls=2)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED and outcome.reason == "budget_exhausted"
    assert outcome.calls == 2


def test_a_repair_that_touches_an_unflagged_turn_or_unknown_fact_is_invalid() -> None:
    touches_clean_turn = DialogueRepair(fixes=[TurnFix(turn=0, text="改了不该改的一轮。", fact_refs=[f(1)])])
    unknown_ref = DialogueRepair(fixes=[TurnFix(turn=1, text="好的。", fact_refs=["zzz"]), TurnFix(turn=4, text="好的。", fact_refs=[f(5)])])
    for repair in (touches_clean_turn, unknown_ref):
        pipeline, _, _ = build(draft_with_two_problems(), repair=repair)
        outcome = run(pipeline)
        assert outcome.reason == "invalid_repair" and outcome.calls == 3


def test_a_provider_failure_rejects_the_passage_instead_of_raising() -> None:
    pipeline, _, _ = build(clean_draft(), writer_llm=ScriptedLLM(ProviderTimeoutError("slow")))

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED
    assert outcome.reason == "provider_failed:ProviderTimeoutError" and outcome.calls == 1


def test_an_unavailable_checker_never_lets_factual_sentences_through() -> None:
    mat = material()
    judge = JudgingLLM(mat, [clean_draft()])
    judge.fail = unavailable()
    pipeline, _, _ = build(clean_draft(), checker_llm=judge, repair=good_repair())

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED and not outcome.model_checked
    assert outcome.reason == "checker_unavailable" and outcome.calls == 2  # no repair for "unknown"


def test_cancellation_is_not_swallowed() -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        class Hangs:
            async def structured(self, *args, **kwargs):  # noqa: ANN002, ANN003
                started.set()
                await asyncio.sleep(30)

        pipeline = DialoguePipeline(
            writer=DialogueWriter(Hangs()),  # type: ignore[arg-type]
            checker=DialogueFactChecker(ScriptedLLM()),
            repairer=DialogueRepairer(ScriptedLLM()),
        )
        task = asyncio.create_task(pipeline.produce(material(), SLOT))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_the_night_station_has_no_dialogue_and_makes_no_calls() -> None:
    pipeline, writer, judge = build(clean_draft())

    outcome = run(pipeline, SLOT.__class__(**{**SLOT.__dict__, "station": StationId.NIGHT}))

    assert outcome.status is DialogueStatus.SKIPPED and outcome.calls == 0
    assert writer.calls == [] and judge.calls == []


# --- save and read back ------------------------------------------------------------------------------


def test_a_checked_passage_is_saved_and_read_back_whole(tmp_path: Path) -> None:
    pipeline, _, _ = build(draft_with_two_problems(), repair=good_repair())
    outcome = run(pipeline)
    store = DialogueArtifactStore(LocalObjectStorageProvider(tmp_path / "store"))

    key = asyncio.run(store.save("ep-1", outcome.to_record()))
    loaded = asyncio.run(store.load("ep-1", "block-1"))

    assert key == artifact_key("ep-1", "block-1")
    assert loaded == outcome.to_record()
    assert loaded is not None
    original = outcome.block
    assert original is not None
    assert [(t.speaker, t.text, t.fact_refs) for t in loaded.block.turns] == [
        (t.speaker, t.text, t.fact_refs) for t in original.turns
    ]
    assert (loaded.block.block_id, loaded.block.slot_id) == ("block-1", "slot-1")
    assert loaded.repaired_turns == [1, 4] and loaded.status == "repaired"
    assert set(loaded.block.fact_refs) <= set(loaded.material.fact_ids)
    assert {i.turn for i in loaded.first_check_issues} == {1, 4}
    assert loaded.material.backstage  # kept for inspection, with the material it came from


def test_reading_back_refuses_damaged_foreign_or_unversioned_records(tmp_path: Path) -> None:
    pipeline, _, _ = build(clean_draft())
    record = run(pipeline).to_record()
    storage = LocalObjectStorageProvider(tmp_path / "store")
    store = DialogueArtifactStore(storage)
    asyncio.run(store.save("ep-1", record))
    assert asyncio.run(store.load("ep-1", "nothing-here")) is None

    def put(payload: bytes, block_id: str = "block-1") -> None:
        asyncio.run(storage.put(artifact_key("ep-1", block_id), payload, "application/json"))

    put(b"{not json")
    with pytest.raises(DialogueArtifactError, match="damaged"):
        asyncio.run(store.load("ep-1", "block-1"))

    future = record.model_dump(mode="json") | {"schema_version": 2}
    put(__import__("json").dumps(future).encode())
    with pytest.raises(DialogueArtifactError, match="schema_version 2"):
        asyncio.run(store.load("ep-1", "block-1"))

    broken = record.model_dump(mode="json")
    broken["block"]["turns"][0]["fact_refs"] = ["fdt-F99"]
    put(__import__("json").dumps(broken).encode())
    with pytest.raises(DialogueArtifactError):
        asyncio.run(store.load("ep-1", "block-1"))

    other = record.model_dump(mode="json")
    put(__import__("json").dumps(other).encode(), "block-2")
    with pytest.raises(DialogueArtifactError, match="another block"):
        asyncio.run(store.load("ep-1", "block-2"))


def test_storage_keys_cannot_escape() -> None:
    for bad in ("../x", "a/b", "", " x", "x" * 121):
        with pytest.raises(ValueError):
            artifact_key("ep-1", bad)
        with pytest.raises(ValueError):
            artifact_key(bad, "block-1")


def test_a_record_cannot_be_built_with_references_the_material_lacks() -> None:
    pipeline, _, _ = build(clean_draft())
    data = run(pipeline).to_record().model_dump(mode="json")
    data["material"]["facts"] = data["material"]["facts"][:1]

    with pytest.raises(ValueError):
        CheckedDialogueRecord.model_validate(data)


# --- roles -------------------------------------------------------------------------------------------


def test_the_material_writer_and_checker_models_are_separate_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: dict[str, ScriptedLLM] = {}

    def factory(kind: str):
        def make(*_args, **kwargs):  # noqa: ANN002, ANN003
            fake = ScriptedLLM()
            fake.kind = kind  # type: ignore[attr-defined]
            fake.role = kwargs.get("role")  # type: ignore[attr-defined]
            made[f"{kind}:{kwargs.get('role', 'deepseek')}"] = fake
            return fake

        return make

    monkeypatch.setattr("wavecast.providers.llm_factory.DeepSeekLLMProvider", factory("deepseek"))
    monkeypatch.setattr("wavecast.providers.llm_factory.ArkLLMProvider", factory("ark"))
    settings = ProviderSettings(
        mode="live",
        writer_provider="ark",
        material_provider="deepseek",
        ark_api_key="k",
        ark_models={"writer": "doubao-seed-2-1-lite-260915"},
    )

    stack = create_dialogue_stack(settings, ledger=UsageLedger(), mock=ScriptedLLM())

    assert isinstance(stack.material, StoryMaterialService)
    assert stack.pipeline._writer._llm.kind == "ark"  # type: ignore[attr-defined]
    assert stack.pipeline._repairer._llm is stack.pipeline._writer._llm  # repair = the Writer's model
    assert stack.pipeline._checker._llm.kind == "deepseek"  # type: ignore[attr-defined]
    assert stack.material._llm.kind == "deepseek"  # type: ignore[attr-defined]
    assert stack.pipeline._checker._llm is not stack.pipeline._writer._llm


def test_the_stack_closes_each_client_once(monkeypatch: pytest.MonkeyPatch) -> None:
    closes: list[int] = []

    class Shared:
        async def aclose(self) -> None:
            closes.append(1)

    shared = Shared()
    monkeypatch.setattr("wavecast.providers.llm_factory.DeepSeekLLMProvider", lambda *_a, **_k: shared)
    stack = create_dialogue_stack(ProviderSettings(mode="live"), ledger=UsageLedger(), mock=ScriptedLLM())

    asyncio.run(stack.aclose())

    assert closes == [1]


# --- review fixes: what is spoken is what was checked; ceilings after repair; no degraded story ----


def test_the_writer_cannot_supply_what_is_spoken() -> None:
    # A model-written turn has no tts_text field at all, and extra fields are refused.
    assert "tts_text" not in DraftTurn.model_fields
    with pytest.raises(ValueError):
        DraftTurn.model_validate({"speaker": "A", "text": "好。", "fact_refs": [], "tts_text": "不同的朗读"})
    pipeline, _, _ = build(clean_draft())

    outcome = run(pipeline)

    assert outcome.block is not None and all(t.tts_text is None for t in outcome.block.turns)


def test_a_block_that_carries_unchecked_spoken_text_is_refused_by_validation() -> None:
    from wavecast.intelligence.dialogue import DialogueValidationError, validate_dialogue_block
    from wavecast.models.dialogue import DialogueBlock, DialogueTurn

    block = DialogueBlock(
        block_id="b",
        slot_id="s",
        purpose=DialoguePurpose.TRANSITION,
        turns=[DialogueTurn(speaker="A", text="三号海岸。", tts_text="完全不同的话", fact_refs=[])],  # type: ignore[arg-type]
        duration_seconds=5,
    )

    with pytest.raises(DialogueValidationError, match="never fact-checked"):
        validate_dialogue_block(block, allowed_fact_refs=[])
    # Only a deterministic conversion of the checked text may opt in.
    assert validate_dialogue_block(block, allowed_fact_refs=[], allow_tts_text=True) is block


def test_a_repair_that_lengthens_the_passage_past_the_ceiling_is_rejected_without_a_recheck() -> None:
    long_fix = DialogueRepair(
        fixes=[
            TurnFix(turn=1, text="方大同说，他理解的爱不只是男女之间的爱情。" * 40, fact_refs=[f(4)]),
            TurnFix(turn=4, text=clean_draft().turns[4].text, fact_refs=[f(5)]),
        ]
    )
    pipeline, _, judge = build(draft_with_two_problems(), repair=long_fix)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED and outcome.reason == "too_long_after_repair"
    assert outcome.calls == 3  # draft, check, repair - no spend on re-checking a passage that cannot stand
    assert len(judge.calls) == 1 and outcome.block is None


def _bare_fact_material() -> StoryMaterial:
    """Facts with none of the words (years, creation, roles...) that make code demand a source."""
    return StoryMaterial.model_validate(
        {
            "story_id": "plain",
            "subject": "方大同",
            "scope": "background",
            "central_question": "他在哪里长大？",
            "facts": [
                {
                    "fact_id": "plain-F1",
                    "statement": "方大同在上海长大。",
                    "evidence_id": "E9",
                    "quote": "方大同在上海长大",
                    "scope": "background",
                    "subject": "方大同",
                    "version_scope": None,
                }
            ],
        }
    )


def test_a_story_is_rejected_when_the_checker_is_down_even_if_no_keyword_marks_it_factual() -> None:
    mat = _bare_fact_material()
    draft = DialogueDraft(turns=[DraftTurn(speaker="A", text="方大同在上海长大。", fact_refs=["plain-F1"])])  # type: ignore[arg-type]
    from wavecast.intelligence.fact_support import must_be_supported

    assert not must_be_supported("方大同在上海长大。")  # nothing in the sentence trips a keyword

    writer = ScriptedLLM(draft)
    judge = JudgingLLM(mat, [draft])
    judge.fail = unavailable()
    pipeline = DialoguePipeline(
        writer=DialogueWriter(writer),
        checker=DialogueFactChecker(judge),
        repairer=DialogueRepairer(writer),
    )

    outcome = asyncio.run(pipeline.produce(mat, SLOT))

    assert outcome.status is DialogueStatus.REJECTED and outcome.reason == "checker_unavailable"
    assert outcome.calls == 2 and outcome.block is None and not outcome.speakable
    assert ("DialogueRepair", "dialogue_repair") not in writer.calls  # no repair spent either


def test_a_non_story_passage_may_pass_without_a_judgement_when_nothing_in_it_needs_a_source() -> None:
    mat = _bare_fact_material()
    draft = DialogueDraft(turns=[DraftTurn(speaker="A", text="接下来是下一首。", fact_refs=[])])  # type: ignore[arg-type]
    writer = ScriptedLLM(draft)
    judge = JudgingLLM(mat, [draft])
    judge.fail = unavailable()
    pipeline = DialoguePipeline(
        writer=DialogueWriter(writer),
        checker=DialogueFactChecker(judge),
        repairer=DialogueRepairer(writer),
    )
    slot = DialogueSlot(
        slot_id="s", block_id="b", purpose=DialoguePurpose.TRANSITION, station=StationId.PORTRAIT
    )

    outcome = asyncio.run(pipeline.produce(mat, slot))

    assert outcome.status is DialogueStatus.READY and not outcome.model_checked


def test_a_record_without_a_declared_version_is_refused_not_assumed_to_be_version_one(
    tmp_path: Path,
) -> None:
    import json

    pipeline, _, _ = build(clean_draft())
    record = run(pipeline).to_record()
    storage = LocalObjectStorageProvider(tmp_path / "store")
    store = DialogueArtifactStore(storage)
    raw = record.model_dump(mode="json")
    del raw["schema_version"]
    asyncio.run(storage.put(artifact_key("ep-1", "block-1"), json.dumps(raw).encode(), "application/json"))

    with pytest.raises(DialogueArtifactError, match="does not declare a schema_version"):
        asyncio.run(store.load("ep-1", "block-1"))
    with pytest.raises(ValueError):
        CheckedDialogueRecord.model_validate(raw)  # the model itself does not default it either
    for odd in ("1", None, 1.5, True):
        asyncio.run(
            storage.put(
                artifact_key("ep-1", "block-1"),
                json.dumps({**raw, "schema_version": odd}).encode(),
                "application/json",
            )
        )
        with pytest.raises(DialogueArtifactError):
            asyncio.run(store.load("ep-1", "block-1"))

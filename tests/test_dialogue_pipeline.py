"""Shared material → Lite two-host draft → basic validation → a saved passage ready to voice.

Everything runs on fixed responses.  Which statements a real model would make, and whether Ark
accepts these schemas, are not tested here (see ADR 0025).  There is no model check, repair or
re-check on this path (ADR 0029): the tests below pin what code still validates and what it
deliberately no longer judges.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from wavecast.intelligence.dialogue_pipeline import (
    DialogueOutcome,
    DialoguePipeline,
    DialogueStatus,
    create_dialogue_stack,
)
from wavecast.intelligence.dialogue_writer import DialogueSlot, DialogueWriter
from wavecast.intelligence.story_material import StoryMaterialService
from wavecast.models.dialogue import DialogueDraft, DialoguePurpose, DraftTurn
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderTimeoutError
from wavecast.providers.usage import UsageLedger
from wavecast.spoken_form import KnownTrack, has_unspeakable_script
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
    ScriptedLLM,
    clean_draft,
    draft_with_two_problems,
    evidence,
    f,
    material_draft,
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


def build(draft: DialogueDraft | BaseException) -> tuple[DialoguePipeline, ScriptedLLM]:
    writer_llm = ScriptedLLM(draft)
    return DialoguePipeline(writer=DialogueWriter(writer_llm)), writer_llm  # type: ignore[arg-type]


def run(pipeline: DialoguePipeline, slot: DialogueSlot = SLOT) -> DialogueOutcome:
    return asyncio.run(pipeline.produce(material(), slot))


# --- the path through ---------------------------------------------------------------------------


def test_a_valid_draft_goes_straight_to_ready_with_one_model_call_and_no_check() -> None:
    draft = clean_draft()
    pipeline, writer = build(draft)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.speakable
    assert outcome.calls == 1 and not outcome.model_checked  # honest: nothing judged it
    assert [(t.speaker, t.text, t.fact_refs, t.tts_text) for t in outcome.block.turns] == [  # type: ignore[union-attr]
        (t.speaker, t.text, t.fact_refs, None) for t in draft.turns
    ]
    assert writer.calls == [("DialogueDraft", "dialogue_writer")]  # no check, repair or re-check
    assert outcome.first_check_issues == [] and outcome.repaired_turns == []


def test_what_the_old_check_would_have_flagged_is_no_longer_judged() -> None:
    # 一直坚持 / 更成熟 are in the draft; semantics are the material's and the prompt's business.
    pipeline, writer = build(draft_with_two_problems())

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.calls == 1
    assert "一直坚持" in outcome.block.text and "更成熟" in outcome.block.text  # type: ignore[union-attr]
    assert [name for name, _ in writer.calls] == ["DialogueDraft"]


def test_the_first_telling_is_the_writers_the_material_holds_no_lines() -> None:
    pipeline, writer = build(clean_draft())
    run(pipeline)
    # The writer was called once with the material; nothing pre-wrote the turns.
    assert writer.calls[0][0] == "DialogueDraft"
    assert not hasattr(material(), "turns")


def test_the_passage_that_is_saved_says_it_was_not_model_checked(tmp_path: Path) -> None:
    pipeline, _ = build(clean_draft())
    record = run(pipeline).to_record()

    assert record.status == "ready" and record.model_checked is False
    assert record.repaired_turns == [] and record.first_check_issues == [] and record.calls_used == 1


# --- failure paths ----------------------------------------------------------------------------------


def test_unknown_fact_refs_reject_the_draft() -> None:
    bad = DialogueDraft(turns=[DraftTurn(speaker="A", text="一句话。", fact_refs=["nope-F9"])])  # type: ignore[arg-type]
    pipeline, _ = build(bad)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED
    assert outcome.reason == "invalid_draft" and outcome.calls == 1
    assert "nope-F9" in outcome.final_issues[0].message


def test_a_fact_that_exists_in_the_material_is_accepted_whichever_turn_cites_it() -> None:
    # Which turn lists which fact is the Writer's bookkeeping; only ids outside the material count.
    draft = DialogueDraft(
        turns=[
            DraftTurn(speaker="A", text="方大同说，他理解的爱不只是男女之间的爱情。", fact_refs=[f(2)]),  # type: ignore[arg-type]
            DraftTurn(speaker="B", text="对，音乐对他来说是沟通。", fact_refs=[f(4)]),  # type: ignore[arg-type]
        ]
    )
    pipeline, _ = build(draft)

    assert run(pipeline).status is DialogueStatus.READY


def test_a_story_without_any_reference_is_rejected_and_never_filled_in() -> None:
    bare = DialogueDraft(turns=[DraftTurn(speaker="A", text="一段没有出处的话。", fact_refs=[])])  # type: ignore[arg-type]
    pipeline, _ = build(bare)

    outcome = run(pipeline)

    assert outcome.reason == "invalid_draft" and outcome.block is None


def test_a_short_passage_is_fine_there_is_no_minimum() -> None:
    short = DialogueDraft(turns=[DraftTurn(speaker="A", text="方大同说，他理解的爱不只是男女之间的爱情。", fact_refs=[f(4)])])  # type: ignore[arg-type]
    pipeline, _ = build(short)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.READY and outcome.block.duration_seconds < 10  # type: ignore[union-attr]


def test_a_runaway_draft_over_the_stations_hard_ceiling_is_rejected() -> None:
    long = DialogueDraft(
        turns=[
            DraftTurn(speaker="A" if i % 2 == 0 else "B", text="方大同说，他理解的爱不只是男女之间的爱情。" * 6, fact_refs=[f(4)])  # type: ignore[arg-type]
            for i in range(10)
        ]
    )
    pipeline, _ = build(long)

    outcome = run(pipeline, SLOT.__class__(**{**SLOT.__dict__, "station": StationId.CASUAL}))

    assert outcome.status is DialogueStatus.REJECTED
    assert outcome.reason == "too_long" and outcome.calls == 1


def test_a_provider_failure_rejects_the_passage_instead_of_raising() -> None:
    pipeline, _ = build(ProviderTimeoutError("slow"))

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED
    assert outcome.reason == "provider_failed:ProviderTimeoutError" and outcome.calls == 1


def test_cancellation_is_not_swallowed() -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        class Hangs:
            async def structured(self, *args, **kwargs):  # noqa: ANN002, ANN003
                started.set()
                await asyncio.sleep(30)

        pipeline = DialoguePipeline(writer=DialogueWriter(Hangs()))  # type: ignore[arg-type]
        task = asyncio.create_task(pipeline.produce(material(), SLOT))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_the_night_station_has_no_dialogue_and_makes_no_calls() -> None:
    pipeline, writer = build(clean_draft())

    outcome = run(pipeline, SLOT.__class__(**{**SLOT.__dict__, "station": StationId.NIGHT}))

    assert outcome.status is DialogueStatus.SKIPPED and outcome.calls == 0
    assert writer.calls == []


def test_a_non_story_passage_needs_no_reference() -> None:
    draft = DialogueDraft(turns=[DraftTurn(speaker="A", text="接下来是下一首。", fact_refs=[])])  # type: ignore[arg-type]
    pipeline, _ = build(draft)
    slot = DialogueSlot(
        slot_id="s", block_id="b", purpose=DialoguePurpose.TRANSITION, station=StationId.PORTRAIT
    )

    outcome = asyncio.run(pipeline.produce(material(), slot))

    assert outcome.status is DialogueStatus.READY and not outcome.model_checked


# --- save and read back ------------------------------------------------------------------------------


def test_a_passage_is_saved_and_read_back_whole(tmp_path: Path) -> None:
    pipeline, _ = build(clean_draft())
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
    assert loaded.status == "ready" and loaded.model_checked is False
    assert set(loaded.block.fact_refs) <= set(loaded.material.fact_ids)
    assert loaded.material.backstage  # kept for inspection, with the material it came from


def test_a_record_saved_while_a_model_check_existed_still_loads_and_keeps_its_own_state(
    tmp_path: Path,
) -> None:
    pipeline, _ = build(clean_draft())
    old = run(pipeline).to_record().model_dump(mode="json") | {
        "status": "repaired",
        "repaired_turns": [1, 4],
        "model_checked": True,
        "calls_used": 4,
        "first_check_issues": [
            {"turn": 1, "sentence": 1, "code": "insufficient", "message": "once flagged"},
            {"turn": 4, "sentence": 0, "code": "insufficient", "message": "once flagged"},
        ],
    }
    storage = LocalObjectStorageProvider(tmp_path / "store")
    store = DialogueArtifactStore(storage)
    asyncio.run(storage.put(artifact_key("ep-1", "block-1"), json.dumps(old).encode(), "application/json"))

    loaded = asyncio.run(store.load("ep-1", "block-1"))

    assert loaded is not None
    assert loaded.status == "repaired" and loaded.model_checked is True  # as it really was
    assert loaded.repaired_turns == [1, 4] and {i.turn for i in loaded.first_check_issues} == {1, 4}
    restored = DialogueOutcome.from_record(loaded)
    assert restored.status is DialogueStatus.REPAIRED and restored.speakable and restored.calls == 0
    assert restored.model_checked is True and restored.repaired_turns == [1, 4]  # not rewritten as new


def test_reading_back_refuses_damaged_foreign_or_unversioned_records(tmp_path: Path) -> None:
    pipeline, _ = build(clean_draft())
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
    put(json.dumps(future).encode())
    with pytest.raises(DialogueArtifactError, match="schema_version 2"):
        asyncio.run(store.load("ep-1", "block-1"))

    broken = record.model_dump(mode="json")
    broken["block"]["turns"][0]["fact_refs"] = ["fdt-F99"]
    put(json.dumps(broken).encode())
    with pytest.raises(DialogueArtifactError):
        asyncio.run(store.load("ep-1", "block-1"))

    other = record.model_dump(mode="json")
    put(json.dumps(other).encode(), "block-2")
    with pytest.raises(DialogueArtifactError, match="another block"):
        asyncio.run(store.load("ep-1", "block-2"))


def test_storage_keys_cannot_escape() -> None:
    for bad in ("../x", "a/b", "", " x", "x" * 121):
        with pytest.raises(ValueError):
            artifact_key("ep-1", bad)
        with pytest.raises(ValueError):
            artifact_key(bad, "block-1")


def test_a_record_cannot_be_built_with_references_the_material_lacks() -> None:
    pipeline, _ = build(clean_draft())
    data = run(pipeline).to_record().model_dump(mode="json")
    data["material"]["facts"] = data["material"]["facts"][:1]

    with pytest.raises(ValueError):
        CheckedDialogueRecord.model_validate(data)


def test_a_record_without_a_declared_version_is_refused_not_assumed_to_be_version_one(
    tmp_path: Path,
) -> None:
    pipeline, _ = build(clean_draft())
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


# --- roles -------------------------------------------------------------------------------------------


def test_the_material_and_writer_models_are_separate_roles_and_no_checker_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: dict[str, ScriptedLLM] = {}

    def factory(kind: str):  # type: ignore[no-untyped-def]
        def make(*_args, **kwargs):  # type: ignore[no-untyped-def]  # noqa: ANN002, ANN003
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
    assert stack.material._llm.kind == "deepseek"  # type: ignore[attr-defined]
    assert len(stack.owned_clients) == 2  # the material and the writer; there is no fact-check model
    assert not hasattr(stack.pipeline, "_checker") and not hasattr(stack.pipeline, "_repairer")


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


# --- what is spoken is what was written ------------------------------------------------------------


def test_the_writer_cannot_supply_what_is_spoken() -> None:
    # A model-written turn has no tts_text field at all, and extra fields are refused.
    assert "tts_text" not in DraftTurn.model_fields
    with pytest.raises(ValueError):
        DraftTurn.model_validate({"speaker": "A", "text": "好。", "fact_refs": [], "tts_text": "不同的朗读"})
    pipeline, _ = build(clean_draft())

    outcome = run(pipeline)

    assert outcome.block is not None and all(t.tts_text is None for t in outcome.block.turns)


@pytest.mark.parametrize("spoken_title", [None, "同一夜晚"])
def test_known_foreign_names_get_spoken_forms_without_changing_the_turns_or_facts(
    tmp_path: Path, spoken_title: str | None
) -> None:
    text = "宇多田ヒカル的《同じ夜》把这个问题留在了歌里。"
    draft = DialogueDraft(turns=[DraftTurn(speaker="A", text=text, fact_refs=[f(1)])])  # type: ignore[arg-type]
    pipeline, writer = build(draft)
    slot = replace(SLOT, tracks=(KnownTrack("宇多田ヒカル", "同じ夜", spoken_title),))

    outcome = run(pipeline, slot)

    assert outcome.status is DialogueStatus.READY and outcome.block is not None
    turn = outcome.block.turns[0]
    assert turn.text == text and turn.fact_refs == [f(1)]
    assert turn.tts_text == f"宇多田光的{spoken_title or '这首歌'}把这个问题留在了歌里。"
    assert not has_unspeakable_script(turn.tts_text)
    assert writer.calls == [("DialogueDraft", "dialogue_writer")]
    store = DialogueArtifactStore(LocalObjectStorageProvider(tmp_path))
    asyncio.run(store.save("ep-foreign", outcome.to_record()))
    saved = asyncio.run(store.load("ep-foreign", SLOT.block_id))
    assert saved is not None and saved.block == outcome.block


def test_unresolved_foreign_names_leave_the_single_host_fallback_available() -> None:
    # A tour name is not a known track: do not strip its kana into a misleading partial name.
    text = "她在2003年的“雙六エクスタシー”巡演中与这些乐手合作。"
    draft = DialogueDraft(turns=[DraftTurn(speaker="A", text=text, fact_refs=[f(1)])])  # type: ignore[arg-type]
    pipeline, writer = build(draft)

    outcome = run(pipeline)

    assert outcome.status is DialogueStatus.REJECTED
    assert outcome.reason == "unspeakable_script" and outcome.block is None
    assert draft.turns[0].text == text
    assert writer.calls == [("DialogueDraft", "dialogue_writer")]


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

"""The fact check as a light safety net, offline.

Fixed text, the frozen 2026-10-14 evidence and the archived 2026-10-15 portrait run
(tests/fixtures/dialogue_portrait_20261015).  What this does not show: how a real Pro model
judges with the new context - that needs a separate, explicitly scoped live call.

The contract under test: the Pro call decides meaning (who said it, qualifiers, faithful
paraphrase); code decides structure only (ids, declared refs, quotes that are real stretches of
the source); pattern matches are hints that never reject a passage or start a repair.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from wavecast.intelligence.dialogue_check import DialogueCheck, DialogueFactChecker, SentenceFinding
from wavecast.intelligence.dialogue_writer import DialogueRepair, DialogueRepairer, TurnFix
from wavecast.intelligence.fact_support import source_context, watch_notes
from wavecast.intelligence.models import Evidence
from wavecast.intelligence.story_material import DraftFact, StoryMaterialDraft, verify_material
from wavecast.models.dialogue import DialogueBlock, DialoguePurpose, DialogueSpeaker, DialogueTurn
from wavecast.models.story_material import MaterialFact, StoryMaterial, StoryScope

from tests.dialogue_fixtures import ScriptedLLM

FIXTURES = Path(__file__).parent / "fixtures" / "dialogue_portrait_20261015"
NAME = "方大同"
QUOTE = "我希望自己的歌曲能夠喚起大家愛的共鳴"
SAID = "他说过，希望自己的歌曲能够唤起大家爱的共鸣。"
INTERVIEW = (
    "▲對台灣的感覺如何？ 有家的感覺。因為我在台灣是有親戚的。"
    "▲情歌對你而言是怎樣的一種力量？ 我認為音樂本身是一種溝通。所以我希望自己的歌曲能夠喚起大家愛的共鳴。"
    "只要有了愛，我們就能作更多的事。"
)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CapturingLLM(ScriptedLLM):
    def __init__(self, *responses: Any) -> None:
        super().__init__(*responses)
        self.prompts: list[str] = []

    async def structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        self.prompts.append(prompt)
        return await super().structured(prompt, output_type, **kwargs)


def block_saying(*texts: str, refs: list[str] | None = None) -> DialogueBlock:
    return DialogueBlock(
        block_id="b", slot_id="s", story_id="st", purpose=DialoguePurpose.STORY, duration_seconds=10,
        turns=[
            DialogueTurn(speaker=DialogueSpeaker.A, text=text, tts_text=None, fact_refs=refs if refs is not None else ["st-F1"])
            for text in texts
        ],
    )  # fmt: skip


def material_with(*, title: str | None = None, context: str | None = None) -> StoryMaterial:
    return StoryMaterial(
        story_id="st", subject="s", scope=StoryScope.BACKGROUND, central_question="q",
        facts=[
            MaterialFact(fact_id="st-F1", statement="他希望歌曲唤起共鸣", evidence_id="E1", quote=QUOTE,
                         scope=StoryScope.BACKGROUND, subject=NAME, source_title=title, context=context),
            MaterialFact(fact_id="st-F2", statement="他对台湾有家的感觉", evidence_id="E1",
                         quote="有家的感覺。因為我在台灣是有親戚的", scope=StoryScope.BACKGROUND, subject=NAME),
        ],
    )  # fmt: skip


def review(text: str, finding: SentenceFinding, material: StoryMaterial | None = None, llm: ScriptedLLM | None = None):  # noqa: ANN201
    llm = llm or ScriptedLLM(DialogueCheck(findings=[finding]))
    return asyncio.run(DialogueFactChecker(llm).review(block_saying(text), material or material_with()))  # type: ignore[arg-type]


def supported(quote: str = QUOTE, ids: tuple[str, ...] = ("st-F1",)) -> SentenceFinding:
    return SentenceFinding(sentence=0, verdict="supported", fact_ids=list(ids), quote=quote)


# --- semantics belong to the model ---------------------------------------------------------------


def test_a_he_said_sentence_passes_when_the_model_says_supported_though_the_quote_has_no_say_word() -> None:
    report = review(SAID, supported())

    assert report.issues == [] and report.flagged_turns() == {}
    assert report.model_checked and report.supported == {0: ["st-F1"]}


@pytest.mark.parametrize(
    "sentence",
    [
        "他第一次说过，希望自己的歌曲能够唤起大家爱的共鸣。",
        "周杰伦说过，希望自己的歌曲能够唤起大家爱的共鸣。",
        "他一直希望自己的歌曲能够唤起大家爱的共鸣，这首歌由他作曲。",
    ],
)
def test_a_pattern_that_the_quote_does_not_carry_is_a_hint_and_never_an_issue(sentence: str) -> None:
    report = review(sentence, supported())

    assert report.issues == [] and report.flagged_turns() == {}  # unknown is not a verdict
    assert report.hints, "the pointer is still recorded for whoever reads the report"
    assert {hint.code for hint in report.hints} <= {"qualifier_not_in_quote", "role_not_in_quote"}


def test_what_the_model_judges_insufficient_or_contradicted_is_the_only_thing_that_flags_a_turn() -> None:
    insufficient = SentenceFinding(sentence=0, verdict="insufficient", fact_ids=[], quote="")
    contradicted = SentenceFinding(sentence=0, verdict="contradicted", fact_ids=["st-F1"], quote=QUOTE)

    assert [i.code for i in review("他第一次说过这些。", insufficient).issues] == ["insufficient"]
    wrong = review("他说他不希望唤起共鸣。", contradicted)
    assert [i.code for i in wrong.issues] == ["contradicted"] and wrong.flagged_turns() == {0: wrong.issues[0].message}


def test_a_sentence_the_model_calls_not_factual_is_never_an_accusation() -> None:
    free = SentenceFinding(sentence=0, verdict="not_factual", fact_ids=[], quote="")

    report = review("这段旋律听起来特别温柔，像是一次小小的拥抱。", free)

    assert report.issues == [] and report.hints == []  # impression, style: not a reason to send it back


def test_a_sentence_the_model_left_out_is_unknown_not_an_issue() -> None:
    llm = ScriptedLLM(DialogueCheck(findings=[]))

    report = review("他说过，这首歌由他作曲。", supported(), llm=llm)

    assert report.issues == [] and [h.code for h in report.hints] == ["unchecked"]
    assert report.model_checked  # the call worked; this one sentence has no verdict


def test_an_unavailable_check_gives_no_issues_and_says_it_judged_nothing() -> None:
    llm = ScriptedLLM(RuntimeError("down"))

    report = review("他说过，这首歌由他作曲。", supported(), llm=llm)

    assert not report.model_checked and report.issues == []
    assert [h.code for h in report.hints] == ["unchecked"]  # the caller refuses to voice it on trust


# --- structure is code's, and still enforced ----------------------------------------------------------


def test_a_quote_that_is_not_in_the_cited_source_is_an_issue() -> None:
    report = review(SAID, supported(quote="这句话从来没有出现过在素材里"))

    assert [i.code for i in report.issues] == ["quote_not_in_source"]


def test_a_supported_verdict_with_an_unknown_fact_id_is_an_issue() -> None:
    assert [i.code for i in review(SAID, supported(ids=("st-F9",))).issues] == ["unknown_fact_id"]
    assert [i.code for i in review(SAID, supported(ids=())).issues] == ["unknown_fact_id"]


def test_relying_on_a_fact_the_turn_did_not_declare_is_an_issue() -> None:
    block = block_saying(SAID, refs=["st-F2"])
    llm = ScriptedLLM(DialogueCheck(findings=[supported()]))

    report = asyncio.run(DialogueFactChecker(llm).review(block, material_with()))  # type: ignore[arg-type]

    assert [i.code for i in report.issues] == ["undeclared_fact_ref"]


def test_a_quote_from_the_context_outside_the_source_text_does_not_count_as_a_quote() -> None:
    context = "▲情歌對你而言是怎樣的一種力量？ 我認為音樂本身是一種溝通。所以我希望自己的歌曲能夠喚起大家愛的共鳴。只要有了愛，我們就能作更多的事。"
    report = review(SAID, supported(quote="只要有了愛，我們就能作更多的事"), material_with(context=context))

    assert [i.code for i in report.issues] == ["quote_not_in_source"]  # context informs the judge; it is not evidence


# --- what the model is shown ---------------------------------------------------------------------------------------


def prompt_for(text: str, material: StoryMaterial, refs: list[str] | None = None) -> str:
    llm = CapturingLLM(DialogueCheck(findings=[supported()]))
    block = block_saying(text, refs=refs)
    asyncio.run(DialogueFactChecker(llm).review(block, material))  # type: ignore[arg-type]
    (prompt,) = llm.prompts
    return prompt


def test_the_cited_fact_comes_with_its_title_and_surrounding_text() -> None:
    material = material_with(title="找出音樂最平凡的感動－方大同", context=INTERVIEW)

    prompt = prompt_for(SAID, material)

    assert "source title: 找出音樂最平凡的感動－方大同" in prompt
    assert f"context: {INTERVIEW}" in prompt
    assert f"source text: {QUOTE}" in prompt


def test_a_fact_nobody_cites_is_not_shown_with_context() -> None:
    material = material_with(title="t", context="只在引用时才展示的上下文")

    prompt = prompt_for("这是一句过渡。", material, refs=["st-F2"])

    assert "只在引用时才展示的上下文" not in prompt  # no extra text for facts the dialogue never relies on


def test_a_word_that_often_needs_a_closer_look_is_marked_as_a_pointer_not_a_finding() -> None:
    prompt = prompt_for(SAID, material_with())

    assert "note: check against the source" in prompt
    assert "only a pointer, not a finding" in prompt
    plain = prompt_for("这首歌的旋律很温柔。", material_with())
    assert "note:" not in plain.split("Dialogue:")[1]


def test_the_prompt_reserves_insufficient_for_real_factual_gaps_not_style() -> None:
    prompt = prompt_for(SAID, material_with())

    assert "never for style" in prompt and "faithful paraphrase" in prompt.lower()
    assert "interviewee's own words" in prompt


def test_watch_notes_find_pointers_but_a_miss_means_nothing() -> None:
    assert watch_notes("他第一次说过，这首歌由他作曲。")
    assert watch_notes("这首歌的旋律很温柔。") == []


# --- the material records where a fact came from ---------------------------------------------------------------------


def evidence(text: str, title: str | None) -> Evidence:
    return Evidence(
        id="E1", claim_or_excerpt=text, source_url="https://example.test/e1", source_provider="exa",
        confidence=0.8, query=NAME, source_title=title,
    )  # fmt: skip


def draft_for() -> StoryMaterialDraft:
    return StoryMaterialDraft(
        subject=NAME, scope="background", central_question="为什么？",
        facts=[DraftFact(statement="他希望自己的歌曲能唤起大家的共鸣。", evidence_id="E1", quote=QUOTE,
                         scope="background", subject=NAME, version_scope=None),
               DraftFact(statement="他对台湾有家的感觉。", evidence_id="E1", quote="有家的感覺。因為我在台灣是有親戚的",
                         scope="background", subject=NAME, version_scope=None)],
        editorial_angle=None, do_not_infer=[], backstage=[],
    )  # fmt: skip


def test_verifying_material_keeps_the_title_and_the_text_around_the_quote() -> None:
    material = verify_material(draft_for(), [evidence(INTERVIEW, "找出音樂最平凡的感動－方大同")], story_id="s")

    assert material is not None
    fact = material.facts[0]
    assert fact.source_title == "找出音樂最平凡的感動－方大同"
    assert fact.context is not None and "情歌對你而言是怎樣的一種力量" in fact.context and QUOTE in fact.context


def test_source_context_is_bounded_and_script_insensitive() -> None:
    long_text = "前" * 600 + QUOTE + "后" * 600
    context = source_context(long_text, QUOTE)

    assert context is not None and QUOTE in context and len(context) <= 280 + len(QUOTE) + 100
    assert source_context(INTERVIEW, "所以我希望自己的歌曲能够唤起大家爱的共鸣") is not None  # simplified vs traditional
    assert source_context(INTERVIEW, "这句话从来没有出现过") is None


def test_material_saved_before_these_fields_existed_still_loads() -> None:
    saved = load("material.normalized.json")["material"]
    assert all("source_title" not in fact and "context" not in fact for fact in saved["facts"])

    material = StoryMaterial.model_validate(saved)

    assert all(fact.source_title is None and fact.context is None for fact in material.facts)


# --- the archived run -------------------------------------------------------------------------------------------------------


def archived_material() -> StoryMaterial:
    """The saved material with title and context derived from the frozen evidence it came from."""

    sources = {item["id"]: item for item in load("evidence.frozen.json")}
    material = StoryMaterial.model_validate(load("material.normalized.json")["material"])
    facts = []
    for fact in material.facts:
        source = sources[fact.evidence_id]
        facts.append(
            fact.model_copy(
                update={
                    "source_title": source["source_title"],
                    "context": source_context(source["claim_or_excerpt"], fact.quote),
                }
            )
        )
    return material.model_copy(update={"facts": facts})


def test_the_archived_interview_answers_are_given_to_the_model_with_their_questions_and_titles() -> None:
    material = archived_material()
    interview_facts = [material.fact(f"live-fdt-F{n}") for n in range(1, 9)]

    assert all(fact is not None and fact.context for fact in interview_facts)
    hope = material.fact("live-fdt-F6")
    assert hope is not None and hope.source_title and "方大同" in hope.source_title
    assert hope.context is not None and "▲" in hope.context  # the question the answer belongs to is in view


def test_the_two_sentences_the_old_rule_refused_are_no_longer_refused() -> None:
    candidate = load("candidate.unchecked.json")["turns"]
    first = candidate[5]["text"].split("。")[1] + "。"
    second = candidate[7]["text"].split("。")[0] + "。"
    assert first.startswith("他还说过") and second.startswith("他说过")
    material = archived_material()

    for sentence, cited in ((first, "live-fdt-F8"), (second, "live-fdt-F6")):
        fact = material.fact(cited)
        assert fact is not None
        finding = SentenceFinding(sentence=0, verdict="supported", fact_ids=[cited], quote=fact.quote[:60])
        block = block_saying(sentence, refs=[cited])
        report = asyncio.run(
            DialogueFactChecker(ScriptedLLM(DialogueCheck(findings=[finding]))).review(block, material)  # type: ignore[arg-type]
        )
        assert report.issues == [] and report.flagged_turns() == {}  # passes on Pro's "supported"


def test_a_pro_verdict_of_insufficient_on_an_archived_sentence_still_triggers_a_repair() -> None:
    material = archived_material()
    sentence = "他还说过，自己是在上海出生的。"  # not in any source
    finding = SentenceFinding(sentence=0, verdict="insufficient", fact_ids=[], quote="")
    block = block_saying(sentence, refs=["live-fdt-F8"])

    report = asyncio.run(
        DialogueFactChecker(ScriptedLLM(DialogueCheck(findings=[finding]))).review(block, material)  # type: ignore[arg-type]
    )

    assert [i.code for i in report.issues] == ["insufficient"] and report.flagged_turns()


# --- the repair prompt -----------------------------------------------------------------------------------------------------------


def test_the_repair_prompt_asks_for_rewording_first_and_keeping_what_is_supported() -> None:
    llm = CapturingLLM(DialogueRepair(fixes=[TurnFix(turn=0, text="好的。", fact_refs=[])]))
    asyncio.run(DialogueRepairer(llm).repair(block_saying(SAID), material_with(), {0: "adds a qualifier"}))  # type: ignore[arg-type]

    (prompt,) = llm.prompts
    assert "优先改写有问题的那个说法，保留这一轮里已经有素材支持的内容" in prompt
    assert "不要为了通过核对而把整句话删掉" in prompt
    assert "完全找不到" in prompt and "才可以删掉那一句" in prompt  # deleting is the last resort
    assert "adds a qualifier" in prompt and SAID in prompt  # the reason and the turn are still given

"""Whose words a quote is, decided from the source - and the rest of the fact check unchanged.

Offline: fixed text, the frozen 2026-10-14 evidence, and the archived 2026-10-15 portrait run
(tests/fixtures/dialogue_portrait_20261015).  What this does not show: how a real checker model
words its quotes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from wavecast.intelligence.attribution import own_words_of, says_only_what_the_speaker_said
from wavecast.intelligence.dialogue_check import DialogueCheck, DialogueFactChecker, SentenceFinding
from wavecast.intelligence.dialogue_writer import DialogueRepairer
from wavecast.intelligence.fact_support import qualifiers_missing
from wavecast.intelligence.models import Evidence
from wavecast.intelligence.story_material import DraftFact, StoryMaterialDraft, verify_material
from wavecast.models.dialogue import DialogueBlock, DialoguePurpose, DialogueSpeaker, DialogueTurn
from wavecast.models.story_material import MaterialFact, StoryMaterial, StoryScope

from tests.dialogue_fixtures import ScriptedLLM

FIXTURES = Path(__file__).parent / "fixtures" / "dialogue_portrait_20261015"
NAME = "方大同"
INTERVIEW = (
    "▲對台灣的感覺如何？ 有家的感覺。因為我在台灣是有親戚的。"
    "▲為什麼三張專輯貫來都是唱著國語歌不是粵語歌？ 其實我的語言一直都是中文啊。所以我開口唱歌理所當然就是唱國語。"
    "▲情歌對你而言是怎樣的一種力量？ 我認為音樂本身是一種溝通。所以我希望自己的歌曲能夠喚起大家愛的共鳴。"
)
HOPE = "所以我希望自己的歌曲能夠喚起大家愛的共鳴"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- the source side ---------------------------------------------------------------------------


def test_an_interview_answer_is_the_interviewees_own_words() -> None:
    assert own_words_of(INTERVIEW, HOPE, NAME, title="找出音樂最平凡的感動－方大同") == NAME
    assert own_words_of(INTERVIEW, HOPE, NAME, title="方大同專訪：關於愛") == NAME
    assert own_words_of(INTERVIEW, HOPE, NAME, title="獨家專訪方大同") == NAME


@pytest.mark.parametrize(
    "title",
    [
        "\"玩乐男孩\"方大同专访：玩转灵魂音乐的稀有动物_网易娱乐",
        "專訪方大同：關於愛",
        "方大同專訪_某某雜誌",
        "音樂人訪談－方大同",
    ],
)
def test_a_title_that_names_him_as_the_interviewee_still_counts(title: str) -> None:
    assert own_words_of(INTERVIEW, HOPE, NAME, title=title) == NAME


def test_the_whole_name_is_needed_not_a_suffix_or_a_prefix_of_somebody_else() -> None:
    assert own_words_of(INTERVIEW, HOPE, "方大", title="專訪方大同") is None
    assert own_words_of(INTERVIEW, HOPE, "大同", title="方大同專訪") is None


def test_script_variants_are_located_like_everywhere_else() -> None:
    assert own_words_of(INTERVIEW, "所以我希望自己的歌曲能够唤起大家爱的共鸣", NAME, title="专访方大同") == NAME


@pytest.mark.parametrize(
    "title",
    [
        "專訪方大同的製作人",  # the producer is the interviewee, he is only mentioned
        "專訪方大同的朋友周耀輝",
        "方大同的朋友專訪",
        "專訪方大同和周杰倫",  # a joint interview: not his alone
        "方大同專訪周杰倫",  # he is the interviewer
        "歌手方大同專訪",  # not a whole name: something runs into it
        "周耀輝談方大同",  # an interview about him, not of him
        "周耀輝專訪",  # somebody else is the interviewee
        "音樂的平凡時刻",  # nobody is named
        "",
    ],
)
def test_an_interview_that_is_not_of_this_person_is_not_their_words(title: str) -> None:
    assert own_words_of(INTERVIEW, HOPE, NAME, title=title) is None


def test_the_word_I_alone_proves_nothing() -> None:
    review = f"樂評人寫道：{HOPE}，我很喜歡這樣的音樂。這張專輯讓我想起很多事。"
    assert own_words_of(review, HOPE, NAME, title="方大同專輯樂評－某某") is None
    assert own_words_of(review, HOPE, NAME, title="方大同專訪") is None  # a title cannot make an article an interview


def test_a_speaker_label_decides_who_is_speaking() -> None:
    labelled = f"記者：你為什麼唱國語？\n方大同：{HOPE}。\n周耀輝：我覺得他唱得很好。"
    assert own_words_of(labelled, HOPE, NAME) == NAME
    third = "周耀輝：我覺得方大同的歌曲能夠喚起大家愛的共鳴，這是他說的。"
    assert own_words_of(third, "我覺得方大同的歌曲能夠喚起大家愛的共鳴", NAME, title="方大同專訪") is None
    metadata = f"歌手：{NAME}\n語言：國語\n發行時間：2006-12-31"
    assert own_words_of(metadata, "發行時間：2006-12-31", NAME, title="方大同專訪") is None


def test_a_question_is_not_an_answer() -> None:
    assert own_words_of(INTERVIEW, "為什麼三張專輯貫來都是唱著國語歌不是粵語歌", NAME, title="專訪方大同") is None


def test_a_quote_that_is_not_in_the_source_is_nobodys_words() -> None:
    assert own_words_of(INTERVIEW, "這句話從來沒有出現過在訪談裡", NAME, title="專訪方大同") is None
    assert own_words_of("", HOPE, NAME) is None
    assert own_words_of(INTERVIEW, HOPE, "", title="專訪方大同") is None


# --- the sentence side -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "ok"),
    [
        ("他还说过，自己没学过创作。", True),
        ("他说过，希望自己的歌曲能够唤起大家爱的共鸣。", True),
        ("他自己说过，写歌靠摸索。", True),
        ("方大同曾说，写歌靠摸索。", True),
        ("周杰伦说过，他喜欢这首歌。", False),  # the saying is given to somebody else
        ("乐评人说过，他的歌很好。", False),
        ("周杰伦和方大同说过，写歌靠摸索。", False),  # the saying is shared: not his alone
        ("周杰伦、方大同说过，写歌靠摸索。", False),
        ("他和方大同说过，写歌靠摸索。", False),
        ("方大同和周杰伦都说过，写歌靠摸索。", False),
        ("音乐人方大同说过，写歌靠摸索。", False),  # a title run into the name: not the whole name
        ("接着，方大同说过，写歌靠摸索。", True),
        ("这首歌很好听。", False),  # nothing is attributed: this rule has nothing to say
    ],
)
def test_the_sentence_must_give_the_saying_to_that_person(sentence: str, ok: bool) -> None:
    assert says_only_what_the_speaker_said(sentence, NAME) is ok


# --- the rule: only "said" is relaxed ----------------------------------------------------------

SAID = "他说过，希望自己的歌曲能够唤起大家爱的共鸣。"
QUOTE = "所以我希望自己的歌曲能夠喚起大家愛的共鳴。"


def test_a_he_said_sentence_needs_the_word_only_without_proof_of_whose_words_they_are() -> None:
    assert qualifiers_missing(SAID, QUOTE) == ["self-said"]  # unchanged default
    assert qualifiers_missing(SAID, QUOTE, own_words_of=NAME) == []


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("他第一次说过，希望自己的歌曲能够唤起大家爱的共鸣。", ["first"]),
        ("他说过，他一直希望自己的歌曲能够唤起大家爱的共鸣。", ["always"]),
        ("他说过，所有歌曲都希望唤起大家爱的共鸣。", ["whole"]),
        ("他说过，他的歌曲唯一的希望是唤起大家爱的共鸣。", ["only"]),
        ("他说过，这样的想法影响了后来的歌手。", ["influence"]),
    ],
)
def test_every_other_qualifier_still_has_to_be_in_the_quote(sentence: str, expected: list[str]) -> None:
    assert qualifiers_missing(sentence, QUOTE, own_words_of=NAME) == expected


def test_somebody_elses_saying_is_not_covered_by_the_interviewees_words() -> None:
    assert qualifiers_missing("周杰伦说过，希望唤起大家爱的共鸣。", QUOTE, own_words_of=NAME) == ["self-said"]


# --- the material gets it from the source ------------------------------------------------------


def evidence(text: str, title: str) -> Evidence:
    return Evidence(
        id="E1", claim_or_excerpt=text, source_url="https://example.test/e1", source_provider="exa",
        confidence=0.8, query=NAME, source_title=title,
    )  # fmt: skip


def draft_for(quote: str) -> StoryMaterialDraft:
    def fact(statement: str, q: str) -> DraftFact:
        return DraftFact(statement=statement, evidence_id="E1", quote=q, scope="background", subject=NAME, version_scope=None)

    return StoryMaterialDraft(
        subject=NAME, scope="background", central_question="为什么？",
        facts=[fact("他希望自己的歌曲能唤起大家的共鸣。", quote), fact("他对台湾有家的感觉。", "有家的感覺。因為我在台灣是有親戚的")],
        editorial_angle=None, do_not_infer=[], backstage=[],
    )  # fmt: skip


def test_verifying_material_records_whose_words_a_fact_is() -> None:
    material = verify_material(draft_for(HOPE), [evidence(INTERVIEW, "找出音樂最平凡的感動－方大同")], story_id="s")
    assert material is not None
    assert [fact.own_words_of for fact in material.facts] == [NAME, NAME]

    about = verify_material(draft_for(HOPE), [evidence(INTERVIEW, "周耀輝談方大同")], story_id="s")
    assert about is not None and [fact.own_words_of for fact in about.facts] == [None, None]


def test_an_interview_of_somebody_around_him_is_not_his_own_words_in_the_material() -> None:
    for title in ("專訪方大同的製作人", "專訪方大同和周杰倫"):
        material = verify_material(draft_for(HOPE), [evidence(INTERVIEW, title)], story_id="s")
        assert material is not None and [fact.own_words_of for fact in material.facts] == [None, None]


def test_material_saved_before_the_field_existed_still_loads_and_stays_strict() -> None:
    saved = load("material.normalized.json")["material"]
    assert all("own_words_of" not in fact for fact in saved["facts"])
    material = StoryMaterial.model_validate(saved)
    assert all(fact.own_words_of is None for fact in material.facts)


# --- the checker end to end --------------------------------------------------------------------


def block_saying(text: str) -> DialogueBlock:
    return DialogueBlock(
        block_id="b", slot_id="s", story_id="st", purpose=DialoguePurpose.STORY, duration_seconds=10,
        turns=[DialogueTurn(speaker=DialogueSpeaker.A, text=text, tts_text=None, fact_refs=["st-F1"])],
    )  # fmt: skip


def material_with(own: str | None) -> StoryMaterial:
    return StoryMaterial(
        story_id="st", subject="s", scope=StoryScope.BACKGROUND, central_question="q",
        facts=[MaterialFact(fact_id="st-F1", statement="他希望歌曲唤起共鸣", evidence_id="E1", quote=QUOTE,
                            scope=StoryScope.BACKGROUND, subject=NAME, own_words_of=own),
               MaterialFact(fact_id="st-F2", statement="他对台湾有家的感觉", evidence_id="E1", quote="有家的感覺。因為我在台灣是有親戚的",
                            scope=StoryScope.BACKGROUND, subject=NAME, own_words_of=own)],
    )  # fmt: skip


def check(text: str, own: str | None, quote: str = QUOTE) -> list[str]:
    llm = ScriptedLLM(DialogueCheck(findings=[SentenceFinding(sentence=0, verdict="supported", fact_ids=["st-F1"], quote=quote)]))
    report = asyncio.run(DialogueFactChecker(llm).review(block_saying(text), material_with(own)))  # type: ignore[arg-type]
    return [issue.code for issue in report.issues]


def test_an_interview_fact_lets_he_said_pass_but_a_third_party_comment_cannot_pose_as_the_artist() -> None:
    assert check(SAID, own=None) == ["qualifier_not_in_quote"]  # what the live run met
    assert check(SAID, own=NAME) == []  # own interview, traced from its source
    # A quote of somebody else's remark (no proof it is his): still refused.
    assert check("周杰伦说过，希望自己的歌曲能够唤起大家爱的共鸣。", own=NAME) == ["qualifier_not_in_quote"]


def test_a_shared_saying_is_not_covered_by_his_own_words() -> None:
    assert check("周杰伦和方大同说过，希望自己的歌曲能够唤起大家爱的共鸣。", own=NAME) == ["qualifier_not_in_quote"]


def test_other_rules_are_untouched_for_an_interview_fact() -> None:
    assert check("他第一次说过，希望自己的歌曲能够唤起大家爱的共鸣。", own=NAME) == ["qualifier_not_in_quote"]
    # a role claim still needs a quote that speaks of that role
    assert check("他说过，这首歌由他作曲。", own=NAME) == ["role_not_in_quote"]
    # and a quote that is not in the cited fact is still refused
    assert check(SAID, own=NAME, quote="完全无关的一句话在这里出现") == ["quote_not_in_source"]


# --- the archived run --------------------------------------------------------------------------


def archived_material_with_attribution() -> StoryMaterial:
    """The saved material, with ``own_words_of`` derived from the frozen evidence it came from."""

    sources = {item["id"]: item for item in load("evidence.frozen.json")}
    material = StoryMaterial.model_validate(load("material.normalized.json")["material"])
    facts = []
    for fact in material.facts:
        source = sources[fact.evidence_id]
        own = own_words_of(source["claim_or_excerpt"], fact.quote, fact.subject, title=source["source_title"])
        facts.append(fact.model_copy(update={"own_words_of": own}))
    return material.model_copy(update={"facts": facts})


def test_the_archived_interview_facts_are_the_artists_words_and_the_album_page_is_not() -> None:
    by_id = {fact.fact_id: fact.own_words_of for fact in archived_material_with_attribution().facts}
    assert all(by_id[f"live-fdt-F{n}"] == NAME for n in range(1, 9))  # the Hitoradio answers
    assert all(by_id[f"live-fdt-F{n}"] is None for n in (9, 10, 11))  # the album record page


def test_narration_and_questions_in_the_archived_feature_article_are_not_his_words() -> None:
    sources = {item["id"]: item for item in load("evidence.frozen.json")}
    feature = sources["C-E2"]
    text, title = feature["claim_or_excerpt"], feature["source_title"]
    # The writer's description of him ...
    assert own_words_of(text, "戴着黑框眼镜的方大同，像个永远不会出格的好学生", NAME, title=title) is None
    # ... and the answer that follows the interviewer's question, which is his.
    assert own_words_of(text, "从小喜欢怎样的音乐，长大了就会往这个方向发展", NAME, title=title) == NAME
    assert own_words_of(text, "我从小听黑人音乐", NAME, title=title) == NAME


def test_the_two_sentences_the_live_check_refused_pass_with_the_derived_attribution() -> None:
    candidate = load("candidate.unchecked.json")["turns"]
    first_sentence = candidate[5]["text"].split("。")[1] + "。"
    assert first_sentence.startswith("他还说过")
    second_sentence = candidate[7]["text"].split("。")[0] + "。"
    assert second_sentence.startswith("他说过")
    cases = [
        (first_sentence, ["live-fdt-F8", "live-fdt-F7"], "live-fdt-F8"),
        (second_sentence, ["live-fdt-F6"], "live-fdt-F6"),
    ]
    before, after = StoryMaterial.model_validate(load("material.normalized.json")["material"]), archived_material_with_attribution()
    for sentence, refs, cited in cases:
        finding = SentenceFinding(sentence=0, verdict="supported", fact_ids=[cited], quote=before.fact(cited).quote[:60])  # type: ignore[union-attr]
        assert DialogueFactChecker._why_not_supported(sentence, finding, before) == "qualifier_not_in_quote"  # as refused live
        assert DialogueFactChecker._why_not_supported(sentence, finding, after) is None
        assert refs  # the turn declared these facts


def test_a_fact_from_the_album_page_cannot_back_he_said_even_with_the_attribution_derived() -> None:
    after = archived_material_with_attribution()
    finding = SentenceFinding(sentence=0, verdict="supported", fact_ids=["live-fdt-F11"], quote=after.fact("live-fdt-F11").quote[:60])  # type: ignore[union-attr]
    assert DialogueFactChecker._why_not_supported("他说过，所有歌曲都是他一手包办作曲。", finding, after) == "qualifier_not_in_quote"


# --- the repair prompt -------------------------------------------------------------------------


class CapturingLLM(ScriptedLLM):
    def __init__(self, *responses: Any) -> None:
        super().__init__(*responses)
        self.prompts: list[str] = []

    async def structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        self.prompts.append(prompt)
        return await super().structured(prompt, output_type, **kwargs)


def test_the_repair_prompt_asks_for_rewording_first_and_keeping_what_is_supported() -> None:
    from wavecast.intelligence.dialogue_writer import DialogueRepair, TurnFix

    llm = CapturingLLM(DialogueRepair(fixes=[TurnFix(turn=0, text="好的。", fact_refs=[])]))
    asyncio.run(DialogueRepairer(llm).repair(block_saying(SAID), material_with(NAME), {0: "adds a qualifier"}))  # type: ignore[arg-type]

    (prompt,) = llm.prompts
    assert "优先改写有问题的那个说法，保留这一轮里已经有素材支持的内容" in prompt
    assert "不要为了通过核对而把整句话删掉" in prompt
    assert "完全找不到" in prompt and "才可以删掉那一句" in prompt  # deleting is the last resort
    assert "adds a qualifier" in prompt and SAID in prompt  # the reason and the turn are still given

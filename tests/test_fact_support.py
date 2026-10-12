"""A factual sentence needs a source: attributions, creation stories and made-up titles are caught.

The regression cases come from a real portrait programme (久石让): a song by 木村弓 credited to
the subject as composer, a Kitano-film song described as part of a Miyazaki film, poems and a
musical scale that no source mentions, and a Chinese title the Writer made up.  Ordinary
background and listening talk must pass untouched.
"""

import asyncio
import re

from wavecast.intelligence.fact_support import (
    FactCheck,
    FactChecker,
    FactFinding,
    quote_in_source,
    split_sentences,
)
from wavecast.intelligence.models import (
    Evidence,
    NarrationSlotContext,
    NarrationSlotPlacement,
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
)
from wavecast.intelligence.writer import WriterService
from wavecast.spoken_form import KnownTrack
from wavecast.stations import StationId

from tests.test_voice import _chapter

HISAISHI_PAGE = (
    "久石让的电影配乐主要是与宫崎骏和北野武两位导演，电影例如《天空之城》、《龙猫》、《千与千寻》、"
    "《菊次郎的夏天》等。《菊次郎的夏天》中的音乐《Summer》就是如此，这首歌已成为许多人的夏季限定曲。"
)
SUMMER_PAGE_TRADITIONAL = "同樣的《菊次郎之夏》的主題音樂〈Summer〉，也都契合電影主題。"

SUBJECT_COMPOSER_SENTENCE = "二〇〇一年，《千与千寻》的主题曲，作曲是久石让，唱的是木村弓。"


def _evidence(*texts: str) -> list[Evidence]:
    return [
        Evidence(
            id=f"e{i}",
            claim_or_excerpt=text,
            source_url="https://example.test",
            source_provider="fixture",
            confidence=0.8,
            query="q",
        )
        for i, text in enumerate(texts, start=1)
    ]


def _script(*texts: str, kind: RadioScriptBlockKind = RadioScriptBlockKind.TRACK_INTRO) -> RadioScript:
    return RadioScript(
        blocks=[RadioScriptBlock(kind=kind, text=text, duration_seconds=8) for text in texts]
    )


class Dispatch:
    """Scripts: Writer drafts in order, and one fact check answer per check call."""

    def __init__(
        self, drafts: list[RadioScript], checks: list[FactCheck | Exception], *, complete: bool = True
    ) -> None:
        # ``complete`` answers like a compliant checker: a sentence the test gives no finding
        # for is judged "not_factual".  ``complete=False`` leaves it out.
        self.complete = complete
        self.drafts, self.checks = list(drafts), list(checks)
        self.prompts: list[str] = []
        self.check_prompts: list[str] = []

    async def structured(self, prompt: str, output_type: type[object], **_kwargs: object) -> object:
        if output_type is FactCheck:
            self.check_prompts.append(prompt)
            answer = self.checks[min(len(self.check_prompts) - 1, len(self.checks) - 1)]
            if isinstance(answer, Exception):
                raise answer
            if self.complete:
                asked = {int(n) for n in re.findall(r"^(\d+)\. ", prompt.split("Sentences (numbered):")[-1], re.M)}
                missing = asked - {finding.sentence for finding in answer.findings}
                answer = FactCheck(
                    findings=[*answer.findings, *(_finding(n, "not_factual") for n in sorted(missing))]
                )
            return answer
        self.prompts.append(prompt)
        return self.drafts[min(len(self.prompts) - 1, len(self.drafts) - 1)]


def _finding(sentence: int, verdict: str, source: str = "", quote: str = "") -> FactFinding:
    return FactFinding(sentence=sentence, verdict=verdict, source=source, quote=quote)  # type: ignore[arg-type]


def _review(script: RadioScript, evidence: list[Evidence], check: FactCheck | Exception, **kwargs):  # type: ignore[no-untyped-def]
    checker = FactChecker(Dispatch([], [check]))  # type: ignore[arg-type]
    return asyncio.run(checker.review(script, evidence, **kwargs))


# --- what counts as a source -------------------------------------------------------------------


def test_a_quote_must_be_found_in_its_source() -> None:
    assert quote_in_source("菊次郎之夏的主題音樂〈Summer〉", SUMMER_PAGE_TRADITIONAL)
    assert not quote_in_source("菊次郎之夏", HISAISHI_PAGE)  # a different title is not the same text
    assert not quote_in_source("宫崎骏给久石让寄了九首短诗", HISAISHI_PAGE)
    assert not quote_in_source("短", HISAISHI_PAGE)  # too short to show anything


def test_sentences_keep_their_punctuation() -> None:
    assert split_sentences("先说这个。再说那个！") == ["先说这个。", "再说那个！"]


# --- the regression cases ----------------------------------------------------------------------


def test_a_composer_credit_with_no_source_is_unsupported() -> None:
    evidence = _evidence(HISAISHI_PAGE)
    report = _review(
        _script(SUBJECT_COMPOSER_SENTENCE),
        evidence,
        FactCheck(findings=[_finding(0, "insufficient")]),
        tracks=[KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")],
    )

    assert [issue.code for issue in report.issues] == ["insufficient"]
    assert "not supported" in report.issues[0].message


def test_a_song_placed_in_the_wrong_film_is_contradicted_by_the_source() -> None:
    evidence = _evidence(SUMMER_PAGE_TRADITIONAL)
    report = _review(
        _script("上一首是《Summer》，同一支曲子在宫崎骏的电影里后来长成了另一段旋律。"),
        evidence,
        FactCheck(findings=[_finding(0, "contradicted", "e1", "《菊次郎之夏》的主題音樂〈Summer〉")]),
        tracks=[KnownTrack(artist="久石譲", title="Summer")],
    )

    assert [issue.code for issue in report.issues] == ["contradicted"]
    assert "菊次郎" in report.issues[0].message  # the Writer is told what the source says


def test_invented_creation_details_are_unsupported() -> None:
    report = _review(
        _script("宫崎骏给久石让寄了九首短诗，其中一首就叫《魔法公主》。他用日本音阶写成。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "insufficient"), _finding(1, "insufficient")]),
    )

    # 《魔法公主》 is in no source either, so the first sentence is flagged on both counts.
    assert [(issue.sentence, issue.code) for issue in report.issues] == [
        (0, "unknown_title"),
        (1, "insufficient"),
    ]


def test_a_title_the_writer_made_up_is_caught_without_asking_a_model() -> None:
    report = _review(
        _script("接下来是《永远常在》。"),
        _evidence(HISAISHI_PAGE),
        RuntimeError("no model needed"),
        tracks=[KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")],
    )

    assert [issue.code for issue in report.issues] == ["unknown_title"]


def test_the_catalogs_own_title_and_a_work_named_in_the_evidence_are_fine() -> None:
    report = _review(
        _script("接下来是《永远同在》，选自《千与千寻》。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[]),
        tracks=[KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")],
    )

    assert report.issues == []


# --- what must not be caught -------------------------------------------------------------------


def test_a_supported_background_sentence_is_kept_and_its_source_recorded() -> None:
    report = _review(
        _script("久石让的电影配乐主要是和宫崎骏、北野武两位导演合作。听听这段木管。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(
            findings=[_finding(0, "supported", "e1", "久石让的电影配乐主要是与宫崎骏和北野武两位导演")]
        ),
    )

    assert report.issues == []
    assert report.supported[0][0].evidence_ids == ["e1"]


def test_listening_talk_needs_no_source() -> None:
    report = _review(
        _script("木管和钢琴一起，把这个主题慢慢铺开。下一首听它。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[]),
    )

    assert report.issues == []


def test_an_attribution_the_checker_calls_not_factual_is_still_checked() -> None:
    report = _review(
        _script("这首歌的作曲是久石让。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[]),  # the checker skipped it, but it names a composer
    )

    assert [issue.code for issue in report.issues] == ["unchecked"]


def test_a_quote_that_is_not_in_the_source_does_not_support_anything() -> None:
    report = _review(
        _script("这首歌的作曲是久石让。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "supported", "e1", "久石让亲自作曲并担任钢琴演奏")]),
    )

    assert [issue.code for issue in report.issues] == ["insufficient"]


def test_a_quote_that_never_speaks_of_the_claimed_role_does_not_support_it() -> None:
    # The name is there, but the quote is about directors, not about who composed the song.
    report = _review(
        _script("这首歌的作曲是久石让。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "supported", "e1", "宫崎骏和北野武两位导演")]),
    )

    assert [issue.code for issue in report.issues] == ["insufficient"]


def test_a_quote_about_another_piece_does_not_support_an_attribution_about_this_one() -> None:
    page = "由久石让作曲的主题曲《伴随着你》（通称：天空之城）。"
    report = _review(
        _script("《永远同在》是久石让作曲的。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "由久石让作曲的主题曲《伴随着你》")]),
        tracks=[KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")],
    )

    assert [issue.code for issue in report.issues] == ["insufficient"]

    own_piece = _review(
        _script("《伴随着你》是久石让作曲的。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "由久石让作曲的主题曲《伴随着你》")]),
        tracks=[KnownTrack(artist="久石譲", title="伴随着你")],
    )
    assert own_piece.issues == []


def test_the_composer_of_the_film_is_not_the_composer_of_its_song() -> None:
    page = "《千与千寻》的音乐由久石让作曲。主题歌《永远同在》由木村弓作曲并演唱。"
    track = KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")

    film_credit = _review(
        _script("《永远同在》是《千与千寻》的主题曲，作曲久石让。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "《千与千寻》的音乐由久石让作曲")]),
        tracks=[track],
    )
    own_credit = _review(
        _script("《永远同在》是《千与千寻》的主题曲，作曲木村弓。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "主题歌《永远同在》由木村弓作曲并演唱")]),
        tracks=[track],
    )

    assert [issue.code for issue in film_credit.issues] == ["insufficient"]
    assert own_credit.issues == []


def test_the_catalog_names_a_credit_and_never_a_role() -> None:
    track = KnownTrack(artist="木村弓", title="いつも何度でも")
    credit = "is credited to the performer 木村弓"
    for sentence in ("这首歌是木村弓演唱的。", "这首歌是木村弓作曲的。"):
        report = _review(
            _script(sentence),
            _evidence(HISAISHI_PAGE),
            FactCheck(findings=[_finding(0, "supported", "catalog", credit)]),
            tracks=[track],
        )
        assert [issue.code for issue in report.issues] == ["insufficient"], sentence

    plain = _review(  # a bare statement of whose track it is needs no role
        _script("接下来是木村弓的《永远同在》。"),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "supported", "catalog", credit)]),
        tracks=[KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")],
    )
    assert plain.issues == []


def test_a_quote_must_be_complete_so_a_dropped_negation_does_not_pass() -> None:
    source = "这首曲子并不是久石让作曲的，作曲者另有其人。"
    assert quote_in_source("这首曲子并不是久石让作曲的", source)
    assert not quote_in_source("这首曲子是久石让作曲的", source)

    report = _review(
        _script("这首曲子是久石让作曲的。"),
        _evidence(source),
        FactCheck(findings=[_finding(0, "supported", "e1", "这首曲子是久石让作曲的")]),
    )
    assert [issue.code for issue in report.issues] == ["insufficient"]


def test_a_quote_must_speak_of_the_same_role_not_a_neighbouring_one() -> None:
    page = "《风之谷》的主题由久石让编曲，宫崎骏在1983年第一次听到。"

    arranged = _review(
        _script("这首的作曲是久石让。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "主题由久石让编曲")]),
    )
    assert [issue.code for issue in arranged.issues] == ["insufficient"]

    same_role = _review(
        _script("这首的编曲是久石让。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "主题由久石让编曲")]),
    )
    assert same_role.issues == []

    played = _review(
        _script("这首是久石让亲自演唱的。"),
        _evidence("久石让亲自演奏了钢琴部分，由他完成录音。"),
        FactCheck(findings=[_finding(0, "supported", "e1", "久石让亲自演奏了钢琴部分")]),
    )
    assert [issue.code for issue in played.issues] == ["insufficient"]  # played is not sang


def test_a_closing_is_not_cut_for_summing_up_the_route_but_is_for_a_fact() -> None:
    summing_up = _review(
        _script("这条线从《天空之城》走到最后。", kind=RadioScriptBlockKind.OUTRO),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "not_factual")]),
    )
    assert summing_up.issues == []

    # A closing is checked like any other block: a claim the checker calls a fact without a source goes.
    claiming = _review(
        _script("这条线从《天空之城》走到最后，一直是在给故事铺底。", kind=RadioScriptBlockKind.OUTRO),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "insufficient")]),
    )
    assert [issue.code for issue in claiming.issues] == ["insufficient"]

    attributing = _review(
        _script("最后这首的作曲是久石让。", kind=RadioScriptBlockKind.OUTRO),
        _evidence(HISAISHI_PAGE),
        FactCheck(findings=[_finding(0, "insufficient")]),
    )
    assert [issue.code for issue in attributing.issues] == ["insufficient"]


def test_when_the_checker_is_down_attributions_are_left_out_and_the_rest_goes_on() -> None:
    report = _review(
        _script("听听这段木管。这首的作曲是久石让。"),
        _evidence(HISAISHI_PAGE),
        RuntimeError("provider down"),
    )

    assert not report.model_checked
    assert [(issue.sentence, issue.code) for issue in report.issues] == [(1, "unchecked")]


# --- in the Writer -----------------------------------------------------------------------------


def _slot() -> NarrationSlotContext:
    return NarrationSlotContext(
        chapter_index=2,
        placement=NarrationSlotPlacement.BEFORE_TRACK,
        allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
        chapter_track=ResolvedTrack(
            track_ref="n:2", canonical_artist="木村弓", canonical_title="いつも何度でも", spoken_title="永远同在"
        ),
        upcoming_track=ResolvedTrack(
            track_ref="n:2", canonical_artist="木村弓", canonical_title="いつも何度でも", spoken_title="永远同在"
        ),
    )


def _write(llm: Dispatch, **kwargs):  # type: ignore[no-untyped-def]
    evidence = _evidence(HISAISHI_PAGE)
    chapter = _chapter().model_copy(update={"evidence_ids": ["e1"]})
    result = asyncio.run(
        WriterService(llm, fact_checker=FactChecker(llm)).write(  # type: ignore[arg-type]
            chapter,
            evidence,
            slot_context=_slot(),
            target_duration_seconds=30,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
            **kwargs,
        )
    )
    assert isinstance(result, RadioScript)
    return result


GOOD = "听听这段钢琴和人声。"
BAD = "这首歌作曲是久石让，唱的是木村弓。"


def test_an_unsupported_sentence_is_sent_back_once_and_the_rewrite_is_used() -> None:
    llm = Dispatch(
        [_script(f"{BAD}{GOOD}"), _script(f"久石让的电影配乐主要是与宫崎骏合作的。{GOOD}")],
        [
            FactCheck(findings=[_finding(0, "insufficient")]),
            FactCheck(findings=[_finding(0, "supported", "e1", "久石让的电影配乐主要是与宫崎骏和北野武两位导演")]),
        ],
    )

    result = _write(llm)

    assert len(llm.prompts) == 2 and len(llm.check_prompts) == 2
    assert "is not supported by the evidence" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [f"久石让的电影配乐主要是与宫崎骏合作的。{GOOD}"]


def test_a_sentence_still_unsupported_after_the_rewrite_is_left_out_not_the_block() -> None:
    llm = Dispatch(
        [_script(f"{BAD}{GOOD}")],
        [FactCheck(findings=[_finding(0, "insufficient")])],
    )

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert [block.text for block in result.blocks] == [GOOD]
    assert "久石让" not in (result.blocks[0].tts_text or "")


def test_a_sentence_that_leaned_on_a_removed_one_goes_with_it() -> None:
    llm = Dispatch(
        [_script(f"这首歌作曲是久石让。因此他的名字出现在片尾。{GOOD}")],
        [FactCheck(findings=[_finding(0, "insufficient")])],
    )

    result = _write(llm)

    assert [block.text for block in result.blocks] == [GOOD]


def test_a_block_with_nothing_supportable_is_skipped_and_the_music_goes_on() -> None:
    llm = Dispatch([_script(BAD)], [FactCheck(findings=[_finding(0, "insufficient")])])

    result = _write(llm)

    assert result.blocks == []


def test_a_clean_draft_costs_one_check_and_no_rewrite() -> None:
    llm = Dispatch([_script(GOOD)], [FactCheck(findings=[])])

    result = _write(llm)

    assert len(llm.prompts) == 1 and len(llm.check_prompts) == 1
    assert [block.text for block in result.blocks] == [GOOD]


def test_the_checker_sees_only_the_chapters_scoped_evidence_and_the_catalog_lines() -> None:
    llm = Dispatch([_script(GOOD)], [FactCheck(findings=[])])

    _write(llm)

    prompt = llm.check_prompts[0]
    assert "[e1]:" in prompt and "[catalog]:" in prompt
    assert "is credited to the performer 木村弓" in prompt


def test_the_writer_is_told_the_catalog_artist_is_a_performer_credit() -> None:
    llm = Dispatch([_script(GOOD)], [FactCheck(findings=[])])

    _write(llm)

    prompt = llm.prompts[0]
    assert "performer the catalog credits" in prompt
    assert "never credit that track's composition" in prompt


def test_without_a_checker_the_writer_behaves_as_before() -> None:
    llm = Dispatch([_script(BAD)], [])
    chapter = _chapter().model_copy(update={"evidence_ids": ["e1"]})

    result = asyncio.run(
        WriterService(llm).write(  # type: ignore[arg-type]
            chapter,
            _evidence(HISAISHI_PAGE),
            slot_context=_slot(),
            target_duration_seconds=30,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
        )
    )

    assert isinstance(result, RadioScript) and llm.check_prompts == []


def test_a_closing_cut_by_the_fact_check_becomes_a_route_closing_with_the_sign_off() -> None:
    from wavecast.stations import compose_signoff

    from tests.test_voice import _final_slot

    llm = Dispatch(
        [_script("最后这首的作曲是久石让。", kind=RadioScriptBlockKind.OUTRO)],
        [FactCheck(findings=[_finding(0, "insufficient")])],
    )
    result = asyncio.run(
        WriterService(llm, fact_checker=FactChecker(llm)).write(  # type: ignore[arg-type]
            _chapter().model_copy(update={"evidence_ids": ["e1"]}),
            _evidence(HISAISHI_PAGE),
            slot_context=_final_slot(),
            target_duration_seconds=16,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
            route_tracks=["久石譲 - Summer", "木村弓 - いつも何度でも", "久石譲 - Spirited Away"],
        )
    )

    assert isinstance(result, RadioScript)
    signoff = compose_signoff(StationId.PORTRAIT, "programme-1")
    # the first and last songs are named when the voice can say them; a Japanese title is not
    assert [block.text for block in result.blocks] == [f"这一程从《Summer》听到《Spirited Away》，就走到这里。{signoff}"]


def test_a_statement_resting_on_another_song_of_the_programme_is_not_about_this_slot() -> None:
    page = "さんぽ 宫崎骏请中川李枝子写词，后来进了小学音乐课本。"
    opening = KnownTrack(artist="久石譲", title="さんぽ")
    following = KnownTrack(artist="久石譲", title="君をのせて", spoken_title="伴随着你")

    report = _review(
        _script("这首歌本来是动画歌，后来进了小学音乐课本。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "后来进了小学音乐课本")]),
        focus_tracks=[following],
        other_tracks=[opening],
    )
    background = _review(
        _script("这首歌本来是动画歌，后来进了小学音乐课本。"),
        _evidence("宫崎骏的动画歌曲后来进了小学音乐课本。"),
        FactCheck(findings=[_finding(0, "supported", "e1", "后来进了小学音乐课本")]),
        focus_tracks=[following],
        other_tracks=[opening],
    )

    assert [issue.code for issue in report.issues] == ["wrong_subject"]
    assert background.issues == []  # general background that names no other song is fine


def test_a_block_that_still_talks_about_another_song_after_the_rewrite_is_dropped() -> None:
    from tests.test_voice import Sequenced, _slot

    text = "刚才的One之后，是Other Song的故事。"
    llm = Sequenced(_script(text), _script(text))

    result = asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
            route_tracks=["A - One", "A - Jody", "B - Other Song"],
        )
    )

    assert isinstance(result, RadioScript)
    assert result.blocks == []


def test_the_right_role_for_the_wrong_person_is_not_support() -> None:
    page = "《永远同在》 作词：觉和歌子 作曲：木村弓 编曲：木村弓"
    track = KnownTrack(artist="木村弓", title="いつも何度でも", spoken_title="永远同在")
    other = KnownTrack(artist="久石譲", title="Summer")

    wrong_person = _review(
        _script("《永远同在》的作曲是久石让。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "《永远同在》 作词：觉和歌子 作曲：木村弓")]),
        tracks=[track, other],
    )
    right_person = _review(
        _script("《永远同在》的作曲是木村弓。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "《永远同在》 作词：觉和歌子 作曲：木村弓")]),
        tracks=[track, other],
    )

    assert [issue.code for issue in wrong_person.issues] == ["insufficient"]
    assert right_person.issues == []


# --- every sentence is judged; qualifiers belong to the claim --------------------------------


HOSHINO_SENTENCES = (
    "最后来听《好き》。他自己说，从前一直回避写自己，到了《喜劇》才第一次把家庭写进歌里。这一首，延续的就是那个方向。"
)
HOSHINO_TRACKS = [KnownTrack(artist="星野源", title="好き")]
HOSHINO_SOURCE = "星野源在读完漫画《间谍过家家》里的家庭故事之后，写下了《喜劇》。"


def _asked_numbers(prompt: str) -> list[int]:
    return [int(n) for n in re.findall(r"^(\d+)\. ", prompt.split("Sentences (numbered):")[-1], re.M)]


def test_a_sentence_the_checker_left_out_is_asked_about_once_and_never_taken_as_harmless() -> None:
    llm = Dispatch([], [FactCheck(findings=[]), FactCheck(findings=[_finding(0, "not_factual"), _finding(2, "not_factual")])], complete=False)
    report = asyncio.run(
        FactChecker(llm).review(_script(HOSHINO_SENTENCES), _evidence(HOSHINO_SOURCE), tracks=HOSHINO_TRACKS)  # type: ignore[arg-type]
    )
    assert len(llm.check_prompts) == 2  # the one extra ask is for the sentences left out
    assert _asked_numbers(llm.check_prompts[1]) == [0, 1, 2]
    # Sentence 1 stayed without a judgement through both asks, so it is flagged, not passed.
    assert [(issue.sentence, issue.code) for issue in report.issues] == [(1, "unchecked")]


def test_a_complete_answer_costs_one_ask_and_an_unavailable_second_ask_flags_the_rest() -> None:
    llm = Dispatch([], [FactCheck(findings=[_finding(0, "not_factual")])], complete=False)
    asyncio.run(FactChecker(llm).review(_script("先听一段。"), _evidence(HOSHINO_SOURCE)))  # type: ignore[arg-type]
    assert len(llm.check_prompts) == 1

    llm = Dispatch([], [FactCheck(findings=[]), RuntimeError("down")], complete=False)
    report = asyncio.run(FactChecker(llm).review(_script("先听一段。"), _evidence(HOSHINO_SOURCE)))  # type: ignore[arg-type]
    assert [issue.code for issue in report.issues] == ["unchecked"]


def test_a_quote_that_only_names_the_work_does_not_back_first_time_or_says_himself() -> None:
    # The checker says "supported" with a quote that does name 《喜劇》 and the writing of it.
    report = _review(
        _script("他自己说，到了《喜劇》才第一次把家庭写进歌里。"),
        _evidence(HOSHINO_SOURCE),
        FactCheck(findings=[_finding(0, "supported", "e1", "写下了《喜劇》")]),
    )
    assert [issue.code for issue in report.issues] == ["insufficient"]

    plain = _review(
        _script("他读完漫画里的家庭故事之后，写下了《喜劇》。"),
        _evidence(HOSHINO_SOURCE),
        FactCheck(findings=[_finding(0, "supported", "e1", "读完漫画《间谍过家家》里的家庭故事之后，写下了《喜劇》")]),
    )
    assert plain.issues == []


def test_cause_influence_and_instruments_need_to_be_in_the_quote() -> None:
    page = (
        "〈秋天的落叶〉采用 AABC 结构。比尔·埃文斯三重奏的录音是 this kind of melodically "
        "interactive trio。《回到那个夏天》由钢琴和弦乐演奏。"
    )
    cause = _review(
        _script("它采用 AABC 结构，所以比尔·埃文斯能弹出对话感。", kind=RadioScriptBlockKind.OUTRO),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "〈秋天的落叶〉采用 AABC 结构")]),
    )
    assert [issue.code for issue in cause.issues] == ["insufficient"]

    influence = _review(
        _script("这种三重奏的对话方式影响了后来的爵士钢琴三重奏。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "this kind of melodically interactive trio")]),
    )
    assert [issue.code for issue in influence.issues] == ["insufficient"]

    instruments = _review(
        _script("刚才那首是钢琴和小乐队的写法。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "由钢琴和弦乐演奏")]),
    )
    assert [issue.code for issue in instruments.issues] == ["insufficient"]  # no "small band" in the quote

    kept = _review(
        _script("那一首由钢琴和弦乐演奏。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "由钢琴和弦乐演奏")]),
    )
    assert kept.issues == []


def test_a_period_claim_needs_the_period_in_the_quote() -> None:
    page = "宮崎さんの映画は、ぼくにとって、特に一番大きな仕事ですね。"
    report = _review(
        _script("宫崎骏的电影，是他一年里最大的一份工作。"),
        _evidence(page),
        FactCheck(findings=[_finding(0, "supported", "e1", "特に一番大きな仕事ですね")]),
    )
    assert [issue.code for issue in report.issues] == ["insufficient"]


def test_biographical_turns_and_theory_are_facts_even_when_called_not_factual() -> None:
    for text in ("到《好き》，家庭第一次成了正面写的东西。", "它几乎全靠二级、五级、一级的进行撑起来。"):
        report = _review(
            _script(text), _evidence(HOSHINO_SOURCE), FactCheck(findings=[_finding(0, "not_factual")]), tracks=HOSHINO_TRACKS
        )
        assert [issue.code for issue in report.issues] == ["unchecked"], text
    # A view the host puts is still welcome.
    view = _review(_script("这一首，是那条线的延续。"), _evidence(HOSHINO_SOURCE), FactCheck(findings=[_finding(0, "not_factual")]))
    assert view.issues == []


def test_the_prompt_puts_rules_and_sources_before_the_sentences_in_a_stable_order() -> None:
    llm = Dispatch([], [FactCheck(findings=[_finding(0, "not_factual")])])
    evidence = list(reversed(_evidence("乙的说明文字。", "甲的说明文字。")))
    asyncio.run(FactChecker(llm).review(_script("先听一段。"), evidence))  # type: ignore[arg-type]
    prompt = llm.check_prompts[0]
    assert prompt.index("Return exactly one finding") < prompt.index("Sources (id: text):") < prompt.index("Sentences (numbered):")
    assert prompt.index("[e1]") < prompt.index("[e2]")


def test_a_sentence_after_a_removed_one_that_starts_with_this_piece_goes_with_it() -> None:
    from wavecast.intelligence.fact_support import _kept_sentences

    assert _kept_sentences(["先说他自己说。", "这一首，延续的就是那个方向。", "好，听歌。"], {0}) == ["好，听歌。"]

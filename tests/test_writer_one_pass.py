"""The release writing path preserves a telling and spends no calls reviewing it.

Fixed responses test the runtime contract, not the prose quality of a live model.
"""

import asyncio

import pytest
from wavecast.intelligence.models import OutputLanguage, RadioScript
from wavecast.intelligence.writer import WriterService

from tests.test_voice import Sequenced, _chapter, _closing, _script, _slot, _write


@pytest.mark.parametrize("text", [
    "刚才那首，吉他一层层叠起来。两个作品并排放在一起。所以这首可以换个角度听。",
    "《才二十三》让人想到时间。这个问题可以留在歌里，听听它怎样展开。",
    "和前面那首一样，这里也绕回了爱是什么。下一首是《Jody》。",
])
def test_style_and_unrecognized_titles_never_cut_up_or_rewrite_a_complete_block(text: str) -> None:
    llm = Sequenced(_script(text), _script("这份第二稿不该被请求。"))

    result = _write(llm)

    assert len(llm.prompts) == 1
    assert [block.text for block in result.blocks] == [text]
    assert [item.evidence_ids for item in result.blocks] == [[]]


@pytest.mark.parametrize("unsafe", [
    "他上个月又发行了新专辑。听听接下来的歌。",
    "他最近还在写歌。这个故事先放到这里。",
    "我小时候就听过这首歌。下一首是《Jody》。",
])
def test_a_time_or_invented_experience_problem_omits_the_whole_block(unsafe: str) -> None:
    llm = Sequenced(_script(unsafe))

    result = _write(llm, previous_committed_context="可靠素材已确认这位艺人已经离世。")

    assert result.blocks == []  # never keep a disconnected remnant of the paragraph
    assert len(llm.prompts) == 1


def test_a_spoken_override_cannot_hide_an_unanchored_claim() -> None:
    script = _script("2006 年他发行了这张专辑。")
    script.blocks[0].tts_text = "他上个月发行了这张新专辑。"

    assert _write(Sequenced(script)).blocks == []


@pytest.mark.parametrize("title", ["最近比较烦", "我记得", "去年夏天"])
@pytest.mark.parametrize("authored_speech", [False, True])
def test_literal_song_titles_survive_the_complete_path_including_spoken_conversion(
    title: str, authored_speech: bool,
) -> None:
    slot = _slot()
    assert slot.upcoming_track is not None
    track = slot.upcoming_track.model_copy(update={"canonical_title": title})
    slot = slot.model_copy(update={"chapter_track": track, "upcoming_track": track})
    text = f"下一首是《{title}》。"
    script = _script(text)
    if authored_speech:
        script.blocks[0].tts_text = f"下一首是{title}。"
    llm = Sequenced(script)

    result = asyncio.run(WriterService(llm).write(
        _chapter(), [], slot_context=slot, output_language=OutputLanguage.ZH_CN,
    ))

    assert isinstance(result, RadioScript)
    assert [block.text for block in result.blocks] == [text]
    assert result.blocks[0].tts_text == f"下一首是{title}。"
    assert len(llm.prompts) == 1


def test_traditional_chinese_cannot_bypass_the_time_guard_before_spoken_conversion() -> None:
    assert _write(Sequenced(_script("他上個月發行了新專輯。"))).blocks == []


def test_an_anchored_historical_release_is_kept_in_display_and_speech() -> None:
    text = "2006 年他发行了新专辑《爱爱爱》。这也是他第二张专辑。"
    llm = Sequenced(_script(text))

    result = _write(llm)

    assert [block.text for block in result.blocks] == [text]
    assert "二零零六年" in (result.blocks[0].tts_text or "")
    assert len(llm.prompts) == 1


def test_a_rejected_closing_still_has_a_real_ending_without_requesting_another_draft() -> None:
    from wavecast.stations import StationId, compose_signoff

    llm = Sequenced(_script("他最近正在筹备一张专辑。"))
    result = _closing(llm, StationId.PORTRAIT)

    assert [block.text for block in result.blocks] == [
        "这一程就走到这里。" + (compose_signoff(StationId.PORTRAIT, "programme-1") or "")
    ]
    assert len(llm.prompts) == 1


def test_dates_and_status_are_instructions_not_a_request_to_read_source_metadata() -> None:
    from wavecast.intelligence.models import Evidence

    source = Evidence(
        id="bio", claim_or_excerpt="这位艺人于 2025 年离世。",
        source_url="https://example.test/bio", source_provider="fixture", confidence=0.9,
        query="q", published_at="2025-03-01",
    )
    chapter = _chapter().model_copy(update={"evidence_ids": ["bio"]})
    llm = Sequenced(_script("下一首是《Jody》。"))
    result = asyncio.run(WriterService(llm).write(
        chapter, [source], slot_context=_slot(), output_language=OutputLanguage.ZH_CN,
    ))

    assert isinstance(result, RadioScript)
    prompt = llm.prompts[0]
    assert "2025-03-01" in prompt and "2025 年离世" in prompt
    assert "A publication date is not an event date" in prompt
    assert "posthumous releases need their own evidence" in prompt
    assert "Earlier narration is for continuity, never a source of facts" in prompt

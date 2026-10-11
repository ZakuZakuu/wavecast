"""A block the voice cannot read is rewritten, not silently lost; a closing never vanishes."""

import asyncio

from wavecast.intelligence.models import (
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
)
from wavecast.intelligence.writer import WriterService
from wavecast.stations import StationId, compose_signoff

from tests.test_voice import Sequenced, _chapter, _final_slot, _script, _write

JAPANESE = "Jody 之后是《千と千尋の神隠し》的音乐。"
CHINESE = "Jody 之后是《千与千寻》的音乐。"


def test_a_block_the_voice_cannot_read_is_sent_back_for_a_rewrite_in_chinese() -> None:
    llm = Sequenced(_script(JAPANESE), _script(CHINESE))

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert "The voice cannot read" in llm.prompts[1] and "千と千尋の神隠し" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [CHINESE]


def test_a_block_still_unreadable_after_the_rewrite_is_dropped() -> None:
    llm = Sequenced(_script(JAPANESE), _script(JAPANESE))

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert result.blocks == []


def _final_write(llm: Sequenced, station: StationId | None, route_tracks=()):  # type: ignore[no-untyped-def]
    result = asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_final_slot(),
            target_duration_seconds=16,
            output_language=OutputLanguage.ZH_CN,
            station=station,
            voice_seed="programme-1",
            route_tracks=list(route_tracks),
        )
    )
    assert isinstance(result, RadioScript)
    return result


def _outro(text: str) -> RadioScript:
    return RadioScript(
        blocks=[RadioScriptBlock(kind=RadioScriptBlockKind.OUTRO, text=text, duration_seconds=8)]
    )


def test_a_closing_that_cannot_be_read_is_replaced_by_the_sign_off_alone() -> None:
    bad = "这一程到「となりのトトロ」的《風のとおり道》为止。"
    llm = Sequenced(_outro(bad), _outro(bad))

    result = _final_write(llm, StationId.PORTRAIT)

    signoff = compose_signoff(StationId.PORTRAIT, "programme-1")
    assert [block.text for block in result.blocks] == [signoff]
    assert result.blocks[0].kind is RadioScriptBlockKind.OUTRO


def test_a_closing_may_name_any_song_of_the_programme_even_with_a_japanese_title() -> None:
    text = "这一程从《あの夏へ》走到了这里。"
    llm = Sequenced(_outro(text))

    result = _final_write(llm, StationId.PORTRAIT, route_tracks=["久石譲 - あの夏へ", "A - Jody"])

    assert len(llm.prompts) == 1  # nothing to rewrite: the application says the title for it
    assert "あの夏へ" in result.blocks[0].text  # the listener-visible copy keeps the title
    assert "あの夏へ" not in (result.blocks[0].tts_text or "")  # the voice is given a readable one
    assert result.blocks[0].text.endswith(compose_signoff(StationId.PORTRAIT, "programme-1") or "")


def test_the_writer_is_told_to_use_chinese_titles_or_say_what_a_foreign_title_means() -> None:
    llm = Sequenced(_script("Jody 是同一个人写的。"))

    _write(llm)

    prompt = llm.prompts[0]
    assert "speaks only Chinese and English" in prompt
    assert "established Chinese title" in prompt
    assert "这首歌的名字，中文意思是" in prompt
    assert "do not invent a Chinese title" in prompt


def test_the_rewrite_for_unreadable_text_offers_the_meaning_phrase() -> None:
    llm = Sequenced(_script(JAPANESE), _script(CHINESE))

    _write(llm)

    assert "这首歌的名字，中文意思是" in llm.prompts[1]

import asyncio

import pytest
from wavecast.intelligence.models import (
    NarrationSlotContext,
    NarrationSlotPlacement,
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
)
from wavecast.intelligence.voice import (
    MOVE_INSTRUCTIONS,
    STATION_VOICES,
    Move,
    max_characters,
    move_for,
    pick_examples,
    voice_instructions,
)
from wavecast.intelligence.writer import WriterService
from wavecast.stations import StationId

from tests.test_intelligence_services import StructuredFixture, skeleton


def test_every_station_has_a_voice_and_every_move_an_instruction() -> None:
    assert set(STATION_VOICES) == set(StationId)
    assert set(MOVE_INSTRUCTIONS) == set(Move)


def test_moves_are_deterministic_for_a_seed() -> None:
    first = [move_for("programme-1", StationId.CRATE, index) for index in range(12)]
    again = [move_for("programme-1", StationId.CRATE, index) for index in range(12)]

    assert first == again


def test_a_move_never_repeats_the_one_before_it() -> None:
    for station in (StationId.CASUAL, StationId.CRATE, StationId.PORTRAIT, StationId.LINEAGE):
        for seed in ("a", "b", "c", "programme-42"):
            moves = [move_for(seed, station, index) for index in range(20)]
            assert all(left != right for left, right in zip(moves, moves[1:], strict=False))


def test_different_programmes_get_different_move_sequences() -> None:
    sequences = {
        tuple(move_for(f"programme-{n}", StationId.CASUAL, i) for i in range(8)) for n in range(20)
    }

    assert len(sequences) > 10


def test_moves_come_from_the_stations_own_mix() -> None:
    portrait_moves = {move_for(f"p{n}", StationId.PORTRAIT, 1) for n in range(60)}

    assert Move.ASK not in portrait_moves  # the profile station never asks questions
    assert Move.FACT in portrait_moves


def test_examples_vary_with_the_programme_but_are_a_subset_of_the_voice() -> None:
    voice = STATION_VOICES[StationId.CASUAL]
    picks = {tuple(pick_examples(f"p{n}", StationId.CASUAL, 1)) for n in range(30)}

    assert len(picks) > 1
    assert all(set(pick) <= set(voice.examples) for pick in picks)


def test_the_character_limit_follows_the_window() -> None:
    assert max_characters(None) is None
    assert max_characters(14) == 63
    assert max_characters(2) == 12


def test_instructions_name_the_move_limit_and_banned_openers() -> None:
    text = voice_instructions(
        station=StationId.LINEAGE,
        seed="s",
        index=2,
        window_seconds=14,
        used_openers=["刚才", "Jody"],
    )

    assert "Station: 来龙去脉" in text
    assert f"({move_for('s', StationId.LINEAGE, 2).value})" in text
    assert "between 40 and 63 Chinese characters" in text
    assert "never with 刚才、接下来、我们先从、下一首" in text
    assert "刚才、Jody" in text
    assert "不是……而是……" in text


def test_opening_and_closing_blocks_have_their_own_instruction() -> None:
    opening = voice_instructions(
        station=StationId.CASUAL, seed="s", index=0, window_seconds=12, is_opening=True
    )
    closing = voice_instructions(
        station=StationId.CASUAL, seed="s", index=9, window_seconds=25, is_final=True
    )

    assert "This is the opening" in opening and "This block's move" not in opening
    assert "closes the programme" in closing and "This block's move" not in closing


def test_the_night_voice_offers_no_examples_to_copy() -> None:
    text = voice_instructions(station=StationId.NIGHT, seed="s", index=1, window_seconds=6)

    assert "Register samples" not in text


def _slot() -> NarrationSlotContext:
    return NarrationSlotContext(
        chapter_index=2,
        placement=NarrationSlotPlacement.BEFORE_TRACK,
        allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
        chapter_track=ResolvedTrack(track_ref="n:2", canonical_artist="A", canonical_title="Jody"),
        just_played_track=ResolvedTrack(track_ref="n:1", canonical_artist="A", canonical_title="One"),
        upcoming_track=ResolvedTrack(track_ref="n:2", canonical_artist="A", canonical_title="Jody"),
    )


def _chapter():
    return skeleton().chapters[0].model_copy(update={"evidence_ids": []})


def _script(text: str) -> RadioScript:
    return RadioScript(
        blocks=[
            RadioScriptBlock(kind=RadioScriptBlockKind.TRACK_INTRO, text=text, duration_seconds=8)
        ]
    )


class Sequenced:
    """Returns the scripted outputs in order; records every prompt."""

    def __init__(self, *outputs: RadioScript) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def structured(self, prompt: str, _type: type[object], **_kwargs: object) -> object:
        self.prompts.append(prompt)
        return self.outputs[min(len(self.prompts) - 1, len(self.outputs) - 1)]


def _write(llm: Sequenced, **kwargs) -> RadioScript:
    result = asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CASUAL,
            voice_seed="programme-1",
            **kwargs,
        )
    )
    assert isinstance(result, RadioScript)
    return result


def test_the_voice_section_reaches_the_prompt() -> None:
    llm = Sequenced(_script("Jody 是同一个人写的。"))

    _write(llm, used_openers=["刚才"])

    assert "Voice:" in llm.prompts[0]
    assert "Chinese characters" in llm.prompts[0]
    assert "刚才" in llm.prompts[0]


def test_a_clean_draft_is_not_rewritten() -> None:
    llm = Sequenced(_script("Jody 是同一个人写的。"))

    result = _write(llm)

    assert len(llm.prompts) == 1
    assert result.blocks[0].text == "Jody 是同一个人写的。"


def test_a_draft_with_stock_phrasing_gets_one_rewrite_with_the_reasons() -> None:
    llm = Sequenced(
        _script("刚才那首，吉他一层层叠起来，慢慢铺开。"),
        _script("Jody 是同一个人写的，节奏松很多。"),
    )

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert "stock figurative wording" in llm.prompts[1]
    assert "一层层" in llm.prompts[1]
    assert "starts with 刚才" in llm.prompts[1]
    assert result.blocks[0].text == "Jody 是同一个人写的，节奏松很多。"


def test_a_rewrite_that_is_no_better_is_discarded() -> None:
    first = _script("刚才那首，吉他一层层叠起来。")
    worse = _script("刚才那首，吉他一层层叠起来，慢慢铺开，这也提醒我们很多。")
    llm = Sequenced(first, worse)

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert result.blocks[0].text == first.blocks[0].text


def test_rewriting_is_bounded_to_one_extra_call() -> None:
    bad = _script("刚才那首，吉他一层层叠起来。")
    llm = Sequenced(bad, bad, bad)

    _write(llm)

    assert len(llm.prompts) == 2


def test_rewriting_can_be_turned_off() -> None:
    llm = Sequenced(_script("刚才那首，吉他一层层叠起来。"))

    asyncio.run(
        WriterService(llm, max_revisions=0).write(
            _chapter(), [], slot_context=_slot(), output_language=OutputLanguage.ZH_CN
        )
    )

    assert len(llm.prompts) == 1


@pytest.mark.parametrize("language", [OutputLanguage.EN_US, OutputLanguage.JA_JP])
def test_the_chinese_voice_section_is_not_used_for_other_languages(language) -> None:
    llm = StructuredFixture(RadioScript(blocks=[]))
    asyncio.run(
        WriterService(llm).write(
            _chapter(), [], slot_context=_slot(), output_language=language, station=StationId.CASUAL
        )
    )

    assert "Voice:" not in llm.prompts[0]


def test_a_year_that_is_not_in_the_evidence_triggers_a_rewrite() -> None:
    from wavecast.intelligence.models import Evidence

    chapter = skeleton().chapters[0]  # evidence_ids == ["e1"]
    evidence = [
        Evidence(
            id="e1",
            claim_or_excerpt="《Ride on Time》是山下达郎 1980 年的专辑。",
            source_url="https://example.test",
            source_provider="fixture",
            confidence=0.8,
            query="q",
        )
    ]
    llm = Sequenced(_script("Jody 是 1979 年的歌。"), _script("Jody 是 1980 年的歌。"))

    result = asyncio.run(
        WriterService(llm).write(
            chapter,
            evidence,
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
        )
    )

    assert len(llm.prompts) == 2
    assert "gives a year that is not in the evidence (1979)" in llm.prompts[1]
    assert result.blocks[0].text == "Jody 是 1980 年的歌。"

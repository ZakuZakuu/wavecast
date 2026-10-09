"""The host never names an artist the programme does not play."""

import asyncio

from wavecast.intelligence.models import (
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
)
from wavecast.intelligence.writer import WriterService
from wavecast.narration_quality import check_block
from wavecast.stations import StationId

from tests.test_voice import Sequenced, _chapter, _script, _slot, _write

BAD = "Jody 之后，Explosions In The Sky 会接上来。"
GOOD = "Jody 是同一个人写的。"


def _two_blocks(first: str, second: str) -> RadioScript:
    return RadioScript(
        blocks=[
            RadioScriptBlock(kind=RadioScriptBlockKind.TRACK_INTRO, text=first, duration_seconds=8),
            RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, text=second, duration_seconds=8),
        ]
    )


def test_a_block_that_still_names_an_unplayed_artist_after_the_rewrite_is_dropped() -> None:
    llm = Sequenced(_script(BAD), _script(BAD))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert len(llm.prompts) == 2  # the rewrite was tried
    assert result.blocks == []


def test_only_the_conflicting_block_goes() -> None:
    llm = Sequenced(_two_blocks(BAD, GOOD), _two_blocks(BAD, GOOD))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert [block.text for block in result.blocks] == [GOOD]


def test_a_rewrite_that_fixes_the_conflict_is_kept() -> None:
    llm = Sequenced(_script(BAD), _script(GOOD))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert [block.text for block in result.blocks] == [GOOD]


def test_the_original_with_a_conflict_is_not_kept_when_the_rewrite_is_not_better() -> None:
    # The rewrite is longer and no better; the old rule kept the original, conflict included.
    llm = Sequenced(_script(BAD), _script(BAD + "还有别的。"))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert result.blocks == []


def test_the_drop_does_not_depend_on_a_rewrite_being_allowed() -> None:
    llm = Sequenced(_script(BAD))

    result = asyncio.run(
        WriterService(llm, max_revisions=0).write(
            _chapter(),
            [],
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CASUAL,
            voice_seed="programme-1",
            unplayed_artists=["Explosions In The Sky"],
        )
    )

    assert isinstance(result, RadioScript)
    assert len(llm.prompts) == 1
    assert result.blocks == []


def test_nothing_is_dropped_when_every_planned_artist_plays() -> None:
    llm = Sequenced(_script(GOOD))

    result = _write(llm, unplayed_artists=[])

    assert [block.text for block in result.blocks] == [GOOD]


def test_a_requested_artist_the_programme_cannot_play_is_named_to_the_writer() -> None:
    llm = Sequenced(_script(GOOD))

    _write(llm, unfulfilled_artists=["Explosions in the Sky"], unplayed_artists=["Explosions in the Sky"])

    prompt = llm.prompts[0]
    assert "The listener asked for Explosions in the Sky, but this programme does not play them" in prompt
    assert "heading to them" in prompt


def test_the_writer_prompt_is_unchanged_when_every_requested_artist_plays() -> None:
    llm = Sequenced(_script(GOOD))

    _write(llm, unfulfilled_artists=[])

    assert "The listener asked for" not in llm.prompts[0]


def test_an_artist_is_matched_as_a_word_not_inside_another_word() -> None:
    assert not [
        issue
        for issue in check_block("This category is wide.", unplayed_names=["Cat"]).issues
        if issue.startswith("mentions_unplayed")
    ]
    assert [
        issue
        for issue in check_block("Cat Power is next.", unplayed_names=["Cat"]).issues
        if issue.startswith("mentions_unplayed")
    ]
    assert [
        issue
        for issue in check_block("久石让写的这段。", unplayed_names=["久石譲"]).issues
        if issue.startswith("mentions_unplayed")
    ]


# --- closing and repetition (2026-10-09 live programmes) ------------------------------------


def _final_slot():
    from wavecast.intelligence.models import (
        NarrationSlotContext,
        NarrationSlotPlacement,
        ResolvedTrack,
    )

    return NarrationSlotContext(
        chapter_index=3,
        placement=NarrationSlotPlacement.AFTER_FINAL_TRACK,
        allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
        just_played_track=ResolvedTrack(
            track_ref="n:4", canonical_artist="E", canonical_title="Your Hand in Mine"
        ),
        is_final=True,
    )


def _outro(text: str) -> RadioScript:
    return RadioScript(
        blocks=[RadioScriptBlock(kind=RadioScriptBlockKind.OUTRO, text=text, duration_seconds=10)]
    )


def _write_final(llm: Sequenced, **kwargs) -> RadioScript:
    result = asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_final_slot(),
            target_duration_seconds=20,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CASUAL,
            voice_seed="programme-1",
            **kwargs,
        )
    )
    assert isinstance(result, RadioScript)
    return result


ROUTE_TRACKS = [
    "Hammock - Breathturn",
    "Mogwai - Take Me Somewhere Nice",
    "Explosions In The Sky - Your Hand in Mine",
]


def test_an_outro_that_lists_the_route_is_rewritten() -> None:
    recap = "从 Breathturn 到 Take Me Somewhere Nice，再到 Your Hand in Mine，就到这儿。"
    plain = "最后是 Your Hand in Mine，就到这儿。"
    llm = Sequenced(_outro(recap), _outro(plain))

    result = _write_final(llm, route_tracks=ROUTE_TRACKS)

    assert len(llm.prompts) == 2
    assert "one by one" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [plain]


def test_a_block_that_repeats_an_earlier_one_is_rewritten() -> None:
    earlier = "他们受访时说，早年开始做纯器乐，就是因为受了 Mogwai 很大的影响。"
    repeat = "他们说过，早年做纯器乐是受了 Mogwai 的影响。"
    fresh = "今晚就到这儿。"
    llm = Sequenced(_outro(repeat), _outro(fresh))

    result = _write_final(llm, previous_committed_context=earlier, route_tracks=ROUTE_TRACKS)

    assert len(llm.prompts) == 2
    assert "already said" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [fresh]


def test_the_closing_guidance_forbids_listing_the_route_and_repeating_earlier_blocks() -> None:
    llm = Sequenced(_outro("今晚就到这儿。"))

    _write_final(llm)

    prompt = llm.prompts[0]
    assert "Never list the tracks played" in prompt
    assert "do not repeat anything an earlier block already said" in prompt


def test_a_length_of_time_the_evidence_does_not_give_is_rewritten() -> None:
    invented = "回到 Mogwai，这首歌八分钟，吉他慢慢堆起来。"
    plain = "回到 Mogwai，这首歌的吉他从头到尾没停。"
    llm = Sequenced(_script(invented), _script(plain))

    result = _write(llm)

    assert len(llm.prompts) == 2
    assert "how long a song is" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [plain]


def test_a_length_of_time_is_rewritten_even_when_the_evidence_gives_it() -> None:
    from wavecast.intelligence.models import Evidence

    # The evidence describes the album version; the file that plays can be shorter.
    evidence = Evidence(
        id="e1",
        claim_or_excerpt="这首歌的专辑版长达十六分钟。",
        source_url="https://example.com/a",
        source_provider="fixture",
        confidence=0.9,
        query="fixture",
    )
    chapter = _chapter().model_copy(update={"evidence_ids": ["e1"]})
    stated = "回到 Mogwai，这首十六分钟，平静和轰鸣一直在换。"
    plain = "回到 Mogwai，平静和轰鸣一直在换。"
    llm = Sequenced(_script(stated), _script(plain))

    result = asyncio.run(
        WriterService(llm).write(
            chapter,
            [evidence],
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CASUAL,
            voice_seed="programme-1",
        )
    )

    assert len(llm.prompts) == 2
    assert isinstance(result, RadioScript)
    assert [block.text for block in result.blocks] == [plain]


def test_the_voice_instructions_forbid_questions_and_sound_similes() -> None:
    llm = Sequenced(_script("Jody 是同一个人写的。"))

    _write(llm)

    assert "questions put to the listener" in llm.prompts[0]
    assert "similes for how music sounds; how long a song is" in llm.prompts[0]


def test_a_closing_with_a_year_is_rewritten() -> None:
    bio = "最后停在 Breathturn。Hammock 2004 年前后在纳什维尔成形。"
    plain = "最后停在 Hammock 的 Breathturn，就到这儿。"
    llm = Sequenced(_outro(bio), _outro(plain))

    result = _write_final(llm, route_tracks=ROUTE_TRACKS)

    assert len(llm.prompts) == 2
    assert "closing" in llm.prompts[1]
    assert [block.text for block in result.blocks] == [plain]

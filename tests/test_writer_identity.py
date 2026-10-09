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

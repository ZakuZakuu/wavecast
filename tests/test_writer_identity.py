"""The host never names an artist the programme does not play."""

from wavecast.intelligence.models import RadioScript, RadioScriptBlock, RadioScriptBlockKind
from wavecast.narration_quality import check_block
from wavecast.stations import StationId

from tests.test_voice import Sequenced, _closing, _script, _write

BAD = "Jody 之后，Explosions In The Sky 会接上来。"
GOOD = "Jody 是同一个人写的。"


def _two_blocks(first: str, second: str) -> RadioScript:
    return RadioScript(
        blocks=[
            RadioScriptBlock(kind=RadioScriptBlockKind.TRACK_INTRO, text=first, duration_seconds=8),
            RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, text=second, duration_seconds=8),
        ]
    )


def test_a_block_promising_an_unplayed_artist_is_dropped_without_rewriting() -> None:
    llm = Sequenced(_script(BAD))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert len(llm.prompts) == 1
    assert result.blocks == []


def test_only_the_conflicting_block_goes() -> None:
    llm = Sequenced(_two_blocks(BAD, GOOD))

    result = _write(llm, unplayed_artists=["Explosions In The Sky"])

    assert [block.text for block in result.blocks] == [GOOD]


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


def test_the_closing_guidance_forbids_listing_the_route_and_repeating_earlier_blocks() -> None:
    llm = Sequenced(_script("今晚就到这儿。"))

    _closing(llm, StationId.CASUAL)

    prompt = llm.prompts[0]
    assert "never list them" in prompt
    assert "repeat nothing an earlier block already said" in prompt
    assert "give no year" in prompt


def test_the_voice_instructions_forbid_questions_and_sound_similes() -> None:
    llm = Sequenced(_script("Jody 是同一个人写的。"))

    _write(llm)

    assert "questions put to the listener" in llm.prompts[0]
    assert "similes for how music sounds; how long a song is" in llm.prompts[0]


# --- a block talks about the two tracks around it -------------------------------------------

OTHER_TRACKS = ["A - One", "A - Jody", "A - Struttin' With Some Barbecue"]


def test_naming_the_track_just_played_and_the_next_is_fine() -> None:
    fine = "One 刚放完，Jody 是同一个人写的。"
    llm = Sequenced(_script(fine))

    result = _write(llm, route_tracks=OTHER_TRACKS)

    assert len(llm.prompts) == 1
    assert [block.text for block in result.blocks] == [fine]


def test_a_very_short_title_is_not_counted_as_a_mention() -> None:
    from wavecast.narration_quality import check_block

    issues = check_block(
        "他回到 Home 的路上，Jody 响起来。",
        route_titles=["Home", "Jody"],
        focus_titles=["Jody"],
    ).issues

    assert not [issue for issue in issues if issue.startswith("names_other_track")]


def test_the_check_is_off_without_neighbours_and_in_the_closing() -> None:
    from wavecast.narration_quality import check_block

    text = "Struttin' With Some Barbecue 是最早的一首。"
    titles = ["Jody", "Struttin' With Some Barbecue"]

    assert not [i for i in check_block(text, route_titles=titles).issues if i.startswith("names_other")]
    assert not [
        i
        for i in check_block(text, route_titles=titles, focus_titles=["Jody"], is_final=True).issues
        if i.startswith("names_other")
    ]

import asyncio

import pytest
from wavecast.intelligence.models import (
    NarrationSlotContext,
    NarrationSlotPlacement,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
)
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import NarrationSegment, SegmentState
from wavecast.providers.fakes import MockTTSProvider
from wavecast.spoken_form import (
    KnownTrack,
    has_unspeakable_script,
    spoken_artist,
    spoken_title,
    to_spoken_form,
)
from wavecast.storage import LocalObjectStorageProvider

from tests.test_intelligence_services import StructuredFixture, skeleton


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("夏天的风", "夏天的风"),  # Chinese is read as it is
        ("Jody", "Jody"),  # short English is read as it is
        ("Take Me Somewhere Nice", "Take Me Somewhere Nice"),
        ("Summer (《菊次郎的夏天》电影主题曲斯坦威钢琴版)", "Summer"),  # version suffix dropped
        ("天空の城ラピュタ", None),  # Japanese is not read
        ("뿌리", None),  # neither is Korean
        ("Cello Suite No. 1 in G Major, Bwv 1007: I. Prélude", None),  # catalogue-style
        ("Sonata No. 14", None),  # a short catalogue-style title is still not read
        ("Symphony No. 5", None),
        ("Simon & Garfunkel Medley", "Simon and Garfunkel Medley"),
        ("One Two Three Four Five Six Seven Eight", None),  # too long to read
    ],
)
def test_spoken_title_chooses_what_the_voice_can_say(title: str, expected: str | None) -> None:
    assert spoken_title(title) == expected


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ("久石譲", "久石让"),  # kanji credit is read in Chinese
        ("山下達郎", "山下达郎"),
        ("Mogwai", "Mogwai"),
        ("宇多田ヒカル", "宇多田光"),  # a known Chinese name
        ("あいみょん", None),  # unknown kana name: not spoken
        ("A, B, C", "A和B"),  # at most two are named
        ("あいみょん, Mogwai", "Mogwai"),
    ],
)
def test_spoken_artist(artist: str, expected: str | None) -> None:
    assert spoken_artist(artist) == expected


def test_known_tracks_get_spoken_forms_and_the_display_text_is_untouched() -> None:
    tracks = [KnownTrack("久石譲", "天空の城ラピュタ"), KnownTrack("山下達郎", "Jody")]
    text = "刚才是久石譲的《天空の城ラピュタ》，下一首是山下達郎的《Jody》。"

    spoken = to_spoken_form(text, tracks)

    assert spoken.tts_text == "刚才是久石让的这首歌，下一首是山下达郎的Jody。"
    assert spoken.ok
    assert "天空の城ラピュタ" in text


def test_an_unspeakable_title_is_not_doubled_when_the_text_already_says_song() -> None:
    spoken = to_spoken_form("《天空の城ラピュタ》这首歌写于1986年。", [KnownTrack("久石譲", "天空の城ラピュタ")])

    assert spoken.tts_text == "这首歌写于1986年。"


def test_an_original_name_aside_is_dropped_from_speech() -> None:
    spoken = to_spoken_form("它的名字（原名：もののけ姫）很有名。")

    assert spoken.tts_text == "它的名字很有名。"
    assert spoken.ok


def test_names_the_application_does_not_know_are_reported_not_guessed() -> None:
    spoken = to_spoken_form("他还写过「もののけ姫」。", [KnownTrack("久石譲", "天空の城ラピュタ")])

    assert not spoken.ok
    assert any("もののけ姫" in item for item in spoken.unspeakable)


def test_an_authored_tts_text_is_the_base_for_substitution() -> None:
    spoken = to_spoken_form(
        "展示用的文字", [KnownTrack("a", "Jody")], tts_text="朗读用的《Jody》"
    )

    assert spoken.tts_text == "朗读用的Jody"


def test_unspeakable_script_detection() -> None:
    assert has_unspeakable_script("ラピュタ")
    assert has_unspeakable_script("한국어")
    assert not has_unspeakable_script("Hello 你好 Prélude 1986年")


def _chapter():
    return skeleton().chapters[0].model_copy(update={"evidence_ids": []})


def _slot(just_played: ResolvedTrack, upcoming: ResolvedTrack) -> NarrationSlotContext:
    return NarrationSlotContext(
        chapter_index=2,
        placement=NarrationSlotPlacement.BEFORE_TRACK,
        allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
        chapter_track=upcoming,
        just_played_track=just_played,
        upcoming_track=upcoming,
    )


def _block(text: str, tts_text: str | None = None) -> RadioScriptBlock:
    return RadioScriptBlock(
        kind=RadioScriptBlockKind.TRACK_INTRO,
        text=text,
        tts_text=tts_text,
        duration_seconds=10,
    )


def _write(blocks: list[RadioScriptBlock]) -> RadioScript:
    played = ResolvedTrack(track_ref="n:1", canonical_artist="久石譲", canonical_title="天空の城ラピュタ")
    coming = ResolvedTrack(track_ref="n:2", canonical_artist="山下達郎", canonical_title="Jody")
    service = WriterService(StructuredFixture(RadioScript(blocks=blocks)))
    result = asyncio.run(
        service.write(_chapter(), [], slot_context=_slot(played, coming))
    )
    assert isinstance(result, RadioScript)
    return result


def test_writer_blocks_keep_display_text_and_get_a_speakable_tts_text() -> None:
    result = _write([_block("刚才是《天空の城ラピュタ》，接下来是山下達郎的《Jody》。")])

    assert result.blocks[0].text == "刚才是《天空の城ラピュタ》，接下来是山下達郎的《Jody》。"
    assert result.blocks[0].tts_text == "刚才是这首歌，接下来是山下达郎的Jody。"


def test_writer_block_that_cannot_be_spoken_is_dropped_not_sent_to_tts() -> None:
    result = _write(
        [
            _block("他还写过「もののけ姫」。"),
            _block("接下来是山下達郎的《Jody》。"),
        ]
    )

    assert [block.text for block in result.blocks] == ["接下来是山下達郎的《Jody》。"]


def test_writer_prompt_tells_the_model_not_to_translate_titles() -> None:
    fixture = StructuredFixture(RadioScript(blocks=[]))
    asyncio.run(WriterService(fixture).write(_chapter(), []))

    assert "never translate or transliterate a title" in fixture.prompts[0]


def test_materializer_never_sends_unreadable_text_to_the_voice(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    provider = MockTTSProvider(storage)
    segment = NarrationSegment(
        id="n1",
        chapter_id="chapter-2",
        order=1,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=8,
        title="Intro",
        narration_text="接下来是《もののけ姫》。",
    )

    result = asyncio.run(NarrationMaterializer(provider, storage).materialize(segment))

    assert result.state is SegmentState.SKIPPED
    assert provider.calls == 0


def test_the_opening_host_line_is_spoken_in_a_readable_form() -> None:
    from wavecast.models.episode import CoverParams, EpisodeSeed

    from services.api import main as api_module

    def seed(text: str, seed_id: str) -> EpisodeSeed:
        return EpisodeSeed(
            id=seed_id,
            title="Opening",
            topic="Japanese pop",
            short_description="x",
            estimated_duration_seconds=600,
            opening_track_ref="mock:opening",
            opening_track_title="天空の城ラピュタ",
            opening_track_artist="久石譲",
            opening_narration_text=text,
            cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
        )

    readable = seed("我们先从久石譲的《天空の城ラピュタ》开始。", "spoken-open-1")
    episode = api_module.orchestrator.start(readable, "spoken-listener")
    prepared = asyncio.run(api_module._prepare_opening_host(episode, readable))
    host = next(item for item in prepared.segments if item.id == "segment-opening-host")
    assert host.narration_text == "我们先从久石譲的《天空の城ラピュタ》开始。"
    assert host.tts_text == "我们先从久石让的这首歌开始。"

    unreadable = seed("先听听《もののけ姫》。", "spoken-open-2")
    episode = api_module.orchestrator.start(unreadable, "spoken-listener-2")
    skipped = asyncio.run(api_module._prepare_opening_host(episode, unreadable))
    assert all(item.id != "segment-opening-host" for item in skipped.segments)

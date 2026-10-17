"""What can be said about the track that plays: found for it, bound to it, and checked."""

from __future__ import annotations

import asyncio

import pytest
from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrativeRole,
    OutputLanguage,
    ResearchBundle,
    ResolvedTrack,
)
from wavecast.intelligence.track_research import (
    TalkingPoint,
    TrackResearchService,
    _Briefing,
    _queries,
    _RawPoint,
    mentions_track,
    verified_points,
)
from wavecast.intelligence.writer import WriterService
from wavecast.models.progressive import ProgressiveAssemblyChapter
from wavecast.providers.contracts import SearchResult
from wavecast.stations import StationId

from tests.test_voice import Sequenced, _chapter, _script, _slot

SUMMER = ResolvedTrack(
    track_ref="n:1", canonical_artist="久石譲", canonical_title="Summer", album="菊次郎の夏 オリジナル・サウンドトラック"
)
KIMURA = ResolvedTrack(
    track_ref="n:2",
    canonical_artist="木村弓",
    canonical_title="いつも何度でも",
    spoken_title="永远同在",
    album="千と千尋の神隠し サウンドトラック",
)
SECOND_ON_ALBUM = ResolvedTrack(
    track_ref="n:3",
    canonical_artist="久石譲",
    canonical_title="あの夏へ",
    spoken_title="回到那个夏天",
    album="千と千尋の神隠し サウンドトラック",
)

SUMMER_PAGE = "《Summer》是日本作曲家久石让创作的钢琴曲，为北野武执导的电影《菊次郎的夏天》的主题曲。"
KIMURA_PAGE = "《いつも何度でも》由木村弓作曲并演唱，是动画电影《千与千寻》的片尾曲，收录于《千と千尋の神隠し サウンドトラック》。"
ARTIST_ONLY_PAGE = "久石让，日本作曲家，与宫崎骏长期合作，作品遍及电影与音乐会。"
HOMONYM_PAGE = "Summer is the warmest season of the year in the northern hemisphere."


def _evidence(identifier: str, text: str) -> Evidence:
    return Evidence(
        id=f"evidence-{identifier}",
        claim_or_excerpt=text,
        source_url=f"https://example.test/{identifier}",
        source_provider="fixture",
        confidence=0.8,
        query="q",
        source_title="",
    )


class Briefer:
    """Answers the briefing call; records prompts."""

    def __init__(self, *answers: _Briefing | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def structured(self, prompt: str, _type: type[object], **_kwargs: object) -> object:
        self.prompts.append(prompt)
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


class DynamicBriefer:
    """Cites whichever source it is shown first, with a fixed text and quote."""

    def __init__(self, text: str, quote: str) -> None:
        self.text, self.quote = text, quote
        self.prompts: list[str] = []

    async def structured(self, prompt: str, _type: type[object], **_kwargs: object) -> object:
        import re

        self.prompts.append(prompt)
        match = re.search(r"\[(evidence-[0-9a-f]+)\]", prompt)
        points = [_RawPoint(text=self.text, source=match.group(1), quote=self.quote)] if match else []
        return _Briefing(points=points)


class Searcher:
    def __init__(self, *pages: tuple[str, str] | Exception) -> None:
        self.pages = list(pages)
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int = 5, stage: str | None = None) -> list[SearchResult]:
        self.queries.append(query)
        if any(isinstance(page, Exception) for page in self.pages):
            raise RuntimeError("search down")
        return [
            SearchResult(
                title=title, url=f"https://example.test/{abs(hash(text)) % 10_000}", snippet=text,
                provider="fixture", query=query, content=text,
            )
            for title, text in self.pages  # type: ignore[misc]
        ][:limit]


def _point(text: str, source: str, quote: str) -> _RawPoint:
    return _RawPoint(text=text, source=source, quote=quote)


def _service(searcher: Searcher, briefer: Briefer | DynamicBriefer) -> TrackResearchService:
    return TrackResearchService(search=searcher, llm=briefer)  # type: ignore[arg-type]


def _prepare(service: TrackResearchService, track: ResolvedTrack, evidence: list[Evidence], station=StationId.PORTRAIT, episode="e1"):  # type: ignore[no-untyped-def]
    return asyncio.run(
        service.prepare(episode_id=episode, track=track, evidence=evidence, station=station, subject="久石让")
    )


# --- is the page about the recording? ----------------------------------------------------------


def test_a_page_about_the_artist_is_not_about_the_song() -> None:
    assert mentions_track(SUMMER_PAGE, SUMMER)
    assert mentions_track("专辑《千と千尋の神隠し サウンドトラック》曲目", SECOND_ON_ALBUM)
    assert mentions_track("片尾曲《永远同在》", KIMURA)  # the catalog's Chinese title
    assert not mentions_track(ARTIST_ONLY_PAGE, SUMMER)


def test_a_short_latin_title_needs_the_artist_next_to_it() -> None:
    short = ResolvedTrack(track_ref="n:9", canonical_artist="Some Band", canonical_title="Home")
    assert not mentions_track("There is no place like home.", short)
    assert mentions_track("Some Band recorded Home in 2010.", short)


def test_a_version_label_in_the_title_does_not_hide_the_work() -> None:
    piano = ResolvedTrack(track_ref="n:4", canonical_artist="久石譲", canonical_title="Summer (《菊次郎的夏天》钢琴版)")
    assert mentions_track(SUMMER_PAGE, piano)


def test_the_first_query_is_about_the_album_when_the_catalog_names_one() -> None:
    assert "千と千尋の神隠し サウンドトラック" in _queries(KIMURA)[0]
    assert "いつも何度でも" in _queries(ResolvedTrack(track_ref="n:5", canonical_artist="木村弓", canonical_title="いつも何度でも"))[0]


# --- finding and checking ----------------------------------------------------------------------


def test_what_is_already_known_about_the_track_is_used_without_a_search() -> None:
    searcher = Searcher()
    briefer = Briefer(
        _Briefing(points=[_point("《Summer》是《菊次郎的夏天》的主题曲", "evidence-s", "为北野武执导的电影《菊次郎的夏天》的主题曲")])
    )

    result = _prepare(_service(searcher, briefer), SUMMER, [_evidence("s", SUMMER_PAGE), _evidence("a", ARTIST_ONLY_PAGE)])

    assert searcher.queries == [] and result is not None
    assert [point.evidence_id for point in result.points] == ["evidence-s"]
    assert result.evidence_ids == ["evidence-s"] and result.evidence == []  # nothing new to store


def test_a_missing_track_is_searched_and_only_pages_about_it_are_kept() -> None:
    searcher = Searcher(("久石让简介", ARTIST_ONLY_PAGE), ("Summer 词条", HOMONYM_PAGE), ("千与千寻原声", KIMURA_PAGE))
    briefer = Briefer(
        _Briefing(points=[_point("《永远同在》是《千与千寻》的片尾曲，木村弓作曲并演唱", "", "")]),
    )

    result = _prepare(_service(searcher, briefer), KIMURA, [_evidence("a", ARTIST_ONLY_PAGE)])

    assert result is not None and result.searches >= 1
    assert [item.track_refs for item in result.evidence] == [["n:2"]]  # only the page about it
    assert "木村弓作曲" in result.evidence[0].claim_or_excerpt


def test_points_survive_only_when_the_quote_is_in_the_source() -> None:
    sources = {"evidence-k": KIMURA_PAGE}

    kept = verified_points(
        [_point("《永远同在》由木村弓作曲并演唱", "evidence-k", "《いつも何度でも》由木村弓作曲并演唱")], sources, KIMURA, {}
    )
    invented = verified_points(
        [_point("《永远同在》由久石让作曲", "evidence-k", "由久石让作曲并担任指挥")], sources, KIMURA
    )
    wrong_role = verified_points(
        [_point("《永远同在》由木村弓作曲", "evidence-k", "是动画电影《千与千寻》的片尾曲")], sources, KIMURA
    )
    wrong_source = verified_points([_point("片尾曲", "evidence-zzz", "是动画电影《千与千寻》的片尾曲")], sources, KIMURA)
    other_work = verified_points(
        [_point("它是《龙猫》的片尾曲", "evidence-k", "是动画电影《千与千寻》的片尾曲")], sources, KIMURA
    )

    assert [point.evidence_id for point in kept] == ["evidence-k"]
    assert invented == [] and wrong_role == [] and wrong_source == [] and other_work == []


def test_old_relative_times_are_removed_from_material_before_writing_not_cut_from_scripts() -> None:
    source = "2006年他发行了新专辑。报道说，他上个月发行了新专辑。"
    points = [
        _point("他上个月发行了新专辑", "e", "他上个月发行了新专辑"),
        _point("2006年他发行了新专辑", "e", "2006年他发行了新专辑"),
    ]

    assert [p.text for p in verified_points(points, {"e": source})] == ["2006年他发行了新专辑"]
    assert [p.text for p in verified_stories(points, {"e": source})] == ["2006年他发行了新专辑"]


def test_track_and_background_briefing_receive_publication_dates_without_changing_quotes() -> None:
    class Capture:
        def __init__(self):
            self.prompts = []

        async def structured(self, prompt, output_type, **_kwargs):
            self.prompts.append(prompt)
            return output_type()

    llm = Capture()
    service = _service(Searcher(), llm)  # type: ignore[arg-type]
    source = _evidence("dated", BIO).model_copy(update={"published_at": "2025-03-10"})

    asyncio.run(service._brief(SUMMER, "久石让", [source]))
    asyncio.run(service._stories("久石让", ["久石让"], [source]))

    assert len(llm.prompts) == 2
    for prompt in llm.prompts:
        assert "[evidence-dated] (published 2025-03-10): " + BIO in prompt
        assert "Programme date:" in prompt


def test_a_japanese_source_line_backs_a_chinese_credit_when_the_page_is_about_the_work() -> None:
    line = "覚 和歌子が作詞、木村 弓が作曲および歌唱を担当し、編曲も木村 弓による。"
    sources = {"evidence-j": f"いつも何度でも - Wikipedia\n{line}"}
    leads = {"evidence-j": sources["evidence-j"]}

    kept = verified_points([_point("觉和歌子作词，木村弓作曲并演唱", "evidence-j", line)], sources, KIMURA, leads)
    two_roles_one_stated = verified_points(
        [_point("觉和歌子作曲，木村弓作词", "evidence-j", "木村 弓が作曲および歌唱を担当し")], sources, KIMURA, leads
    )

    assert [point.evidence_id for point in kept] == ["evidence-j"]
    assert two_roles_one_stated == []  # the quote states composing, not writing the words
    # a role the line does not state is not backed
    assert verified_points([_point("木村弓导演了它", "evidence-j", line)], sources, KIMURA, leads) == []


def test_a_row_about_another_track_of_the_page_is_not_borrowed() -> None:
    page = "となりのトトロ サウンドトラック\n風のとおり道 作曲：久石譲\nいつも何度でも 作曲：木村弓"
    sources = {"evidence-t": page}
    leads = {"evidence-t": "となりのトトロ サウンドトラック"}  # the page is about the album, not this song

    borrowed = verified_points([_point("它是木村弓作曲的", "evidence-t", "風のとおり道 作曲：久石譲")], sources, KIMURA, leads)
    own_row = verified_points([_point("它是木村弓作曲的", "evidence-t", "いつも何度でも 作曲：木村弓")], sources, KIMURA, leads)

    assert borrowed == []
    assert [point.evidence_id for point in own_row] == ["evidence-t"]


def test_a_film_may_be_named_as_any_source_names_it_but_an_invented_title_is_dropped() -> None:
    sources = {"evidence-a": "いつも何度でも は 千と千尋の神隠し の主題歌。", "evidence-b": "《千与千寻》是宫崎骏的作品。"}

    named_elsewhere = verified_points(
        [_point("它是《千与千寻》的主题歌", "evidence-a", "千と千尋の神隠し の主題歌")], sources, KIMURA, sources
    )
    invented = verified_points(
        [_point("它是《龙猫》的主题歌", "evidence-a", "千と千尋の神隠し の主題歌")], sources, KIMURA, sources
    )

    assert len(named_elsewhere) == 1 and invented == []


def test_a_second_track_on_the_same_album_shares_the_search_but_not_the_song_facts() -> None:
    searcher = Searcher(("千与千寻原声", KIMURA_PAGE))
    briefer = DynamicBriefer("它是《千与千寻》的片尾曲", "是动画电影《千与千寻》的片尾曲")
    service = _service(searcher, briefer)  # type: ignore[arg-type]

    first = _prepare(service, KIMURA, [])
    album_query = searcher.queries[0]
    second = _prepare(service, SECOND_ON_ALBUM, [])

    assert first is not None and first.points  # the page opens with Kimura's song: it speaks for it
    assert searcher.queries.count(album_query) == 1  # the album question was asked once
    assert second is not None and second.evidence_ids  # the page is still available to the second
    # and no claim about the first song's role in the film is lent to the second track
    assert all("片尾曲" not in point.text for point in second.points)


def test_album_background_is_shared_and_labelled_but_song_facts_are_not() -> None:
    page = "《千と千尋の神隠し サウンドトラック》于2001年发行，是宫崎骏动画的原声带。いつも何度でも 作曲：木村弓"
    sources = {"evidence-a": page}
    leads = {"evidence-a": "千と千尋の神隠し サウンドトラック"}

    album = verified_points(
        [_RawPoint(text="这张原声带于2001年发行", source="evidence-a", quote="于2001年发行，是宫崎骏动画的原声带", scope="album")],
        sources, SECOND_ON_ALBUM, leads,
    )
    credit_as_background = verified_points(
        [_RawPoint(text="木村弓作曲了其中一首", source="evidence-a", quote="いつも何度でも 作曲：木村弓", scope="album")],
        sources, SECOND_ON_ALBUM, leads,
    )
    song = verified_points(
        [_RawPoint(text="它是木村弓作曲的", source="evidence-a", quote="いつも何度でも 作曲：木村弓", scope="track")],
        sources, SECOND_ON_ALBUM, leads,
    )
    unrelated_album = verified_points(
        [_RawPoint(text="这张原声带于2001年发行", source="evidence-a", quote="于2001年发行，是宫崎骏动画的原声带", scope="album")],
        sources, SUMMER, {"evidence-a": "无关页面"},
    )

    assert [point.scope for point in album] == ["album"]
    assert credit_as_background == []  # who composed what is about one song, not the album
    assert song == []  # that row is another song's
    assert unrelated_album == []  # the page is not about this track's album


def test_the_search_budget_is_per_station_and_stops_when_nothing_turns_up() -> None:
    portrait = Searcher(("无关", HOMONYM_PAGE))
    _prepare(_service(portrait, Briefer(_Briefing(points=[]))), KIMURA, [], station=StationId.PORTRAIT)
    crate = Searcher(("无关", HOMONYM_PAGE))
    _prepare(_service(crate, Briefer(_Briefing(points=[]))), KIMURA, [], station=StationId.CRATE)

    assert len(portrait.queries) == 2 and len(crate.queries) == 1


def test_stations_that_talk_little_do_no_track_research() -> None:
    searcher, briefer = Searcher(("x", KIMURA_PAGE)), Briefer(_Briefing(points=[]))

    assert _prepare(_service(searcher, briefer), KIMURA, [], station=StationId.CASUAL) is None
    assert _prepare(_service(searcher, briefer), KIMURA, [], station=None) is None
    assert searcher.queries == [] and briefer.prompts == []


def test_a_failed_search_or_briefing_leaves_the_chapter_with_less_to_say_not_broken() -> None:
    down = _prepare(_service(Searcher(RuntimeError("x")), Briefer(_Briefing(points=[]))), KIMURA, [])
    assert down is not None and down.points == []

    no_model = _prepare(
        _service(Searcher(), Briefer(RuntimeError("down"))), SUMMER, [_evidence("s", SUMMER_PAGE)]
    )
    assert no_model is not None and no_model.points == [] and no_model.evidence_ids == ["evidence-s"]


# --- the Writer --------------------------------------------------------------------------------


def _write(llm: Sequenced, points):  # type: ignore[no-untyped-def]
    return asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
            track_points=points,
        )
    )


def test_the_writer_builds_on_the_verified_points() -> None:
    llm = Sequenced(_script("听听这段旋律。"))

    _write(llm, [TalkingPoint(text="《Summer》是《菊次郎的夏天》的主题曲", evidence_id="e", quote="x" * 4)])

    assert "Verified points about this chapter's track" in llm.prompts[0]
    assert "《Summer》是《菊次郎的夏天》的主题曲" in llm.prompts[0]


def test_with_no_verified_point_a_middle_chapter_says_nothing_and_costs_no_call() -> None:
    llm = Sequenced(_script("接着听。"))

    result = _write(llm, [])

    assert llm.prompts == [] and result.blocks == []


def test_with_no_verified_point_the_closing_is_still_written() -> None:
    from tests.test_voice import _final_slot

    llm = Sequenced(_script("这一程到这里。"))
    result = asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_final_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.PORTRAIT,
            voice_seed="programme-1",
            track_points=[],
        )
    )

    assert len(llm.prompts) == 1
    assert "a closing introduces no new fact" in llm.prompts[0]
    assert result.blocks


def test_a_closing_only_recaps_what_was_played_even_when_verified_points_exist() -> None:
    from tests.test_voice import _final_slot

    llm = Sequenced(_script("这张专辑附了一篇短篇故事。这一路到这里。"))
    album = TalkingPoint(text="这张专辑是概念专辑，随CD附有一篇短篇故事", evidence_id="e", quote="x" * 4, scope="album")
    asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            slot_context=_final_slot(),
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CRATE,
            voice_seed="programme-1",
            track_points=[album],
        )
    )

    prompt = llm.prompts[0]
    assert "First tell ONE of the verified points" not in prompt
    assert "a closing introduces no new fact" in prompt


def test_without_track_research_the_prompt_is_unchanged() -> None:
    llm = Sequenced(_script("听听这段旋律。"))

    _write(llm, None)

    assert "Verified points" not in llm.prompts[0] and "state no facts about the song" not in llm.prompts[0]


# --- persisting what was found -----------------------------------------------------------------


def test_research_found_for_a_chapter_is_merged_into_the_session() -> None:
    from wavecast.orchestration.generation import GeneratedChapter
    from wavecast.orchestration.narration_enrichment import _with_chapter_research

    chapter = ChapterPlan(index=1, narrative_role=NarrativeRole.ANCHOR, reason="r", narration_goal="g", evidence_ids=["evidence-old"])
    session = ProgressiveSessionStub.build(chapter)
    found = _evidence("new", KIMURA_PAGE)
    generated = GeneratedChapter.model_construct(
        chapter_id="chapter-2", segments=[], research_evidence=[found], research_evidence_ids=["evidence-new", "evidence-old"]
    )

    update = _with_chapter_research(session, "chapter-2", generated)  # type: ignore[arg-type]

    assert [item.id for item in update["research"].evidence] == ["evidence-old", "evidence-new"]  # type: ignore[attr-defined]
    assert update["chapters"][0].chapter.evidence_ids == ["evidence-old", "evidence-new"]  # type: ignore[index, attr-defined]


class ProgressiveSessionStub:
    @staticmethod
    def build(chapter: ChapterPlan):  # type: ignore[no-untyped-def]
        from wavecast.models.progressive import ProgressiveAssemblySession

        old = _evidence("old", SUMMER_PAGE)
        return ProgressiveAssemblySession.model_construct(
            research=ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[old], candidates=[]),
            chapters=[ProgressiveAssemblyChapter.model_construct(chapter_id="chapter-2", chapter=chapter)],
            narration_authored_chapter_ids=[],
        )


def test_catalogue_data_and_traditional_characters_are_handled() -> None:
    sources = {"evidence-k": "《いつも何度でも》是千與千尋的片尾曲，曲目編號12，時長1分48秒。"}
    trivia = verified_points(
        [_point("它的曲目编号12，时长1分48秒", "evidence-k", "曲目編號12，時長1分48秒")], sources, KIMURA, sources
    )
    story = verified_points(
        [_point("它是千與千尋的片尾曲", "evidence-k", "是千與千尋的片尾曲")], sources, KIMURA, sources
    )

    assert trivia == []
    assert [point.text for point in story] == ["它是千与千寻的片尾曲"]  # said in Simplified Chinese


# --- programme background -----------------------------------------------------------------------

from wavecast.intelligence.track_research import _Stories, verified_stories  # noqa: E402

BIO = (
    "1983年，宫崎骏正在制作《风之谷》，经人介绍在一间破烂酒吧改造的工作室里见到了久石让。"
    "宫崎骏说，他的作品都患了久石让依赖症。两人合作了40年，完成11部电影。"
)
BIO_SOURCES = {"evidence-b": BIO}


def _story(text: str, quote: str, source: str = "evidence-b") -> _RawPoint:
    return _RawPoint(text=text, source=source, quote=quote)


def test_a_background_story_needs_its_quote_a_subject_and_a_standalone_telling() -> None:
    kept = verified_stories(
        [_story("1983年宫崎骏在一间酒吧改的工作室见到了久石让", "在一间破烂酒吧改造的工作室里见到了久石让")],
        BIO_SOURCES, ["久石让"],
    )
    assert [point.scope for point in kept] == ["background"]

    rejected = {
        "pointing at a song": _story("这首歌是他们合作的开始", "在一间破烂酒吧改造的工作室里见到了久石让"),
        "invented quote": _story("久石让在1983年写了第一首曲子", "久石让写下了第一首曲子"),
        "year not in the source": _story("1985年宫崎骏见到了久石让", "在一间破烂酒吧改造的工作室里见到了久石让"),
        "another subject": _story("宫崎骏说他的作品都患了依赖症", "他的作品都患了久石让依赖症"),
    }
    for name, raw in rejected.items():
        names = ["坂本龙一"] if name == "another subject" else ["久石让"]
        assert verified_stories([raw], BIO_SOURCES, names) == [], name


def test_the_same_story_is_not_told_twice_in_other_words() -> None:
    stories = verified_stories(
        [
            _story("1983年宫崎骏在酒吧改的工作室见到久石让", "在一间破烂酒吧改造的工作室里见到了久石让"),
            _story("宫崎骏1983年在酒吧改的工作室里见到了久石让", "在一间破烂酒吧改造的工作室里见到了久石让"),
            _story("久石让和宫崎骏合作了40年", "两人合作了40年，完成11部电影"),
        ],
        BIO_SOURCES, ["久石让"],
    )

    assert len(stories) == 2


class StoryBriefer:
    """No song facts; three background stories, one call for the whole programme."""

    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, prompt: str, output_type: type[object], **_kwargs: object) -> object:
        self.calls += 1
        if output_type is _Stories:
            return _Stories(
                stories=[
                    _story("1983年宫崎骏在酒吧改的工作室见到了久石让", "在一间破烂酒吧改造的工作室里见到了久石让"),
                    _story("宫崎骏说他的作品都患了久石让依赖症", "他的作品都患了久石让依赖症"),
                ]
            )
        return _Briefing(points=[])


def test_a_chapter_with_nothing_about_its_song_tells_the_next_unused_story() -> None:
    briefer = StoryBriefer()
    service = TrackResearchService(search=Searcher(), llm=briefer)  # type: ignore[arg-type]
    programme = [_evidence("b", BIO)]

    def prepare(track: ResolvedTrack, station=StationId.PORTRAIT):  # type: ignore[no-untyped-def]
        return asyncio.run(
            service.prepare(
                episode_id="ep", track=track, evidence=programme, station=station,
                subject="久石让", subject_names=["久石让"],
            )
        )

    first, second, third = prepare(SUMMER), prepare(SECOND_ON_ALBUM), prepare(KIMURA)

    assert first is not None and [point.scope for point in first.points] == ["background"]
    assert "evidence-b" in first.evidence_ids  # the writer and the fact check can see the source
    assert second is not None and second.points and second.points[0].text != first.points[0].text
    assert third is not None and third.points == []  # both stories are used; nothing is repeated
    assert sum("background_brief" in p for p in []) == 0 and briefer.calls >= 1
    # other stations do not tell programme background
    crate = prepare(SUMMER, station=StationId.CRATE)
    assert crate is not None and all(point.scope != "background" for point in crate.points)


def test_the_writer_is_told_a_background_story_is_not_about_the_song() -> None:
    llm = Sequenced(_script("1983年，宫崎骏见到了久石让。"))

    _write(llm, [TalkingPoint(text="1983年宫崎骏见到了久石让", evidence_id="e", quote="x" * 4, scope="background")])

    assert "programme background about the person or the period" in llm.prompts[0]
    assert "never call it 这首歌" in llm.prompts[0]


def test_a_point_crediting_someone_the_quote_does_not_name_is_dropped() -> None:
    sources = {"evidence-k": "《いつも何度でも》 作曲：木村弓"}
    point = _point("它的作曲是久石让", "evidence-k", "《いつも何度でも》 作曲：木村弓")
    right = _point("它的作曲是木村弓", "evidence-k", "《いつも何度でも》 作曲：木村弓")

    assert verified_points([point], sources, KIMURA, sources, ["久石让"]) == []
    assert len(verified_points([right], sources, KIMURA, sources, ["久石让"])) == 1


def test_a_portrait_tells_a_background_story_on_every_other_chapter_even_with_song_facts() -> None:
    class Both:
        async def structured(self, prompt: str, output_type: type[object], **_kwargs: object) -> object:
            if output_type is _Stories:
                return _Stories(
                    stories=[
                        _story("1983年宫崎骏在酒吧改的工作室见到了久石让", "在一间破烂酒吧改造的工作室里见到了久石让"),
                        _story("宫崎骏说他的作品都患了久石让依赖症", "他的作品都患了久石让依赖症"),
                    ]
                )
            import re

            source = re.search(r"\[(evidence-[0-9a-f]+)\]", prompt)
            return _Briefing(
                points=[_RawPoint(text="它是《千与千寻》的片尾曲", source=source.group(1), quote="是动画电影《千与千寻》的片尾曲")]
                if source
                else []
            )

    service = TrackResearchService(search=Searcher(("千与千寻原声", KIMURA_PAGE)), llm=Both())  # type: ignore[arg-type]
    programme = [_evidence("b", BIO)]

    scopes = []
    for track in (KIMURA, KIMURA.model_copy(update={"track_ref": "n:9"}), KIMURA.model_copy(update={"track_ref": "n:10"})):
        result = asyncio.run(
            service.prepare(
                episode_id="alt", track=track, evidence=programme, station=StationId.PORTRAIT,
                subject="久石让", subject_names=["久石让"],
            )
        )
        assert result is not None
        scopes.append([point.scope for point in result.points])

    assert scopes[0] == ["track"] and scopes[1] == ["background"] and scopes[2] == ["track"]


def test_briefing_extracts_a_source_bound_title_without_an_extra_call():
    from wavecast.intelligence.track_research import _TitleAlias

    track = ResolvedTrack(
        track_ref="n:rin", canonical_artist="椎名林檎", canonical_title="丸ノ内サディスティック"
    )
    quote = "椎名林檎的《丸ノ内サディスティック》，中文通常译作《丸之内虐待狂》。"
    source = _evidence("alias-source", quote)
    briefer = Briefer(
        _Briefing(spoken_title=_TitleAlias(text="丸之内虐待狂", source=source.id, quote=quote))
    )
    service = _service(Searcher(), briefer)
    outcome = asyncio.run(service._brief(track, "椎名林檎", [source]))
    assert outcome.spoken_title == "丸之内虐待狂"
    assert outcome.spoken_title_evidence_id == source.id
    assert len(briefer.prompts) == 1
    assert outcome.points == []  # a title is not forced into a spoken fact


@pytest.mark.parametrize(
    "title,source_id,quote",
    [
        ("丸之内虐待狂", "missing-source", "《丸ノ内サディスティック》中文名为《丸之内虐待狂》。"),
        (
            "丸之内虐待狂",
            "evidence-alias-source",
            "这是一句没有出现在来源中的丸ノ内サディスティック丸之内虐待狂",
        ),
        (
            "另一首歌",
            "evidence-alias-source",
            "《丸ノ内サディスティック》中文名为《丸之内虐待狂》。",
        ),
        ("丸之内虐待狂", "evidence-alias-source", "《丸之内虐待狂》是一首歌曲。"),
    ],
)
def test_unbound_or_invented_spoken_title_is_not_accepted(title, source_id, quote):
    from wavecast.intelligence.track_research import _TitleAlias

    track = ResolvedTrack(
        track_ref="n:rin", canonical_artist="椎名林檎", canonical_title="丸ノ内サディスティック"
    )
    source = _evidence(
        "alias-source",
        "《丸ノ内サディスティック》中文名为《丸之内虐待狂》。另有《丸之内虐待狂》是一首歌曲。",
    )
    briefer = Briefer(
        _Briefing(spoken_title=_TitleAlias(text=title, source=source_id, quote=quote))
    )
    outcome = asyncio.run(_service(Searcher(), briefer)._brief(track, "椎名林檎", [source]))
    assert outcome.spoken_title is None


@pytest.mark.parametrize(
    "angle,goal",
    [
        ("久石让作品里的钢琴表达", "用这首歌建立钢琴与人声关系的切口"),
        ("久石让与动画叙事", "理解这首片尾曲在故事结束时的作用"),
    ],
)
def test_programme_angle_reaches_existing_track_brief_without_more_calls(angle, goal):
    source = _evidence("focus", KIMURA_PAGE)
    briefer = Briefer(
        _Briefing(
            points=[
                _RawPoint(
                    text="它是《千与千寻》的片尾曲",
                    source=source.id,
                    quote="是动画电影《千与千寻》的片尾曲",
                )
            ]
        )
    )
    searcher = Searcher()
    result = asyncio.run(
        _service(searcher, briefer).prepare(
            episode_id="focus",
            track=KIMURA,
            evidence=[source],
            station=StationId.PORTRAIT,
            subject="久石让",
            programme_brief=angle,
            editorial_goal=goal,
        )
    )
    assert len(briefer.prompts) == 1 and not searcher.queries
    assert angle in briefer.prompts[0] and goal in briefer.prompts[0]
    assert "not evidence" in briefer.prompts[0]
    assert result.points


def test_background_material_retains_programme_angle_and_existing_episode_cache():
    briefer = Briefer(_Stories(stories=[]))
    service = _service(Searcher(), briefer)

    async def twice():
        for _ in range(2):
            await service.background_story(
                episode_id="focus",
                station=StationId.PORTRAIT,
                subject="久石让",
                subject_names=["久石让"],
                evidence=[_evidence("bio", BIO)],
                programme_brief="久石让与动画叙事",
            )

    asyncio.run(twice())
    assert len(briefer.prompts) == 1
    assert "久石让与动画叙事" in briefer.prompts[0] and "not evidence" in briefer.prompts[0]

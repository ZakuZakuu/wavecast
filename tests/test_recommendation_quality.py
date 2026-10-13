"""Home ideas choose a station and a subject, and a batch that is worded from one template is asked for again."""

from pydantic import BaseModel
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.recommendations import (
    BATCH_SIZE,
    SHELF_SIZE,
    DeterministicRecommendationPlanner,
    InMemoryProgramIdeaRepository,
    ProgramIdea,
    ProgramIdeaDraft,
    ProgramIdeaDraftBatch,
    ProgramIdeaResponse,
    ProviderBackedRecommendationPlanner,
    RecommendationService,
    UserContext,
    UserContextAggregator,
    batch_penalty,
    batch_problems,
)
from wavecast.stations import StationId
from wavecast.title_style import (
    ends_with_stock_word,
    invented_situation_words,
    shared_frames,
    title_names_subject,
    uses_formulaic_shape,
)
from wavecast.user_context import InMemoryUserEventRepository, InMemoryUserPreferencesRepository

from tests.test_recommendations import InMemoryProgramProposalRepository


def _draft(
    title: str,
    station: StationId | None = StationId.CRATE,
    subject: str | None = "主题",
    cover_title: str | None = None,
) -> ProgramIdeaDraft:
    return ProgramIdeaDraft(
        station=station,
        subject=subject,
        title=title,
        cover_title=cover_title,
        description="d",
        reason="r",
    )


def _good_batch() -> list[ProgramIdeaDraft]:
    return [
        _draft("方大同的节奏与灵魂", StationId.PORTRAIT, "方大同"),
        _draft("Bossa Nova 如何变奏", StationId.LINEAGE, "Bossa Nova"),
        _draft("像 Glasper 那样融合", StationId.CRATE, "Glasper"),
        _draft("慢拍电子与爵士", StationId.CASUAL, "Chill 电子"),
        _draft("Norah Jones 的嗓音变化", StationId.PORTRAIT, "Norah Jones"),
        _draft("新灵魂乐的几种声音", StationId.LINEAGE, "新灵魂乐"),
    ]


CONTEXT = UserContext(user_id="u", genres=["Jazz"], moods=["Chill"], discovery_level=0.5)


def test_title_helpers_recognise_the_shapes_the_shelf_must_not_share() -> None:
    assert uses_formulaic_shape("暖风从 Bossa Nova 吹到 R&B")
    assert uses_formulaic_shape("贝斯先走，车再跟上")
    assert not uses_formulaic_shape("鼓和贝斯往后坐半拍")
    assert not uses_formulaic_shape("方大同的节奏与灵魂")

    assert shared_frames(["喜欢方大同还能听谁", "喜欢 Chill 还能听谁", "喜欢久石让还能听谁"]) == ["喜欢", "能听谁"]
    assert shared_frames(["方大同的节奏", "Bossa Nova 如何变奏", "Norah Jones 的嗓音"]) == []

    assert ends_with_stock_word("Mogwai 之路") and ends_with_stock_word("后摇入门")
    assert not ends_with_stock_word("后摇不只有一种声音")

    assert title_names_subject("Bossa Nova 的根源", "Bossa Nova 是怎么来的")
    assert title_names_subject("喜欢久石让还能听格拉斯", "菲利普·格拉斯")
    assert not title_names_subject("喜欢方大同还能听谁", "Clazziquai")
    assert not title_names_subject("任何标题", None)

    assert invented_situation_words("都市傍晚的城市流行", "Chill Jazz") == ["傍晚"]
    assert invented_situation_words("都市傍晚的城市流行", "傍晚散步") == []


def test_a_good_batch_has_no_problems() -> None:
    assert batch_problems(_good_batch(), CONTEXT) == []
    assert batch_penalty(_good_batch(), CONTEXT) == 0


def test_each_kind_of_flaw_is_named_for_the_retry() -> None:
    def problems(ideas: list[ProgramIdeaDraft]) -> str:
        return " ".join(batch_problems(ideas, CONTEXT))

    colon = _good_batch()
    colon[0] = _draft("方大同：节奏与灵魂", StationId.PORTRAIT, "方大同")
    assert "forbidden 'A：B' form" in problems(colon)

    templated = [
        _draft(title, StationId.CASUAL, "x")
        for title in ["慢下来，等爵士", "贝斯先走，车再跟上", "钢琴停下，人声才开口", "鼓刷之后，节奏还没停"]
    ]
    assert "transition sentence" in problems(templated + _good_batch()[:2])

    alike = [_draft(f"喜欢{name}还能听谁", StationId.CRATE, name) for name in ["方大同", "Glasper", "久石让"]]
    assert "open or end alike" in problems(alike + _good_batch()[:3])

    missing = _good_batch()
    missing[0] = _draft("方大同的节奏与灵魂", None, None)
    assert "needs a station and a concrete subject" in problems(missing)

    one_station = [_draft(f"第{i}种说法的爵士", StationId.CASUAL, "爵士") for i in range(6)]
    assert "station(s) are used" in problems(one_station)

    wrong = _good_batch()
    wrong[2] = _draft("喜欢方大同还能听谁", StationId.CRATE, "Clazziquai", cover_title="Clazziquai")
    assert "must name their own subject" in problems(wrong)

    stock = _good_batch()
    stock[3] = _draft("爵士入门", StationId.CASUAL, "爵士")
    assert "catalogue word" in problems(stock)

    scene = _good_batch()
    scene[3] = _draft("都市傍晚的爵士", StationId.CASUAL, "爵士")
    assert "invent a situation" in problems(scene)


def test_a_title_may_use_an_alias_if_the_cover_label_names_it_and_a_night_context_allows_night_words() -> None:
    ideas = _good_batch()
    ideas[2] = _draft("电台司令的转型轨迹", StationId.CRATE, "Radiohead", cover_title="电台司令")
    assert not any("name their own subject" in text for text in batch_problems(ideas, CONTEXT))

    ideas[3] = _draft("睡前听的钢琴", StationId.NIGHT, "钢琴")
    night_context = UserContext(user_id="u", contexts=["睡前"], discovery_level=0.5)
    assert not any("invent" in text for text in batch_problems(ideas, night_context))


class _Sequenced:
    def __init__(self, *batches: list[ProgramIdeaDraft]) -> None:
        self.batches = [ProgramIdeaDraftBatch(ideas=batch) for batch in batches]
        self.prompts: list[str] = []

    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport,
        profile: InferenceProfile,
        stage: str | None = None,
    ) -> BaseModel:
        self.prompts.append(prompt)
        return self.batches[min(len(self.prompts) - 1, len(self.batches) - 1)]

    async def aclose(self) -> None:
        return None


def _plan(llm: _Sequenced, context: UserContext = CONTEXT) -> list[ProgramIdeaDraft]:
    return ProviderBackedRecommendationPlanner(lambda: llm).generate_program_ideas(context)  # type: ignore[arg-type, return-value]


def test_a_clean_batch_costs_one_call_and_a_single_stray_flaw_does_not_cost_a_second() -> None:
    llm = _Sequenced(_good_batch())
    assert len(_plan(llm)) == 6 and len(llm.prompts) == 1

    stray = _good_batch()
    stray[3] = _draft("都市傍晚的爵士", StationId.CASUAL, "爵士")  # one invented scene: penalty 1
    llm = _Sequenced(stray)
    _plan(llm)
    assert len(llm.prompts) == 1


def test_a_templated_batch_is_asked_for_again_with_the_problems_named_and_the_better_one_is_kept() -> None:
    templated = [
        _draft(title, StationId.CASUAL, "x")
        for title in ["慢下来，等爵士", "贝斯先走，车再跟上", "钢琴停下，人声才开口", "鼓刷之后，节奏还没停", "夜色里，旋律慢慢走"]
    ] + [_draft("爵士里的松弛感", StationId.CASUAL, "爵士")]
    llm = _Sequenced(templated, _good_batch())

    ideas = _plan(llm)

    assert len(llm.prompts) == 2
    assert "previous attempt had these problems" in llm.prompts[1] and "贝斯先走，车再跟上" in llm.prompts[1]
    assert [idea.title for idea in ideas] == [idea.title for idea in _good_batch()]

    worse = _Sequenced(templated, [*templated, _draft("再来一个，同样的模板", StationId.CASUAL, "x")][:6])
    assert [idea.title for idea in _plan(worse)] == [idea.title for idea in templated]


def test_the_night_station_is_kept_for_listeners_who_ask_for_that_state() -> None:
    batch = _good_batch()
    batch[3] = _draft("没有歌词的钢琴小品", StationId.NIGHT, "钢琴")

    plain = _plan(_Sequenced(batch))
    assert plain[3].station is StationId.CASUAL

    sleepy = _plan(_Sequenced(batch), UserContext(user_id="u", contexts=["睡前"], discovery_level=0.5))
    assert sleepy[3].station is StationId.NIGHT


def test_a_colon_title_that_survives_the_retry_loses_its_colon() -> None:
    batch = _good_batch()
    batch[0] = _draft("方大同：节奏与灵魂", StationId.PORTRAIT, "方大同")
    ideas = _plan(_Sequenced(batch, batch))
    assert ideas[0].title == "方大同 节奏与灵魂"


def test_the_prompt_lists_the_stations_and_what_was_offered_but_carries_no_example_titles() -> None:
    llm = _Sequenced(_good_batch())
    context = UserContext(
        user_id="u",
        genres=["Jazz"],
        avoid_titles=["旧标题一"],
        avoid_subjects=["Bossa Nova"],
        discovery_level=0.5,
    )
    _plan(llm, context)
    prompt = llm.prompts[0]

    for station in StationId:
        assert f"- {station.value}:" in prompt
    assert f"Create {BATCH_SIZE} distinct" in prompt and f"shows {SHELF_SIZE} at a time" in prompt
    assert '"avoid_subjects": ["Bossa Nova"]' in prompt
    # old titles would be read as examples of how to write one
    assert "旧标题一" not in prompt
    # the model copies any title it is shown, so the guidance must not contain one
    for copied in ["后摇不只有一种声音", "星野源的早期与后来", "Autumn Leaves 的几种唱法", "喜欢 Clazziquai 还能听谁"]:
        assert copied not in prompt


def test_the_station_and_subject_reach_the_stored_idea_the_response_and_the_proposal_request() -> None:
    class Planner:
        source = "stub"

        def generate_program_ideas(self, context: UserContext) -> list[ProgramIdeaDraft]:
            self.seen = context
            return [
                _draft("方大同的节奏与灵魂", StationId.PORTRAIT, "方大同"),
                _draft("慢拍电子与爵士", None, None),
            ]

    planner = Planner()
    repository = InMemoryProgramIdeaRepository()
    service = RecommendationService(
        UserContextAggregator(
            InMemoryUserPreferencesRepository(),
            InMemoryUserEventRepository(),
            InMemoryProgramProposalRepository(),
        ),
        planner,
        repository,
    )

    ideas = {idea.title: idea for idea in service.inventory_for_user("u")}

    portrait = ideas["方大同的节奏与灵魂"]
    assert portrait.station is StationId.PORTRAIT and portrait.subject == "方大同"
    assert portrait.to_proposal_seed().request.station is StationId.PORTRAIT
    response = ProgramIdeaResponse.from_idea(portrait).model_dump(mode="json")
    assert response["station"] == "portrait" and "subject" not in response
    # an idea without a station leaves the request's station unset
    assert ideas["慢拍电子与爵士"].to_proposal_seed().request.station is None

    # what was offered comes back as subjects (the subject, or the title for older ideas)
    service.next_shelf("u", [idea.id for idea in ideas.values()])  # a second batch is made
    assert set(planner.seen.avoid_subjects) >= {"方大同", "慢拍电子与爵士"}


def test_ideas_stored_before_stations_existed_and_unknown_fields_still_load() -> None:
    old = {
        "id": "i1",
        "user_id": "u",
        "title": "t",
        "description": "d",
        "reason": "r",
    }
    assert ProgramIdea.model_validate(old).station is None
    newer = {**old, "station": "lineage", "subject": "Bossa Nova", "someday": 1}
    loaded = ProgramIdea.model_validate(newer)
    assert loaded.station is StationId.LINEAGE and loaded.subject == "Bossa Nova"


def test_a_long_subject_is_clipped_instead_of_failing_the_batch() -> None:
    draft = _draft("方大同的节奏", StationId.PORTRAIT, "很长" * 80)
    assert draft.subject is not None and len(draft.subject) == 60


def test_the_heuristic_planner_also_chooses_a_station_and_a_subject() -> None:
    context = UserContext(
        user_id="u",
        genres=["Soul"],
        moods=["Late Night"],
        recent_interests=["很长的最近兴趣" * 20],
        favorite_interests=["夜航"],
        discovery_level=0.5,
    )
    ideas = DeterministicRecommendationPlanner().generate_program_ideas(context)
    assert ideas and all(idea.station is not None and idea.subject for idea in ideas)
    assert all(len(idea.subject or "") <= 60 for idea in ideas)

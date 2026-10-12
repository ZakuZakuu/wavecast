"""Programme titles and the short cover label (title_style, proposals, recommendations)."""

import asyncio

import pytest
from pydantic import BaseModel
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.recommendations import (
    DeterministicRecommendationPlanner,
    ProgramIdea,
    ProgramIdeaDraft,
    ProgramIdeaDraftBatch,
    ProviderBackedRecommendationPlanner,
    UserContext,
)
from wavecast.title_style import (
    MAX_COVER_WIDTH,
    TITLE_GUIDANCE,
    count_colon_titles,
    cover_title,
    uses_colon_subtitle,
    visual_width,
)


def test_a_colon_subtitle_title_is_recognised_and_others_are_not() -> None:
    assert uses_colon_subtitle("星野源：创作脉络小径")
    assert uses_colon_subtitle("Jazz: from origins to now")
    assert not uses_colon_subtitle("睡前半小时，不要歌词")
    assert not uses_colon_subtitle("Bossa Nova 是怎么学会慵懒的")
    assert count_colon_titles(["星野源：创作脉络小径", "睡前半小时", "A：B 之旅"]) == 2


@pytest.mark.parametrize(
    ("candidate", "title"),
    [
        ("Bossa Nova", "Bossa Nova 是怎么学会慵懒的"),
        ("《睡前半小时》", "睡前半小时，不要歌词"),
        (None, "星野源：创作脉络小径"),
        ("", "喜欢 Lo-fi 的话，还能听什么"),
        ("这是一个远远超过封面宽度的非常长的标签", "短标题"),
        (None, "这是一个非常非常长而且没有任何标点的节目标题"),
        (None, "Autumn Leavesxxxxxxxxxxxxxxxx 很长"),
    ],
)
def test_the_cover_label_always_fits_and_is_never_blank(candidate: str | None, title: str) -> None:
    label = cover_title(candidate, title)
    assert label.strip()
    assert visual_width(label) <= MAX_COVER_WIDTH


def test_the_models_label_is_kept_when_it_fits_and_the_title_head_is_the_fallback() -> None:
    assert cover_title("下班路上", "写给下班路上的轻音乐") == "下班路上"
    assert cover_title(None, "星野源：创作脉络小径") == "星野源"
    # not cut inside a Latin word
    assert cover_title(None, "Autumn Leavesxxxxxxxxxxxxxxxx 很长") == "Autumn"


class _Sequenced:
    def __init__(self, *batches: ProgramIdeaDraftBatch) -> None:
        self.batches = list(batches)
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


def _batch(*titles: str) -> ProgramIdeaDraftBatch:
    return ProgramIdeaDraftBatch(
        ideas=[
            ProgramIdeaDraft(title=title, description=f"说明{i}", reason=f"理由{i}", tags=["Jazz"])
            for i, title in enumerate(titles)
        ]
    )


CONTEXT = UserContext(user_id="u", genres=["Jazz"], moods=["Chill"], discovery_level=0.5)


def test_ideas_with_colon_titles_are_asked_for_again_once_and_the_better_batch_is_used() -> None:
    llm = _Sequenced(
        _batch("星野源：创作脉络小径", "爵士入门：从起源到现代", "睡前半小时"),
        _batch("星野源写歌的三个房间", "爵士是怎么变得好听的", "睡前半小时"),
    )

    ideas = ProviderBackedRecommendationPlanner(lambda: llm).generate_program_ideas(CONTEXT)  # type: ignore[arg-type, return-value]

    assert len(llm.prompts) == 2
    assert "forbidden 'A：B' title pattern" in llm.prompts[1] and "星野源：创作脉络小径" in llm.prompts[1]
    assert [idea.title for idea in ideas] == ["星野源写歌的三个房间", "爵士是怎么变得好听的", "睡前半小时"]


def test_a_batch_without_colon_titles_costs_one_call_and_the_title_guidance_is_in_the_prompt() -> None:
    llm = _Sequenced(_batch("睡前半小时，不要歌词", "写给下班路上的轻音乐", "一首 Autumn Leaves，五种秋天"))

    ProviderBackedRecommendationPlanner(lambda: llm).generate_program_ideas(CONTEXT)  # type: ignore[arg-type]

    assert len(llm.prompts) == 1
    assert TITLE_GUIDANCE in llm.prompts[0]


def test_a_retry_that_is_no_better_keeps_the_first_batch() -> None:
    first = _batch("星野源：创作脉络小径", "爵士是怎么变得好听的", "睡前半小时")
    worse = _batch("星野源：创作脉络小径", "爵士入门：从起源到现代", "睡前半小时")
    llm = _Sequenced(first, worse)

    ideas = ProviderBackedRecommendationPlanner(lambda: llm).generate_program_ideas(CONTEXT)  # type: ignore[arg-type]

    assert [idea.title for idea in ideas] == [idea.title for idea in first.ideas]


def test_the_heuristic_planner_no_longer_writes_colon_titles() -> None:
    context = UserContext(
        user_id="u",
        genres=["Soul"],
        moods=["Late Night"],
        preferred_artists=["方大同"],
        favorite_interests=["夜航"],
        discovery_level=0.5,
    )
    ideas = DeterministicRecommendationPlanner().generate_program_ideas(context)
    assert count_colon_titles([idea.title for idea in ideas]) == 0


def test_ideas_carry_a_fitting_cover_label_into_the_proposal() -> None:
    from wavecast.proposals import (
        DeterministicMockProgramProposalGenerator,
        ProposalGenerationRequest,
    )

    idea = ProgramIdea(
        id="i1", user_id="u", title="写给下班路上的轻音乐", cover_title="下班路上", description="d", reason="r"
    )
    request = ProposalGenerationRequest(prompt="下班路上听点轻松的", count=1)
    proposal = asyncio.run(DeterministicMockProgramProposalGenerator().generate(request))[0]

    applied = idea.apply_to_proposal(proposal)

    assert applied.title == "写给下班路上的轻音乐" and applied.cover_title == "下班路上"
    assert applied.to_episode_seed().cover_title == "下班路上"
    # an idea without a label leaves the proposal's own
    plain = ProgramIdea(id="i2", user_id="u", title="t", description="d", reason="r")
    assert plain.apply_to_proposal(proposal).cover_title == proposal.cover_title

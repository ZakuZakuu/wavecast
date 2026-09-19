from wavecast.evals import PHASE51_EDITORIAL_CASES, build_phase51_evaluation
from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    TrackProposal,
)


def _artifact(case_index: int, artists: list[str]):
    case = PHASE51_EDITORIAL_CASES[case_index]
    tracks = [
        TrackProposal(
            artist=artist,
            title=f"Track {index}",
            confidence=0.8,
            novelty_distance=(
                NoveltyDistance.VERY_CLOSE
                if index == 0
                else NoveltyDistance.BRIDGE
            ),
        )
        for index, artist in enumerate(artists)
    ]
    plan = FastStartPlan(
        anchor_understanding=["fixture"],
        immediate_taste_hypotheses=[],
        next_candidates=tracks,
        first_narration=NarrationScript(text="Start.", intended_duration_seconds=5),
    )
    skeleton = ProgramSkeleton(
        thesis="fixture arc",
        estimated_duration_seconds=300,
        chapters=[
            ChapterPlan(
                index=index,
                track=track,
                narrative_role=(
                    NarrativeRole.ANCHOR if index == 0 else NarrativeRole.BRIDGE
                ),
                reason="fixture route",
                novelty_distance=track.novelty_distance,
                narration_goal="explain route",
            )
            for index, track in enumerate(tracks)
        ],
    )
    return case, plan, skeleton


def test_phase51_suite_has_four_fixed_cases_and_b2_obligation() -> None:
    assert [case.case_id for case in PHASE51_EDITORIAL_CASES] == [
        "phase51-fang-datong-biography",
        "phase51-fang-to-musiq-discovery",
        "phase51-uk-garage",
        "phase51-chinese-rock-history",
    ]
    assert PHASE51_EDITORIAL_CASES[0].required_route_artists == []
    assert PHASE51_EDITORIAL_CASES[1].required_route_artists == ["Musiq Soulchild"]
    assert PHASE51_EDITORIAL_CASES[1].minimum_distinct_artists == 3


def test_biography_allows_same_artist_route() -> None:
    case, plan, skeleton = _artifact(0, ["Biography Artist"] * 3)
    evaluation = build_phase51_evaluation(case, plan, skeleton)
    assert evaluation.diagnostics.distinct_artist_count == 1
    check = next(
        item for item in evaluation.hard_checks
        if item.name == "benchmark_route_obligation"
    )
    assert check.status == "not_observed"


def test_b2_reports_missing_musiq_bridge() -> None:
    case, plan, skeleton = _artifact(1, ["Anchor Artist", "Third Artist", "Fourth Artist"])
    evaluation = build_phase51_evaluation(case, plan, skeleton)
    check = next(
        item for item in evaluation.hard_checks
        if item.name == "benchmark_route_obligation"
    )
    assert check.status == "fail"
    assert "Musiq Soulchild" in check.summary



def test_b2_requires_minimum_distinct_artists_in_addition_to_musiq() -> None:
    case, plan, skeleton = _artifact(1, ["Anchor Artist", "Musiq Soulchild"])
    evaluation = build_phase51_evaluation(case, plan, skeleton)
    check = next(
        item for item in evaluation.hard_checks
        if item.name == "benchmark_route_obligation"
    )
    assert check.status == "fail"
    assert "at least 3 distinct artists" in check.summary


def test_b2_passes_when_both_route_obligations_are_met() -> None:
    case, plan, skeleton = _artifact(
        1, ["Anchor Artist", "Musiq Soulchild", "Third Artist"]
    )
    evaluation = build_phase51_evaluation(case, plan, skeleton)
    check = next(
        item for item in evaluation.hard_checks
        if item.name == "benchmark_route_obligation"
    )
    assert check.status == "pass"

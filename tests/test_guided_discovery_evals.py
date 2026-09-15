from wavecast.evals import GUIDED_DISCOVERY_CASES, build_review_bundle
from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    TrackCandidate,
)


def test_guided_discovery_fixtures_cover_four_distinct_failure_modes() -> None:
    assert len(GUIDED_DISCOVERY_CASES) >= 4
    assert len({case.failure_mode for case in GUIDED_DISCOVERY_CASES}) == len(
        GUIDED_DISCOVERY_CASES
    )
    assert {case.case_id for case in GUIDED_DISCOVERY_CASES} >= {
        "third-coast-same-artist-trap",
        "persona-style-explanation",
        "artist-to-scene-bridge",
        "late-night-city-drive",
    }


def test_review_bundle_is_compact_and_requires_human_quality_review() -> None:
    case = GUIDED_DISCOVERY_CASES[0]
    candidate = TrackCandidate(
        artist="Adjacent Artist",
        title="Bridge Track",
        reasons=["shares syncopated bass and warm vocal layering"],
        similarity_dimensions=["groove", "vocal treatment"],
        evidence_ids=["e1"],
        confidence=0.8,
        novelty_distance=NoveltyDistance.BRIDGE,
    )
    plan = FastStartPlan(
        anchor_understanding=["warm syncopated groove"],
        immediate_taste_hypotheses=[],
        next_candidates=[candidate],
        first_narration=NarrationScript(text="Start here.", intended_duration_seconds=5),
    )
    skeleton = ProgramSkeleton(
        thesis="Move from groove to a new scene.",
        estimated_duration_seconds=600,
        chapters=[
            ChapterPlan(
                index=0,
                track=candidate,
                narrative_role=NarrativeRole.BRIDGE,
                reason="connects the anchor groove to a different scene",
                novelty_distance=NoveltyDistance.BRIDGE,
                evidence_ids=["e1"],
                narration_goal="explain the bridge",
            )
        ],
    )

    report = build_review_bundle(case, plan, skeleton)

    assert report.quality_status == "human_review_required"
    assert report.candidates[0].artist == "Adjacent Artist"
    assert report.candidates[0].similarity_dimensions == ["groove", "vocal treatment"]
    assert report.program_arc[0].narrative_role is NarrativeRole.BRIDGE
    assert report.program_arc[0].scene_cluster_rationale
    assert len(report.human_review_questions) >= 5
    assert "DiscoveryRadius" in {dimension.value for dimension in report.rubric.dimensions}

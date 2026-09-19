from __future__ import annotations

from types import SimpleNamespace

import pytest
from wavecast.evals.listening import REVIEW_QUESTIONS, build_listening_evaluation
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    RadioScriptBlock,
    RadioScriptBlockKind,
    TrackProposal,
)
from wavecast.models.episode import (
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.timing import ProgramTimingSummary


def _skeleton() -> ProgramSkeleton:
    return ProgramSkeleton(
        thesis="A compact route",
        estimated_duration_seconds=500,
        chapters=[
            ChapterPlan(
                index=index,
                track=TrackProposal(
                    artist=f"Artist {index}",
                    title=f"Track {index}",
                    confidence=0.8,
                    novelty_distance=(
                        NoveltyDistance.VERY_CLOSE if index == 0 else NoveltyDistance.BRIDGE
                    ),
                ),
                narrative_role=(NarrativeRole.ANCHOR if index == 0 else NarrativeRole.BRIDGE),
                reason="fixture route",
                novelty_distance=NoveltyDistance.BRIDGE,
                narration_goal="connect the route",
            )
            for index in range(3)
        ],
    )


def _episode() -> PlayableEpisode:
    return PlayableEpisode(
        segments=[
            MusicSegment(
                chapter_id="chapter-0",
                order=0,
                track_ref="netease:0",
                title="Track 0",
                artist="Artist 0",
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                state=SegmentState.AUDIO_READY,
            ),
            NarrationSegment(
                chapter_id="chapter-0",
                order=1,
                title="Bridge 0",
                narration_text="A short bridge.",
                planned_duration_seconds=30,
                actual_duration_seconds=30,
                state=SegmentState.AUDIO_READY,
            ),
            MusicSegment(
                chapter_id="chapter-1",
                order=2,
                track_ref="netease:1",
                title="Track 1",
                artist="Artist 1",
                planned_duration_seconds=80,
                actual_duration_seconds=80,
                state=SegmentState.AUDIO_READY,
            ),
            NarrationSegment(
                chapter_id="chapter-1",
                order=3,
                title="Bridge 1",
                narration_text="崔健的《一无所有》是一首重要作品。",
                planned_duration_seconds=40,
                actual_duration_seconds=40,
                state=SegmentState.AUDIO_READY,
            ),
            MusicSegment(
                chapter_id="chapter-2",
                order=4,
                track_ref="netease:2",
                title="Track 2",
                artist="Artist 2",
                planned_duration_seconds=150,
                actual_duration_seconds=150,
                state=SegmentState.AUDIO_READY,
            ),
        ]
    )


def _timing() -> ProgramTimingSummary:
    return ProgramTimingSummary(
        desired_total_seconds=500,
        music_seconds=350,
        planned_narration_seconds=100,
        actual_narration_seconds=70,
        planned_total_seconds=450,
        actual_total_seconds=420,
        target_error_seconds=-80,
        planned_vs_actual_narration_error_seconds=-30,
        target_narration_ratio=0.15,
        planned_narration_ratio=100 / 450,
        actual_narration_ratio=70 / 420,
        duration_target_feasible=True,
    )


def _writer_chapters() -> list[SimpleNamespace]:
    parsed = RadioScriptBlock(
        kind=RadioScriptBlockKind.TRANSITION,
        text="崔健的《一无所有》是一首重要作品。",
        duration_seconds=40,
    )
    normalized = RadioScriptBlock(
        kind=RadioScriptBlockKind.TRANSITION,
        text="崔健的《一无所有》是一首重要作品。",
        duration_seconds=40,
    )
    other = RadioScriptBlock(
        kind=RadioScriptBlockKind.TRANSITION,
        text="Other bridge.",
        duration_seconds=40,
    )
    return [
        SimpleNamespace(
            chapter_index=0,
            parsed_blocks=[parsed],
            normalized_blocks=[normalized],
        ),
        SimpleNamespace(
            chapter_index=1,
            parsed_blocks=[other],
            normalized_blocks=[],
        ),
    ]


def test_build_listening_evaluation_reports_route_pacing_duration_and_continuity() -> None:
    evaluation = build_listening_evaluation(
        skeleton=_skeleton(),
        resolved_chapter_indices=[0, 2],
        unresolved_chapter_indices=[1],
        unresolved_track_references=[("崔健", "一无所有")],
        episode=_episode(),
        timing_summary=_timing(),
        writer_chapters=_writer_chapters(),
        window_seconds=300,
    )

    assert evaluation.route_survival.selected_track_count == 3
    assert evaluation.route_survival.resolved_track_count == 2
    assert evaluation.route_survival.unresolved_track_count == 1
    assert evaluation.route_survival.resolution_survival_rate == pytest.approx(2 / 3)
    assert evaluation.route_survival.expected_transition_count == 2
    assert evaluation.route_survival.surviving_transition_count == 0
    assert evaluation.route_survival.lost_transition_count == 2

    assert evaluation.duration.target_seconds == 500
    assert evaluation.duration.planned_seconds == 450
    assert evaluation.duration.materialized_seconds == 420
    assert evaluation.duration.absolute_error_seconds == 80
    assert evaluation.duration.relative_error == pytest.approx(-0.16)
    assert evaluation.duration.materialized_narration_seconds == 70

    assert len(evaluation.pacing.windows) == 2
    assert evaluation.pacing.windows[0].music_seconds == 230
    assert evaluation.pacing.windows[0].narration_seconds == 70
    assert evaluation.pacing.windows[0].narration_ratio == pytest.approx(70 / 300)
    assert evaluation.pacing.longest_uninterrupted_music_seconds == 150
    assert evaluation.pacing.longest_narration_burst_seconds == 40
    assert evaluation.pacing.narration_heaviest_window_index == 0

    assert evaluation.writer_continuity.writer_chapter_count == 2
    assert evaluation.writer_continuity.parsed_block_count == 2
    assert evaluation.writer_continuity.normalized_block_count == 1
    assert evaluation.writer_continuity.normalized_block_loss_count == 1
    assert evaluation.writer_continuity.final_timeline_narration_segments == 2
    assert evaluation.writer_continuity.unresolved_track_mention_count == 1
    assert evaluation.human_review_required is True
    assert evaluation.review_questions == REVIEW_QUESTIONS

    serialized = evaluation.model_dump_json()
    assert "崔健《一无所有》" not in serialized


def test_listening_evaluation_rejects_non_positive_pacing_window() -> None:
    with pytest.raises(ValueError, match="window_seconds must be positive"):
        build_listening_evaluation(
            skeleton=_skeleton(),
            resolved_chapter_indices=[0, 2],
            unresolved_chapter_indices=[1],
            unresolved_track_references=[],
            episode=_episode(),
            timing_summary=_timing(),
            writer_chapters=[],
            window_seconds=0,
        )

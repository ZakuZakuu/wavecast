from wavecast.timing import build_program_timing_plan, summarize_program_timing


def test_timing_plan_allocates_requested_narration_when_music_leaves_room() -> None:
    plan = build_program_timing_plan(
        desired_total_seconds=900,
        target_narration_ratio=0.15,
        resolved_music_seconds=700,
        chapter_slot_counts=[1, 1, 1],
    )

    assert plan.requested_narration_seconds == 135
    assert plan.available_narration_seconds == 200
    assert plan.allocated_narration_seconds == 135
    assert plan.duration_target_feasible is True
    assert sum(item.target_narration_seconds for item in plan.chapter_budgets) == 135


def test_timing_plan_compresses_narration_to_remaining_duration() -> None:
    plan = build_program_timing_plan(
        desired_total_seconds=900,
        target_narration_ratio=0.15,
        resolved_music_seconds=800,
        chapter_slot_counts=[1, 1, 1],
    )

    assert plan.requested_narration_seconds == 135
    assert plan.available_narration_seconds == 100
    assert plan.allocated_narration_seconds == 100
    assert plan.duration_target_feasible is True


def test_timing_plan_marks_music_filled_target_infeasible_without_dropping_chapters() -> None:
    plan = build_program_timing_plan(
        desired_total_seconds=900,
        target_narration_ratio=0.15,
        resolved_music_seconds=900,
        chapter_slot_counts=[1, 2],
    )

    assert plan.duration_target_feasible is False
    assert len(plan.chapter_budgets) == 2
    assert all(item.target_narration_seconds > 0 for item in plan.chapter_budgets)
    assert plan.allocated_narration_seconds == 2


def test_timing_plan_uses_deterministic_slot_weighting_and_exact_sum() -> None:
    plan = build_program_timing_plan(
        desired_total_seconds=1000,
        target_narration_ratio=0.01,
        resolved_music_seconds=100,
        chapter_slot_counts=[1, 2, 3],
    )

    assert [item.target_narration_seconds for item in plan.chapter_budgets] == [2, 3, 5]
    assert sum(item.target_narration_seconds for item in plan.chapter_budgets) == 10


def test_timing_summary_exposes_planned_and_actual_drift() -> None:
    plan = build_program_timing_plan(
        desired_total_seconds=900,
        target_narration_ratio=0.15,
        resolved_music_seconds=700,
        chapter_slot_counts=[1],
    )

    summary = summarize_program_timing(
        plan,
        planned_narration_seconds=135,
        actual_narration_seconds=128,
    )

    assert summary.planned_total_seconds == 835
    assert summary.actual_total_seconds == 828
    assert summary.target_error_seconds == -72

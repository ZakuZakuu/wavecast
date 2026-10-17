"""Duration-based scheduling, delivered coverage and the bounded backup; no paid calls."""

import asyncio

import pytest
from wavecast.hosting import (
    DiscussionPlan,
    backup_ready,
    delivered_discussions,
    discussion_counts,
    plan_discussions,
)
from wavecast.intelligence.models import ChapterPlan, NarrationSlotContext, ResolvedTrack
from wavecast.models.dialogue import DialogueBlock, DialoguePurpose, DialogueTurn
from wavecast.models.episode import EpisodeState, NarrationSegment, SegmentState
from wavecast.models.progressive import ProgressiveAssemblyChapter
from wavecast.orchestration.episode import EpisodeOrchestrator
from wavecast.orchestration.narration_enrichment import author_pending_narration
from wavecast.presentation import HostMode
from wavecast.stations import StationId

from tests.test_narration_authoring import _authored_chapter, _Host, _pending_episode


@pytest.mark.parametrize("station", [StationId.PORTRAIT, StationId.LINEAGE])
@pytest.mark.parametrize("seconds,expected", [(1800, (3, 2)), (2100, (3, 2)), (3600, (5, 4))])
def test_heavy_station_counts_follow_programme_duration(station, seconds, expected):
    assert discussion_counts(station, HostMode.FULL, seconds) == expected


@pytest.mark.parametrize("station", list(StationId))
def test_light_and_music_only_intent_override_the_station(station):
    assert discussion_counts(station, HostMode.LIGHT, 3600) is None
    assert discussion_counts(station, HostMode.NONE, 3600) is None
    if station not in {StationId.PORTRAIT, StationId.LINEAGE}:
        assert discussion_counts(station, HostMode.FULL, 3600) is None


def _chapters(lengths):
    return [
        ProgressiveAssemblyChapter.model_construct(
            chapter_id=f"chapter-{i + 2}",
            chapter=ChapterPlan.model_construct(),
            resolved_track=ResolvedTrack(
                track_ref=f"mock:{i}",
                canonical_artist="A",
                canonical_title=str(i),
                duration_seconds=length,
            ),
            slot_contexts=[
                NarrationSlotContext.model_construct(
                    is_opening=False, is_final=i == len(lengths) - 1
                )
            ],
            target_narration_seconds=20,
        )
        for i, length in enumerate(lengths)
    ]


def test_discussions_spread_by_music_time_with_one_later_backup():
    chapters = _chapters([180, 180, 180, 600, 180, 180, 180, 180])
    plan = plan_discussions(chapters, target=3, minimum=2)
    assert plan.chapter_ids == ["chapter-4", "chapter-5", "chapter-7"]
    assert plan.opening_chapter_ids == ["chapter-2", "chapter-3"]
    assert plan.backup_chapter_id == "chapter-8"
    assert plan == plan_discussions(chapters, target=3, minimum=2)
    assert "chapter-2" not in plan.chapter_ids  # already-owned fast opening
    assert "chapter-9" not in plan.chapter_ids  # closing


def test_a_short_route_does_not_silently_lower_the_promised_minimum():
    plan = plan_discussions(_chapters([180, 180, 180]), target=3, minimum=2)
    assert len(plan.chapter_ids) == 0
    assert (plan.target, plan.minimum) == (3, 2)
    assert plan.backup_chapter_id is None


def _discussion(chapter="chapter-2", state=SegmentState.AUDIO_READY):
    return NarrationSegment(
        id=f"{chapter}:discussion",
        chapter_id=chapter,
        order=1,
        state=state,
        title="Discussion",
        planned_duration_seconds=60,
        actual_duration_seconds=60 if state is SegmentState.AUDIO_READY else None,
        asset_ref="voice" if state is SegmentState.AUDIO_READY else None,
        audio_source_url="/api/audio/mock/voice" if state is SegmentState.AUDIO_READY else None,
        dialogue=DialogueBlock(
            block_id=f"dlg-{chapter}",
            slot_id=f"{chapter}:before-track",
            purpose=DialoguePurpose.STORY,
            duration_seconds=60,
            turns=[
                DialogueTurn(speaker=speaker, text="A checked point.", fact_refs=["f1"])
                for speaker in ("A", "B", "A")
            ],
        ),
    )


def test_only_actual_voiced_discussions_count_and_shortfall_is_explicit():
    _, episode = _pending_episode()
    episode.progressive_session.discussion_plan = DiscussionPlan(
        target=3, minimum=2, chapter_ids=["chapter-2", "chapter-3"]
    )
    discussion = _discussion()
    episode.segments = [discussion]
    assert delivered_discussions(episode) == 1
    assert episode.hosting_coverage.status == "pending"
    episode.state = EpisodeState.MATERIALIZED
    assert episode.hosting_coverage.status == "shortfall"
    assert episode.hosting_coverage.reason == "discussion_not_delivered"
    for change in (
        {"state": SegmentState.SCRIPT_READY},
        {"state": SegmentState.SKIPPED},
        {
            "dialogue": discussion.dialogue.model_copy(
                update={"turns": discussion.dialogue.turns[:1]}
            )
        },
        {"dialogue": discussion.dialogue.model_copy(update={"purpose": DialoguePurpose.OUTRO})},
    ):
        episode.segments = [discussion.model_copy(update=change)]
        assert delivered_discussions(episode) == 0
    episode.segments = [discussion, _discussion("chapter-3")]
    assert episode.hosting_coverage.status == "met"


def _backup_episode():
    repository, episode = _pending_episode()
    session = episode.progressive_session
    session.discussion_plan = DiscussionPlan(
        target=3, minimum=2, chapter_ids=[], backup_chapter_id="chapter-2"
    )
    return repository, episode


def test_backup_waits_for_primary_voicing_and_never_runs_as_ordinary_authoring():
    repository, episode = _backup_episode()
    host = _Host(repository)

    class Runtime:
        calls = 0

        async def author_narration(self, episode, chapter_id):
            self.calls += 1
            return None

    host.progressive_runtime = Runtime()
    asyncio.run(author_pending_narration(host, episode.id))
    assert host.progressive_runtime.calls == 0
    episode.progressive_session.discussion_plan.chapter_ids = ["primary"]
    assert not backup_ready(episode)
    episode.progressive_session.narration_authored_chapter_ids = ["primary"]
    pending = _discussion("primary", SegmentState.SCRIPT_READY)
    episode.segments.append(pending)
    assert not backup_ready(episode)
    pending.state = SegmentState.SKIPPED
    assert backup_ready(episode)


@pytest.mark.parametrize("skipped,already_met", [(False, False), (True, False), (False, True)])
def test_one_backup_attempt_counts_only_its_audio_and_respects_skipped_seams(skipped, already_met):
    repository, episode = _backup_episode()
    if skipped:
        episode.segment("chapter-2:narration:pending").state = SegmentState.SKIPPED
    if already_met:
        episode.segments.extend([_discussion("primary-1"), _discussion("primary-2")])

    class Runtime:
        calls = 0
        tts_calls = 0

        async def author_narration(self, episode, chapter_id):
            self.calls += 1
            result = _authored_chapter()
            result.segments[0] = _discussion(state=SegmentState.SCRIPT_READY)
            return result

        async def materialize_narration(self, segment):
            self.tts_calls += 1
            return _discussion()

    runtime = Runtime()
    orchestrator = EpisodeOrchestrator(repository, progressive_runtime=runtime)

    async def run():
        await orchestrator.complete_hosting_async(episode.id)
        await orchestrator.complete_hosting_async(episode.id)

    asyncio.run(run())
    expected = 0 if skipped or already_met else 1
    assert runtime.calls == runtime.tts_calls == expected
    assert delivered_discussions(repository.get(episode.id)) == (2 if already_met else expected)
    assert (
        "chapter-2" in repository.get(episode.id).progressive_session.narration_authored_chapter_ids
    )


@pytest.mark.parametrize("seconds,target,minimum", [(1800, 3, 2), (3600, 5, 4)])
def test_assembly_persists_the_discussion_plan_and_reserves_music_time(seconds, target, minimum):
    from types import SimpleNamespace

    from wavecast.assembly import LiveEpisodeAssemblyRequest, _build_progressive_session
    from wavecast.models.progressive import ProgressiveAssemblySession
    from wavecast.presentation import PresentationIntent

    from tests.test_episode_assembly import _resolved_chapter
    from tests.test_staged_intelligence import _session

    old = _session()
    route = [_resolved_chapter(i, i) for i in range(16)]
    for item in route:
        item.track.duration_seconds = 180
    prepared = SimpleNamespace(
        resolved_chapters=route,
        unresolved=[],
        unfulfilled_artists=[],
        bundle=old.research,
        fast_result=SimpleNamespace(plan=old.fast_plan),
        skeleton=old.skeleton,
    )
    session = _build_progressive_session(
        request=LiveEpisodeAssemblyRequest(
            topic="An artist through their work",
            station=StationId.LINEAGE,
            presentation_intent=PresentationIntent(host_mode=HostMode.FULL),
            desired_duration_seconds=seconds,
            max_tracks=16,
            max_chapters=24,
        ),
        prepared=prepared,
        opening_track=route[0].track,
        narration_ratio=0.15,
    )
    plan = session.discussion_plan
    assert (plan.target, plan.minimum) == (target, minimum)
    assert len(plan.chapter_ids) == target
    assert session.timing_plan.resolved_music_seconds == (len(session.chapters) + 1) * 180
    assert session.timing_plan.allocated_narration_seconds == target * 95 + 120
    total = (
        session.timing_plan.resolved_music_seconds + session.timing_plan.allocated_narration_seconds
    )
    # Existing fitting ends on the nearest complete song, which may exceed the soft target.
    assert total <= seconds + 180
    assert session.timing_plan.duration_target_feasible == (total <= seconds)
    assert (
        ProgressiveAssemblySession.model_validate_json(session.model_dump_json()).discussion_plan
        == plan
    )
    assert _session().discussion_plan is None  # durable older sessions retain legacy selection


@pytest.mark.parametrize("tts_failures,delivered,backup_calls", [(0, 3, 0), (2, 2, 1), (3, 1, 1)])
def test_full_lifecycle_settles_primary_audio_then_attempts_one_backup_and_closes(
    tts_failures, delivered, backup_calls
):
    from wavecast.models.episode import MusicSegment
    from wavecast.orchestration.generation import GeneratedChapter

    repository, episode = _pending_episode()
    session = episode.progressive_session
    session.chapters = _chapters([180] * 6)
    for chapter in session.chapters:
        chapter.chapter = ChapterPlan.model_construct(track=None)
    session.discussion_plan = DiscussionPlan(
        target=3,
        minimum=2,
        chapter_ids=["chapter-3", "chapter-4", "chapter-5"],
        backup_chapter_id="chapter-6",
    )
    episode.segments = [episode.segments[0]]
    for index, chapter in enumerate(session.chapters):
        episode.segments.extend(
            [
                NarrationSegment(
                    id=f"{chapter.chapter_id}:pending",
                    chapter_id=chapter.chapter_id,
                    order=index * 2 + 1,
                    state=SegmentState.PLANNED,
                    planned_duration_seconds=60,
                    title="Pending",
                ),
                MusicSegment(
                    id=f"{chapter.chapter_id}:music",
                    chapter_id=chapter.chapter_id,
                    order=index * 2 + 2,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=180,
                    actual_duration_seconds=180,
                    audio_source_url="/api/audio/mock/music",
                    track_ref=chapter.resolved_track.track_ref,
                    artist="A",
                    title=chapter.resolved_track.canonical_title,
                ),
            ]
        )
    events = []

    class Runtime:
        def create_generator(self, session):
            return self

        async def generate_next(self, episode):
            return None

        async def author_narration(self, episode, chapter_id):
            events.append(f"write:{chapter_id}")
            music = next(
                s
                for s in episode.segments
                if s.chapter_id == chapter_id and isinstance(s, MusicSegment)
            )
            if chapter_id in {"chapter-2", "chapter-7"}:
                narration = NarrationSegment(
                    id=f"{chapter_id}:single",
                    chapter_id=chapter_id,
                    order=music.order - 1,
                    state=SegmentState.SCRIPT_READY,
                    title="Opening/closing",
                    planned_duration_seconds=20,
                    narration_text="An opening or closing.",
                )
            else:
                narration = _discussion(chapter_id, SegmentState.SCRIPT_READY)
            return GeneratedChapter(chapter_id=chapter_id, segments=[narration, music])

        async def materialize_narration(self, segment):
            events.append(f"voice:{segment.chapter_id}")
            failed = segment.chapter_id in [f"chapter-{i + 3}" for i in range(tts_failures)]
            return segment.model_copy(
                update={
                    "state": SegmentState.SKIPPED if failed else SegmentState.AUDIO_READY,
                    "actual_duration_seconds": 60,
                    "asset_ref": "voice",
                    "audio_source_url": "/api/audio/mock/voice",
                }
            )

    orchestrator = EpisodeOrchestrator(repository, progressive_runtime=Runtime())
    completed = asyncio.run(orchestrator.materialize_all_async(episode.id))
    assert completed.state is EpisodeState.MATERIALIZED
    assert completed.hosting_coverage.delivered == delivered
    assert completed.hosting_coverage.status == ("shortfall" if delivered < 2 else "met")
    assert events.count("write:chapter-6") == backup_calls
    assert events.index("write:chapter-7") > events.index("voice:chapter-5")
    if backup_calls:
        assert events.index("write:chapter-6") > events.index("voice:chapter-5")
        assert events.index("write:chapter-7") > events.index("write:chapter-6")
    assert sum(isinstance(s, MusicSegment) for s in completed.timeline_segments) == 7


def test_short_bridge_does_not_complete_opening_and_opening_does_not_replace_body():
    from wavecast.hosting import has_programme_opening, needs_programme_opening

    _, episode = _pending_episode()
    episode.progressive_session.discussion_plan = DiscussionPlan(
        target=3,
        minimum=2,
        chapter_ids=["body"],
        opening_chapter_ids=["chapter-2", "chapter-3"],
    )
    short = NarrationSegment(
        chapter_id="chapter-1",
        order=0,
        state=SegmentState.AUDIO_READY,
        title="Welcome",
        planned_duration_seconds=10,
        actual_duration_seconds=10,
        narration_text="欢迎收听。",
        audio_source_url="/welcome",
    )
    episode.segments = [short]
    assert not has_programme_opening(episode)
    assert needs_programme_opening(episode, "chapter-2")
    assert needs_programme_opening(episode, "chapter-3")
    assert not needs_programme_opening(episode, "chapter-4")
    opening = _discussion().model_copy(update={"hosting_role": "opening"})
    episode.segments.append(opening)
    assert has_programme_opening(episode)
    assert not needs_programme_opening(episode, "chapter-3")
    assert delivered_discussions(episode) == 0
    assert episode.hosting_coverage.opening == "delivered"
    opening.state = SegmentState.SKIPPED
    assert needs_programme_opening(episode, "chapter-3")
    episode.state = EpisodeState.MATERIALIZED
    assert episode.hosting_coverage.opening == episode.hosting_coverage.closing == "missed"


def test_opening_window_uses_music_positions_not_narrative_chapter_numbers():
    chapters = _chapters([180] * 8)
    beat = chapters[0].model_copy(update={"chapter_id": "beat", "resolved_track": None})
    plan = plan_discussions([beat, *chapters], target=3, minimum=2)
    assert plan.opening_chapter_ids == ["beat", "chapter-3"]
    assert not set(plan.opening_chapter_ids) & set(plan.chapter_ids)


@pytest.mark.parametrize("fail_opening", [False, True])
def test_early_takeover_and_closing_settle_real_tts_before_deciding(fail_opening):
    from wavecast.hosting import has_programme_opening, needs_programme_opening
    from wavecast.models.episode import MusicSegment
    from wavecast.orchestration.generation import GeneratedChapter

    repository, episode = _pending_episode()
    session = episode.progressive_session
    first = session.chapters[0]
    session.chapters = [
        first,
        first.model_copy(update={"chapter_id": "chapter-3"}),
        first.model_copy(update={"chapter_id": "chapter-4"}),
    ]
    session.discussion_plan = DiscussionPlan(
        target=3, minimum=2, chapter_ids=[], opening_chapter_ids=["chapter-2", "chapter-3"]
    )
    # Existing primary script is waiting for TTS; the second gap must learn its actual result.
    primary = episode.segment("chapter-2:narration:pending")
    primary.state = SegmentState.SCRIPT_READY
    primary.hosting_role = "opening"
    primary.narration_text = "PRIMARY"
    session.narration_authored_chapter_ids = ["chapter-2"]
    episode.segments.append(
        NarrationSegment(
            chapter_id="chapter-3",
            order=3,
            title="Pending",
            state=SegmentState.PLANNED,
            planned_duration_seconds=75,
        )
    )
    episode.segment("chapter-3:music:0").order = 4
    episode.segments.extend(
        [
            NarrationSegment(
                chapter_id="chapter-4",
                order=5,
                title="Close",
                state=SegmentState.PLANNED,
                planned_duration_seconds=45,
            ),
            MusicSegment(
                chapter_id="chapter-4",
                order=6,
                track_ref="mock:last",
                title="Last",
                artist="Artist",
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=180,
                audio_source_url="/last",
            ),
        ]
    )
    events = []

    class Runtime:
        async def materialize_narration(self, segment):
            events.append("voice:" + segment.narration_text)
            return segment.model_copy(
                update={
                    "state": SegmentState.SKIPPED
                    if fail_opening and segment.narration_text == "PRIMARY"
                    else SegmentState.AUDIO_READY,
                    "actual_duration_seconds": 40,
                    "audio_source_url": "/voiced",
                }
            )

        async def author_narration(self, snapshot, chapter_id):
            events.append("write:" + chapter_id)
            music = next(
                s
                for s in snapshot.segments
                if isinstance(s, MusicSegment) and s.chapter_id == chapter_id
            )
            if chapter_id == "chapter-3":
                assert needs_programme_opening(snapshot, chapter_id)
                text, role = "TAKEOVER", "opening"
            else:
                assert has_programme_opening(snapshot)
                assert not any(
                    isinstance(s, NarrationSegment) and s.state is SegmentState.SCRIPT_READY
                    for s in snapshot.segments
                )
                text, role = "CLOSE", "closing"
            narration = NarrationSegment(
                chapter_id=chapter_id,
                order=music.order - 1,
                title=text,
                state=SegmentState.SCRIPT_READY,
                planned_duration_seconds=40,
                narration_text=text,
                hosting_role=role,
            )
            return GeneratedChapter(chapter_id=chapter_id, segments=[narration, music])

    repository.save(episode)
    orchestrator = EpisodeOrchestrator(repository, progressive_runtime=Runtime())
    saved = asyncio.run(orchestrator.author_pending_narration_async(episode.id, max_chapters=10))
    assert ("write:chapter-3" in events) == fail_opening
    assert events[0] == "voice:PRIMARY"
    assert events[-1] == "write:chapter-4"
    assert saved.hosting_coverage.opening == "delivered"


def test_missing_bookends_cannot_report_a_complete_heavy_programme():
    _, episode = _pending_episode()
    episode.progressive_session.discussion_plan = DiscussionPlan(
        target=3, minimum=2, chapter_ids=["body-a", "body-b"], opening_chapter_ids=["chapter-2"]
    )
    episode.segments = [_discussion("body-a"), _discussion("body-b")]
    episode.state = EpisodeState.MATERIALIZED
    assert episode.hosting_coverage.status == "shortfall"
    assert episode.hosting_coverage.reason == "opening_not_delivered"
    opening = _discussion("opening").model_copy(update={"hosting_role": "opening"})
    episode.segments.append(opening)
    assert episode.hosting_coverage.reason == "closing_not_delivered"
    episode.segments.append(
        NarrationSegment(
            chapter_id="closing",
            order=5,
            title="Close",
            state=SegmentState.AUDIO_READY,
            planned_duration_seconds=40,
            narration_text="收束。",
            hosting_role="closing",
            audio_source_url="/close",
        )
    )
    assert episode.hosting_coverage.status == "met"
    assert episode.hosting_coverage.delivered == 2

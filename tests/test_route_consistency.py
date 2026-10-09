"""A chapter's text describes the track that plays, not the one that was planned."""

import asyncio

import pytest
from wavecast.assembly import LiveEpisodeAssemblyRequest
from wavecast.intelligence.models import (
    ChapterPlan,
    ClaimSupport,
    ClaimType,
    EditorialConnection,
    EditorialRelationType,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.route_consistency import (
    chapter_text,
    foreign_artists,
    known_artist_names,
    track_true_chapter,
    used_an_alternate,
)
from wavecast.text_identity import text_mentions_name

from tests.test_episode_assembly import RecordingAssemblyLLM, service

OPENING = ResolvedTrack(
    track_ref="mock:opening", canonical_artist="Mira Fields", canonical_title="Neon First Light"
)


def proposal(artist: str, title: str = "Song") -> TrackProposal:
    return TrackProposal(artist=artist, title=title, confidence=0.9, evidence_ids=["e-own"])


def chapter(
    artist: str | None,
    reason: str = "fixture",
    goal: str = "fixture goal",
    *,
    title: str = "Song",
    alternates: list[TrackProposal] | None = None,
    role: NarrativeRole = NarrativeRole.BRIDGE,
    index: int = 0,
) -> ChapterPlan:
    return ChapterPlan(
        index=index,
        track=proposal(artist, title) if artist is not None else None,
        track_alternates=alternates or [],
        narrative_role=role,
        reason=reason,
        novelty_distance=NoveltyDistance.CLOSE,
        narration_goal=goal,
        evidence_ids=["e1"],
    )


# --- mentioning a name ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name", "expected"),
    [
        ("A category of sound", "Cat", False),
        ("Cat Power sings", "Cat", True),
        ("the mogwai sound", "Mogwai", True),
        ("MOGWAI.", "mogwai", True),
        ("久石让的配乐", "久石譲", True),
        ("坂本龍一的钢琴", "坂本龙一", True),
        ("hello", "x", False),
        ("Explosions in the Sky are from Texas", "Explosions in the Sky", True),
        ("U2 and others", "U2", True),
        ("Version 2 of it", "U2", False),
    ],
)
def test_a_name_is_found_as_a_whole_word_or_across_script_variants(
    text: str, name: str, expected: bool
) -> None:
    assert text_mentions_name(text, name) is expected


# --- who the plan can write about ----------------------------------------------------------


def test_known_names_are_the_requested_the_named_and_the_proposed_without_repeats() -> None:
    names = known_artist_names(
        [proposal("Hammock"), proposal("hammock"), proposal("Mogwai")],
        ["Explosions in the Sky"],
        "from Mogwai to Explosions in the Sky",
    )

    assert names == ["Explosions in the Sky", "Mogwai", "Hammock"]


# --- spotting text about someone else ------------------------------------------------------


def test_text_about_an_artist_who_is_not_playing_is_flagged() -> None:
    plan = chapter("Mogwai", reason="Explosions in the Sky build slowly.", goal="Introduce them.")

    found = foreign_artists(plan, "Mogwai", ["Explosions in the Sky", "Mogwai"], [])

    assert found == ["Explosions in the Sky"]


def test_a_bridge_that_also_names_its_own_artist_is_left_alone() -> None:
    plan = chapter("Mogwai", reason="Move from Hammock's drone to Mogwai's noise.")

    assert foreign_artists(plan, "Mogwai", ["Hammock", "Mogwai"], []) == []


def test_an_artist_already_heard_may_be_referred_back_to() -> None:
    plan = chapter("Mogwai", reason="After Hammock, something louder.")

    assert foreign_artists(plan, "Mogwai", ["Hammock"], ["Hammock"]) == []
    assert foreign_artists(plan, "Mogwai", ["Hammock"], []) == ["Hammock"]


def test_a_collaborator_in_the_bound_credit_is_not_foreign() -> None:
    plan = chapter("Hammock", reason="Mogwai joins on this one.")

    assert foreign_artists(plan, "Hammock, Mogwai", ["Mogwai"], []) == []


def test_claims_and_the_connection_count_as_chapter_text() -> None:
    plan = chapter("Mogwai").model_copy(
        update={
            "claim_support": [
                ClaimSupport(
                    claim_type=ClaimType.FACT, claim="Hammock formed in 2004.", evidence_ids=["e1"]
                )
            ],
            "connection_from_previous_track": EditorialConnection(
                relation_type=EditorialRelationType.SHARED_RHYTHMIC_POCKET,
                rationale="Same pulse as Explosions in the Sky.",
            ),
        }
    )

    assert "Hammock formed in 2004." in chapter_text(plan)
    assert foreign_artists(plan, "Mogwai", ["Hammock", "Explosions in the Sky"], []) == [
        "Hammock",
        "Explosions in the Sky",
    ]


def test_a_chapter_without_names_has_nothing_foreign() -> None:
    plan = chapter("Mogwai", reason="A louder turn.", goal="Say what to listen for.")

    assert foreign_artists(plan, "Mogwai", ["Hammock"], []) == []


# --- alternates and neutral text ---------------------------------------------------------------


def test_an_alternate_is_detected_by_the_proposal_that_plays() -> None:
    plan = chapter("Ghost Band", title="Never", alternates=[proposal("Hammock", "Tape")])

    assert used_an_alternate(plan, plan.track_alternates[0]) is True
    assert used_an_alternate(plan, plan.track) is False
    assert used_an_alternate(plan, None) is False
    assert used_an_alternate(chapter(None), proposal("Hammock")) is False


def test_track_true_text_keeps_the_role_and_position_but_drops_the_old_claims() -> None:
    plan = chapter(
        "Ghost Band",
        reason="Ghost Band's 1999 album changed everything.",
        goal="Tell the Ghost Band story.",
        alternates=[proposal("Hammock", "Tape")],
        role=NarrativeRole.DISCOVERY,
        index=3,
    ).model_copy(
        update={
            "claim_support": [
                ClaimSupport(claim_type=ClaimType.FACT, claim="Ghost Band 1999.", evidence_ids=["e1"])
            ]
        }
    )

    neutral = track_true_chapter(plan, plan.track_alternates[0])

    assert neutral.index == 3 and neutral.narrative_role is NarrativeRole.DISCOVERY
    assert neutral.track is not None and neutral.track.artist == "Hammock"
    assert "Ghost" not in chapter_text(neutral)
    assert neutral.track_alternates == [] and neutral.claim_support == []
    assert neutral.connection_from_previous_track is None
    assert neutral.evidence_ids == ["e-own"]


# --- the whole route ---------------------------------------------------------------------------


class _PlannedLLM(RecordingAssemblyLLM):
    """A Curator that returns exactly the chapters a test gives it."""

    def __init__(self, chapters: list[ChapterPlan]) -> None:
        super().__init__()
        self.planned = chapters

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        if output_type is ProgramSkeleton:
            return ProgramSkeleton(
                thesis="fixture", chapters=self.planned, estimated_duration_seconds=5 * 60
            )
        return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]


def _prepare(tmp_path, chapters: list[ChapterPlan]) -> ProgressiveAssemblySession:
    assembly = service(tmp_path, _PlannedLLM(chapters))
    return asyncio.run(
        assembly.prepare_progressive_session(  # type: ignore[attr-defined]
            LiveEpisodeAssemblyRequest(
                topic="Southbound FM, Signal Garden and Mira Fields",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
            ),
            opening_track=OPENING,
        )
    )


def _text(session: ProgressiveAssemblySession, position: int) -> str:
    return chapter_text(session.chapters[position].chapter)


def _artist(session: ProgressiveAssemblySession, position: int) -> str:
    track = session.chapters[position].resolved_track
    assert track is not None
    return track.canonical_artist


def test_the_alternate_that_plays_does_not_inherit_the_planned_artists_story(tmp_path) -> None:
    session = _prepare(
        tmp_path,
        [
            chapter(
                "Ghost Band",
                reason="Ghost Band's 1999 album is the turning point.",
                goal="Tell the Ghost Band story.",
                title="Never Released",
                alternates=[proposal("Signal Garden", "Midnight Transfer")],
            )
        ],
    )

    assert _artist(session, 0) == "Signal Garden"
    assert "Ghost Band" not in _text(session, 0)
    assert session.chapters[0].chapter.claim_support == []


def test_text_about_an_artist_who_does_not_play_is_replaced_by_generic_text(tmp_path) -> None:
    session = _prepare(
        tmp_path,
        [
            chapter(
                "Southbound FM",
                title="Afterimage Avenue",
                reason="Signal Garden's patient build is the heart of this route.",
                goal="Explain why Signal Garden matters.",
            ),
            chapter(
                "Signal Garden",
                title="Midnight Transfer",
                reason="The second Signal Garden track.",
                goal="Say what to notice.",
                role=NarrativeRole.DISCOVERY,
                index=1,
            ),
        ],
    )

    assert _artist(session, 0) == "Southbound FM"
    assert "Signal Garden" not in _text(session, 0)


def test_a_chapter_that_describes_its_own_track_is_left_exactly_as_planned(tmp_path) -> None:
    session = _prepare(
        tmp_path,
        [
            chapter(
                "Southbound FM",
                title="Afterimage Avenue",
                reason="Southbound FM keeps the pulse after Mira Fields.",
                goal="Note the steady drums.",
            )
        ],
    )

    assert _text(session, 0) == (
        "Southbound FM keeps the pulse after Mira Fields.\nNote the steady drums."
    )


def test_a_bridge_naming_both_artists_is_left_as_planned(tmp_path) -> None:
    session = _prepare(
        tmp_path,
        [
            chapter(
                "Southbound FM",
                title="Afterimage Avenue",
                reason="Southbound FM is where this route is going.",
                goal="Move on to Southbound FM.",
            ),
            chapter(
                "Signal Garden",
                title="Midnight Transfer",
                reason="From Southbound FM's pulse to Signal Garden's glow.",
                goal="Bridge the two.",
                role=NarrativeRole.DISCOVERY,
                index=1,
            ),
        ],
    )

    assert "Southbound FM" in _text(session, 1) and "Signal Garden" in _text(session, 1)
    assert "Southbound FM is where this route is going." in _text(session, 0)


def test_a_neutralised_chapter_is_logged_with_its_cause_and_no_names(tmp_path, caplog) -> None:
    with caplog.at_level("INFO", logger="wavecast.assembly"):
        _prepare(
            tmp_path,
            [
                chapter(
                    "Ghost Band",
                    reason="Ghost Band's 1999 album is the turning point.",
                    title="Never Released",
                    alternates=[proposal("Signal Garden", "Midnight Transfer")],
                )
            ],
        )

    logged = [r.getMessage() for r in caplog.records if "chapter_text_neutralised" in r.getMessage()]
    assert logged == ["chapter_text_neutralised chapter=0 cause=alternate_track foreign_artists=0"]

"""The route plays the artists the listener named, or says it could not."""

from wavecast.catalog_pool import CatalogPool, PoolEntry, PoolSource
from wavecast.coverage import (
    candidate_artist_names,
    covered_artists,
    ensure_required_coverage,
    entries_for_artist,
    rebind_chapter,
    unfulfilled_artists,
)
from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrativeRole,
    NoveltyDistance,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.providers.retrieval import VersionKind


def entry(ref: str, artist: str, title: str) -> PoolEntry:
    return PoolEntry(
        track_ref=f"netease:{ref}",
        artist=artist,
        title=title,
        primary_artist=artist.split(",")[0].strip(),
        duration_seconds=200,
        version_kind=VersionKind.UNKNOWN,
        source=PoolSource.ARTIST_SEARCH,
    )


def chapter(
    index: int,
    artist: str | None,
    title: str = "Song",
    role: NarrativeRole = NarrativeRole.BRIDGE,
    evidence_ids: list[str] | None = None,
    reason: str = "fixture",
) -> ChapterPlan:
    return ChapterPlan(
        index=index,
        track=(
            TrackProposal(artist=artist, title=title, confidence=0.9) if artist is not None else None
        ),
        narrative_role=role,
        reason=reason,
        novelty_distance=NoveltyDistance.CLOSE,
        narration_goal="fixture goal",
        evidence_ids=evidence_ids or [],
    )


def resolved(artist: str, title: str = "Song") -> ResolvedTrack:
    return ResolvedTrack(track_ref=f"r:{artist}:{title}", canonical_artist=artist, canonical_title=title)


def evidence(id_: str, text: str) -> Evidence:
    return Evidence(
        id=id_,
        claim_or_excerpt=text,
        source_url="https://example.com/a",
        source_provider="fixture",
        confidence=0.9,
        query="fixture",
    )


# --- finding the names in a request -------------------------------------------------------


def test_names_in_a_request_are_the_latin_phrases_that_are_not_genres() -> None:
    names = candidate_artist_names("从 Mogwai 到 Explosions in the Sky 的后摇路线")

    assert names == ["Mogwai", "Explosions in the Sky"]


def test_generic_style_words_are_not_names_and_the_count_is_bounded() -> None:
    assert candidate_artist_names("下班听点 Jazz 和 City Pop") == []
    assert len(candidate_artist_names("Aa Bb Cc, Dd Ee, Ff Gg, Hh Ii", limit=2)) == 2


def test_a_name_ends_at_the_first_plain_lower_case_word() -> None:
    assert candidate_artist_names("Mogwai live sessions") == ["Mogwai"]
    assert candidate_artist_names("late night synth drive") == []
    assert candidate_artist_names("from Mogwai to Explosions in the Sky") == [
        "Mogwai",
        "Explosions in the Sky",
    ]
    assert candidate_artist_names("The Smiths and Bill Evans") == ["The Smiths", "Bill Evans"]


def test_the_same_name_is_not_listed_twice() -> None:
    assert candidate_artist_names("Mogwai 和 Mogwai") == ["Mogwai"]


# --- which required artists a route plays ---------------------------------------------------


def test_an_artist_is_covered_by_a_credit_that_names_them_not_by_a_substring() -> None:
    credits = ["Mogwai", "Bill Evans, Jim Hall"]

    assert covered_artists(["Mogwai", "Jim Hall", "Hall"], credits) == ["Mogwai", "Jim Hall"]


def test_unfulfilled_artists_are_the_ones_the_final_route_does_not_play() -> None:
    route = [resolved("Mogwai"), resolved("Hammock")]

    assert unfulfilled_artists(["Mogwai", "Explosions in the Sky"], route) == [
        "Explosions in the Sky"
    ]
    assert unfulfilled_artists([], route) == []


def test_entries_for_artist_ignore_covers_credited_to_someone_else() -> None:
    pool = CatalogPool(
        entries=[
            entry("1", "Explosions In The Sky", "Your Hand in Mine"),
            entry("2", "Tribute Band", "Explosions in the Sky Tribute"),
        ]
    )

    assert [item.title for item in entries_for_artist(pool, "Explosions in the Sky")] == [
        "Your Hand in Mine"
    ]
    assert entries_for_artist(None, "Explosions in the Sky") == []


# --- patching the plan ---------------------------------------------------------------------


def test_a_missing_artist_takes_the_chapter_of_a_repeated_artist() -> None:
    plan = [
        chapter(0, "Mogwai", "Hunted by a Freak"),
        chapter(1, "Hammock", "Breathturn", NarrativeRole.VALIDATION),
        chapter(2, "Hammock", "Tape", NarrativeRole.DISCOVERY),
    ]
    pool = CatalogPool(entries=[entry("9", "Explosions In The Sky", "Your Hand in Mine")])

    patched, missing = ensure_required_coverage(
        plan, pool, ["Mogwai", "Explosions in the Sky"], [], protected_indices=[]
    )

    assert missing == []
    assert [item.track.artist for item in patched if item.track] == [
        "Mogwai",
        "Hammock",
        "Explosions In The Sky",
    ]
    assert [item.index for item in patched] == [0, 1, 2]


def test_a_lone_artist_is_given_up_when_nothing_repeats_but_never_a_required_one() -> None:
    plan = [chapter(0, "Mogwai"), chapter(1, "Hammock", role=NarrativeRole.DISCOVERY)]
    pool = CatalogPool(entries=[entry("9", "Explosions In The Sky", "Your Hand in Mine")])

    patched, missing = ensure_required_coverage(
        plan, pool, ["Mogwai", "Explosions in the Sky"], [], protected_indices=[]
    )

    assert missing == []
    assert [item.track.artist for item in patched if item.track] == [
        "Mogwai",
        "Explosions In The Sky",
    ]


def test_a_repeated_artist_is_given_up_before_a_lone_one_whatever_the_role() -> None:
    plan = [
        chapter(0, "Lone", role=NarrativeRole.DISCOVERY),
        chapter(1, "Twice", "A", NarrativeRole.BRIDGE),
        chapter(2, "Twice", "B", NarrativeRole.BRIDGE),
    ]
    pool = CatalogPool(entries=[entry("9", "Mogwai", "Auto Rock")])

    patched, _ = ensure_required_coverage(plan, pool, ["Mogwai"], [], protected_indices=[])

    assert [item.track.artist for item in patched if item.track] == ["Lone", "Mogwai", "Twice"]


def test_the_protected_and_reserved_tracks_are_not_replaced() -> None:
    plan = [chapter(0, "Hammock"), chapter(1, "Mogwai")]
    pool = CatalogPool(entries=[entry("9", "Explosions In The Sky", "Your Hand in Mine")])

    patched, missing = ensure_required_coverage(
        plan, pool, ["Mogwai", "Explosions in the Sky"], [], protected_indices=[0]
    )

    assert missing == ["Explosions in the Sky"]  # only Hammock could go, and it is protected
    assert patched == plan


def test_an_artist_the_opening_already_plays_is_covered() -> None:
    plan = [chapter(0, "Hammock")]
    pool = CatalogPool(entries=[entry("9", "Mogwai", "Hunted by a Freak")])

    patched, missing = ensure_required_coverage(
        plan, pool, ["Mogwai"], [], reserved=[resolved("Mogwai")], protected_indices=[]
    )

    assert missing == []
    assert patched == plan


def test_an_artist_with_no_playable_track_is_reported_not_invented() -> None:
    plan = [chapter(0, "Hammock"), chapter(1, "Hammock", "Tape")]

    patched, missing = ensure_required_coverage(
        plan, CatalogPool(), ["Explosions in the Sky"], [], protected_indices=[]
    )
    patched_without_pool, missing_without_pool = ensure_required_coverage(
        plan, None, ["Explosions in the Sky"], [], protected_indices=[]
    )

    assert missing == missing_without_pool == ["Explosions in the Sky"]
    assert patched == patched_without_pool == plan


def test_an_alternate_does_not_count_as_coverage() -> None:
    first = chapter(0, "Hammock").model_copy(
        update={
            "track_alternates": [TrackProposal(artist="Mogwai", title="Alt", confidence=0.5)]
        }
    )
    pool = CatalogPool(entries=[entry("9", "Mogwai", "Hunted by a Freak")])

    patched, missing = ensure_required_coverage(
        [first, chapter(1, "Hammock", "Tape")], pool, ["Mogwai"], [], protected_indices=[]
    )

    assert missing == []
    assert any(item.track and item.track.artist == "Mogwai" for item in patched)


def test_one_song_credited_to_two_required_artists_covers_both() -> None:
    plan = [chapter(0, "Other"), chapter(1, "Other", "Again"), chapter(2, "Third", "More")]
    pool = CatalogPool(
        entries=[
            entry("1", "Mogwai, Hammock", "Collab"),
            entry("2", "Hammock", "Tape"),
        ]
    )

    patched, missing = ensure_required_coverage(
        plan, pool, ["Mogwai", "Hammock"], [], protected_indices=[]
    )

    assert missing == []
    assert sum(1 for item in patched if item.track and item.track.title == "Collab") == 1
    assert not any(item.track and item.track.title == "Tape" for item in patched)


# --- what the swapped chapter says -------------------------------------------------------------


def test_a_swapped_chapter_follows_its_new_track_and_keeps_only_evidence_about_that_artist() -> None:
    old = chapter(
        1,
        "Hammock",
        reason="Hammock's drone",
        evidence_ids=["e1", "e2", "e3"],
    )
    facts = [
        evidence("e1", "Hammock formed in Nashville."),
        evidence("e2", "Explosions in the Sky are from Texas."),
        evidence("e3", "Mogwai played with Explosions in the Sky."),
    ]
    pool = CatalogPool(entries=[entry("9", "Explosions In The Sky", "Your Hand in Mine")])

    patched, _ = ensure_required_coverage(
        [chapter(0, "Mogwai"), old, chapter(2, "Hammock", "Tape", NarrativeRole.DISCOVERY)],
        pool,
        ["Mogwai", "Explosions in the Sky"],
        facts,
        protected_indices=[0],
    )

    swapped = next(item for item in patched if item.track and item.track.title == "Your Hand in Mine")
    assert swapped.evidence_ids == ["e2", "e3"]
    assert "Hammock" not in swapped.reason and "Hammock" not in swapped.narration_goal
    assert swapped.track_alternates == []
    assert swapped.claim_support == []
    assert swapped.connection_from_previous_track is None


def test_rebind_drops_claims_that_belonged_to_the_old_track() -> None:
    proposal = TrackProposal(artist="Mogwai", title="Auto Rock", confidence=0.6)

    rebound = rebind_chapter(chapter(1, "Hammock", evidence_ids=["e1"]), proposal, [], "Mogwai")

    assert rebound.track == proposal
    assert rebound.evidence_ids == []

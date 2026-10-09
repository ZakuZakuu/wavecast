"""Verified-playable catalog candidate pool (ADR 0022, step 1).

The pool answers "which real, playable tracks exist for this programme?" before any
LLM chooses the route.  It is deterministic application code: it only calls the
``MusicProvider`` catalog seam (never a paid LLM, search or TTS provider), every
catalog call is bounded, and every entry has been confirmed playable through the
authoritative track-detail endpoint.

Nothing in the runtime consumes the pool yet; later steps hand it to the Curator.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from wavecast.intelligence.models import ResolvedTrack, TrackProposal
from wavecast.providers.errors import ProviderError
from wavecast.providers.retrieval import (
    MusicRetrievalService,
    RetrievalFailure,
    RetrievedTrack,
    VersionKind,
)
from wavecast.text_identity import (
    base_title_key,
    canonical_name,
    same_catalog_name,
    without_feature_credit,
)

# Catalog credits separate artists with commas; "&", "/" and "x" appear inside real
# names (Simon & Garfunkel, AC/DC, X Japan), so they are deliberately not separators.
_ARTIST_SEPARATORS = re.compile(r"\s*(?:,|，|、|;|；|\bfeat\.?|\bft\.?)\s*", re.I)
_DEFAULT_EXCLUDED_VERSIONS = frozenset({VersionKind.LIVE, VersionKind.REMIX, VersionKind.ACOUSTIC})


class PoolSource(StrEnum):
    """Where a candidate came from, ordered from most to least trusted."""

    LLM_CANDIDATE = "llm_candidate"
    ARTIST_SEARCH = "artist_search"
    KEYWORD_SEARCH = "keyword_search"


_SOURCE_ORDER = {
    PoolSource.LLM_CANDIDATE: 0,
    PoolSource.ARTIST_SEARCH: 1,
    PoolSource.KEYWORD_SEARCH: 2,
}


class AvailabilityStatus(StrEnum):
    PLAYABLE = "playable"
    UNPLAYABLE = "unplayable"
    NOT_FOUND = "not_found"
    PROVIDER_ERROR = "provider_error"


def split_artists(value: str) -> tuple[str, ...]:
    """Split a catalog artist credit such as ``"A, B & C"`` into its artists."""

    parts = [part.strip() for part in _ARTIST_SEPARATORS.split(value) if part.strip()]
    return tuple(parts) if parts else (value.strip(),)


def primary_artist(value: str) -> str:
    return split_artists(value)[0]


def artist_credit_includes(credit: str, artist: str) -> bool:
    """True when ``artist`` is one of the credited artists (script variants folded)."""

    return any(same_catalog_name(part, artist) for part in split_artists(credit)) or (
        same_catalog_name(credit, artist)
    )


def artist_named_in_query(query: str, credit: str) -> bool:
    """True when a credited artist is literally named in ``query`` (script variants folded)."""

    folded_query = canonical_name(query)
    for part in split_artists(credit):
        name = canonical_name(part)
        if len(name) < 2:
            continue
        if name.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", folded_query):
                return True
        elif name in folded_query:
            return True
    return False


class PoolEntry(BaseModel):
    """One catalog track confirmed playable.  ``track_ref`` is its stable identity."""

    model_config = ConfigDict(frozen=True)

    track_ref: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    primary_artist: str = Field(min_length=1, max_length=300)
    duration_seconds: int = Field(gt=0)
    version_kind: VersionKind
    source: PoolSource

    def resolved_track(self) -> ResolvedTrack:
        return ResolvedTrack(
            track_ref=self.track_ref,
            canonical_artist=self.artist[:120],
            canonical_title=self.title[:160],
        )


class CandidateOutcome(BaseModel):
    """What happened to one examined candidate; safe to log (no provider URLs)."""

    model_config = ConfigDict(frozen=True)

    source: PoolSource
    artist: str
    title: str
    status: AvailabilityStatus
    track_ref: str | None = None


class CatalogPool(BaseModel):
    entries: list[PoolEntry] = Field(default_factory=list)
    outcomes: list[CandidateOutcome] = Field(default_factory=list)
    verification_count: int = 0
    search_failure_count: int = 0
    # Why catalog calls failed, by "provider:ExceptionClass"; lets an outage, a refused
    # credential and a rate limit be told apart without reading provider messages.
    failure_kinds: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: int = 0
    truncated: bool = False

    def by_source(self, source: PoolSource) -> list[PoolEntry]:
        return [entry for entry in self.entries if entry.source is source]

    def count(self, status: AvailabilityStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)

    def find(self, artist: str, title: str) -> PoolEntry | None:
        """The entry for a Curator-chosen track: credited to ``artist`` with the same title."""

        for entry in self.entries:
            if same_catalog_name(entry.title, title) and artist_credit_includes(
                entry.artist, artist
            ):
                return entry
        return None

    def listing(
        self, *, max_entries: int = 40, max_per_artist: int = 3, max_per_anchor_artist: int = 6
    ) -> list[PoolEntry]:
        """Entries offered to the Curator, most trusted first, with a per-artist cap.

        Artists named by the listener (``ARTIST_SEARCH`` entries) get a higher cap so a
        career-focused programme can still stay on that artist.  The cap is enforced here,
        in code, so the Curator can never choose more tracks by one artist than allowed.
        """

        anchors = {
            canonical_name(entry.primary_artist)
            for entry in self.entries
            if entry.source is PoolSource.ARTIST_SEARCH
        }
        ranked = sorted(
            enumerate(self.entries), key=lambda pair: (_SOURCE_ORDER[pair[1].source], pair[0])
        )
        # A keyword hit that only repeats a trusted entry's song under another artist is a
        # cover or re-release of it; do not offer it as a second song.
        trusted_songs = {
            base_title_key(entry.title)
            for entry in self.entries
            if entry.source is not PoolSource.KEYWORD_SEARCH
        }
        counts: dict[str, int] = {}
        listed: list[PoolEntry] = []
        for _index, entry in ranked:
            if (
                entry.source is PoolSource.KEYWORD_SEARCH
                and base_title_key(entry.title) in trusted_songs
            ):
                continue
            artist = canonical_name(entry.primary_artist)
            cap = max_per_anchor_artist if artist in anchors else max_per_artist
            if counts.get(artist, 0) >= cap:
                continue
            counts[artist] = counts.get(artist, 0) + 1
            listed.append(entry)
            if len(listed) >= max_entries:
                break
        return listed

    def unavailable(self, limit: int = 12) -> list[dict[str, str]]:
        """Known unplayable tracks, so the Curator does not propose them again."""

        return [
            {"artist": outcome.artist, "title": outcome.title}
            for outcome in self.outcomes
            if outcome.status is AvailabilityStatus.UNPLAYABLE
        ][:limit]

    def unplayable_artists(self) -> list[str]:
        """Primary artists with candidates that exist in the catalog but cannot be played."""

        seen: dict[str, str] = {}
        for outcome in self.outcomes:
            if outcome.status is AvailabilityStatus.UNPLAYABLE:
                name = primary_artist(outcome.artist)
                seen.setdefault(canonical_name(name), name)
        return sorted(seen.values())

    def summary(self) -> dict[str, object]:
        """Counts only, for logs and reviews."""

        return {
            "entries": len(self.entries),
            "by_source": {source.value: len(self.by_source(source)) for source in PoolSource},
            "outcomes": {status.value: self.count(status) for status in AvailabilityStatus},
            "verification_count": self.verification_count,
            "search_failure_count": self.search_failure_count,
            "failure_kinds": dict(sorted(self.failure_kinds.items())),
            "elapsed_ms": self.elapsed_ms,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class PoolBuildConfig:
    """Bounds on catalog work.  Initial values come from the 2026-10-08 experiment."""

    max_verifications: int = 24
    concurrency: int = 3
    search_limit: int = 10
    max_keyword_entries: int = 8
    max_refs_per_song: int = 3
    timeout_seconds: float = 45.0
    excluded_versions: frozenset[VersionKind] = field(default=_DEFAULT_EXCLUDED_VERSIONS)

    def __post_init__(self) -> None:
        if self.max_verifications < 0:
            raise ValueError("max_verifications must not be negative")
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self.search_limit < 1:
            raise ValueError("search_limit must be at least 1")
        if self.max_refs_per_song < 1:
            raise ValueError("max_refs_per_song must be at least 1")
        if self.max_keyword_entries < 0:
            raise ValueError("max_keyword_entries must not be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass
class _Verified:
    """Result of examining one candidate; plain fields so unresolved proposals fit too."""

    source: PoolSource
    status: AvailabilityStatus
    artist: str
    title: str
    track_ref: str | None = None
    key: str = ""
    version_kind: VersionKind = VersionKind.UNKNOWN
    duration_seconds: int = 0

    @classmethod
    def of(
        cls,
        track: RetrievedTrack,
        source: PoolSource,
        status: AvailabilityStatus,
        duration_seconds: int = 0,
    ) -> _Verified:
        return cls(
            source=source,
            status=status,
            artist=track.artist,
            title=track.title,
            track_ref=track.track_ref,
            key=_song_key(track),
            version_kind=track.version_kind,
            duration_seconds=duration_seconds,
        )


def _song_key(track: RetrievedTrack) -> str:
    """Identity of a song across catalog entries: credited artists as a set, title without
    a trailing ``(feat. X)``, and the version kind.  ``A, B`` and ``B, A`` are one credit."""

    artists = sorted({canonical_name(part) for part in split_artists(track.artist)})
    return "|".join(
        (
            "/".join(artists),
            canonical_name(without_feature_credit(track.base_title or track.title)),
            track.version_kind.value,
        )
    )


class CatalogPoolBuilder:
    """Build a :class:`CatalogPool` with bounded, deterministic catalog calls."""

    def __init__(
        self, retrieval: MusicRetrievalService, config: PoolBuildConfig | None = None
    ) -> None:
        self.retrieval = retrieval
        self.config = config or PoolBuildConfig()

    async def build(
        self,
        *,
        proposals: Sequence[TrackProposal] = (),
        artist_queries: Sequence[str] = (),
        keyword_queries: Sequence[str] = (),
    ) -> CatalogPool:
        """Examine candidates from three sources, most trusted first.

        * ``proposals``: LLM-named tracks; must match a catalog track exactly (script
          variants folded) and be playable.
        * ``artist_queries``: artists the programme is centred on; only tracks credited
          to that artist are kept (covers and tribute artists are dropped).
        * ``keyword_queries``: topic keywords; filler only, capped.

        On timeout the pool built so far is returned with ``truncated=True``.
        """

        started = perf_counter()
        pool = CatalogPool()
        state = _BuildState(semaphore=asyncio.Semaphore(self.config.concurrency))
        try:
            await asyncio.wait_for(
                self._build(pool, state, proposals, artist_queries, keyword_queries),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError:
            pool.truncated = True
        self._finalize(pool, state)
        pool.elapsed_ms = int((perf_counter() - started) * 1000)
        return pool

    async def _build(
        self,
        pool: CatalogPool,
        state: _BuildState,
        proposals: Sequence[TrackProposal],
        artist_queries: Sequence[str],
        keyword_queries: Sequence[str],
    ) -> None:
        # Stage 1: LLM-named tracks (bounded by the caller's proposal count).
        async def examine(index: int, proposal: TrackProposal) -> None:
            state.record((0, index), await self._resolve_proposal(proposal, state))

        await asyncio.gather(*(examine(i, proposal) for i, proposal in enumerate(proposals)))

        # Stage 2: searches for the other two sources, run concurrently.
        artist_batches, keyword_batches = await asyncio.gather(
            self._search_all(artist_queries, state),
            self._search_all(keyword_queries, state),
        )
        candidates: list[tuple[RetrievedTrack, PoolSource]] = []
        for artist, tracks in zip(artist_queries, artist_batches, strict=True):
            candidates.extend(
                (track, PoolSource.ARTIST_SEARCH)
                for track in tracks
                if artist_credit_includes(track.artist, artist)
            )
        for query, tracks in zip(keyword_queries, keyword_batches, strict=True):
            # A keyword query that names an artist ("椎名林檎") is also an artist search:
            # tracks credited to that artist are trusted like an explicit artist query.
            candidates.extend(
                (
                    track,
                    PoolSource.ARTIST_SEARCH
                    if artist_named_in_query(query, track.artist)
                    else PoolSource.KEYWORD_SEARCH,
                )
                for track in tracks
            )
        candidates.sort(key=lambda item: item[1] is not PoolSource.ARTIST_SEARCH)

        # Stage 3: group candidates by song (one song often has several catalog entries,
        # not all playable), then verify within the budget in deterministic order.
        groups: dict[str, list[tuple[RetrievedTrack, PoolSource]]] = {}
        for track, source in candidates:
            key = _song_key(track)
            if track.version_kind in self.config.excluded_versions or key in state.examined:
                continue
            groups.setdefault(key, []).append((track, source))
        songs = list(groups.values())[: self.config.max_verifications]

        async def verify_song(index: int, entries: list[tuple[RetrievedTrack, PoolSource]]) -> None:
            state.record((1, index), await self._verify_song(entries, state))

        await asyncio.gather(*(verify_song(i, entries) for i, entries in enumerate(songs)))

    async def _verify_song(
        self, entries: list[tuple[RetrievedTrack, PoolSource]], state: _BuildState
    ) -> _Verified:
        """Try a song's catalog entries in order until one is confirmed playable."""

        last: _Verified | None = None
        for track, source in entries[: self.config.max_refs_per_song]:
            verified = await self._verify(track, source, state)
            if verified.status is AvailabilityStatus.PLAYABLE:
                return verified
            # A provider error is not evidence of unavailability; keep it over "unplayable".
            if last is None or verified.status is AvailabilityStatus.PROVIDER_ERROR:
                last = verified
        assert last is not None  # entries is never empty
        return last

    async def _search_all(
        self, queries: Sequence[str], state: _BuildState
    ) -> list[list[RetrievedTrack]]:
        async def one(query: str) -> list[RetrievedTrack]:
            async with state.semaphore:
                report = await self.retrieval.search_report(query, limit=self.config.search_limit)
            state.search_failures += len(report.failures)
            state.note_failures(report.failures)
            return list(report.candidates)

        return list(await asyncio.gather(*(one(query) for query in queries)))

    async def _resolve_proposal(self, proposal: TrackProposal, state: _BuildState) -> _Verified:
        """Find the exact catalog track for an LLM proposal and verify it."""

        queries = [f"{proposal.artist} {proposal.title}"]
        if proposal.title != queries[0]:
            queries.append(proposal.title)
        exact: list[RetrievedTrack] = []
        search_failed = False
        for query in queries:
            async with state.semaphore:
                report = await self.retrieval.search_report(
                    query,
                    requested_artist=proposal.artist,
                    requested_title=proposal.title,
                    limit=self.config.search_limit,
                )
            state.search_failures += len(report.failures)
            state.note_failures(report.failures)
            search_failed = search_failed or bool(report.failures)
            exact = [
                track
                for track in report.candidates
                if track.track_ref.startswith(f"{track.provider}:")
                and same_catalog_name(track.artist, proposal.artist)
                and same_catalog_name(track.title, proposal.title)
            ]
            if exact:
                break
        if not exact:
            # A failed search is an outage, not evidence the track is missing from the catalog.
            return _Verified(
                source=PoolSource.LLM_CANDIDATE,
                status=(
                    AvailabilityStatus.PROVIDER_ERROR
                    if search_failed
                    else AvailabilityStatus.NOT_FOUND
                ),
                artist=proposal.artist,
                title=proposal.title,
            )
        last = _Verified.of(exact[0], PoolSource.LLM_CANDIDATE, AvailabilityStatus.UNPLAYABLE)
        for track in exact[: self.config.max_refs_per_song]:
            verified = await self._verify(track, PoolSource.LLM_CANDIDATE, state)
            if verified.status is AvailabilityStatus.PLAYABLE:
                return verified
            if verified.status is AvailabilityStatus.PROVIDER_ERROR:
                last = verified
        return last

    async def _verify(
        self, track: RetrievedTrack, source: PoolSource, state: _BuildState
    ) -> _Verified:
        async with state.semaphore:
            state.verifications += 1
            try:
                metadata = await self.retrieval.registry.resolve_track(
                    ResolvedTrack(
                        track_ref=track.track_ref,
                        canonical_artist=track.artist[:120],
                        canonical_title=track.title[:160],
                    )
                )
            except (ProviderError, ValueError) as error:
                state.note_failure(f"{track.provider}:{type(error).__name__}")
                return _Verified.of(track, source, AvailabilityStatus.PROVIDER_ERROR)
        if metadata.playable and metadata.duration_seconds > 0:
            return _Verified.of(
                track, source, AvailabilityStatus.PLAYABLE, metadata.duration_seconds
            )
        return _Verified.of(track, source, AvailabilityStatus.UNPLAYABLE)

    def _finalize(self, pool: CatalogPool, state: _BuildState) -> None:
        keyword_entries = 0
        for _order, item in sorted(state.items, key=lambda pair: pair[0]):
            pool.outcomes.append(
                CandidateOutcome(
                    source=item.source,
                    artist=item.artist,
                    title=item.title,
                    status=item.status,
                    track_ref=item.track_ref,
                )
            )
            if item.status is not AvailabilityStatus.PLAYABLE or item.track_ref is None:
                continue
            key = item.key
            if key in state.accepted:
                continue
            if item.source is PoolSource.KEYWORD_SEARCH:
                if keyword_entries >= self.config.max_keyword_entries:
                    continue
                keyword_entries += 1
            state.accepted.add(key)
            pool.entries.append(
                PoolEntry(
                    track_ref=item.track_ref,
                    artist=item.artist,
                    title=item.title,
                    primary_artist=primary_artist(item.artist),
                    duration_seconds=item.duration_seconds,
                    version_kind=item.version_kind,
                    source=item.source,
                )
            )
        pool.verification_count = state.verifications
        pool.search_failure_count = state.search_failures
        pool.failure_kinds = dict(state.failure_kinds)


@dataclass
class _BuildState:
    semaphore: asyncio.Semaphore
    items: list[tuple[tuple[int, int], _Verified]] = field(default_factory=list)
    examined: set[str] = field(default_factory=set)
    accepted: set[str] = field(default_factory=set)
    verifications: int = 0
    search_failures: int = 0
    failure_kinds: dict[str, int] = field(default_factory=dict)

    def note_failure(self, kind: str) -> None:
        self.failure_kinds[kind] = self.failure_kinds.get(kind, 0) + 1

    def note_failures(self, failures: Sequence[RetrievalFailure]) -> None:
        for failure in failures:
            self.note_failure(f"{failure.provider}:{failure.error_type or failure.kind}")

    def record(self, order: tuple[int, int], item: _Verified) -> None:
        """Store a finished result under its input position, so output order is stable."""

        self.items.append((order, item))
        if item.key:
            self.examined.add(item.key)

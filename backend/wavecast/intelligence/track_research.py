"""Research bound to the recordings that actually play, and the points a chapter may talk about.

Programme-level research is organised around the request, before the route exists.  Once a
track is on the route, the Writer needs material about *that* recording: where the piece comes
from, who made it, what it belongs to.  Without it, the Writer fills the gap from memory, which
is where the wrong credits came from.  For each chapter's track this service

1. keeps the evidence already gathered that is about the track (it names the title, its Chinese
   title or its album; an artist's name alone does not make a page about a song);
2. searches for what is missing, once per album when the catalog names one (a film's soundtrack
   serves every track on it) and otherwise once per track, within a small per-station budget;
3. asks one short model call for up to two *talking points* about the work, each with the source
   and a quote, and checks the quotes in code; only points found in a source survive.

The Writer is then given those verified points to build the talk around.  When there are none
it is told to say no facts about the song rather than fill the gap.  Everything degrades: no
search result, a failed call or an unmatched quote leaves a chapter with less to say, never a
broken programme.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha1

from pydantic import BaseModel, Field, field_validator

from wavecast.narration_quality import durations_in, years_in
from wavecast.providers.contracts import SearchProvider
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.stations import StationId
from wavecast.text_identity import base_title_key, to_simplified

from .fact_support import (
    _IGNORED,
    _TITLE_IN_BRACKETS,
    _squash,
    credited_people,
    people_missing_from_quote,
    quote_backs_roles,
    quote_in_source,
    roles_in,
)
from .fast_start import FastStructuredProvider
from .models import Evidence, ResolvedTrack
from .research import (
    DEEP_EXCERPT_CHARS,
    STANDARD_EXCERPT_CHARS,
    _source_metadata,
    canonicalize_url,
    normalize_results,
)

logger = logging.getLogger(__name__)

# Searches allowed per chapter.  Stations that tell stories get a second, differently worded
# query when the first one produced nothing to say; the rest of the stations talk too little to
# justify the lookups.
SEARCH_BUDGET: dict[StationId, int] = {
    StationId.PORTRAIT: 2,
    StationId.LINEAGE: 2,
    StationId.CRATE: 1,
}
DEEP_STATIONS = frozenset({StationId.PORTRAIT, StationId.LINEAGE})
# Stations whose programme is about a person: a chapter with nothing checkable about its song may
# tell one of the programme's background stories instead.
BACKGROUND_STATIONS = frozenset({StationId.PORTRAIT})
_MAX_STORIES = 3
_STORY_SOURCES = 12
_STORY_SOURCE_CHARS = 900
_MAX_POINTS = 2
_RESULTS_PER_QUERY = 5
_MIN_IDENTIFIER_CHARS = 3
_SHORT_ASCII_TITLE = 8
_CACHE_EPISODES = 32
_CATALOGUE_TRIVIA = re.compile(r"曲目编号|第\s*\d+\s*(?:首|轨)|编号\s*\d+|track\s*(?:no|number)|\bNo\.?\s*\d+", re.IGNORECASE)
_CREDIT_ROLES = frozenset({"composer", "arranger", "score", "lyricist", "vocal", "instrumental", "creation", "cast", "director"})
_VERSION_MARKER = re.compile(r"\((?:live|remix|piano|instrumental|[^)]*版)[^)]*\)|（[^）]*版[^）]*）", re.IGNORECASE)


class TalkingPoint(BaseModel):
    """One statement that a source states, with the proof.

    ``scope`` says what it is about: the recording itself (``track``), the album / film it
    belongs to (``album``), or the person and period the programme is about (``background``).
    What a source says about the album is shared by its tracks; what it says about one song is
    that song's alone; background is told once, as a story, and is never about a song.
    """

    text: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=300)
    scope: str = Field(default="track", pattern="^(track|album|background)$")


class _RawPoint(BaseModel):
    text: str = ""
    source: str = ""
    quote: str = ""
    scope: str = "track"

    @field_validator("scope", mode="before")
    @classmethod
    def _scope(cls, value: object) -> str:
        return "album" if str(value or "").strip().lower() == "album" else "track"

    @field_validator("text", "source", "quote", mode="before")
    @classmethod
    def _clip(cls, value: object) -> str:
        return str(value or "")[:300]


class _Briefing(BaseModel):
    points: list[_RawPoint] = Field(default_factory=list, max_length=6)


@dataclass
class TrackResearch:
    """What the chapter may be written from; ``evidence`` holds only newly found items."""

    evidence: list[Evidence] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    points: list[TalkingPoint] = field(default_factory=list)
    searches: int = 0


# --- is this page about this recording? --------------------------------------------------------


def _primary_artist(credit: str) -> str:
    # Imported here: catalog_pool depends on the intelligence package this module belongs to.
    from wavecast.catalog_pool import primary_artist

    return primary_artist(credit)


def _identifiers(track: ResolvedTrack) -> list[str]:
    names = [track.canonical_title, base_title_key(track.canonical_title), track.spoken_title or ""]
    found = [_squash(name) for name in names if name]
    if track.album:
        found.append(_squash(track.album))
    unique: list[str] = []
    for item in found:
        if len(item) >= _MIN_IDENTIFIER_CHARS and item not in unique:
            unique.append(item)
    return unique


def mentions_track(text: str, track: ResolvedTrack) -> bool:
    """True when ``text`` names the recording's title, its Chinese title or its album.

    An artist's name alone is not enough: a page about the artist is not about this song.  A
    short Latin title ("Home", "Time") appears everywhere, so it counts only next to the artist.
    """

    squashed = _squash(text)
    artist = _squash(_primary_artist(track.canonical_artist))
    title_ascii = track.canonical_title.isascii()
    for identifier in _identifiers(track):
        if identifier not in squashed:
            continue
        is_title = identifier != _squash(track.album or "\0")
        if is_title and title_ascii and len(identifier) < _SHORT_ASCII_TITLE:
            if artist and artist in squashed:
                return True
            continue
        return True
    return False


def mentions_title(text: str, track: ResolvedTrack) -> bool:
    """True when ``text`` names the recording's title (original or Chinese), not just its album."""

    squashed = _squash(text)
    titles = [track.canonical_title, base_title_key(track.canonical_title), track.spoken_title or ""]
    for name in titles:
        key = _squash(name)
        if len(key) < _MIN_IDENTIFIER_CHARS or key not in squashed:
            continue
        if name.isascii() and len(key) < _SHORT_ASCII_TITLE:
            artist = _squash(_primary_artist(track.canonical_artist))
            if not artist or artist not in squashed:
                continue
        return True
    return False


def _album_key(track: ResolvedTrack) -> str:
    return "album:" + _squash(track.album) if track.album else "track:" + track.track_ref


def _queries(track: ResolvedTrack) -> list[str]:
    artist = _primary_artist(track.canonical_artist)
    title = _VERSION_MARKER.sub("", track.canonical_title).strip() or track.canonical_title
    name = f"{title} {track.spoken_title}" if track.spoken_title else title
    # The album query does not name the artist, so every track of the album asks the same
    # question and the search is done once.
    first = (
        f"{track.album} 曲目 作曲 创作背景" if track.album else f"{artist} {name} 创作背景 作曲 来源"
    )
    return [first, f"{artist} {name} 歌曲 电影 专辑 作曲 编曲 简介"]


# --- the model call ----------------------------------------------------------------------------

_PROMPT = """You prepare ONE radio chapter about ONE recording. Use ONLY the sources below; never use \
your own knowledge. If the sources do not say it, it is not a point.

Recording: “{title}”{zh}{album}. The catalog credits {artist} as performer on this recording; that is a \
performer credit, not a statement about who composed, wrote or arranged the piece.
Programme subject: {subject}.

Sources (id: text):
{sources}

Give up to {limit} talking points that a host could say about THIS work or recording, most interesting \
first: where the piece comes from (film, album, event), who composed / arranged / wrote / sang it as the \
source states, how it was made, how this version relates to the original. Say in "scope" what a point \
is about: "track" when it is about this very recording or work, "album" when it is about the \
album, film or event it belongs to (never about the song itself). Each point is one short \
statement in Simplified Chinese (at most 80 characters) that one source states, with that source's id and a quote \
copied word for word, in the source's own script and without translating (at most 60 characters). The \
quote must itself say what the point says, including who did what, and must include the work's name \
whenever the source gives it next to that statement. In the point itself call the recording 这首歌 or \
它: never write or translate its title. Other works (a film, an album) may be named in 《》 as the \
sources name them. When a source says a credit belongs to a particular version (a single, a \
soundtrack cut, a cover), the point must say which version or be left out. If a source is about a different \
song, a different version, or only about the artist in general, it supports no point. Prefer a story a listener would \
remember (why it was made, what it was for, who it was made with, where it sits in the film) over \
catalogue data: give no track numbers, running times, catalogue numbers or release formats. Return an \
empty list when nothing qualifies.

Return JSON {{"points": [{{"text": "...", "source": "id", "quote": "...", "scope": "track|album"}}]}}."""


class TrackResearchService:
    """Finds and checks what can be said about a chapter's track; see the module docstring."""

    def __init__(
        self,
        *,
        search: SearchProvider,
        llm: FastStructuredProvider,
        deep_search: SearchProvider | None = None,
        profile: InferenceProfile = InferenceProfile.FAST,
    ) -> None:
        self._search = search
        self._deep = deep_search
        self._llm = llm
        self._profile = profile
        self._found: OrderedDict[str, dict[str, list[Evidence]]] = OrderedDict()
        self._asked: dict[str, set[str]] = {}
        self._background: dict[str, list[TalkingPoint]] = {}
        self._chapters: dict[str, int] = {}

    def enabled_for(self, station: StationId | None) -> bool:
        return station in SEARCH_BUDGET

    async def prepare(
        self,
        *,
        episode_id: str,
        track: ResolvedTrack,
        evidence: Sequence[Evidence],
        station: StationId | None,
        subject: str,
        subject_names: Sequence[str] = (),
    ) -> TrackResearch | None:
        """None when this station does not research tracks; otherwise what the chapter may use."""

        if station is None or station not in SEARCH_BUDGET:
            return None
        budget = SEARCH_BUDGET[station]
        per_episode = self._found.setdefault(episode_id, {})
        self._found.move_to_end(episode_id)
        while len(self._found) > _CACHE_EPISODES:
            dropped, _ = self._found.popitem(last=False)
            self._asked.pop(dropped, None)
            self._chapters.pop(dropped, None)
            self._background.pop(dropped, None)
        key = _album_key(track)
        known_ids = {item.id for item in evidence}

        def about_track() -> list[Evidence]:
            pool = [*evidence, *per_episode.get(key, [])]
            seen: set[str] = set()
            result: list[Evidence] = []
            for item in pool:
                if item.id in seen or not mentions_track(f"{item.source_title}\n{item.claim_or_excerpt}", track):
                    continue
                seen.add(item.id)
                result.append(item)
            return result

        outcome = TrackResearch()
        queries = _queries(track)
        for round_number in range(budget + 1):
            candidates = about_track()
            if candidates:
                outcome.points = await self._brief(track, subject, candidates, subject_names)
                if outcome.points:
                    break
            if outcome.searches >= budget:
                break
            asked = self._asked.setdefault(episode_id, set())
            query = next((item for item in queries if item not in asked), None)
            if query is None:
                break  # everything worth asking about this track has been asked
            asked.add(query)
            fresh = await self._find(query, track, station)
            outcome.searches += 1
            if fresh:
                per_episode.setdefault(key, []).extend(
                    item for item in fresh if item.id not in {e.id for e in per_episode.get(key, [])}
                )
        used = about_track()
        if station in BACKGROUND_STATIONS:
            # A portrait is about a person: every other chapter (and any with nothing checkable
            # about its song) tells one of the programme's background stories, each once, so
            # the talk is not only catalogue notes on the songs.
            number = self._chapters[episode_id] = self._chapters.get(episode_id, 0) + 1
            if number % 2 == 0 or not outcome.points:
                story = await self._next_background(episode_id, subject, subject_names, evidence)
                if story is not None:
                    outcome.points = [story]
        outcome.evidence_ids = [item.id for item in used]
        outcome.evidence_ids.extend(
            point.evidence_id for point in outcome.points if point.evidence_id not in outcome.evidence_ids
        )
        outcome.evidence = [item for item in used if item.id not in known_ids]
        logger.info(
            "track_research searches=%d bound=%d new=%d points=%d",
            outcome.searches,
            len(used),
            len(outcome.evidence),
            len(outcome.points),
        )
        return outcome

    async def background_story(
        self, *, episode_id: str, station: StationId | None, subject: str, subject_names: Sequence[str], evidence: Sequence[Evidence]
    ) -> TalkingPoint | None:
        """An untold background story for a chapter whose own material came to nothing."""

        if station not in BACKGROUND_STATIONS:
            return None
        return await self._next_background(episode_id, subject, subject_names, evidence)

    async def _next_background(
        self, episode_id: str, subject: str, names: Sequence[str], evidence: Sequence[Evidence]
    ) -> TalkingPoint | None:
        """The next story about the person or period that this programme has not told yet."""

        if episode_id not in self._background:
            self._background[episode_id] = await self._stories(subject, names, evidence)
            logger.info("background_stories found=%d", len(self._background[episode_id]))
        remaining = self._background[episode_id]
        return remaining.pop(0) if remaining else None

    async def _stories(
        self, subject: str, names: Sequence[str], evidence: Sequence[Evidence]
    ) -> list[TalkingPoint]:
        general = [item for item in evidence if not item.track_refs][:_STORY_SOURCES]
        if not general:
            return []
        sources = {item.id: item.claim_or_excerpt[:_STORY_SOURCE_CHARS] for item in general}
        prompt = _STORY_PROMPT.format(
            subject=subject or "(none)",
            sources="\n".join(f"[{source_id}]: {text}" for source_id, text in sources.items()),
            limit=_MAX_STORIES,
        )
        try:
            result = await self._llm.structured(
                prompt,
                _Stories,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.SYNTHESIS,
                stage="background_brief",
            )
        except Exception as error:  # noqa: BLE001 - background is optional
            logger.warning("background_brief_unavailable error_type=%s", type(error).__name__)
            return []
        if not isinstance(result, _Stories):
            return []
        return verified_stories(result.stories, sources, names)

    async def _find(self, query: str, track: ResolvedTrack, station: StationId) -> list[Evidence]:
        deep = station in DEEP_STATIONS and self._deep is not None
        provider = self._deep if deep and self._deep is not None else self._search
        try:
            results = await provider.search(query, limit=_RESULTS_PER_QUERY, stage="track_research")
        except Exception as error:  # noqa: BLE001 - research is best effort
            logger.warning("track_research_search_failed error_type=%s", type(error).__name__)
            return []
        excerpt = DEEP_EXCERPT_CHARS if deep else STANDARD_EXCERPT_CHARS
        found: list[Evidence] = []
        for result in normalize_results(results, excerpt_chars=excerpt):
            url = canonicalize_url(result.url)
            text = result.content or result.snippet or result.title
            if not mentions_track(f"{result.title}\n{text}", track):
                continue
            domain, category = _source_metadata(url)
            found.append(
                Evidence(
                    id="evidence-"
                    + sha1((url or f"{result.provider}:{result.title.casefold()}:{query.casefold()}").encode()).hexdigest()[:12],
                    claim_or_excerpt=text[:excerpt],
                    source_url=url,
                    canonical_url=url,
                    source_domain=domain,
                    source_category=category,
                    source_provider=result.provider,
                    confidence=result.score if result.score is not None else 0.5,
                    query=query,
                    source_title=result.title,
                    track_refs=[track.track_ref],
                )
            )
        return found

    async def _brief(
        self,
        track: ResolvedTrack,
        subject: str,
        candidates: Sequence[Evidence],
        people: Sequence[str] = (),
    ) -> list[TalkingPoint]:
        chosen = list(candidates[:6])
        sources = {item.id: item.claim_or_excerpt for item in chosen}
        leads = {item.id: f"{item.source_title}\n{item.claim_or_excerpt[:150]}" for item in chosen}
        prompt = _PROMPT.format(
            title=track.canonical_title,
            zh=f" (Chinese title in the catalog: {track.spoken_title})" if track.spoken_title else "",
            album=f", on the album “{track.album}”" if track.album else "",
            artist=track.canonical_artist,
            subject=subject or "(none)",
            sources="\n".join(f"[{source_id}]: {text}" for source_id, text in sources.items()),
            limit=_MAX_POINTS,
        )
        try:
            result = await self._llm.structured(
                prompt,
                _Briefing,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=self._profile,
                stage="track_brief",
            )
        except Exception as error:  # noqa: BLE001 - a missing briefing means less to say
            logger.warning("track_brief_unavailable error_type=%s", type(error).__name__)
            return []
        if not isinstance(result, _Briefing):
            return []
        return verified_points(result.points, sources, track, leads, people)


class _Stories(BaseModel):
    stories: list[_RawPoint] = Field(default_factory=list, max_length=6)


_STORY_PROMPT = """You prepare background stories for a radio programme about: {subject}. Use ONLY the \
sources below; never use your own knowledge.

Sources (id: text):
{sources}

Give up to {limit} DIFFERENT stories a host could tell in two or three short sentences about the \
person or the period: something that happened to them, a working relationship, a turning point, how a \
famous collaboration or work came about. Each story is about a different event (not the same event in \
other words, and not three facts about one moment) and, where possible, comes from a different source. \
Each is one self-contained statement in Simplified Chinese (at most 120 characters) with the source id \
and a quote copied word for word, in the source's own script and without translating (at most 80 \
characters), that states its main fact. Do not write about a particular song and do not call anything \
"this song"; no track numbers, running times or catalogue data. Return an empty list if the sources \
hold none.

Return JSON {{"stories": [{{"text": "...", "source": "id", "quote": "..."}}]}}."""

_ABOUT_A_SONG = re.compile(r"这首|这支曲|这段旋律|这张专辑|该曲|本曲")


def verified_stories(
    raw: Sequence[_RawPoint], sources: dict[str, str], subject_names: Sequence[str] = ()
) -> list[TalkingPoint]:
    """Background stories whose quote is in the named source and that can stand on their own.

    The same code checks as for song facts (verbatim quote, the claimed role stated, years and
    works found in the sources), plus: a story may not point at "this song", it must be about
    the programme's subject when one is known, and two stories may not tell the same thing.
    """

    everything = _squash("\n".join(sources.values()))
    wanted = [_squash(name) for name in subject_names if _squash(name)]
    stories: list[TalkingPoint] = []
    for item in raw:
        text, source_id, quote = item.text.strip(), item.source.strip(), item.quote.strip()
        source = sources.get(source_id, "")
        if not text or not source or not quote_in_source(quote, source):
            continue
        if _ABOUT_A_SONG.search(text) or _CATALOGUE_TRIVIA.search(text) or durations_in(text):
            continue
        roles = roles_in(text)
        if roles and not quote_backs_roles(quote, roles):
            continue
        if roles and people_missing_from_quote(text, quote, credited_people(subject_names)):
            continue
        if years_in(text) - years_in(source):
            continue
        if wanted and not any(name in _squash(f"{text}{quote}") for name in wanted):
            continue
        if any(_squash(name) not in everything for name in _TITLE_IN_BRACKETS.findall(text)):
            continue
        simplified = to_simplified(text)[:200]
        if any(_similar(simplified, other.text) for other in stories):
            continue
        stories.append(
            TalkingPoint(text=simplified, evidence_id=source_id, quote=quote[:300], scope="background")
        )
        if len(stories) == _MAX_STORIES:
            break
    return stories


def _similar(left: str, right: str) -> bool:
    """Two statements that overlap by half or more of the shorter one tell the same thing."""

    def grams(value: str) -> set[str]:
        squashed = _squash(value)
        return {squashed[i : i + 2] for i in range(len(squashed) - 1)}

    a, b = grams(left), grams(right)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.5


def verified_points(
    raw: Sequence[_RawPoint],
    sources: dict[str, str],
    track: ResolvedTrack | None = None,
    leads: dict[str, str] | None = None,
    people: Sequence[str] = (),
) -> list[TalkingPoint]:
    """The points whose quote is in the named source, speaks of the claimed role and the work.

    * the quote must be a verbatim stretch of that source;
    * a claimed role (composed, arranged, sang, wrote the words...) must be stated, as that role,
      in the quote, and the line must be about this work: the quote names it, or the page is
      about it (its title or opening names it), so a track list's other rows cannot be borrowed;
    * a work named in 《》 must be named somewhere in the sources (an invented title is dropped);
      the recording's own titles count when a source about the recording names it.
    """

    everything = _squash("\n".join(sources.values()))
    own = {_squash(name) for name in (track.canonical_title, track.spoken_title or "") if name} if track else set()
    points: list[TalkingPoint] = []
    for item in raw:
        text, source_id, quote = item.text.strip(), item.source.strip(), item.quote.strip()
        source = sources.get(source_id, "")
        if not text or not source or not quote_in_source(quote, source):
            continue
        if _CATALOGUE_TRIVIA.search(text) or durations_in(text):
            continue  # track numbers and running times are catalogue data, not a story
        roles = roles_in(text)
        if roles and not quote_backs_roles(quote, roles):
            continue
        if roles and track is not None and people_missing_from_quote(
            text, quote, credited_people([track.canonical_artist, *people])
        ):
            continue  # the right role, but the line does not name the person the point credits
        if item.scope == "album" and roles & _CREDIT_ROLES:
            continue  # who composed, arranged or sang is a statement about one song
        if track is not None:
            line = f"{quote}\n{(leads or {}).get(source_id, '')}"
            if item.scope == "album":
                # Background about the album or film: the line (or the page) must be about it.
                if not track.album or _squash(track.album) not in _squash(line):
                    continue
            elif not (
                mentions_title(quote, track) or mentions_title((leads or {}).get(source_id, ""), track)
            ):
                # About the song itself: the line, or a page about it, must name this song.
                # A page about the album or another track cannot speak for this one.
                continue
        if years_in(text) - years_in(source):
            continue  # a year the source does not contain
        names_ok = True
        for name in _TITLE_IN_BRACKETS.findall(text):
            key = _squash(name)
            if key in everything:
                continue
            if key in own and track is not None and mentions_track(source, track):
                continue
            names_ok = False
        if not names_ok:
            continue
        if _IGNORED.sub("", text) in {_IGNORED.sub("", p.text) for p in points}:
            continue
        points.append(
            TalkingPoint(
                text=to_simplified(text)[:200], evidence_id=source_id, quote=quote[:300], scope=item.scope
            )
        )
        if len(points) == _MAX_POINTS:
            break
    return points

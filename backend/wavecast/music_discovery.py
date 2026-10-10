"""Finding music for a request without asking a model to remember it.

A request such as "想听点后摇" is a genre, not a song.  Searching the catalog with the whole
sentence returns whatever happens to contain those characters; searching with the genre word
returns the genre's artists.  This module is the deterministic half of discovery:

* ``catalog_queries`` turns a request into a few short catalog queries (the genre in the
  request's own words and in the catalog's usual English, with the rest of the request kept
  so a region, a work or a listening constraint is not lost);
* ``artist_scores`` ranks the artists those searches return.

The ranking is a *ranking*, not a verdict.  An artist found by several queries or named in
independent web research ranks higher, but one search system answering several phrasings is
not independent evidence, so nothing here decides who is "core" and nothing requires a
second sighting: a lone hit stays eligible, just later.  Playability is still confirmed by
the music provider, and the choice of route is still the Curator's.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

from wavecast.text_identity import canonical_name

# Genre words as people write them in a request, and the English the catalog also uses.
GENRE_ALIASES: dict[str, tuple[str, ...]] = {
    "后摇": ("post-rock", "post rock"),
    "数学摇滚": ("math rock",),
    "盯鞋": ("shoegaze",),
    "爵士": ("jazz",),
    "蓝调": ("blues",),
    "摇滚": ("rock",),
    "朋克": ("punk",),
    "金属": ("metal",),
    "民谣": ("folk",),
    "乡村": ("country",),
    "古典": ("classical",),
    "电子": ("electronic",),
    "氛围": ("ambient",),
    "嘻哈": ("hip hop",),
    "说唱": ("rap",),
    "放克": ("funk",),
    "灵魂乐": ("soul",),
    "雷鬼": ("reggae",),
    "城市流行": ("city pop",),
    "独立音乐": ("indie",),
    "新世纪": ("new age",),
    "拉丁": ("latin",),
    "波萨诺瓦": ("bossa nova",),
}

# Themes a request pairs with a genre ("游戏里的爵士"): searched together with the genre, since
# the genre alone finds the genre's usual artists and the theme alone finds a catalogue of it.
THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "游戏": ("game", "video game"),
    "电影": ("film", "movie"),
    "动漫": ("anime",),
    "动画": ("anime",),
    "剧集": ("tv series",),
}

# Genres whose music is made by bands: "<genre> 乐队" finds bands rather than songs titled so.
_BAND_GENRES = frozenset({"后摇", "数学摇滚", "盯鞋", "摇滚", "朋克", "金属"})

_LEADING_FILLER = re.compile(
    r"^(?:我(?:现在)?想(?:要)?听|想听|想要听|来(?:点|些|一些|几首)|放(?:点|些|一些|几首)"
    r"|给我(?:放|来|找)?(?:点|些|一些|几首)?|推荐(?:点|些|一些|几首)?|听(?:点|些|一些)"
    r"|有没有)\s*(?:点|些|一些|几首)?\s*"
)
_TRAILING_FILLER = re.compile(r"(?:的)?(?:歌曲|歌|曲子|曲目)$")
_MAX_QUERIES = 5
# Search-hit labels that mark an artist listed under a community tag rather than found by a query.
TAG_LABEL_PREFIX = "tag:"


def _clean(topic: str) -> str:
    text = topic.strip()
    previous = None
    while previous != text:
        previous = text
        text = _LEADING_FILLER.sub("", text).strip()
        text = _TRAILING_FILLER.sub("", text).strip()
    return text or topic.strip()


def catalog_queries(topic: str) -> list[str]:
    """Short catalog queries for a request; never empty.

    A recognised genre gives the genre word, its English forms and, for band music, the
    genre plus "乐队"; the rest of the request is kept as one more query so constraints
    (a country, a game, an era) still narrow the search.  A request with no recognised
    genre keeps its cleaned wording, since it usually names an artist or a work.
    """

    cleaned = _clean(topic)
    folded = cleaned.casefold()
    queries: list[str] = []

    def add(query: str) -> None:
        query = query.strip()
        if query and query.casefold() not in {existing.casefold() for existing in queries}:
            queries.append(query)

    matched = [
        zh
        for zh, english in GENRE_ALIASES.items()
        if zh in cleaned or any(alias in folded for alias in english)
    ]
    if not matched:
        add(cleaned)
        return queries[:_MAX_QUERIES]
    themes = [zh for zh in THEME_ALIASES if zh in cleaned]
    for theme in themes[:1]:
        for zh in matched[:1]:
            add(f"{theme} {zh}")
            add(f"{THEME_ALIASES[theme][0]} {GENRE_ALIASES[zh][0]}")
    for zh in matched[:2]:
        add(zh)
        add(GENRE_ALIASES[zh][0])
        if zh in _BAND_GENRES:
            add(f"{zh} 乐队")
        if len(GENRE_ALIASES[zh]) > 1:
            add(GENRE_ALIASES[zh][1])
    add(cleaned)
    return queries[:_MAX_QUERIES]


def community_tags(topic: str) -> list[str]:
    """English community tags for a request that is *only* a genre, else empty.

    A tag lookup returns the genre's usual artists worldwide.  A request that adds anything
    (a country, a game, an era, a mood) is narrower than the tag, so the lookup would pull the
    route away from what was asked; those requests keep the catalog queries alone.
    """

    cleaned = _clean(topic)
    folded = cleaned.casefold()
    tags: list[str] = []
    rest = folded
    for zh, english in GENRE_ALIASES.items():
        if zh in cleaned or any(alias in folded for alias in english):
            tags.append(english[0])
            for word in (zh, *english):
                rest = rest.replace(word.casefold(), " ")
    if not tags:
        return []
    rest = re.sub(r"乐队|音乐|类|风格|的|\s|[-_]", "", rest)
    return [] if rest else tags[:2]


class ArtistHintProvider(Protocol):
    """A secondary, optional source of artists for community tags (e.g. Last.fm).

    Implementations must never raise: a failed or unconfigured lookup returns ``[]``.
    """

    async def artists_for_tag(self, tag: str, *, limit: int) -> list[str]: ...


def _mentions(blob: str, name: str) -> bool:
    if len(name) < 2:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 '’&.\-]*", name):
        return re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", blob) is not None
    return name in blob


def artist_scores(
    hits: Iterable[tuple[str, str]], evidence_texts: Sequence[str] = ()
) -> dict[str, float]:
    """Rank artists from ``(query, credited artist)`` search hits.

    Keys are ``canonical_name`` of the first credited artist.  An artist scores 2 for each
    distinct query that returned it, 1 for each hit, 3 if the independent web research names
    it, and 5 if a community tag lists it (a ``tag:`` query label).  A tag listing is a
    genre-specific vote from outside the catalog's own text matching, which is what lifts a
    genre's well-known artists above artists whose names merely contain the query.  Only the
    order matters.
    """

    queries: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for query, credit in hits:
        first = re.split(r"\s*(?:,|，|、|;|；)\s*", credit.strip())[0]
        key = canonical_name(first)
        if not key:
            continue
        queries[key].add(query)
        counts[key] += 1
    blob = canonical_name("\n".join(evidence_texts)) if evidence_texts else ""
    return {
        key: 2.0 * len(queries[key])
        + counts[key]
        + (3.0 if blob and _mentions(blob, key) else 0.0)
        + (5.0 if any(query.startswith(TAG_LABEL_PREFIX) for query in queries[key]) else 0.0)
        for key in counts
    }

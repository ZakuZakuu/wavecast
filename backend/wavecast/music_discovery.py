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

# Genres whose music is made by bands: "<genre> 乐队" finds bands rather than songs titled so.
_BAND_GENRES = frozenset({"后摇", "数学摇滚", "盯鞋", "摇滚", "朋克", "金属"})

_LEADING_FILLER = re.compile(
    r"^(?:我(?:现在)?想(?:要)?听|想听|想要听|来(?:点|些|一些|几首)|放(?:点|些|一些|几首)"
    r"|给我(?:放|来|找)?(?:点|些|一些|几首)?|推荐(?:点|些|一些|几首)?|听(?:点|些|一些)"
    r"|有没有)\s*(?:点|些|一些|几首)?\s*"
)
_TRAILING_FILLER = re.compile(r"(?:的)?(?:歌曲|歌|音乐|曲子|曲目)$")
_MAX_QUERIES = 5


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
    for zh in matched[:2]:
        add(zh)
        add(GENRE_ALIASES[zh][0])
        if zh in _BAND_GENRES:
            add(f"{zh} 乐队")
        if len(GENRE_ALIASES[zh]) > 1:
            add(GENRE_ALIASES[zh][1])
    add(cleaned)
    return queries[:_MAX_QUERIES]


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
    distinct query that returned it, 1 for each hit, and 3 if the independent web research
    names it.  Only the order matters.
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
        key: 2.0 * len(queries[key]) + counts[key] + (3.0 if blob and _mentions(blob, key) else 0.0)
        for key in counts
    }

"""A request for "the different versions of one work" must be answered with that work.

Most requests are about a genre, an artist or a mood, and a route that wanders is the point.  A
request such as "Autumn Leaves 的不同演奏版本" is about one piece, and only recordings of that piece
answer it: a song whose title merely contains the words, or another song by the same performer,
does not.  When the data cannot confirm enough versions the route is shorter; unrelated songs are
not used to fill the time.

The check is deliberately narrow: the request must ask for versions of a named work, and a
recording counts when its title, once edition labels are removed, is that work's title.  No work
database is involved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from wavecast.text_identity import base_title_key, canonical_name, song_title_key

_VERSION_PHRASE = (
    r"(?:(?:的\s*|\s+)?(?:(?:不同(?:的)?|各种|所有|多个|各个)(?:演奏|演绎|录音|翻唱)?版本|(?:演奏|演绎|翻唱)版本)"
    r"|的\s*版本|版本对比|different versions?|\bversions\b|\bcovers\b)"
)
_QUOTED = re.compile(r"《([^《》]{1,60})》")
_BEFORE_ZH = re.compile(rf"^(?P<work>.{{2,60}}?)\s*{_VERSION_PHRASE}", re.IGNORECASE)
_AFTER_EN = re.compile(r"(?:versions?|covers?)\s+of\s+(?P<work>[A-Za-z0-9'’&.,\- ]{2,60})", re.IGNORECASE)
_LEADING_VERBS = re.compile(r"^(?:比较|对比|想听|听听|听一听|我想听|来点|帮我找|找找|播放)\s*")
_EDITION_SPLIT = re.compile(r"\s+[-–—:：]\s+")


def requested_work(topic: str) -> str | None:
    """The work whose versions the listener asked for, or None for any other request."""

    text = topic.strip()
    if not re.search(_VERSION_PHRASE, text, re.IGNORECASE):
        return None
    quoted = _QUOTED.search(text)
    if quoted:
        return quoted.group(1).strip()
    match = _AFTER_EN.search(text)
    if match:
        return match.group("work").strip(" .,-")
    match = _BEFORE_ZH.match(_LEADING_VERBS.sub("", text))
    if not match:
        return None
    work = match.group("work").strip(" ，,、")
    # An artist or a theme is not a work: a work's title is short and has no "的" inside.
    if not work or "的" in work or len(work) > 40:
        return None
    return work


def is_version_of(title: str, work: str) -> bool:
    """True when ``title`` is a recording of ``work``: same title once edition labels are removed.

    "Autumn Leaves (Live)", "Autumn Leaves - Remastered 2007" and "Autumn Leaves" count;
    "Autumn Leaves Goodnight - Seasons Songs for Kids" and "the-cafe-beneath-the-autumn-leaves"
    do not.
    """

    wanted = {song_title_key(work), base_title_key(work)}
    wanted.discard("")
    heads = [title, _EDITION_SPLIT.split(title.strip(), maxsplit=1)[0]]
    return any(key in wanted for head in heads for key in (song_title_key(head), base_title_key(head)))


# --- "music written for X's films" -------------------------------------------------------------
#
# A request such as "久石让为宫崎骏电影写的配乐" limits the music to the works of one creator, and the
# same performer is not enough: 久石让 also scored films by others.  The application cannot know
# whose film a song belongs to, so it asks the data: a track counts only when its own catalog
# album or title names a work that the research puts next to that creator.  Without that
# confirmation it is simply not used for this request.

_FOR_OWNER = re.compile(
    r"为(?P<owner>[^，,。、的为]{2,12}?)(?:的)?(?:电影|动画|动漫|影片|剧集|游戏|作品)"
    r"(?:所|而)?(?:写|创作|制作|谱写|作)?的?(?:配乐|音乐|原声|主题曲|曲子)"
)
_OWNER_FILMS = re.compile(
    r"(?:^|[，,\s与和])(?P<owner>[^，,\s的为与和]{2,10})的?(?:电影|动画|动漫|影片)的?(?:配乐|原声|音乐)"
)
_FOR_OWNER_EN = re.compile(
    r"(?:music|scores?|soundtracks?)\s+(?:for|of|to)\s+(?P<owner>[A-Z][\w.'’\- ]{2,30}?)(?:'s|’s)?\s+"
    r"(?:films?|movies?|anime)",
    re.IGNORECASE,
)
_WORK_NAME = re.compile(r"《([^《》]{2,40})》")
_SENTENCE_BREAK = re.compile(r"[。！？!?；;\n]+")
_SOUNDTRACK_WORDS = re.compile(
    r"original\s*sound\s*track|soundtrack|ost|サウンドトラック|オリジナル|イメージアルバム|"
    r"image\s*album|原声带?|原声大碟|电影原声",
    re.IGNORECASE,
)
_CONNECTORS = re.compile(r"[\sのノ之的・･:：\-–—~～()（）\[\]「」『』《》〈〉.,，、!！?？'’\"“”]+")


def requested_scope(topic: str) -> str | None:
    """The creator whose works the music must come from ("宫崎骏"), or None for any other request."""

    text = topic.strip()
    for pattern in (_FOR_OWNER, _OWNER_FILMS, _FOR_OWNER_EN):
        match = pattern.search(text)
        if match:
            owner = match.group("owner").strip(" ，,、'’")
            if len(owner) >= 2:
                return owner
    return None


def scope_works(owner: str, texts: Sequence[str]) -> list[str]:
    """Works named in the same sentence as the creator in the research ("宫崎骏……《千与千寻》")."""

    wanted = canonical_name(owner)
    found: list[str] = []
    for text in texts:
        for sentence in _SENTENCE_BREAK.split(text):
            if wanted and wanted in canonical_name(sentence):
                for name in _WORK_NAME.findall(sentence):
                    if name not in found:
                        found.append(name)
    return found


def _bare(value: str) -> str:
    return _CONNECTORS.sub("", _SOUNDTRACK_WORDS.sub(" ", canonical_name(value)))


def names_work(label: str, works: Sequence[str]) -> bool:
    """``label`` (a catalog album or title) names one of the works, ignoring の / 之 / 的 and edition words."""

    bare = _bare(label)
    return bool(bare) and any(len(key) >= 3 and key in bare for key in (_bare(work) for work in works))

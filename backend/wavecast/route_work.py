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

from wavecast.text_identity import base_title_key, song_title_key

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

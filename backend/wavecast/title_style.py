"""How a programme is named: a title that makes a stranger press play, and a short cover label.

The cover draws a short label (the frontend's ``coverHeading`` allows about eight Chinese
characters).  Without one the cover used to be cut from the part of the title before a colon,
which was often too wide and left the cover bare.  Both prompts that write titles (the listener's
request and the recommendation ideas) share the guidance below, and the application checks the
shape of what comes back: a colon-subtitle title is asked for again once, and a cover label that
is missing or too wide is derived, never left blank.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MAX_COVER_WIDTH = 8.0
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_SEPARATORS = re.compile(r"[:：,，、;；|｜—–]|\s-\s")
_EDGE_PUNCTUATION = " \t\"'“”‘’《》「」『』()（）[]·.…-—–:：,，、;；"
_COLON_TITLE = re.compile(r"^[^:：]{1,24}[:：]\s*\S")

TITLE_GUIDANCE = (
    "Title craft. A title does two jobs: it must be true to what this programme will really "
    "contain, and it must make a stranger curious enough to press play. Work it out in this order. "
    "First, decide in one plain sentence what the programme is actually about, from the request and "
    "the route you are planning. Second, find what is worth a listener's attention in it: a question "
    "it answers, a surprise or tension inside it, the way the music feels, or the one thing the "
    "listener walks away with; use whichever is really there, do not force one. Third, say it the "
    "way a person would say it aloud to a friend: natural spoken language, concrete words, roughly "
    "6 to 16 characters, keeping the name of the artist, work or genre the request is about so the "
    "listener recognises it. Fourth, test it against the programme: would the listener feel the "
    "title kept its promise? Cut whatever the programme cannot deliver, and never invent what the "
    "request does not give: no situation, time of day, place or occasion the request and listener "
    "context do not mention (a request for an artist's songs is not 'on the commute'), and no fact "
    "that would need research (a date, a 'first', a ranking, a superlative, a starting artist, a "
    "number of songs). Prefer a title that could only belong to this programme over one that would "
    "fit any programme (a bare 'light playlist' or 'classics' says nothing). Avoid the 'A：B' form "
    "(a name or theme, a colon, a subtitle) and its dash or slash versions, and catalogue filler "
    "such as 之旅, 探索, 漫游, 指南, 入门, 全解析, 秘密, 'journey / explore / discover': they read "
    "like a table of contents, not like a person. Titles in one batch should not share a sentence "
    "shape. "
    "Also give cover_title: a 2 to 8 character label for the cover, a name or keyword taken from the "
    "title that names the subject (an artist, work, genre or occasion; not a sentence and not the "
    "whole title), for example Bossa Nova, 睡前半小时, Autumn Leaves, 星野源, 后摇."
)


def visual_width(text: str) -> float:
    """The frontend's measure: a Chinese character is 1, any other character 0.56."""

    return sum(1.0 if _CJK.match(char) else 0.56 for char in text)


def uses_colon_subtitle(title: str) -> bool:
    return bool(_COLON_TITLE.match(title.strip()))


def count_colon_titles(titles: Sequence[str]) -> int:
    return sum(1 for title in titles if uses_colon_subtitle(title))


def _tidy(text: str) -> str:
    return " ".join(text.split()).strip(_EDGE_PUNCTUATION)


def _shorten(text: str) -> str:
    """The longest prefix that fits the cover; never splits inside a Latin word or digits."""

    chars = list(text)
    width = 0.0
    end = 0
    for index, char in enumerate(chars):
        width += 1.0 if _CJK.match(char) else 0.56
        if width > MAX_COVER_WIDTH:
            break
        end = index + 1
    if end < len(chars) and end > 0 and chars[end - 1].isalnum() and chars[end].isalnum() and not _CJK.match(chars[end]):
        while end > 0 and chars[end - 1].isalnum() and not _CJK.match(chars[end - 1]):
            end -= 1
    return _tidy("".join(chars[:end]))


def cover_title(candidate: str | None, title: str) -> str:
    """A cover label that fits: the model's if usable, else the title's first part, shortened."""

    for text in (candidate or "", _SEPARATORS.split(title)[0], title):
        cleaned = _tidy(text)
        if not cleaned:
            continue
        if visual_width(cleaned) <= MAX_COVER_WIDTH:
            return cleaned
        shortened = _shorten(cleaned)
        if shortened:
            return shortened
    return _shorten(title.strip()) or title.strip()[:8] or "此刻电台"

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
    "Title craft: the title is what makes a stranger press play. Write it like a magazine cover "
    "line or a radio-show name, in natural spoken language, roughly 6 to 16 characters, with one "
    "concrete hook: a question, a scene, a tension, or a specific person, work or genre, and the "
    "listener must still recognise what it is about (keep the artist, work or genre name the "
    "request is about in the title). Do NOT "
    "use the 'A：B' pattern (a name or theme, a colon, a subtitle), nor a dash or slash version of "
    "it, and avoid filler such as 之旅, 探索, 漫游, 指南, 入门, 全解析, 秘密, or 'journey / explore / "
    "discover'. A title may name the artist, work or genre the programme is about, but it must not "
    "state a fact that would need research (a date, a 'first', a ranking, a superlative). Titles "
    "in one batch must not share a sentence shape. Good: 睡前半小时，不要歌词 / 一首 Autumn Leaves，"
    "五种秋天 / Bossa Nova 是怎么学会慵懒的 / 写给下班路上的轻音乐. Bad: 星野源：创作脉络小径 / "
    "爵士入门：从起源到现代 / 夜色漫游：都市之声. "
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

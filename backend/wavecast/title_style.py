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
import unicodedata
from collections.abc import Sequence

MAX_COVER_WIDTH = 8.0
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_SEPARATORS = re.compile(r"[:：,，、;；|｜—–]|\s-\s")
_EDGE_PUNCTUATION = " \t\"'“”‘’《》「」『』()（）[]·.…-—–:：,，、;；"
_COLON_TITLE = re.compile(r"^[^:：]{1,24}[:：]\s*\S")
# "从 X 吹到 Y", "X 慢下来，等 Y 进来": a transition between two things, in a template that read as
# empty once a whole shelf used it.
_FROM_TO = re.compile(r"从.+?(?:到|吹到|走向|走到|拐进|拐到|通向|变成|变为)")
_TWO_CLAUSE = re.compile(r"^[^，,、]{2,}[，,][^，,]{2,}$")
# A batch may hold a couple of these (a plain, true title sometimes has that shape); a shelf of
# them is the template showing.
FORMULAIC_TITLE_LIMIT = 2
_SUBJECT_PARTS = re.compile(r"[/／、,，&+·\s]+|\band\b|和|与")
# Words that set a scene (a time of day, an occasion); a title may use one only if the listener's
# own context does.
_SITUATION_WORDS = re.compile(
    r"睡前|深夜|夜晚|夜间|夜里|傍晚|黄昏|午后|清晨|早晨|周末|通勤|下班|雨天|旅途|开车|咖啡"
)

TITLE_GUIDANCE = (
    "Title craft. The title and cover_title come last in your answer, after the description and the "
    "plan, so name what this programme will really do. A title has two jobs: it must be true to "
    "that plan, and it must make a stranger curious enough to press play. First, look at what you "
    "have just planned and find what is worth a listener's attention in it: a question it answers, "
    "a surprise or tension inside it, the way the music feels, a concrete thing the listener will "
    "hear or take away (a work, a version, a contrast); use whichever is really there, do not force "
    "one. Second, say it the way a person would say it aloud to a friend: natural spoken language, "
    "concrete words, roughly 6 to 16 characters, keeping the name of the artist, work or genre the "
    "request is about so the listener recognises it. Third, test it against the plan: would the "
    "listener feel the title kept its promise? Cut whatever the plan cannot deliver, and never "
    "invent what the request does not give: no situation, time of day, place or occasion the request "
    "and listener context do not mention (a request for an artist's songs is not 'on the commute'), "
    "and no fact that would need research (a date, a 'first', a ranking, a superlative, a number "
    "of songs). Prefer a title that could only belong to this programme over one that would fit any "
    "programme (a bare 'light playlist' or 'classics' says nothing), and do not just repeat the "
    "request back when the plan holds something more specific. Avoid the 'A：B' form (a name or "
    "theme, a colon, a subtitle) and its dash or slash versions, and catalogue filler such as 之旅, "
    "探索, 漫游, 指南, 入门, 全解析, 秘密, 'journey / explore / discover': they read like a table of "
    "contents, not like a person. Titles in one batch should not share a sentence shape. "
    "cover_title is a 2 to 8 character label for the cover, a name or keyword taken from the "
    "title that names the subject (an artist, work, genre or occasion; not a sentence and not the "
    "whole title), for example Bossa Nova, 睡前半小时, Autumn Leaves, 星野源, 后摇."
)


# The shelf of home ideas has its own guidance: there the failure is not one weak title but a whole
# batch worded from the same template, naming moods instead of what will be heard.
RECOMMENDATION_TITLE_GUIDANCE = (
    "Title craft for a shelf. The title comes last, after the station, the subject and the "
    "description. Say it the way a person would tell a friend, roughly 8 to 18 characters, so that "
    "a stranger knows whom or what they will hear and what is worth hearing in it: a comparison, a "
    "question the programme answers, a period, a kind of sound. For portrait, lineage and crate, "
    "name the subject in the title and say something about it beyond the name: a bare name, or a "
    "name plus a stock word (之路, 入门, 推荐, 的旅程), is not a title, and neither is a mood or a "
    "metaphor on its own. Take the wording from this idea's own subject and description, never from "
    "these instructions. Vary the sentence shapes across the batch: no two titles may open with the "
    "same two characters or end with the same three, and at most two may contain a comma or be a "
    "transition sentence ('从 X 到 Y', 'X 吹到 Y'). Never use the 'A：B' form. Never invent a "
    "situation, time of day, place or occasion that the context does not mention, and no fact that "
    "would need research (a date, a 'first', a ranking, a number of songs). Avoid catalogue filler "
    "such as 之旅, 探索, 漫游, 全解析, 秘密, 'journey / explore / discover'. cover_title is a 2 to 8 "
    "character label taken from the title that names the subject (an artist, work, genre or "
    "occasion)."
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


def uses_formulaic_shape(title: str) -> bool:
    """A transition sentence ("从 X 到 Y") or a two-clause template ("X，Y")."""

    stripped = title.strip()
    return bool(_FROM_TO.search(stripped) or _TWO_CLAUSE.match(stripped))


def count_formulaic_titles(titles: Sequence[str]) -> int:
    return sum(1 for title in titles if uses_formulaic_shape(title))


def _plain(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def title_names_subject(title: str, subject: str | None) -> bool:
    """Whether the title says who or what the programme is about (the subject or a named part)."""

    if not subject or not subject.strip():
        return False
    haystack = _plain(title)
    parts = [_plain(part) for part in _SUBJECT_PARTS.split(subject)]
    return any(part and len(part) >= 2 and part in haystack for part in [*parts, _plain(subject)])


_STOCK_ENDING = re.compile(r"(?:之路|入门|推荐|的旅程|之旅|指南|简史)$")


def ends_with_stock_word(title: str) -> bool:
    """A title that stops at a catalogue word (之路, 入门, 推荐 ...) says nothing more than a name."""

    return bool(_STOCK_ENDING.search(title.strip()))


def shared_frames(titles: Sequence[str], *, limit: int = 2) -> list[str]:
    """Openings (two characters) or endings (three) that more than ``limit`` titles share."""

    plain = [_plain(title) for title in titles]
    openings: dict[str, int] = {}
    endings: dict[str, int] = {}
    for text in plain:
        if len(text) >= 2:
            openings[text[:2]] = openings.get(text[:2], 0) + 1
        if len(text) >= 3:
            endings[text[-3:]] = endings.get(text[-3:], 0) + 1
    return [
        frame for counts in (openings, endings) for frame, count in counts.items() if count > limit
    ]


def invented_situation_words(title: str, context_text: str) -> list[str]:
    """Scene-setting words in the title that the listener's context never used."""

    return [word for word in _SITUATION_WORDS.findall(title) if word not in context_text]

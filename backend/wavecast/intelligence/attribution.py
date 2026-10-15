"""Whose words a source quote is - decided from the source, not from the word "I" or "said".

A host may say "he said ..." only if the source shows that the person said it.  The short quote
that supports a sentence often cannot: an interview answer is "我希望自己的歌曲能够唤起大家爱的
共鸣", and the saying is in the *structure* around it - a question, then the interviewee's
answer.  This module looks at that structure, in the source text the application holds:

* the quote is located in the source (script variants and punctuation ignored, as elsewhere);
* it must sit inside an *answer*: after a question marker (``▲ ... ？``, ``Q：``, ``问：``) with no
  further question between, or after a speaker label (``方大同：``);
* the interviewee must be named by the source, not guessed: the speaker label itself, or an
  interview title that puts the person in the interviewee's place (``Name专访``, ``专访Name``,
  ``... - Name``).  An interview *about* the person (``某某谈Name``), a label for somebody else,
  a review, or a passage that merely contains "我" is not the person's own words.

``own_words_of`` returns the person's name or ``None``.  ``None`` keeps the strict rule: the
quote itself must carry the saying word.  Nothing else in the fact check is relaxed.
"""

from __future__ import annotations

import re

from wavecast.text_identity import canonical_name

_IGNORED_FOR_LOCATING = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]+")
# A question in an interview: "▲ ...？", or a "Q：" / "问：" / "记者：" line.
_QUESTION_MARK = re.compile(r"▲[^▲\n]{0,400}?[？?]")
_QUESTION_LINE = re.compile(r"(?m)^[ \t#>*\-]*(?:Q|问|問|记者|記者|主持人|采访者|採訪者|訪問者|提问|提問)[ \t]*[：:][^\n]*")
# A speaker label at the start of a line: "方大同：从小喜欢...".
_LABEL = re.compile(r"(?m)^[ \t#>*\-]*(?P<name>[^\s：:，。！？\"“”「」（）()]{1,16})[ \t]*[：:]")
_INTERVIEW_WORDS = "专访|專訪|访谈|訪談|采访|採訪|访问|訪問|独家专访|獨家專訪|对话|對話"


def _locate(source: str, quote: str) -> tuple[int, int] | None:
    """Where the quote sits in the source, as original character offsets, or ``None``."""

    needle = _IGNORED_FOR_LOCATING.sub("", canonical_name(quote))
    if len(needle) < 4:
        return None
    squashed: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(source):
        folded = _IGNORED_FOR_LOCATING.sub("", canonical_name(char))
        for piece in folded:
            squashed.append(piece)
            origin.append(index)
    at = "".join(squashed).find(needle)
    if at < 0:
        return None
    return origin[at], origin[at + len(needle) - 1] + 1


def _interviewee_in_title(title: str, name: str) -> bool:
    """The title puts ``name`` in the interviewee's place (not merely mentions them)."""

    folded_title, who = canonical_name(title), re.escape(canonical_name(name))
    words = _INTERVIEW_WORDS
    patterns = (
        rf"{who}\s*(?:{words})",
        rf"(?:{words})\s*[:：]?\s*{who}",
        rf"[－\-—–|｜:：]\s*{who}\s*(?:[_|｜].*)?$",
    )
    return any(re.search(pattern, folded_title) for pattern in patterns)


def own_words_of(source: str, quote: str, name: str, *, title: str = "") -> str | None:
    """``name`` if the quote is, by the source's own structure, that person's answer."""

    name = name.strip()
    if not name or not source or not quote.strip():
        return None
    span = _locate(source, quote)
    if span is None:
        return None
    start, end = span
    before = source[:start]
    wanted = canonical_name(name)

    last_question_end = max(
        [match.end() for match in _QUESTION_MARK.finditer(before)]
        + [match.end() for match in _QUESTION_LINE.finditer(before)],
        default=-1,
    )
    # The quote must not be inside a question itself.
    for pattern in (_QUESTION_MARK, _QUESTION_LINE):
        for match in pattern.finditer(source):
            if match.start() < end and start < match.end():
                return None

    # An answer carries a speaker label, or follows a question in an interview about its title.
    answer_start = max(last_question_end, 0)
    labels = [m for m in _LABEL.finditer(before) if m.start() >= answer_start or last_question_end < 0]
    if labels:
        label = canonical_name(labels[-1].group("name"))
        # A label for somebody else (or a metadata line such as "歌手：") is not the person.
        return name if label == wanted else None
    if last_question_end < 0:
        return None  # no question before it: an article, a review - not an answer
    return name if _interviewee_in_title(title, name) else None


# --- the sentence side ---------------------------------------------------------------------

_SELF_SAID = re.compile("|".join(re.escape(w) for w in ("自己说", "自己讲", "曾说", "说过", "曾表示", "坦言", "自述", "亲口", "他说", "她说")))
_CLAUSE_END = re.compile(r"[，。！？；、,.!?;:：“”\"']")
# Words that may stand between the clause start and "说过" without naming anybody else.
# (Qualifiers such as "first" or "always" are checked on their own by the fact check.)
_FILLER = re.compile(
    "|".join(
        (
            "第一次|首次|头一次|初次|首度|第一回|不止一次|多次|反复|曾经|已经|其实|当年|早年|后来|当时|从前",
            "一直|始终|总是|常常|经常|公开|明确|特别|专门|亲口|同时|并且|而且|自己|本人",
            "他|她|还|也|又|再|曾|早|就|才|只|仅|常|并|却|倒|当|后",
        )
    )
)


def says_only_what_the_speaker_said(sentence: str, speaker: str) -> bool:
    """Every "said" in the sentence is by the person the quote is the own words of.

    A pronoun or "himself" is taken to be that person; an explicit name must be theirs.  A
    sentence that gives the saying to someone else ("周杰伦说过 ...") is not backed by the
    person's own words.
    """

    found = False
    who = canonical_name(speaker)
    for match in _SELF_SAID.finditer(sentence):
        found = True
        clause_start = max((m.end() for m in _CLAUSE_END.finditer(sentence[: match.start()])), default=0)
        prefix = sentence[clause_start : match.start()]
        # "自己说" / "他说" carry their own subject inside the matched word.
        remaining = _FILLER.sub("", prefix).strip()
        if remaining and canonical_name(remaining) != who and not canonical_name(remaining).endswith(who):
            return False
    return found

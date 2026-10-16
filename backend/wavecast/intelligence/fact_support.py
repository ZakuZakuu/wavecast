"""Source-verification helpers used while preparing story material and talking points.

There is no post-writing model review or sentence deletion here. Quotes, roles and
qualifiers are checked before the Writer turns the material into a complete telling.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from wavecast.text_identity import canonical_name

_TITLE_IN_BRACKETS = re.compile(r"《([^》]{1,40})》")
_IGNORED = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]+")
_MIN_QUOTE_CHARS = 4


# Who did what, one word family per role.  A sentence that claims a role is supported only by a
# quote that speaks of that same role: "arranged" does not show "composed", and being credited
# on a recording does not show who sang on it.  ``creation`` is the loose "wrote / made" claim,
# which any of the creative roles can back.
_ROLES: dict[str, tuple[str, ...]] = {
    "composer": ("作曲", "谱曲"),
    "arranger": ("编曲",),
    "score": ("配乐",),
    "lyricist": ("作词", "填词", "词作"),
    "vocal": ("演唱", "主唱", "领唱", "唱的是", "唱的", "唱了", "献唱"),
    "instrumental": ("演奏", "弹奏", "独奏"),
    "director": ("导演", "执导"),
    "cast": ("主演",),
    "release": ("发行", "首映", "上映", "公映", "出版", "票房"),
    "award": ("获奖", "荣获", "入围"),
    "creation": ("创作", "写成", "写了", "写出", "谱写"),
}
_CREATIVE_ROLES = ("composer", "arranger", "score", "lyricist", "creation")


def _alternatives(words: Sequence[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(canonical_name(word)) for word in words))


# A sentence that adds one of these to a claim needs a quote that says it as well: a source that
# only names the work does not show that it was "the first", "said by himself", "why", or played
# on a "small band".  (sentence words, words that carry the same qualifier in a quote)
_QUALIFIERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "first",
        ("第一次", "首次", "头一次", "初次", "首度", "第一回"),
        ("初めて", "はじめて", "初の", "初次", "第一次", "第一回", "首次", "首度", "头一次", "first", "ようやく"),
    ),
    (
        "self-said",
        ("自己说", "自己讲", "曾说", "说过", "曾表示", "坦言", "自述", "亲口", "他说", "她说"),
        ("说", "語", "話", "述", "言", "表示", "談", "コメント", "インタビュー", "said", "told", "says", "「", "“", '"'),
    ),
    (
        "cause",
        ("所以", "因此", "因而", "从而", "正因", "导致", "使得", "才让", "才能", "才会", "因为", "由于"),
        ("所以", "ため", "ので", "から", "ゆえ", "故", "因", "由于", "为了", "によって", "ことで", "結果", "导", "導",
         "せい", "おかげ", "because", "so that", "thus", "therefore", "led to", "result", "why"),
    ),
    (
        "influence",
        ("影响了", "影响着", "影响后", "启发了", "奠定", "开创", "后来的", "此后的"),
        ("影響", "影响", "啓発", "启发", "インスパイア", "influence", "inspired", "手本", "模範", "基礎", "後の", "後に",
         "后来", "later", "legacy", "先駆", "pioneer"),
    ),
    ("period", ("一年里", "一年中", "一年内", "每年"), ("年", "year", "annual")),
    (
        "always",
        ("一直", "始终", "总是", "从未", "从来没", "从不", "一向"),
        ("いつも", "ずっと", "常に", "一貫", "一直", "始终", "总是", "从未", "从来", "从不", "決して", "一度も",
         "never", "always", "ever"),
    ),
    ("only", ("唯一", "只有", "仅有"), ("唯一", "only", "のみ", "だけ", "ただ", "仅", "只有", "sole")),
    (
        "whole",
        ("所有", "全部", "整个", "每首", "每部"),
        ("すべて", "全て", "全部", "所有", "整个", "全体", "全", "all", "every", "each", "entire", "whole"),
    ),
)
_QUALIFIER_PATTERNS = tuple(
    (name, _alternatives(sentence_words), _alternatives(quote_words))
    for name, sentence_words, quote_words in _QUALIFIERS
)
# Instruments and ensembles named in a sentence must be named by the quote too.
_INSTRUMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("小乐队", ("小乐队", "小編成", "少人数", "バンド", "small", "combo", "ensemble", "chamber", "室内")),
    ("大乐队", ("大乐队", "大編成", "オーケストラ", "管弦楽", "交響", "orchestra", "symphon", "乐团", "管弦")),
    ("合唱", ("合唱", "コーラス", "混声", "choir", "chorus", "choral")),
    ("定音鼓", ("定音鼓", "ティンパニ", "timpani")),
    ("弦乐", ("弦乐", "弦", "ストリングス", "string")),
    ("钢琴", ("钢琴", "ピアノ", "piano")),
    ("小提琴", ("小提琴", "ヴァイオリン", "バイオリン", "violin")),
    ("吉他", ("吉他", "ギター", "guitar")),
    ("萨克斯", ("萨克斯", "サックス", "sax")),
    ("小号", ("小号", "トランペット", "trumpet")),
    ("长笛", ("长笛", "フルート", "flute")),
    ("合成器", ("合成器", "シンセ", "synth")),
    ("贝斯", ("贝斯", "ベース", "bass")),
)
_INSTRUMENT_PATTERNS = tuple((word, _alternatives(quote_words)) for word, quote_words in _INSTRUMENTS)


def qualifiers_missing(sentence: str, quote: str) -> list[str]:
    """Qualifiers the sentence adds to its claim that the quote does not carry.

    A quote that states a different, narrower or plainer thing than the sentence does not
    support the sentence, even when both name the same work or person.
    """

    folded = canonical_name(quote)
    missing = [
        name
        for name, in_sentence, in_quote in _QUALIFIER_PATTERNS
        if in_sentence.search(sentence) and not in_quote.search(folded)
    ]
    missing += [
        word
        for word, in_quote in _INSTRUMENT_PATTERNS
        if word in sentence and not in_quote.search(folded)
    ]
    return missing


def _squash(text: str) -> str:
    return _IGNORED.sub("", canonical_name(text))


def quote_in_source(quote: str, source: str) -> bool:
    """True when the quote is a verbatim stretch of the source.

    Script variants, spacing and punctuation are ignored (a quote copied from a Traditional
    Chinese page still matches), but the words themselves must be contiguous and complete, so
    a quote with a negation removed does not match.
    """

    squashed = _squash(quote)
    return len(squashed) >= _MIN_QUOTE_CHARS and squashed in _squash(source)


# Words that, in a quoted source, state a role in the ways other languages put it (Japanese
# pages say 歌唱, 歌われる, 歌詞).  They are matched after script variants are folded.
_QUOTE_ROLE_WORDS: dict[str, tuple[str, ...]] = {
    "lyricist": ("歌词",),
    "vocal": ("歌唱", "歌われ", "歌って", "歌わ", "唱:", "唱：", "歌:", "歌：", "vocal"),
}


def roles_in(text: str, *, quote: bool = False) -> set[str]:
    """The roles a sentence claims, or (``quote=True``) a source line states, script-folded."""

    folded = canonical_name(text) if quote else text
    found = {role for role, words in _ROLES.items() if any(word in folded for word in words)}
    if quote:
        found |= {
            role for role, words in _QUOTE_ROLE_WORDS.items() if any(word in folded for word in words)
        }
    return found


def quote_backs_roles(quote: str, roles: set[str]) -> bool:
    """Every role the sentence claims is spoken of, as that role, in the quote."""

    quoted = roles_in(quote, quote=True)
    return all(
        role in quoted or (role == "creation" and quoted & set(_CREATIVE_ROLES)) for role in roles
    )


_ARTIST_SPLIT = re.compile(r"\s*(?:,|，|、|/|&|;|；|\bfeat\.?|\bft\.?)\s*", re.IGNORECASE)


def credited_people(artists: Sequence[str]) -> list[str]:
    """The individual names in artist credits ("久石譲, 奥户巴寿" -> both), squashed for comparison."""

    names: list[str] = []
    for credit in artists:
        for part in _ARTIST_SPLIT.split(credit):
            key = _squash(part)
            if len(key) >= 2 and key not in names:
                names.append(key)
    return names


def people_missing_from_quote(text: str, quote: str, people: Sequence[str]) -> list[str]:
    """People the sentence names (among those the programme knows) that the quote does not.

    "作曲是久石让" backed by a line that says "作曲：木村弓" has the right role and the wrong person.
    """

    squashed_text, squashed_quote = _squash(text), _squash(quote)
    return [name for name in people if name in squashed_text and name not in squashed_quote]


def similar_claim(left: str, right: str) -> bool:
    """Two statements that overlap by half or more of the shorter one say the same thing."""

    def grams(value: str) -> set[str]:
        squashed = _squash(value)
        return {squashed[i : i + 2] for i in range(len(squashed) - 1)}

    a, b = grams(left), grams(right)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.5

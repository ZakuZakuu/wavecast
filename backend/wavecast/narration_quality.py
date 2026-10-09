"""Deterministic checks on narration copy, used to compare Writer prompts before and after.

These measure the things that make synthetic hosts sound alike or sound artificial.  They
do not judge whether a sentence is *good*; that stays a human (or reviewer) call.  Every
pattern list is a starting point to be tuned against real output.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from wavecast.spoken_form import KnownTrack, to_spoken_form
from wavecast.text_identity import canonical_name, text_mentions_name

# Stock figurative verbs and images that recur in generated Chinese music copy.
FIGURATIVE_PHRASES: tuple[str, ...] = (
    "往里收",
    "收了起来",
    "收住",
    "一层层",
    "层层递进",
    "层层叠",
    "慢慢铺开",
    "缓缓铺开",
    "铺陈",
    "铺开",
    "画出",
    "霓虹",
    "余韵",
    "浮出来",
    "浮现",
    "落下来",
    "沉下去",
    "托着",
    "织进",
    "叠上来",
    "叠起来",
    "拉长",
    "留着呼吸",
    "给呼吸",
    "夜色",
    "光泽",
    "微光",
    "质感",
    "之旅",
    "立住",
    "留出空间",
    "站一边",
    "长出来",
    "几条线",
    "连上了",
    "堆到临界",
    "自己就散",
    "铺成",
    "留点空白",
    "旅程",
    "声音世界",
    "直接而有力",
    "带你进入",
    "堆起来",
    "乱一阵",
    "再散开",
    "踮着脚",
    "拉到最大",
    "动静拉",
    "撑起一片天",
    "收到身边",
    "情绪是",
    "情绪收",
    "情绪偏",
)
_CONTRAST_FRAME = re.compile(r"不是[^，。！？]{1,18}[，,]?(?:而是|更像|而像)|与其[^。]{1,18}?不如")
_MORALISING = re.compile(r"这(?:也)?提醒我们|归根结底|某种意义上|说到底|让我们")
_PODCAST_TALK = re.compile(r"下期|下一期|本期节目|各位听众|欢迎收听|感谢收听")
_EVIDENCE_TALK = re.compile(r"资料显示|据说|据了解|据称|证据|不确定|传闻|有说法")
_PERSONAL_EXPERIENCE = re.compile(r"我(?:小时候|曾经|那时候|当年|记得|第一次听|翻开)|翻开(?:这张|了)")
# A question put to the listener to hook them; a radio host states the thing instead.
# Talking about a different song that merely shares the title is a tangent, not the track.
_SAME_NAME_TANGENT = re.compile(r"同名|同样的名字|同一个名字|重名|另一首同名")
_RHETORICAL_HOOK = re.compile(r"有没有想过|你有没有|你知道吗|想象一下|不妨想想|是不是觉得")
# A first sentence that is a question ("安静到底算什么？Mogwai 给了个答案。").
_OPENS_WITH_QUESTION = re.compile(r"[^。！？!?\n]{2,40}[？?]")
_STOCK_OPENERS = ("刚才", "接下来", "我们先从", "下一首")
_LISTEN_CUE = re.compile(r"留意|注意|听听|听它|听他|听她|你听|听着")
_PARALLEL_LIST = re.compile(r"(?:[^，。、]{1,6}、){2}[^，。、]{1,6}")
_SENTENCE_BREAK = re.compile(r"[。！？!?；;\n]+")
_MIN_REPEAT_CHARS = 10
# Share of the shorter sentence's character pairs found in the other.  Measured on real
# programmes: a reworded repeat scores 0.67, unrelated sentences sharing a name 0.2 or less.
_REPEAT_CONTAINMENT = 0.5
_MIN_REPEAT_PAIRS = 8
_RECAP_TITLES = 3
_PUNCTUATION = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]")


_DURATION_CLAIM = re.compile(r"([零〇一二三四五六七八九十两\d]{1,3})\s*(分钟|个小时|小时|秒钟)")
_NUMERALS = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"〇": 0, "两": 2}


def _number(word: str) -> int | None:
    """An Arabic or Chinese numeral up to 99 (``8``, ``八``, ``十二``), else None."""

    if word.isdigit():
        return int(word)
    if word == "十":
        return 10
    if word.startswith("十") and len(word) == 2 and word[1] in _NUMERALS:
        return 10 + _NUMERALS[word[1]]
    if len(word) == 2 and word[1] == "十" and word[0] in _NUMERALS:
        return _NUMERALS[word[0]] * 10
    if len(word) == 3 and word[1] == "十" and word[0] in _NUMERALS and word[2] in _NUMERALS:
        return _NUMERALS[word[0]] * 10 + _NUMERALS[word[2]]
    if len(word) == 1 and word in _NUMERALS:
        return _NUMERALS[word]
    return None


def durations_in(text: str) -> set[str]:
    """Spoken lengths in ``text`` as ``"8分钟"`` (八分钟 and 8 分钟 give the same entry)."""

    found: set[str] = set()
    for amount, unit in _DURATION_CLAIM.findall(text):
        value = _number(amount)
        if value is not None:
            found.add(f"{value}{'小时' if '小时' in unit else unit.replace('秒钟', '秒')}")
    return found


_ARABIC_YEAR = re.compile(r"(?<![\d.])((?:1[89]|20)\d{2})(?!\d)")
_CHINESE_YEAR = re.compile(r"([零〇一二三四五六七八九]{4})年")
_DIGITS = {c: str(i) for i, c in enumerate("零一二三四五六七八九")} | {"〇": "0"}


def years_in(text: str) -> set[str]:
    """Four-digit years mentioned in ``text``, in digits (一九八二年 and 1982 both give 1982)."""

    found = set(_ARABIC_YEAR.findall(text))
    for word in _CHINESE_YEAR.findall(text):
        digits = "".join(_DIGITS[char] for char in word)
        if _ARABIC_YEAR.fullmatch(digits):
            found.add(digits)
    return found


@dataclass(frozen=True)
class BlockCheck:
    text: str
    issues: list[str] = field(default_factory=list)
    figurative_hits: list[str] = field(default_factory=list)
    opener: str = ""
    estimated_seconds: float = 0.0
    listen_cue: bool = False

    @property
    def ai_flavoured(self) -> bool:
        return bool(self.figurative_hits) or any(
            issue.startswith(("contrast_frame", "moralising", "parallel_list")) for issue in self.issues
        )


# Measured with the production voice at speed 0.9 (2026-10-09): about 4.5 Chinese characters per
# second, and roughly 0.6 s for each English word mixed into a Chinese sentence.
CHARS_PER_SECOND = 4.5
SECONDS_PER_ENGLISH_WORD = 0.6
_ENGLISH_WORD = re.compile(r"[A-Za-z][A-Za-z'’.-]*")


def estimate_seconds(spoken_text: str, chars_per_second: float = CHARS_PER_SECOND) -> float:
    """Spoken length: Chinese characters at the measured rate plus a cost per English word."""

    words = _ENGLISH_WORD.findall(spoken_text)
    without_words = _ENGLISH_WORD.sub("", spoken_text)
    voiced = len(_PUNCTUATION.sub("", without_words))
    return voiced / chars_per_second + len(words) * SECONDS_PER_ENGLISH_WORD


def opener_of(text: str) -> str:
    """The first words of a block, normalised, as its repetition fingerprint."""

    stripped = text.strip()
    for stock in _STOCK_OPENERS:
        if stripped.startswith(stock):
            return stock
    return _PUNCTUATION.sub("", stripped)[:4]


def _bigrams(sentence: str) -> set[str]:
    folded = _PUNCTUATION.sub("", canonical_name(sentence))
    return {folded[i : i + 2] for i in range(len(folded) - 1)}


def repeated_sentence(text: str, earlier: str) -> str | None:
    """A sentence of ``text`` that says (nearly) what a sentence of ``earlier`` already said."""

    earlier_sets = [
        _bigrams(sentence)
        for sentence in _SENTENCE_BREAK.split(earlier)
        if len(_PUNCTUATION.sub("", sentence)) >= _MIN_REPEAT_CHARS
    ]
    if not earlier_sets:
        return None
    for sentence in _SENTENCE_BREAK.split(text):
        if len(_PUNCTUATION.sub("", sentence)) < _MIN_REPEAT_CHARS:
            continue
        mine = _bigrams(sentence)
        for theirs in earlier_sets:
            shorter = min(len(mine), len(theirs))
            if shorter >= _MIN_REPEAT_PAIRS and len(mine & theirs) / shorter >= _REPEAT_CONTAINMENT:
                return sentence.strip()
    return None


# Wording the Writer reaches for again and again; once a programme has used it, it is stock.
_STOCK_PHRASES = (re.compile(r"挂在.{1,4}名下"),)
_CLAUSE_BREAK = re.compile(r"[，。！？、；：,.!?;:\s“”\"'‘’《》「」『』（）()\-—…·]+")
_CJK_ONLY = re.compile(r"[\u4e00-\u9fff]+")
_PHRASE_CHARS = 8


def repeated_phrase(text: str, earlier: str) -> str | None:
    """A stock phrase, or a run of eight or more Chinese characters, ``earlier`` already used.

    Sentence-level repetition is ``repeated_sentence``; this catches the same turn of phrase
    reused inside a different sentence.  Runs containing Latin letters or digits are skipped,
    so a name that has to come back (a track or artist) is never counted as a repeat.
    """

    if not earlier:
        return None
    for pattern in _STOCK_PHRASES:
        found = pattern.search(text)
        if found is not None and pattern.search(earlier) is not None:
            return found.group(0)
    seen: set[str] = set()
    for clause in _CLAUSE_BREAK.split(canonical_name(earlier)):
        for run in _CJK_ONLY.findall(clause):
            seen.update(run[i : i + _PHRASE_CHARS] for i in range(len(run) - _PHRASE_CHARS + 1))
    if not seen:
        return None
    for clause in _CLAUSE_BREAK.split(canonical_name(text)):
        for run in _CJK_ONLY.findall(clause):
            for i in range(len(run) - _PHRASE_CHARS + 1):
                if run[i : i + _PHRASE_CHARS] in seen:
                    return run[i : i + _PHRASE_CHARS]
    return None


def titles_named(text: str, route_titles: Sequence[str]) -> list[str]:
    """The distinct route track titles ``text`` writes out."""

    named: list[str] = []
    for title in route_titles:
        if title and title not in named and text_mentions_name(text, title):
            named.append(title)
    return named


def check_block(
    text: str,
    *,
    tts_text: str | None = None,
    window_seconds: float | None = None,
    chars_per_second: float = CHARS_PER_SECOND,
    tracks: Sequence[KnownTrack] = (),
    is_final: bool = False,
    supported_years: set[str] | None = None,
    supported_durations: set[str] | None = None,
    unplayed_names: Sequence[str] = (),
    route_titles: Sequence[str] = (),
    earlier: str = "",
) -> BlockCheck:
    issues: list[str] = []
    figurative = [phrase for phrase in FIGURATIVE_PHRASES if phrase in text]
    if _CONTRAST_FRAME.search(text):
        issues.append("contrast_frame")
    if _MORALISING.search(text):
        issues.append("moralising")
    if _PARALLEL_LIST.search(text):
        issues.append("parallel_list")
    if _PODCAST_TALK.search(text):
        issues.append("podcast_talk")
    if _EVIDENCE_TALK.search(text):
        issues.append("evidence_talk")
    if _PERSONAL_EXPERIENCE.search(text):
        issues.append("personal_experience")
    spoken = to_spoken_form(text, tracks, tts_text=tts_text)
    if not spoken.ok:
        issues.append("unspeakable_script")
    seconds = estimate_seconds(spoken.tts_text, chars_per_second)
    if window_seconds is not None and seconds > window_seconds * 1.25:
        issues.append(f"too_long:{seconds:.0f}s>{window_seconds:.0f}s")
    if is_final and re.search(r"下一首|接下来|下期", text):
        issues.append("final_block_points_forward")
    if is_final and years_in(text):
        issues.append("final_block_gives_year")
    if _RHETORICAL_HOOK.search(text) or _OPENS_WITH_QUESTION.match(text.lstrip()):
        issues.append("rhetorical_hook")
    if _SAME_NAME_TANGENT.search(text):
        issues.append("same_name_tangent")
    if opener_of(text) in _STOCK_OPENERS:
        issues.append("stock_opener")
    for name in unplayed_names:
        if text_mentions_name(text, name):
            issues.append(f"mentions_unplayed:{name}")
    if is_final and len(titles_named(text, route_titles)) >= _RECAP_TITLES:
        issues.append("recap_list")
    if earlier and repeated_sentence(text, earlier) is not None:
        issues.append("repeats_earlier")
    elif earlier and repeated_phrase(text, earlier) is not None:
        issues.append("repeats_phrase")
    if supported_years is not None:
        for year in sorted(years_in(text) - supported_years):
            issues.append(f"unsupported_year:{year}")
    if supported_durations is not None:
        for length in sorted(durations_in(text) - supported_durations):
            issues.append(f"unsupported_duration:{length}")
    return BlockCheck(
        text=text,
        issues=issues,
        figurative_hits=figurative,
        opener=opener_of(text),
        estimated_seconds=seconds,
        listen_cue=bool(_LISTEN_CUE.search(text)),
    )


# Findings that justify asking the Writer for one rewrite.  "parallel_list" is only reported:
# plain lists of names are normal speech.
_REWRITE_ISSUES = (
    "contrast_frame",
    "moralising",
    "podcast_talk",
    "evidence_talk",
    "personal_experience",
    "too_long",
    "final_block_points_forward",
    "final_block_gives_year",
    "rhetorical_hook",
    "stock_opener",
    "unsupported_year",
    "unsupported_duration",
    "mentions_unplayed",
    "recap_list",
    "repeats_earlier",
    "repeats_phrase",
    "same_name_tangent",
)


def rewrite_reasons(check: BlockCheck) -> list[str]:
    """Plain-English problems in a block that are worth one rewrite, or an empty list."""

    reasons: list[str] = []
    if check.figurative_hits:
        reasons.append("stock figurative wording: " + ", ".join(check.figurative_hits))
    for issue in check.issues:
        name = issue.split(":")[0]
        if name in _REWRITE_ISSUES:
            reasons.append(_REASON_TEXT.get(name, name) + (f" ({issue.split(':', 1)[1]})" if ":" in issue else ""))
    return reasons


_REASON_TEXT = {
    "contrast_frame": "uses the frame 不是……而是……/更像……/与其……不如……",
    "moralising": "ends or leans on a moral (这也提醒我们 and similar)",
    "podcast_talk": "uses podcast/episode talk (下期, 本期节目, 各位听众)",
    "evidence_talk": "talks about evidence or certainty (资料显示, 据说)",
    "personal_experience": "claims a personal memory or experience",
    "too_long": "is longer than its spoken window",
    "final_block_points_forward": "points to what comes next in the closing block",
    "stock_opener": "starts with 刚才/接下来/我们先从/下一首",
    "unsupported_year": "gives a year that is not in the evidence",
    "unsupported_duration": "states how long a song is (minutes, hours); the length of the played version is not known",
    "mentions_unplayed": "mentions an artist who is not played in this programme",
    "final_block_gives_year": "gives a year in the closing; the closing only says where the route ended",
    "rhetorical_hook": "opens with a question to the listener (有没有想过, 你知道吗); state the thing instead",
    "recap_list": "lists the tracks played one by one; name at most the last track, or none",
    "repeats_earlier": "says again what an earlier block of this programme already said",
    "same_name_tangent": "talks about another song that only shares the title; it is not what is playing",
    "repeats_phrase": "reuses a turn of phrase an earlier block of this programme already used; word it differently",
}


@dataclass(frozen=True)
class BatchSummary:
    blocks: int
    opener_kinds: int
    opener_diversity: float
    most_common_opener: str
    most_common_opener_share: float
    ai_flavour_rate: float
    mean_figurative_hits: float
    issue_counts: dict[str, int]
    listen_cue_rate: float
    mean_seconds: float


def summarize(checks: Sequence[BlockCheck]) -> BatchSummary:
    count = len(checks)
    if count == 0:
        return BatchSummary(0, 0, 0.0, "", 0.0, 0.0, 0.0, {}, 0.0, 0.0)
    openers = Counter(check.opener for check in checks)
    top, top_count = openers.most_common(1)[0]
    issue_counts: Counter[str] = Counter()
    for check in checks:
        for issue in check.issues:
            issue_counts[issue.split(":")[0]] += 1
    return BatchSummary(
        blocks=count,
        opener_kinds=len(openers),
        opener_diversity=len(openers) / count,
        most_common_opener=top,
        most_common_opener_share=top_count / count,
        ai_flavour_rate=sum(check.ai_flavoured for check in checks) / count,
        mean_figurative_hits=sum(len(check.figurative_hits) for check in checks) / count,
        issue_counts=dict(issue_counts),
        listen_cue_rate=sum(check.listen_cue for check in checks) / count,
        mean_seconds=sum(check.estimated_seconds for check in checks) / count,
    )

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
from wavecast.text_identity import canonical_name

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
)
_CONTRAST_FRAME = re.compile(r"不是[^，。！？]{1,18}[，,]?(?:而是|更像|而像)|与其[^。]{1,18}?不如")
_MORALISING = re.compile(r"这(?:也)?提醒我们|归根结底|某种意义上|说到底|让我们")
_PODCAST_TALK = re.compile(r"下期|下一期|本期节目|各位听众|欢迎收听|感谢收听")
_EVIDENCE_TALK = re.compile(r"资料显示|据说|据了解|据称|证据|不确定|传闻|有说法")
_PERSONAL_EXPERIENCE = re.compile(r"我(?:小时候|曾经|那时候|当年|记得|第一次听|翻开)|翻开(?:这张|了)")
_STOCK_OPENERS = ("刚才", "接下来", "我们先从", "下一首")
_LISTEN_CUE = re.compile(r"留意|注意|听听|听它|听他|听她|你听|听着")
_PARALLEL_LIST = re.compile(r"(?:[^，。、]{1,6}、){2}[^，。、]{1,6}")
_PUNCTUATION = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]")


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


def check_block(
    text: str,
    *,
    tts_text: str | None = None,
    window_seconds: float | None = None,
    chars_per_second: float = CHARS_PER_SECOND,
    tracks: Sequence[KnownTrack] = (),
    is_final: bool = False,
    supported_years: set[str] | None = None,
    unplayed_names: Sequence[str] = (),
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
    if opener_of(text) in _STOCK_OPENERS:
        issues.append("stock_opener")
    folded_text = canonical_name(text)
    for name in unplayed_names:
        folded = canonical_name(name)
        if len(folded) >= 2 and folded in folded_text:
            issues.append(f"mentions_unplayed:{name}")
    if supported_years is not None:
        for year in sorted(years_in(text) - supported_years):
            issues.append(f"unsupported_year:{year}")
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
    "stock_opener",
    "unsupported_year",
    "mentions_unplayed",
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
    "mentions_unplayed": "mentions an artist who is not played in this programme",
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

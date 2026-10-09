"""Spoken forms of display text: what the TTS voice should say.

The synthetic voice reads Chinese and English well; Japanese, Korean and other scripts come
out wrong.  Display text keeps names exactly as the catalog spells them; the spoken form of
a song or artist is chosen here, deterministically, so the Writer never has to translate a
title (and cannot mistranslate one):

* Chinese names are read as they are (CJK ideographs are rendered Simplified).
* Short English titles are read as they are; catalogue-style titles are not read at all.
* Titles or names in any other script are replaced by a plain phrase ("这首歌"), or by a known
  Chinese name where one is on record.

Only entities already known to the application (the tracks of a narration slot) are
substituted; free text is never rewritten with broad patterns.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from wavecast.text_identity import to_simplified

# Kana, Hangul, Cyrillic, Hebrew, Arabic, Devanagari and Thai: the voice reads these badly.
UNSPEAKABLE_SCRIPTS = re.compile(
    "[Ѐ-ӿ֐-ۿऀ-ॿ฀-๿"
    "ᄀ-ᇿ぀-ヿ㄰-㆏ㇰ-ㇿ가-힯ｦ-ﾟ]"
)

# Chinese names for artists whose catalog credit is in another script.  Keep to names that
# are in common use; anything missing is simply not spoken.
KNOWN_CHINESE_NAMES: dict[str, str] = {
    "宇多田ヒカル": "宇多田光",
    "中島みゆき": "中岛美雪",
    "浜崎あゆみ": "滨崎步",
    "방탄소년단": "防弹少年团",
}

GENERIC_SONG = "这首歌"
_TRAILING_GROUP = re.compile(r"\s*[\(\[（][^\)\]）]*[\)\]）]\s*$")
_CATALOGUE_NUMBER = re.compile(r"\b(?:no|op|bwv|k|rv|hob|d|kv|woo)\.?\s*\d", re.IGNORECASE)
_WRAPPERS = "《》「」『』“”\"'‘’"
_MAX_ENGLISH_WORDS = 6
_MAX_SPOKEN_TITLE_CHARS = 40
_ARTIST_SEPARATORS = re.compile(r"\s*(?:,|，|、|;|；|\bfeat\.?|\bft\.?)\s*", re.IGNORECASE)


_DIGIT_WORDS = "零一二三四五六七八九"
_YEAR_RANGE = re.compile(r"(?<![\d.])(\d{4})\s*(至|到|~|-|—|–)\s*(\d{4})\s*(年代?)")
_YEAR = re.compile(r"(?<![\d.])(\d{4})(\s*)(年代?)")
_DECADE = re.compile(r"(?<![\d.])(\d)0(\s*)年代")
_DECADE_WORDS = {"1": "十", "2": "二十", "3": "三十", "4": "四十", "5": "五十",
                 "6": "六十", "7": "七十", "8": "八十", "9": "九十"}


def speak_years(text: str) -> str:
    """Write years the way they are said: 1982 年 -> 一九八二年, 80 年代 -> 八十年代.

    The voice reads a bare "1982" as a quantity, which is wrong for a year.  Only a number
    directly followed by 年 / 年代 is touched; other numbers are left to the voice.
    """

    def spell(digits: str) -> str:
        return "".join(_DIGIT_WORDS[int(d)] for d in digits)

    text = _YEAR_RANGE.sub(
        lambda m: spell(m.group(1)) + ("至" if m.group(2) in "-—–~" else m.group(2)) + spell(m.group(3)) + m.group(4),
        text,
    )
    spelled = _YEAR.sub(
        lambda m: "".join(_DIGIT_WORDS[int(d)] for d in m.group(1)) + m.group(3), text
    )
    return _DECADE.sub(lambda m: _DECADE_WORDS[m.group(1)] + "年代", spelled)


def has_unspeakable_script(text: str) -> bool:
    return UNSPEAKABLE_SCRIPTS.search(text) is not None


def _tidy(value: str) -> str:
    cleaned = value.replace("&", " and " if re.search(r"[A-Za-z]", value) else "和")
    cleaned = re.sub(r"[/／|_~]+", " ", cleaned)
    return " ".join(cleaned.split())


def spoken_title(title: str) -> str | None:
    """How to say a song title, or ``None`` when it should not be read aloud."""

    base = title.strip()
    while True:
        reduced = _TRAILING_GROUP.sub("", base).strip()
        if not reduced or reduced == base:
            break
        base = reduced
    base = to_simplified(base)
    if not base or has_unspeakable_script(base):
        return None
    if _CATALOGUE_NUMBER.search(base):
        return None
    latin_words = re.findall(r"[A-Za-z][A-Za-z'’.-]*", base)
    if len(latin_words) > _MAX_ENGLISH_WORDS or len(base) > _MAX_SPOKEN_TITLE_CHARS:
        return None
    cleaned = _tidy(base)
    return cleaned or None


def spoken_artist(artist: str) -> str | None:
    """How to say an artist credit; unspeakable credits are dropped (at most two are named)."""

    names: list[str] = []
    for part in (item.strip() for item in _ARTIST_SEPARATORS.split(artist) if item.strip()):
        known = KNOWN_CHINESE_NAMES.get(part)
        candidate = known if known is not None else to_simplified(part)
        if has_unspeakable_script(candidate):
            continue
        cleaned = _tidy(candidate)
        if cleaned and cleaned not in names:
            names.append(cleaned)
    if not names:
        return None
    return "和".join(names[:2])


@dataclass(frozen=True)
class KnownTrack:
    """A song the application knows by name (the catalog's spelling)."""

    artist: str
    title: str


@dataclass
class SpokenForm:
    tts_text: str
    # Runs of text the voice cannot read and that could not be replaced.
    unspeakable: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unspeakable


def _variants(value: str) -> list[str]:
    variants = [value.strip()]
    stripped = value.strip()
    while True:
        reduced = _TRAILING_GROUP.sub("", stripped).strip()
        if not reduced or reduced == stripped:
            break
        stripped = reduced
        variants.append(stripped)
    seen: set[str] = set()
    ordered = []
    for item in sorted((v for v in variants if v), key=len, reverse=True):
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _replace_entity(text: str, names: Iterable[str], spoken: str) -> str:
    result = text
    for name in names:
        pattern = re.compile(f"[{re.escape(_WRAPPERS)}]?{re.escape(name)}[{re.escape(_WRAPPERS)}]?")
        result = pattern.sub(lambda _match: spoken, result)
    return result


def to_spoken_form(
    text: str, tracks: Sequence[KnownTrack] = (), *, tts_text: str | None = None
) -> SpokenForm:
    """Return the text the voice should read for ``text`` (or an authored ``tts_text``).

    Known songs and artists are replaced by their spoken forms.  Anything still in a script
    the voice cannot read after that is reported in ``unspeakable``.
    """

    spoken = tts_text if tts_text else text
    # An explanatory original-name aside (“（原名：…）”) is display-only.
    spoken = re.sub(r"[（(][^）)]*" + UNSPEAKABLE_SCRIPTS.pattern + r"[^）)]*[）)]", "", spoken)
    for track in tracks:
        title_spoken = spoken_title(track.title)
        spoken = _replace_entity(spoken, _variants(track.title), title_spoken or GENERIC_SONG)
        artist_spoken = spoken_artist(track.artist)
        credits = [track.artist, *(p for p in _ARTIST_SEPARATORS.split(track.artist) if p.strip())]
        if artist_spoken is not None:
            spoken = _replace_entity(spoken, credits, artist_spoken)
        else:
            spoken = _replace_entity(spoken, credits, "这位艺人")
    spoken = re.sub(f"[{re.escape(_WRAPPERS)}]", "", spoken)
    while f"{GENERIC_SONG}{GENERIC_SONG}" in spoken:
        spoken = spoken.replace(f"{GENERIC_SONG}{GENERIC_SONG}", GENERIC_SONG)
    spoken = spoken.replace(f"{GENERIC_SONG}这首", GENERIC_SONG).replace(f"{GENERIC_SONG}这支", GENERIC_SONG)
    spoken = speak_years(spoken)
    spoken = " ".join(spoken.split()) if "\n" in spoken else spoken
    leftovers = sorted(set(re.findall(rf"\S*{UNSPEAKABLE_SCRIPTS.pattern}\S*", spoken)))
    return SpokenForm(tts_text=spoken, unspeakable=leftovers)

"""Comparison keys for catalog names that differ only by CJK script variant.

Catalogs spell the same artist or title in different forms: ``久石让`` (Simplified),
``久石讓`` (Traditional) and ``久石譲`` (Japanese shinjitai) are one name. These keys
are used only to *compare* names; display text and playback identity never change.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _converters() -> tuple[OpenCC, OpenCC]:
    return OpenCC("jp2t"), OpenCC("t2s")


@lru_cache(maxsize=8192)
def canonical_name(value: str) -> str:
    """Return a script-insensitive key: NFKC, CJK variants folded, casefolded, spaced once.

    Only character variants are folded.  Different words, version labels such as
    ``(Live)``, and punctuation stay distinct, so this is not a fuzzy match.
    """

    japanese_to_traditional, traditional_to_simplified = _converters()
    normalized = unicodedata.normalize("NFKC", value)
    folded = traditional_to_simplified.convert(japanese_to_traditional.convert(normalized))
    return " ".join(folded.casefold().split())


def to_simplified(value: str) -> str:
    """Render CJK ideographs in Simplified form (久石譲 -> 久石让), keeping case and spacing.

    Used when a name is spoken to a Chinese listener; kana and other scripts are untouched.
    """

    japanese_to_traditional, traditional_to_simplified = _converters()
    converted = str(traditional_to_simplified.convert(japanese_to_traditional.convert(value)))
    # The Japanese-to-Traditional table maps 郎 to the variant 郞, which readers do not expect.
    return converted.replace("\u90de", "\u90ce")


def strip_latin_accents(value: str) -> str:
    """Drop accents on Latin letters (``Prélude`` -> ``Prelude``), leaving other scripts alone.

    Kana voicing marks and similar combining marks on non-Latin letters carry meaning, so
    only marks that follow a Latin base letter are removed.
    """

    kept: list[str] = []
    base_is_latin = False
    for char in unicodedata.normalize("NFKD", value):
        if unicodedata.combining(char):
            if not base_is_latin:
                kept.append(char)
            continue
        base_is_latin = ord(char) < 0x250 and char.isalpha()
        kept.append(char)
    return unicodedata.normalize("NFC", "".join(kept))


_FEATURE_CREDIT = re.compile(
    r"\s*(?:[\(\[（]\s*(?:feat|ft|featuring|with)\b\.?[^\)\]）]*[\)\]）]"
    r"|-\s*(?:feat|ft|featuring)\b.*)\s*$",
    re.IGNORECASE,
)


def without_feature_credit(title: str) -> str:
    """Drop a trailing ``(feat. X)`` credit: the same song is listed with and without it."""

    stripped = _FEATURE_CREDIT.sub("", title).strip()
    return stripped or title


_TRAILING_GROUP = re.compile(r"\s*[\(\[（][^\)\]）]*[\)\]）]\s*$")


def base_title_key(title: str) -> str:
    """Comparison key for a song title with every trailing ``(...)`` group removed.

    ``Summer`` and ``Summer (《菊次郎的夏天》钢琴版)`` share a key, so a cover listed with a
    descriptive suffix can be recognised as another take on the same song.
    """

    stripped = title
    while True:
        reduced = _TRAILING_GROUP.sub("", stripped).strip()
        if not reduced or reduced == stripped:
            break
        stripped = reduced
    return canonical_name(stripped)


# A trailing group that only labels the file, not the performance: a date or number, or a
# remaster / mono / stereo note.  "(Live)", "(Remix)", "(Piano Version)" are different
# performances and are deliberately not listed.
_FILE_LABEL = re.compile(
    r"^[\d\s/.\-:,]*$|\b(?:remaster(?:ed)?|digital remaster|mono|stereo|bonus track)\b",
    re.IGNORECASE,
)
_TRAILING_LABEL = re.compile(
    r"\s*(?:[\(\[（]([^\)\]）]*)[\)\]）]|-\s*((?:\d{4}\s+)?(?:digital\s+)?remaster(?:ed)?(?:\s+\d{4})?|mono|stereo))\s*$",
    re.IGNORECASE,
)


def song_title_key(title: str) -> str:
    """Key under which two catalog listings of one recording coincide.

    Folds script variants and Latin accents, drops a trailing feature credit and trailing
    file labels (a date such as ``(04/23)``, ``Remastered 2010``, ``Mono``), and ignores
    spacing, so ``Dippermouth Blues`` and ``Dipper Mouth Blues (04/23)`` are one song.
    Words that name another performance (``Live``, ``Remix``, ``Piano Version``) stay.
    """

    stripped = without_feature_credit(title)
    while True:
        match = _TRAILING_LABEL.search(stripped)
        if match is None:
            break
        group = match.group(1)
        if group is not None and not _FILE_LABEL.search(group):
            break
        reduced = stripped[: match.start()].strip()
        if not reduced:
            break
        stripped = reduced
    words = re.findall(r"\w+", strip_latin_accents(canonical_name(stripped)))
    return "".join(words)


def same_catalog_name(left: str, right: str) -> bool:
    """True when two catalog names are identical after folding script variants."""

    return canonical_name(left) == canonical_name(right)


def text_mentions_name(text: str, name: str) -> bool:
    """True when ``name`` is written in ``text`` (script variants and case folded).

    A name made of Latin letters and digits must stand as a whole word, so ``Cat`` is not
    found in ``category``; a name in another script is matched as a plain substring.
    """

    folded_name = canonical_name(name)
    if len(folded_name) < 2:
        return False
    folded_text = canonical_name(text)
    if re.fullmatch(r"[a-z0-9][a-z0-9 '’&.\-]*", folded_name):
        pattern = rf"(?<![a-z0-9]){re.escape(folded_name)}(?![a-z0-9])"
        return re.search(pattern, folded_text) is not None
    return folded_name in folded_text


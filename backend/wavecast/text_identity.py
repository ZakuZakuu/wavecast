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


def same_catalog_name(left: str, right: str) -> bool:
    """True when two catalog names are identical after folding script variants."""

    return canonical_name(left) == canonical_name(right)

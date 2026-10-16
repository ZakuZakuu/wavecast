"""A small guard against unanchored time wording and invented host experiences.

Material built from old pages and lines written by a model must not say "recently", "last month"
or "the new album" as if the page had been written today, and a host must not claim to have
looked something up or remembered it. This cannot establish semantic accuracy; the
sources and writing instructions still own that. No model is asked here.
"""

from __future__ import annotations

import re

from wavecast.text_identity import to_simplified

# Not 刚 / 刚刚: "刚听完《X》" is the host talking about the song that just played.
_RELATIVE_TIME = re.compile(
    r"最近|近日|近来|近期|上个月|上月|本月|这个月|上周|上星期|这周|本周|前几天|这几天|这两天|前阵子|日前|"
    r"今年|去年|明年|目前|如今|眼下|新近|"
    r"\b(?:recently|nowadays|currently|last\s+(?:month|year|week)|this\s+(?:month|year|week))\b",
    re.IGNORECASE,
)
_NEW_RELEASE = re.compile(r"新推出|新发行|新专辑|新创作|最新|\b(?:new|latest)\s+album\b", re.IGNORECASE)
_ABSOLUTE_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)|[一二两〇零九八七六五四三]{4}年")
_WORK_TITLE = re.compile(r"《[^》]*》")
_INVENTED_EXPERIENCE = re.compile(
    r"我(?:之前|以前|曾经|当年|小时候|那时候|记得|第一次听|翻开)|"
    r"我(?:翻|查|读|看)(?:了|过|到)?(?:资料|文章|报道|采访)|(?:之前|以前)翻(?:了|过)?资料|翻开(?:这张|了)"
)


def has_relative_time(text: str) -> bool:
    """Flag unresolved relative time; allow a new release explicitly anchored in history.

    An absolute year applies only to its own sentence, never to the rest of a passage.
    Other relative expressions still need resolving before writing.
    """

    # A work's title is neither a claim about today nor an event date.
    text = _WORK_TITLE.sub("", to_simplified(text))
    return _RELATIVE_TIME.search(text) is not None or any(
        _NEW_RELEASE.search(sentence) and not _ABSOLUTE_YEAR.search(sentence)
        for sentence in re.split(r"[。！？!?；;\n]|\.\s+", text)
    )


def invents_experience(text: str) -> bool:
    """True when a host claims a personal memory or a piece of research of their own."""

    return _INVENTED_EXPERIENCE.search(_WORK_TITLE.sub("", to_simplified(text))) is not None

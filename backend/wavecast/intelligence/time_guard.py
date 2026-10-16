"""Words that only mean something relative to a moment, and a host's invented experiences.

Material built from old pages and lines written by a model must not say "recently", "last month"
or "the new album" as if the page had been written today, and a host must not claim to have
looked something up or remembered it.  Both are checked in code (no model is asked).
"""

from __future__ import annotations

import re

# Not 刚 / 刚刚: "刚听完《X》" is the host talking about the song that just played.
_RELATIVE_TIME = re.compile(
    r"最近|近日|近来|近期|上个月|上月|本月|这个月|上周|上星期|这周|本周|前几天|这几天|这两天|前阵子|日前|"
    r"目前|如今|眼下|新近|新推出|新发行|新专辑|新创作|最新"
)
_INVENTED_EXPERIENCE = re.compile(
    r"我(?:之前|以前|曾经|当年|小时候|那时候|记得|第一次听|翻开)|"
    r"我(?:翻|查|读|看)(?:了|过|到)?(?:资料|文章|报道|采访)|(?:之前|以前)翻(?:了|过)?资料|翻开(?:这张|了)"
)


def has_relative_time(text: str) -> bool:
    """True when the text uses a word whose meaning depends on when it is said."""

    return _RELATIVE_TIME.search(text) is not None


def invents_experience(text: str) -> bool:
    """True when a host claims a personal memory or a piece of research of their own."""

    return _INVENTED_EXPERIENCE.search(text) is not None

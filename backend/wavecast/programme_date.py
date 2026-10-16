"""The programme's date, as the models are told it.

Writers and the material step are given the day the programme is made, so a source that says
"last month" or "recently" is not read as meaning this month.  The fixed zone is the product's
home zone; the date is only ever used in prompts.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_ZONE = ZoneInfo("Asia/Shanghai")


def programme_date(now: datetime | None = None) -> str:
    """Today in the form a Chinese programme would say it, e.g. 2026年10月16日."""

    moment = (now or datetime.now(_ZONE)).astimezone(_ZONE)
    return f"{moment.year}年{moment.month}月{moment.day}日"

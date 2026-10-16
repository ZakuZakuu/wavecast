from __future__ import annotations

import hashlib
import json

from wavecast.arrangement.models import MixPlan
from wavecast.rendering.ffmpeg import (
    LOUDNESS_RULE,  # a render made under an older rule is not reused
)


def mix_plan_fingerprint(plan: MixPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload + b"|" + LOUDNESS_RULE.encode()).hexdigest()


__all__ = ["mix_plan_fingerprint"]

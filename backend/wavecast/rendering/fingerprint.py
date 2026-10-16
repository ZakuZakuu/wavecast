from __future__ import annotations

import hashlib
import json

from wavecast.arrangement.models import MixPlan
from wavecast.rendering.ffmpeg import LOUDNESS_RULE, NO_LOUDNESS_RULE


def mix_plan_fingerprint(plan: MixPlan, loudness_rule: str = LOUDNESS_RULE) -> str:
    """Hash of the plan under the rule its audio is rendered with.

    "none" is the rule of programmes published before loudness handling: it hashes the plan alone,
    exactly as it was then, so their frozen chunks still verify.
    """

    payload = json.dumps(
        plan.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if loudness_rule != NO_LOUDNESS_RULE:
        payload += b"|" + loudness_rule.encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = ["mix_plan_fingerprint", "LOUDNESS_RULE", "NO_LOUDNESS_RULE"]

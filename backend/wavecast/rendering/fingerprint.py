from __future__ import annotations

import hashlib
import json

from wavecast.arrangement.models import MixPlan


def mix_plan_fingerprint(plan: MixPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["mix_plan_fingerprint"]

"""Print what the home recommendation planner writes for a few fixed listener profiles.

Calls the live DeepSeek planner (a handful of cheap FAST requests; two per profile at most), so it
is run by hand, never in CI.  Needs DEEPSEEK_API_KEY and WAVECAST_PROVIDER_MODE=live like the API.

    PYTHONPATH=backend .venv/bin/python scripts/eval_recommendation_batches.py [profile ...]

The structural checks (stations used, titles that name their subject, template-shaped titles) are
what the application itself retries on; whether the batch makes anyone want to press play is for a
person to judge, which is why every title is printed.
"""

from __future__ import annotations

import sys
from collections import Counter

from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.usage import UsageLedger
from wavecast.recommendations import (
    ProviderBackedRecommendationPlanner,
    UserContext,
    batch_problems,
)

PROFILES: dict[str, UserContext] = {
    "jazz-rnb": UserContext(
        user_id="eval",
        genres=["R&B", "Jazz", "Chill"],
        moods=["Chill"],
        preferred_artists=["方大同", "Robert Glasper"],
        recent_interests=["Bossa Nova 是怎么来的", "Chill 电子"],
        discovery_level=0.7,
    ),
    "post-rock": UserContext(
        user_id="eval",
        genres=["Post-Rock", "Ambient"],
        preferred_artists=["Mogwai", "toe", "惘闻"],
        recent_interests=["后摇入门"],
        discovery_level=0.6,
    ),
    "mandopop-citypop": UserContext(
        user_id="eval",
        genres=["Mandopop", "City Pop"],
        preferred_artists=["陈绮贞", "山下达郎", "王菲"],
        recent_interests=["山下達郎的城市流行"],
        discovery_level=0.5,
    ),
    "sleep-classical": UserContext(
        user_id="eval",
        genres=["Classical", "Film Score"],
        moods=["Calm"],
        contexts=["睡前"],
        preferred_artists=["久石让", "坂本龙一"],
        discovery_level=0.4,
    ),
    "indie-rock": UserContext(
        user_id="eval",
        genres=["Indie Rock", "Alternative"],
        preferred_artists=["Radiohead", "万能青年旅店"],
        discovery_level=0.8,
    ),
    "new-listener": UserContext(user_id="eval", discovery_level=0.5),
}


def main(names: list[str]) -> None:
    settings = ProviderSettings.from_env().for_live_capability()
    settings.credential_for("deepseek")
    ledger = UsageLedger()
    calls = {"count": 0}

    def factory() -> DeepSeekLLMProvider:
        calls["count"] += 1
        return DeepSeekLLMProvider(settings, ledger=ledger)

    planner = ProviderBackedRecommendationPlanner(factory)
    for name in names or list(PROFILES):
        calls["count"] = 0
        context = PROFILES[name]
        ideas = planner.generate_program_ideas(context)
        stations = Counter(idea.station.value if idea.station else "-" for idea in ideas)
        print(f"\n=== {name}  ({len(ideas)} ideas, stations {dict(stations)})")
        for idea in ideas:
            station = idea.station.value if idea.station else "-"
            print(f"  [{station:8}] {idea.title}   <{idea.cover_title}>  subject={idea.subject}")
        problems = batch_problems(ideas)
        print("  remaining problems:", problems or "none")


if __name__ == "__main__":
    unknown = [name for name in sys.argv[1:] if name not in PROFILES]
    if unknown:
        raise SystemExit(f"unknown profile(s) {unknown}; choose from {list(PROFILES)}")
    main(sys.argv[1:])

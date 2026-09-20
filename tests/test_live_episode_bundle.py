from argparse import Namespace
from types import SimpleNamespace

from scripts import live_episode_probe


class BundleEpisode:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "id": "assembled-1",
            "segments": [
                {
                    "id": "track-1",
                    "audio_source_url": "/api/audio/audius/track-1",
                }
            ],
        }


def test_episode_bundle_keeps_browser_playback_payload_and_safe_metadata() -> None:
    result = SimpleNamespace(
        playable_episode=BundleEpisode(),
        duration_summary=SimpleNamespace(total_seconds=1200),
    )
    arguments = Namespace(
        topic="从方大同出发",
        episode_title="从方大同出发：听懂 Soul / R&B",
        episode_seed_id=None,
    )

    bundle = live_episode_probe._episode_bundle(result, arguments)

    assert bundle["seed_id"].startswith("live-")
    assert bundle["title"] == "从方大同出发：听懂 Soul / R&B"
    assert bundle["topic"] == "从方大同出发"
    assert bundle["estimated_duration_seconds"] == 1200
    assert bundle["playable_episode"]["segments"][0]["audio_source_url"] == (
        "/api/audio/audius/track-1"
    )

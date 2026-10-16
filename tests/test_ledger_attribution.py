"""The opening host's voice and the proposal planner are recorded in the ledger the usage report reads.

A real run (docs/research/dialogue-radio-2026-10/programme-acceptance-20261015.md) showed 18 DeepSeek and
6 MiniMax calls started but 17 and 5 stored: the proposal planner and the MiniMax provider built for the
API each had a ledger of their own.  These tests run the real providers over a faked network boundary and
let them record their own events; nothing here writes to the shared ledger by hand.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from wavecast.proposals import ProposalGenerationRequest
from wavecast.providers.config import ProviderSettings
from wavecast.storage import LocalObjectStorageProvider

from services.api import main as api_module

REPO = Path(__file__).resolve().parents[1]


def test_the_assembled_api_gives_the_voice_and_the_planner_the_shared_ledger() -> None:
    """Import the real module under a live-like configuration (no request is made at import)."""

    code = (
        "import json, sys\n"
        f"sys.path[:0] = [{str(REPO / 'backend')!r}, {str(REPO)!r}]\n"
        "from services.api import main as api\n"
        "shared = api._usage_ledger()\n"
        "print(json.dumps({'tts': api._tts_provider.ledger is shared,"
        " 'planner': api.proposal_generator.llm.ledger is shared}))\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "WAVECAST_PROVIDER_MODE": "live",
        "WAVECAST_RECOMMENDATION_PLANNER": "deterministic",
        "WAVECAST_MUSIC_PROVIDER": "mock",
        "WAVECAST_TTS_PROVIDER": "minimax",
        "WAVECAST_PROPOSAL_PLANNER": "deepseek",
        "MINIMAX_API_KEY": "placeholder",
        "MINIMAX_TTS_VOICE_ID": "placeholder",
        "DEEPSEEK_API_KEY": "placeholder",
        "ARK_API_KEY": "placeholder",
        "EXA_API_KEY": "placeholder",
        "TAVILY_API_KEY": "placeholder",
    }
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=False
    )

    assert done.returncode == 0, done.stderr[-800:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"tts": True, "planner": True}


def _minimax_over_a_fake_network(tmp_requests: list[httpx.Request], storage):  # type: ignore[no-untyped-def]
    settings = ProviderSettings(mode="live", minimax_api_key="k", minimax_tts_voice_id="v")

    def handler(request: httpx.Request) -> httpx.Response:
        tmp_requests.append(request)
        return httpx.Response(
            200,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "data": {"audio": "00010203", "status": 2},
                "extra_info": {"audio_length": 2052, "audio_format": "mp3", "usage_characters": 52},
            },
        )

    provider = api_module._build_tts_provider(settings, storage, api_module._usage_ledger())
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    materializer = api_module._build_narration_materializer(
        settings, provider, storage, api_module._usage_ledger()
    )
    return provider, materializer


def test_the_opening_hosts_voice_reaches_the_episode_report_through_the_real_provider(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    requests: list[httpx.Request] = []
    # An empty store: a cached line would be served without a request (and recorded as a cache hit).
    provider, materializer = _minimax_over_a_fake_network(
        requests, LocalObjectStorageProvider(tmp_path / "audio")
    )
    monkeypatch.setattr(api_module, "narration_materializer", materializer)
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "ledger-attribution-opening"}

    batch = client.post(
        "/api/program-proposals",
        json={"prompt": "something to listen to", "count": 1, "duration_intent": "SHORT"},
        headers=owner,
    )
    assert batch.status_code == 200, batch.text
    created = client.post(f"/api/episodes/from-seed/{batch.json()['proposals'][0]['id']}", headers=owner)
    assert created.status_code == 200, created.text
    episode_id = created.json()["id"]
    asyncio.run(api_module._usage_ledger().flush())  # noqa: SLF001

    report = client.get(f"/api/episodes/{episode_id}/usage", headers=owner).json()
    stored = asyncio.run(api_module._usage_event_store.load(episode_id))  # noqa: SLF001

    assert len(requests) == 1  # the opening host really went through the provider
    voice = [e for e in stored if e.provider == "minimax" and e.operation == "tts"]
    assert [e.usage_characters for e in voice] == [52]  # persisted, so a restart keeps it
    assert report["providers"] is not None and report["stored_events"] >= 1
    asyncio.run(provider.client.aclose())


def test_a_proposals_cost_is_recorded_under_its_own_id_and_reported_apart(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    live = ProviderSettings(
        mode="live", deepseek_api_key="k", proposal_planner="deepseek", music_provider="mock"
    )
    generator = api_module._build_proposal_generator(live, api_module._usage_ledger())
    draft = {
        "proposals": [
            {
                "short_description": "a short hour of quiet songs",
                "editorial_route": ["first", "second"],
                "opening_track_candidates": [{"artist": "Mira Fields", "title": "Neon First Light"}],
                "title": "Quiet songs",
            }
        ]
    }

    class Responses:
        async def create(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text=json.dumps(draft))],
                    )
                ],
                usage=SimpleNamespace(input_tokens=11, output_tokens=5),
                _request_id="r",
            )

    generator.llm.client = SimpleNamespace(responses=Responses())
    monkeypatch.setattr(api_module, "proposal_generator", generator)
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "ledger-attribution-proposal"}

    batch = client.post(
        "/api/program-proposals",
        json={"prompt": "quiet songs for an hour", "count": 1, "duration_intent": "SHORT"},
        headers=owner,
    )
    assert batch.status_code == 200, batch.text
    proposal_id = batch.json()["proposals"][0]["id"]
    created = client.post(f"/api/episodes/from-seed/{proposal_id}", headers=owner)
    assert created.status_code == 200, created.text
    episode_id = created.json()["id"]
    asyncio.run(api_module._usage_ledger().flush())  # noqa: SLF001

    planner_events = api_module._usage_ledger().for_scope(proposal_id)  # noqa: SLF001
    report = client.get(f"/api/episodes/{episode_id}/usage", headers=owner).json()

    assert [(e.provider, e.input_tokens) for e in planner_events] == [("deepseek", 11)]
    assert report["proposal"] is not None
    assert report["proposal"]["providers"] is not None
    # the episode's own report does not count the proposal's call, and the proposal is shown apart
    own = report["providers"] or {}
    assert "program_proposal" not in json.dumps(own)
    assert "program_proposal" in json.dumps(report["proposal"]["providers"])
    assert ProposalGenerationRequest  # the request type the endpoint validated


def test_choosing_the_second_of_two_cards_still_finds_the_batchs_cost_after_a_restart(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """One call produced both cards: its cost is shared by them, stored once, found from either."""

    from wavecast.providers.usage import UsageLedger

    live = ProviderSettings(
        mode="live", deepseek_api_key="k", proposal_planner="deepseek", music_provider="mock"
    )
    generator = api_module._build_proposal_generator(live, api_module._usage_ledger())
    one = {
        "short_description": "a short hour of quiet songs",
        "editorial_route": ["first", "second"],
        "opening_track_candidates": [{"artist": "Mira Fields", "title": "Neon First Light"}],
    }
    draft = {"proposals": [{**one, "title": "Quiet songs"}, {**one, "title": "More quiet songs"}]}

    class Responses:
        async def create(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text=json.dumps(draft))],
                    )
                ],
                usage=SimpleNamespace(input_tokens=21, output_tokens=9),
                _request_id="r",
            )

    generator.llm.client = SimpleNamespace(responses=Responses())
    monkeypatch.setattr(api_module, "proposal_generator", generator)
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "ledger-attribution-batch"}

    batch = client.post(
        "/api/program-proposals",
        json={"prompt": "quiet songs for an hour", "count": 2, "duration_intent": "SHORT"},
        headers=owner,
    )
    assert batch.status_code == 200, batch.text
    first, second = (item["id"] for item in batch.json()["proposals"])
    created = client.post(f"/api/episodes/from-seed/{second}", headers=owner)
    assert created.status_code == 200, created.text
    asyncio.run(api_module._usage_ledger().flush())  # noqa: SLF001

    # A new process: nothing of the call is in memory, only what was stored.
    monkeypatch.setattr(api_module, "_usage_ledger", lambda: UsageLedger())
    report = client.get(f"/api/episodes/{created.json()['id']}/usage", headers=owner).json()

    assert report["proposal"] is not None, "the second card must still find the batch's cost"
    assert report["proposal"]["shared_by_proposals"] == 2
    assert "program_proposal" in json.dumps(report["proposal"]["providers"])
    # stored once, under the first id: the second card has no copy of its own
    stored_first = asyncio.run(api_module._usage_event_store.load(first))  # noqa: SLF001
    stored_second = asyncio.run(api_module._usage_event_store.load(second))  # noqa: SLF001
    assert [e.input_tokens for e in stored_first] == [21]
    assert stored_second == []

import asyncio

import pytest
from wavecast.assembly import (
    EpisodeAssemblyError,
    LiveEpisodeAssemblyRequest,
    create_episode_assembly_service,
)
from wavecast.intelligence.curation import CuratorContractError


def test_curator_failure_preserves_safe_pre_curator_research_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = create_episode_assembly_service()

    class FailingCurator:
        llm = None

        async def curate(self, *_args: object, **_kwargs: object) -> object:
            raise CuratorContractError(
                "curator contract validation failed",
                reason_code="curator_chapter_evidence_scope_invalid",
                diagnostics=[
                    {
                        "chapter_index": 2,
                        "reference_kind": "chapter_evidence",
                        "dropped_reference_count": 1,
                        "remaining_reference_count": 0,
                    }
                ],
            )

    service.background_pipeline.curator = FailingCurator()  # type: ignore[assignment]

    with pytest.raises(EpisodeAssemblyError) as failure:
        asyncio.run(
            service.assemble(
                LiveEpisodeAssemblyRequest(topic="fixture", anchor_tracks=["Neon First Light"])
            )
        )

    error = failure.value
    assert error.reason_code == "curator_chapter_evidence_scope_invalid"
    snapshot = error.diagnostics["research_snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["research_plan"] is not None
    assert snapshot["research_evidence"]
    assert snapshot["trace"]
    assert "background_started" in {event["name"] for event in snapshot["trace"]}
    assert snapshot["usage_by_stage"] == {}
    serialized = str(error.diagnostics)
    assert "prompt" not in serialized
    assert "response" not in serialized

    asyncio.run(service.aclose())

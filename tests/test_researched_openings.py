"""Opening reliability and evidence handoff, without paid providers."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from wavecast.intelligence.models import FastResearchInput
from wavecast.intelligence.research import FastResearchService
from wavecast.models.episode import LiveEpisode
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.proposals import (
    REASON_CATALOG_UNAVAILABLE,
    OpeningTrackCandidate,
    ProgramProposal,
    ProgramProposalDraft,
    ProgramProposalDraftBatch,
    ProgramProposalGenerationError,
    ProposalGenerationRequest,
    shared_copy,
)
from wavecast.providers.errors import ProviderSchemaValidationError

from tests.dialogue_fixtures import evidence
from tests.test_program_proposals import _live_generator


def batch(*, size=1, missing=False):
    return ProgramProposalDraftBatch(
        proposals=[
            ProgramProposalDraft(
                title="听节奏里的松弛",
                short_description="从同一个律动问题出发，听不同歌曲的处理。",
                editorial_route=["找到入口", "听见不同"],
                allow_artist_fallback=False,
                opening_track_candidates=[
                    OpeningTrackCandidate(
                        artist="Missing Artist" if missing else "Mira Fields",
                        title="Missing Song" if missing else "Neon First Light",
                    )
                ],
            )
            for _ in range(size)
        ]
    )


class Replies:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.prompts = []

    async def structured(self, prompt, output_type, **kwargs):
        self.prompts.append(prompt)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def generator_with(*replies):
    generator, _ = _live_generator(batch())
    llm = Replies(*replies)
    generator.llm = llm
    return generator, llm


@pytest.mark.parametrize("requested,returned", [(1, 2), (2, 3)])
def test_surplus_drafts_do_not_fail_or_materialize_extra_programmes(requested, returned):
    generator, llm = generator_with(batch(size=returned))
    proposals = asyncio.run(
        generator.generate(
            ProposalGenerationRequest(
                prompt="听一点节奏舒展的音乐",
                count=requested,
            )
        )
    )
    assert len(proposals) == requested
    assert len({p.id for p in proposals}) == requested
    assert len(llm.prompts) == 1


def test_short_batch_gets_one_repair_with_explicit_count():
    generator, llm = generator_with(batch(), batch(size=2))
    proposals = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="两个方向", count=2))
    )
    assert len(proposals) == 2
    assert len(llm.prompts) == 2
    assert "previous response contained 1" in llm.prompts[1]


def test_schema_and_count_repairs_share_one_budget():
    generator, llm = generator_with(ProviderSchemaValidationError("bad shape"), batch())
    with pytest.raises(ProgramProposalGenerationError, match="proposal_count_mismatch"):
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="两个方向", count=2)))
    assert len(llm.prompts) == 2


def test_unresolved_opening_gets_one_new_candidate_set():
    generator, llm = generator_with(batch(missing=True), batch())
    proposal = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="想找类似感觉的歌"))
    )[0]
    assert proposal.opening_track_ref == "mock:opening"
    assert len(llm.prompts) == 2
    assert "SAME listening direction" in llm.prompts[1]
    assert "Missing Artist" in llm.prompts[1]


def test_catalog_outage_does_not_trigger_another_model_call(monkeypatch):
    generator, llm = generator_with(batch(missing=True))
    monkeypatch.setattr(
        generator, "_classify_unresolved", AsyncMock(return_value=REASON_CATALOG_UNAVAILABLE)
    )
    with pytest.raises(ProgramProposalGenerationError, match=REASON_CATALOG_UNAVAILABLE):
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="想找类似感觉的歌")))
    assert len(llm.prompts) == 1


def test_catalog_recovery_cannot_add_a_third_call_after_schema_repair():
    generator, llm = generator_with(ProviderSchemaValidationError("bad shape"), batch(missing=True))
    with pytest.raises(ProgramProposalGenerationError, match="opening_track_not_found"):
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="想找类似感觉的歌")))
    assert len(llm.prompts) == 2


def test_catalog_repair_timeout_cancels_the_call_and_preserves_safe_failure(monkeypatch):
    from wavecast import proposals as module

    cancelled = []

    class SlowRepair(Replies):
        async def structured(self, prompt, output_type, **kwargs):
            if self.prompts:
                self.prompts.append(prompt)
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)
            return await super().structured(prompt, output_type, **kwargs)

    generator, _ = generator_with(batch(missing=True))
    llm = SlowRepair(batch(missing=True))
    generator.llm = llm
    monkeypatch.setattr(module, "_RECOVERY_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(ProgramProposalGenerationError, match="opening_track_not_found"):
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="相近的歌")))
    assert len(llm.prompts) == 2
    assert cancelled == [True]


def test_research_survives_persistence_and_start_but_stays_out_of_public_json(monkeypatch):
    generator, llm = generator_with(batch())
    facts = evidence()
    monkeypatch.setattr(generator, "_research_opening", AsyncMock(return_value=facts))
    proposal = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="爱情表达里的选择"))
    )[0]
    assert facts[0].claim_or_excerpt in llm.prompts[0]
    restored = ProgramProposal.model_validate(proposal.persistence_payload())
    assert restored.opening_evidence == facts
    assert "opening_evidence" not in proposal.model_dump(mode="json")
    seed = restored.to_episode_seed()
    assert "opening_evidence" not in seed.model_dump(mode="json")
    episode = EpisodeOrchestrator(InMemoryEpisodeRepository()).start(seed)
    assert episode.opening_evidence == facts
    assert "opening_evidence" not in episode.model_dump(mode="json")
    # Shared content is constructed from its public fields; research and private queries stay private.
    assert not shared_copy(proposal, new_id="shared").opening_evidence
    assert not ProgramProposal.model_validate(proposal.model_dump()).opening_evidence
    assert not LiveEpisode.model_validate(episode.model_dump()).opening_evidence


def test_cancelled_fast_research_leaves_no_search_tasks_running():
    async def check():
        started, cancelled = [], []
        ready = asyncio.Event()

        class BlockingSearch:
            async def search(self, query, **kwargs):
                started.append(query)
                if len(started) == 2:
                    ready.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(query)

        search = BlockingSearch()
        service = FastResearchService(discovery=search, research=search)
        task = asyncio.create_task(
            service.run(
                FastResearchInput(
                    topic="爵士",
                    desired_duration_seconds=2100,
                )
            )
        )
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(cancelled) == 2

    asyncio.run(check())


def test_research_input_carries_editorial_intent_but_does_not_serialize_private_evidence():
    request = FastResearchInput(
        topic="椎名林檎",
        editorial_brief="只听爵士编配这一面",
        prior_evidence=evidence(),
        desired_duration_seconds=2100,
    )
    from wavecast.intelligence.research import build_fast_queries

    assert all("只听爵士编配这一面" in query for query in build_fast_queries(request))
    assert "prior_evidence" not in request.model_dump()


def test_fourth_candidate_is_checked_before_spending_on_a_repair():
    drafts = batch(missing=True)
    draft = drafts.proposals[0]
    draft.opening_track_candidates = [
        OpeningTrackCandidate(artist="Missing Artist", title=f"Missing {i}") for i in range(3)
    ] + batch().proposals[0].opening_track_candidates
    generator, llm = generator_with(drafts)
    proposal = asyncio.run(generator.generate(ProposalGenerationRequest(prompt="听一些相近的歌")))[
        0
    ]
    assert proposal.opening_track_ref == "mock:opening"
    assert len(llm.prompts) == 1


def test_research_deadline_keeps_ready_sources_and_cancels_slow_search():
    from wavecast.providers.contracts import SearchResult

    cancelled = []

    class Ready:
        async def search(self, query, **kwargs):
            return [
                SearchResult(
                    title="Recording notes",
                    url="https://example.test/notes",
                    snippet="Notes about the actual recording",
                    provider="exa",
                    query=query,
                )
            ]

    class Slow:
        async def search(self, query, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    result = asyncio.run(
        FastResearchService(
            discovery=Ready(),
            research=Slow(),
            deadline_seconds=0.01,
        ).run(FastResearchInput(topic="音乐", desired_duration_seconds=2100))
    )
    assert result.bundle.evidence
    assert cancelled == [True]


def test_fast_and_full_planning_receive_the_same_durable_opening_evidence(tmp_path):
    from wavecast.assembly import LiveEpisodeAssemblyRequest, _locked_successor_fast_result
    from wavecast.intelligence.models import FastStartPlan, ResolvedTrack

    from tests.test_episode_assembly import RecordingAssemblyLLM, service

    llm = RecordingAssemblyLLM()
    assembly = service(tmp_path, llm)
    facts = evidence()
    opening = ResolvedTrack(
        track_ref="mock:opening", canonical_artist="Mira Fields", canonical_title="Neon First Light"
    )
    request = LiveEpisodeAssemblyRequest(
        topic="一位音乐人的爵士切面",
        editorial_brief="只听爵士编配这一面",
        opening_evidence=facts,
    )
    generated = asyncio.run(assembly.prepare_fast_successor(request, opening_track=opening))
    assert generated is not None
    planner_prompt = next(c["prompt"] for c in llm.calls if c["output_type"] is FastStartPlan)
    assert request.editorial_brief in planner_prompt
    assert '"anchor_artists":["Mira Fields"]' in planner_prompt
    assert facts[0].claim_or_excerpt in planner_prompt
    assert set(item.id for item in facts).issubset(
        {item.id for item in generated.research_evidence}
    )
    locked = _locked_successor_fast_result(
        FastResearchInput(
            topic=request.topic,
            editorial_brief=request.editorial_brief,
            prior_evidence=generated.research_evidence,
            desired_duration_seconds=2100,
        ),
        opening,
        request_id="offline",
    )
    assert locked.bundle.evidence == generated.research_evidence


@pytest.mark.parametrize("allow", [False, True])
def test_same_artist_bootstrap_requires_an_explicit_editorial_allowance(tmp_path, allow):
    from wavecast.assembly import LiveEpisodeAssemblyRequest
    from wavecast.intelligence.models import FastStartPlan, ResolvedTrack

    from tests.test_episode_assembly import RecordingAssemblyLLM, service

    class NoCandidateLLM(RecordingAssemblyLLM):
        async def structured(self, prompt, output_type, **kwargs):
            result = await super().structured(prompt, output_type, **kwargs)
            if output_type is FastStartPlan:
                return result.model_copy(
                    update={
                        "selected_next_track": None,
                        "next_candidates": [],
                        "allow_artist_fallback": allow,
                    }
                )
            return result

    assembly = service(tmp_path, NoCandidateLLM())
    search = AsyncMock(return_value=[])
    assembly.retrieval.search = search
    result = asyncio.run(
        assembly.prepare_fast_successor(
            LiveEpisodeAssemblyRequest(topic="只听爵士编配这一面"),
            opening_track=ResolvedTrack(
                track_ref="mock:opening",
                canonical_artist="Mira Fields",
                canonical_title="Neon First Light",
            ),
        )
    )
    assert result is None  # Full route planning can take over; no off-topic song is committed.
    assert search.await_count == int(allow)

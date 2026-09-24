import asyncio

from wavecast.proposals import (
    DeterministicMockProgramProposalGenerator,
    DurationIntent,
    InMemoryProgramProposalRepository,
    ProposalGenerationRequest,
)


def test_mock_proposal_generation_is_deterministic_and_seed_compatible() -> None:
    generator = DeterministicMockProgramProposalGenerator()
    request = ProposalGenerationRequest(
        prompt="下雨的夜晚，想听温柔的爵士，带一点城市感",
        duration_intent=DurationIntent.SHORT,
    )

    first = asyncio.run(generator.generate(request))[0]
    second = asyncio.run(generator.generate(request))[0]

    assert first.model_dump(exclude={"created_at"}) == second.model_dump(exclude={"created_at"})
    assert first.id.startswith("proposal-")
    assert first.estimated_duration_seconds == 22 * 60
    assert "Jazz" in first.genre_tags
    assert len(first.editorial_route) >= 2

    seed = first.to_episode_seed()
    assert seed.id == first.id
    assert seed.topic == request.prompt
    assert seed.opening_track_ref == "mock:opening"
    assert seed.cover == first.cover


def test_mock_generator_can_return_a_bounded_proposal_batch() -> None:
    proposals = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(
                prompt="从合成器流行出发去夜间兜风",
                duration_intent=DurationIntent.STANDARD,
                count=3,
            )
        )
    )

    assert len(proposals) == 3
    assert len({proposal.id for proposal in proposals}) == 3
    assert all(proposal.estimated_duration_seconds == 42 * 60 for proposal in proposals)
    assert all(proposal.title for proposal in proposals)


def test_in_memory_proposal_repository_keeps_generated_programs() -> None:
    proposal = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="Persona 游戏音乐")
        )
    )[0]
    repository = InMemoryProgramProposalRepository()

    assert repository.get(proposal.id) is None
    repository.save_many([proposal])

    assert repository.get(proposal.id) == proposal

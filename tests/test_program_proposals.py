import asyncio

import pytest
from pydantic import BaseModel, ValidationError
from wavecast.proposals import (
    DeterministicMockProgramProposalGenerator,
    DurationIntent,
    InMemoryProgramProposalRepository,
    LLMProgramProposalGenerator,
    OpeningTrackCandidate,
    ProgramProposalDraft,
    ProgramProposalDraftBatch,
    ProgramProposalGenerationError,
    ProposalGenerationRequest,
)
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.fakes import MockMusicProvider
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService


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
    assert first.opening_track_duration_seconds == 22
    assert seed.opening_track_duration_seconds == 22
    assert seed.opening_narration_text == first.opening_narration_text
    assert seed.opening_narration_text
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


def test_proposal_request_normalizes_outer_whitespace_and_rejects_blank_prompt() -> None:
    request = ProposalGenerationRequest(prompt="  night drive  ")

    assert request.prompt == "night drive"
    with pytest.raises(ValidationError):
        ProposalGenerationRequest(prompt="   ")


def test_llm_draft_rejects_blank_identity_and_editorial_copy() -> None:
    with pytest.raises(ValidationError):
        OpeningTrackCandidate(artist="   ", title="Neon First Light")
    with pytest.raises(ValidationError):
        ProgramProposalDraft(
            title="   ",
            short_description="valid description",
            editorial_route=["start", "finish"],
            opening_track_candidates=[
                OpeningTrackCandidate(artist="Mira Fields", title="Neon First Light")
            ],
        )
    with pytest.raises(ValidationError):
        ProgramProposalDraft(
            title="valid title",
            short_description="valid description",
            editorial_route=["start", "   "],
            opening_track_candidates=[
                OpeningTrackCandidate(artist="Mira Fields", title="Neon First Light")
            ],
        )


class _ProposalLLM:
    def __init__(self, batch: ProgramProposalDraftBatch) -> None:
        self.batch = batch
        self.prompt = ""

    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport,
        profile: InferenceProfile,
        stage: str | None = None,
    ) -> BaseModel:
        del transport, profile, stage
        assert output_type is ProgramProposalDraftBatch
        self.prompt = prompt
        return self.batch


def _live_generator(
    batch: ProgramProposalDraftBatch,
) -> tuple[LLMProgramProposalGenerator, _ProposalLLM]:
    llm = _ProposalLLM(batch)
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"mock": MockMusicProvider()}, preference=("mock",))
    )
    return LLMProgramProposalGenerator(llm, retrieval), llm


def test_llm_generator_resolves_opening_track_before_creating_proposal() -> None:
    generator, llm = _live_generator(
        ProgramProposalDraftBatch(
            proposals=[
                ProgramProposalDraft(
                    title="夜色转场",
                    short_description="从柔和的夜色进入更有推进感的电子声场。",
                    editorial_route=["先放慢速度", "沿着夜色推进", "留一个明亮出口"],
                    genre_tags=["Electronic"],
                    mood_tags=["夜晚", "流动"],
                    opening_host_note="先听它把夜色拉开一点，我们再顺着这股空间感往前走。",
                    opening_track_candidates=[
                        OpeningTrackCandidate(
                            artist="Imaginary Artist", title="Imaginary Song"
                        ),
                        OpeningTrackCandidate(
                            artist="Signal Garden", title="Midnight Transfer"
                        ),
                    ],
                )
            ]
        )
    )

    proposal = asyncio.run(
        generator.generate(
            ProposalGenerationRequest(
                prompt="夜里开车，想听一点有空间感的电子乐",
                duration_intent=DurationIntent.DEEP,
                taste_context="偏爱有律动但不过分激烈的声音",
            )
        )
    )[0]

    assert proposal.opening_track_ref == "mock:bridge"
    assert proposal.opening_track_artist == "Signal Garden"
    assert proposal.opening_track_title == "Midnight Transfer"
    assert proposal.opening_track_duration_seconds == 24
    assert proposal.to_episode_seed().opening_track_duration_seconds == 24
    assert proposal.opening_narration_text is not None
    assert "Signal Garden" in proposal.opening_narration_text
    assert "Midnight Transfer" in proposal.opening_narration_text
    assert "先听它把夜色拉开一点" in proposal.opening_narration_text
    assert proposal.anchor_artists == ["Signal Garden"]
    assert proposal.estimated_duration_seconds == 72 * 60
    assert "Taste context:" in llm.prompt
    assert "opening_host_note" in llm.prompt
    opening_schema = ProgramProposalDraftBatch.model_json_schema()["$defs"][
        "OpeningTrackCandidate"
    ]["properties"]
    assert "track_ref" not in opening_schema


def test_llm_generator_falls_back_to_playable_song_by_same_artist() -> None:
    generator, _llm = _live_generator(
        ProgramProposalDraftBatch(
            proposals=[
                ProgramProposalDraft(
                    title="同艺人开场兜底",
                    short_description="精确歌名不可用时仍然从同一艺人的真实目录开始。",
                    editorial_route=["从艺人气质出发", "再向相邻声音展开"],
                    opening_track_candidates=[
                        OpeningTrackCandidate(
                            artist="Signal Garden",
                            title="Definitely Not In Catalog",
                        )
                    ],
                )
            ]
        )
    )

    proposal = asyncio.run(
        generator.generate(
            ProposalGenerationRequest(prompt="想听 Signal Garden 风格的夜间电子乐")
        )
    )[0]

    assert proposal.opening_track_ref == "mock:bridge"
    assert proposal.opening_track_artist == "Signal Garden"
    assert proposal.opening_track_title == "Midnight Transfer"
    assert proposal.opening_track_duration_seconds == 24


def test_llm_generator_fails_closed_when_no_opening_candidate_resolves() -> None:
    generator, _llm = _live_generator(
        ProgramProposalDraftBatch(
            proposals=[
                ProgramProposalDraft(
                    title="不存在的开场",
                    short_description="这个草稿没有任何可验证的开场曲。",
                    editorial_route=["开始", "继续"],
                    opening_track_candidates=[
                        OpeningTrackCandidate(
                            artist="Imaginary Artist", title="Imaginary Song"
                        )
                    ],
                )
            ]
        )
    )

    with pytest.raises(ProgramProposalGenerationError, match="opening_track_unresolved"):
        asyncio.run(
            generator.generate(
                ProposalGenerationRequest(prompt="给我一个无法解析的测试节目")
            )
        )


def test_llm_generator_requires_exact_requested_proposal_count() -> None:
    generator, _llm = _live_generator(
        ProgramProposalDraftBatch(
            proposals=[
                ProgramProposalDraft(
                    title="只有一个",
                    short_description="模型少返回了一个 proposal。",
                    editorial_route=["开始", "结束"],
                    opening_track_candidates=[
                        OpeningTrackCandidate(
                            artist="Mira Fields", title="Neon First Light"
                        )
                    ],
                )
            ]
        )
    )

    with pytest.raises(ProgramProposalGenerationError, match="proposal_count_mismatch"):
        asyncio.run(
            generator.generate(
                ProposalGenerationRequest(prompt="给我两个节目", count=2)
            )
        )


class _VariantCatalog:
    """Catalog that spells the artist in Japanese shinjitai, unlike the proposer."""

    def __init__(self) -> None:
        self.tracks = [
            TrackMetadata(
                track_ref="netease:442682",
                artist="久石譲",
                title="天空の城ラピュタ",
                duration_seconds=235,
                playable=True,
            ),
            TrackMetadata(
                track_ref="netease:28457548",
                artist="久石譲",
                title="娜乌西卡安魂曲",
                duration_seconds=240,
                playable=True,
            ),
        ]

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        return self.tracks[:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return next(track for track in self.tracks if track.track_ref == track_ref)


def _variant_generator(
    batch: ProgramProposalDraftBatch,
) -> LLMProgramProposalGenerator:
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": _VariantCatalog()}, preference=("netease",))
    )
    return LLMProgramProposalGenerator(_ProposalLLM(batch), retrieval)


def _hisaishi_draft(*candidates: OpeningTrackCandidate) -> ProgramProposalDraftBatch:
    return ProgramProposalDraftBatch(
        proposals=[
            ProgramProposalDraft(
                title="久石让的宫崎骏配乐",
                short_description="沿着旋律听电影背后的故事。",
                editorial_route=["从开场曲进入", "再展开配乐的线索"],
                opening_track_candidates=list(candidates),
            )
        ]
    )


def test_opening_track_resolves_when_proposer_uses_a_script_variant_of_the_artist() -> None:
    generator = _variant_generator(
        _hisaishi_draft(
            OpeningTrackCandidate(artist="久石让", title="娜乌西卡安魂曲"),
        )
    )

    proposal = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="久石让为宫崎骏电影写的配乐"))
    )[0]

    assert proposal.opening_track_ref == "netease:28457548"
    assert proposal.opening_track_artist == "久石譲"


def test_same_artist_fallback_matches_a_script_variant_of_the_artist() -> None:
    generator = _variant_generator(
        _hisaishi_draft(
            OpeningTrackCandidate(artist="久石让", title="Definitely Not In Catalog"),
        )
    )

    proposal = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="久石让为宫崎骏电影写的配乐"))
    )[0]

    assert proposal.opening_track_artist == "久石譲"
    assert proposal.opening_track_ref in {"netease:442682", "netease:28457548"}

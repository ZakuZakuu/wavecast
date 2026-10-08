import asyncio

import pytest
from pydantic import BaseModel, ValidationError
from wavecast.catalog_pool import CatalogPoolBuilder
from wavecast.language import OutputLanguage
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
from wavecast.providers.errors import ProviderUnavailableError
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

    with pytest.raises(ProgramProposalGenerationError, match="opening_track_not_found"):
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


class _UnplayableCatalog(_VariantCatalog):
    """Every track exists in the catalog but none can be played (e.g. licensing)."""

    def __init__(self) -> None:
        super().__init__()
        self.tracks = [track.model_copy(update={"playable": False}) for track in self.tracks]


class _DownCatalog:
    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        raise ProviderUnavailableError("music upstream unavailable")

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        raise ProviderUnavailableError("music upstream unavailable")


def _failure_reason(catalog: object, artist: str, title: str) -> str:
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))  # type: ignore[dict-item]
    )
    generator = LLMProgramProposalGenerator(
        _ProposalLLM(_hisaishi_draft(OpeningTrackCandidate(artist=artist, title=title))), retrieval
    )
    with pytest.raises(ProgramProposalGenerationError) as failure:
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="久石让")))
    return failure.value.reason


def test_failure_reason_says_unplayable_when_the_track_exists_but_cannot_be_played() -> None:
    assert (
        _failure_reason(_UnplayableCatalog(), "久石让", "娜乌西卡安魂曲")
        == "opening_track_unplayable"
    )


def test_failure_reason_says_catalog_unavailable_when_the_catalog_is_down() -> None:
    assert _failure_reason(_DownCatalog(), "久石让", "娜乌西卡安魂曲") == "catalog_unavailable"


def test_failure_reason_says_not_found_when_nothing_matches() -> None:
    assert _failure_reason(_VariantCatalog(), "Nobody", "Nothing") == "opening_track_not_found"


class _DeepCatalog:
    """Popular songs rank first and cannot be played; a playable one sits past the first five."""

    def __init__(self) -> None:
        self.tracks = [
            TrackMetadata(
                track_ref=f"netease:{index}",
                artist="椎名林檎",
                title=f"Hit {index}",
                duration_seconds=200,
                playable=index == 7,
            )
            for index in range(8)
        ]

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        # Like the real sidecar, search results never carry playability.
        return [track.model_copy(update={"playable": False}) for track in self.tracks[:limit]]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return next(track for track in self.tracks if track.track_ref == track_ref)


def _deep_generator(*, with_pool: bool) -> LLMProgramProposalGenerator:
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": _DeepCatalog()}, preference=("netease",))  # type: ignore[dict-item]
    )
    return LLMProgramProposalGenerator(
        _ProposalLLM(_hisaishi_draft(OpeningTrackCandidate(artist="椎名林檎", title="Hit 0"))),
        retrieval,
        pool_builder=CatalogPoolBuilder(retrieval) if with_pool else None,
    )


def test_without_the_pool_an_artist_whose_top_results_are_unplayable_fails() -> None:
    with pytest.raises(ProgramProposalGenerationError) as failure:
        asyncio.run(
            _deep_generator(with_pool=False).generate(ProposalGenerationRequest(prompt="椎名林檎"))
        )

    assert failure.value.reason == "opening_track_unplayable"


def test_the_pool_finds_a_playable_track_by_the_artist_beyond_the_first_results() -> None:
    proposal = asyncio.run(
        _deep_generator(with_pool=True).generate(ProposalGenerationRequest(prompt="椎名林檎"))
    )[0]

    assert proposal.opening_track_artist == "椎名林檎"
    assert proposal.opening_track_title == "Hit 7"
    assert proposal.opening_track_duration_seconds == 200


def test_the_pool_fallback_still_fails_when_the_artist_has_nothing_playable() -> None:
    class AllUnplayable(_DeepCatalog):
        def __init__(self) -> None:
            super().__init__()
            self.tracks = [track.model_copy(update={"playable": False}) for track in self.tracks]

    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": AllUnplayable()}, preference=("netease",))  # type: ignore[dict-item]
    )
    generator = LLMProgramProposalGenerator(
        _ProposalLLM(_hisaishi_draft(OpeningTrackCandidate(artist="椎名林檎", title="Hit 0"))),
        retrieval,
        pool_builder=CatalogPoolBuilder(retrieval),
    )

    with pytest.raises(ProgramProposalGenerationError) as failure:
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="椎名林檎")))

    assert failure.value.reason == "opening_track_unplayable"


def _english_request_draft_batch() -> ProgramProposalDraftBatch:
    return ProgramProposalDraftBatch(
        proposals=[
            ProgramProposalDraft(
                title="Night Drive",
                short_description="A slow electronic drive through the city.",
                editorial_route=["slow start", "build", "exit"],
                opening_host_note="Let the night open up first.",
                opening_track_candidates=[
                    OpeningTrackCandidate(artist="Signal Garden", title="Midnight Transfer")
                ],
            )
        ]
    )


def test_an_explicit_programme_language_reaches_the_proposal_prompt_and_the_seed() -> None:
    generator, llm = _live_generator(_english_request_draft_batch())

    proposal = asyncio.run(
        generator.generate(
            ProposalGenerationRequest(
                prompt="late night synth drive", output_language=OutputLanguage.ZH_CN
            )
        )
    )[0]

    assert "Simplified Chinese (zh-CN)" in llm.prompt
    assert "whatever language the request uses" in llm.prompt
    assert proposal.output_language is OutputLanguage.ZH_CN
    assert proposal.to_episode_seed().output_language is OutputLanguage.ZH_CN
    # The opening line follows the chosen language even though the request text is English.
    assert proposal.opening_narration_text is not None
    assert "我们先从" in proposal.opening_narration_text


def test_without_an_explicit_language_the_request_text_still_decides() -> None:
    generator, llm = _live_generator(_english_request_draft_batch())

    proposal = asyncio.run(
        generator.generate(ProposalGenerationRequest(prompt="late night synth drive"))
    )[0]

    assert "Match the listener's natural language." in llm.prompt
    assert proposal.output_language is OutputLanguage.AUTO
    assert proposal.opening_narration_text is not None
    assert "我们先从" not in proposal.opening_narration_text


def test_an_explicit_english_choice_overrides_a_chinese_request_for_the_opening_line() -> None:
    generator, _llm = _live_generator(_english_request_draft_batch())

    proposal = asyncio.run(
        generator.generate(
            ProposalGenerationRequest(prompt="夜里开车", output_language=OutputLanguage.EN_US)
        )
    )[0]

    assert proposal.opening_narration_text is not None
    assert "我们先从" not in proposal.opening_narration_text


def test_seeds_saved_before_the_language_field_default_to_auto() -> None:
    from wavecast.models.episode import EpisodeSeed

    proposal = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="Persona 游戏音乐")
        )
    )[0]
    payload = proposal.to_episode_seed().model_dump(mode="json")
    del payload["output_language"]

    assert EpisodeSeed.model_validate(payload).output_language is OutputLanguage.AUTO

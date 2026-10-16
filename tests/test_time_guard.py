"""An old page's "recently" is not today, a host has no memories, and a fetch time is no publication date."""

import asyncio
from datetime import UTC, datetime

from wavecast.intelligence.dialogue_pipeline import DialoguePipeline
from wavecast.intelligence.models import reliable_publication_date
from wavecast.intelligence.story_material import verify_material
from wavecast.intelligence.time_guard import has_relative_time, invents_experience
from wavecast.programme_date import programme_date

from tests.dialogue_fixtures import STORY_ID, TRACK_REF, clean_draft, evidence, material_draft
from tests.test_dialogue_pipeline import SLOT, material


def test_words_that_depend_on_when_they_are_said_are_found_and_the_just_played_song_is_not() -> None:
    for text in ("方大同上月底刚推出的新创作专辑《15》", "他最近狂练吉他", "这是目前最新的一张", "如今他已经"):
        assert has_relative_time(text), text
    for text in ("刚听完《如果爱》，接下来这首《因为你》", "2008 年发行的专辑", "他十五岁开始学吉他"):
        assert not has_relative_time(text), text


def test_a_host_claiming_to_have_researched_or_remembered_is_found() -> None:
    for text in ("我之前翻资料才知道", "我记得这首歌", "我小时候就听过", "我查了资料，原来是这样"):
        assert invents_experience(text), text
    assert not invents_experience("资料里写到这张专辑是 2008 年发行的")


def test_a_publication_date_is_kept_only_when_it_is_plausible() -> None:
    assert reliable_publication_date("2023-10-05T00:00:00.000Z") == "2023-10-05"
    for raw in (None, "", "yesterday", "0000-00-00", "1850-01-01", "2023-13-40"):
        assert reliable_publication_date(raw) is None


def test_the_programme_date_is_given_in_the_home_zone() -> None:
    assert programme_date(datetime(2026, 10, 16, 20, 30, tzinfo=UTC)) == "2026年10月17日"


def test_a_material_fact_with_a_relative_time_is_dropped() -> None:
    draft = material_draft()
    draft.facts[0].statement = "方大同最近推出了新专辑" + draft.facts[0].statement
    kept = verify_material(draft, evidence(), story_id=STORY_ID, recording_refs=[TRACK_REF])
    baseline = verify_material(material_draft(), evidence(), story_id=STORY_ID, recording_refs=[TRACK_REF])

    assert baseline is not None
    assert kept is None or len(kept.facts) == len(baseline.facts) - 1


def test_a_dialogue_with_a_relative_time_or_an_invented_memory_is_not_voiced() -> None:
    class Writer:
        def __init__(self, text: str) -> None:
            self.text = text

        async def write(self, material, slot, budget):  # type: ignore[no-untyped-def]
            draft = clean_draft()
            draft.turns[0].text = self.text
            return draft

    for text in ("他最近一直在练吉他。", "我之前翻资料才知道这件事。"):
        outcome = asyncio.run(DialoguePipeline(writer=Writer(text)).produce(material(), SLOT))  # type: ignore[arg-type]
        assert outcome.block is None and outcome.reason == "time_or_experience"


def test_the_dialogue_writer_gets_the_whole_previous_host_text_before_this_passages_material() -> None:
    from dataclasses import replace

    from wavecast.intelligence.dialogue_budget import dialogue_budget_for
    from wavecast.intelligence.dialogue_writer import DialogueWriter

    class Capture:
        prompts: list[str]

        def __init__(self) -> None:
            self.prompts = []

        async def structured(self, prompt, output_type, **_kwargs):  # type: ignore[no-untyped-def]
            self.prompts.append(prompt)
            return clean_draft()

    earlier = "\n".join(f"第{i}段主持词，方大同已经离世。" for i in range(200))  # far beyond a thousand characters
    llm = Capture()
    slot = replace(SLOT, previous_context=earlier)
    budget = dialogue_budget_for(slot.station)
    assert budget is not None

    asyncio.run(DialogueWriter(llm).write(material(), slot, budget))  # type: ignore[arg-type]

    prompt = llm.prompts[0]
    assert earlier in prompt  # verbatim, nothing cut
    assert prompt.index("节目日期") < prompt.index(earlier) < prompt.index("素材（JSON）")
    assert "事实依据仍然只来自下面的素材" in prompt


def test_the_single_voice_writer_gets_the_whole_previous_host_text_before_this_chapter() -> None:
    from wavecast.intelligence.models import OutputLanguage
    from wavecast.intelligence.writer import WriterService
    from wavecast.stations import StationId

    from tests.test_track_research import Sequenced, _chapter, _script

    earlier = "\n".join(f"第{i}段主持词。" for i in range(300))
    llm = Sequenced(_script("这一段。"))
    asyncio.run(
        WriterService(llm).write(
            _chapter(),
            [],
            target_duration_seconds=14,
            output_language=OutputLanguage.ZH_CN,
            station=StationId.CRATE,
            voice_seed="programme-1",
            previous_committed_context=earlier,
        )
    )

    prompt = llm.prompts[0]
    assert earlier in prompt
    assert prompt.index("Programme date") < prompt.index(earlier) < prompt.index("Chapter:")

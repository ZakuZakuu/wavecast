"""The Writer for two-host passages (and the bounded repair of single turns).

The Writer receives shared story material and chooses the telling and the turn-taking itself;
the material contains no lines.  It returns a ``DialogueDraft``; identity, duration and
reference validation happen in code afterwards.  Repair rewrites only the turns it is told to,
keeping every speaker and the number of turns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from wavecast.models.dialogue import DialogueBlock, DialogueDraft, DialoguePurpose
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.stations import StationId

from .dialogue_budget import DialogueStationBudget
from .fast_start import FastStructuredProvider


@dataclass(frozen=True)
class DialogueSlot:
    """Where a passage goes.  Identity is the application's; the tracks are for orientation."""

    slot_id: str
    block_id: str
    purpose: DialoguePurpose
    station: StationId
    just_played: str | None = None
    upcoming: str | None = None


_WRITER_PROMPT = """你为一档真实的音乐电台写一段两位主持人的对话。主持人 A 先开口，B 接话；\
他们是同一档节目的两位主持，不是问答机器。

只能使用下面「素材」里列出的事实。每一轮的 fact_refs 填这一轮说到或默认成立的事实的 id（只能是素材里的 \
id）；这一轮没有用到任何事实就填空列表。不要补充素材之外的背景、动机、评价或因果，也不要写「更成熟」\
「一直坚持」这类素材没有说过的判断；editorial_angle 是编辑的看法，只能说成「可以这样听」，不能说成事实。\
do_not_infer 里的内容不能说。backstage 里的内容绝对不要念出来。

怎么说由你定：可以用一个真实的问题带出下一句，但问题里的事实前提也要在 fact_refs 里列出。\
不要在文字里写「A：」「B：」，不要念出事实 id。口语、自然、有来有回，每轮不超过 {max_turn_chars} 字。\
这是一段 {purpose} 用途的对话，位置：{placement}。

篇幅目标约 {min_s}–{max_s} 秒（约 {min_chars}–{max_chars} 字）。这是目标，不是下限：素材不够就写短，\
不要为了凑长度重复或加料。

素材（JSON）：
{material}"""

_REPAIR_PROMPT = """下面是一段两位主持人的对话，核对发现有几轮说了素材不支持的内容。只改下面列出的轮，\
其他轮保持不变。改的方式：删掉没有依据的说法，或改成素材确实说过的；仍然口语、自然，能和前后轮接上，\
说话人不变。不要新增轮次，不要加入素材之外的内容。每个改过的轮给出新的 text 和它用到的事实 id 列表 \
fact_refs（可以为空）。

素材（JSON）：
{material}

整段对话（轮次从 0 开始）：
{dialogue}

需要改的轮和原因：
{problems}"""


class TurnFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int
    text: str
    fact_refs: list[str]


class DialogueRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list[TurnFix]


def _material_json(material: StoryMaterial) -> str:
    """What the Writer sees: facts with their ids and statements, the angle, the limits.

    Quotes and evidence ids stay out of the Writer's view; they are the checker's business.
    """

    return json.dumps(
        {
            "subject": material.subject,
            "central_question": material.central_question,
            "facts": [
                {"id": fact.fact_id, "statement": fact.statement, "about": fact.subject}
                for fact in material.facts
            ],
            "editorial_angle": material.editorial_angle,
            "do_not_infer": material.do_not_infer,
            "backstage": material.backstage,
        },
        ensure_ascii=False,
    )


class DialogueWriter:
    def __init__(
        self, llm: FastStructuredProvider, *, profile: InferenceProfile = InferenceProfile.BALANCED
    ) -> None:
        self._llm = llm
        self._profile = profile

    async def write(
        self, material: StoryMaterial, slot: DialogueSlot, budget: DialogueStationBudget
    ) -> DialogueDraft:
        min_chars, max_chars = budget.target_characters
        placement = "、".join(
            part
            for part in (
                f"刚放完《{slot.just_played}》" if slot.just_played else "",
                f"接下来放《{slot.upcoming}》" if slot.upcoming else "",
            )
            if part
        ) or "两首歌之间"
        prompt = _WRITER_PROMPT.format(
            max_turn_chars=1500,
            purpose=slot.purpose.value,
            placement=placement,
            min_s=budget.target_min_seconds,
            max_s=budget.target_max_seconds,
            min_chars=min_chars,
            max_chars=max_chars,
            material=_material_json(material),
        )
        result = await self._llm.structured(
            prompt,
            DialogueDraft,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=self._profile,
            stage="dialogue_writer",
        )
        if not isinstance(result, DialogueDraft):
            raise ProviderInvalidResponseError("dialogue writer returned invalid output")
        return result


class DialogueRepairer:
    """Rewrites only the flagged turns.  Uses the Writer's model; never the whole passage."""

    def __init__(
        self, llm: FastStructuredProvider, *, profile: InferenceProfile = InferenceProfile.BALANCED
    ) -> None:
        self._llm = llm
        self._profile = profile

    async def repair(
        self, block: DialogueBlock, material: StoryMaterial, problems: dict[int, str]
    ) -> DialogueRepair:
        prompt = _REPAIR_PROMPT.format(
            material=_material_json(material),
            dialogue="\n".join(
                f"{index}. {turn.speaker.value}: {turn.text}"
                for index, turn in enumerate(block.turns)
            ),
            problems="\n".join(f"- 第 {index} 轮：{reason}" for index, reason in sorted(problems.items())),
        )
        result = await self._llm.structured(
            prompt,
            DialogueRepair,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=self._profile,
            stage="dialogue_repair",
        )
        if not isinstance(result, DialogueRepair):
            raise ProviderInvalidResponseError("dialogue repair returned invalid output")
        return result

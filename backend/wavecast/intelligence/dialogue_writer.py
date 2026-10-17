"""The Writer for two-host passages.

The Writer receives shared story material and chooses the telling and the turn-taking itself;
the material contains no lines.  It returns a ``DialogueDraft``; identity, duration and
reference validation happen in code afterwards.  What it may say is bounded by the material and
this prompt; there is no after-the-fact model check (ADR 0029).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from wavecast.models.dialogue import DialogueDraft, DialoguePurpose
from wavecast.models.story_material import StoryMaterial
from wavecast.programme_date import programme_date
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.spoken_form import SPOKEN_NAME_GUIDANCE, KnownTrack, spoken_artist, spoken_title
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
    # What the programme's hosts have already said, so a passage neither contradicts
    # nor repeats it; empty at the start of a programme.
    previous_context: str = ""
    tracks: tuple[KnownTrack, ...] = ()
    editorial_goal: str = ""
    programme_brief: str = ""


_WRITER_PROMPT = """你为一档真实的音乐电台写一段两位主持人的对话。主持人 A 先开口，B 接话；\
他们是同一档节目的两位主持，不是问答机器。

只能使用本段「素材」里列出的事实。每一轮的 fact_refs 填这一轮说到或默认成立的事实的 id（只能是素材里的 \
id）；这一轮没有用到任何事实就填空列表。不要补充素材之外的经历、动机、引语、创作归属或因果。\
可以基于素材展开听感和编辑理解，自然表达，不必套「可以这样听」等固定句式；\
不要把理解说成艺人的本意、原话或已经证实的事实。\
do_not_infer 里的内容不能说。backstage 里的内容绝对不要念出来。

围绕 central_question 讲清一个有意思的点，素材是理解后的内容，不是逐条念的清单。\
不要反复说「有文章指出」「某报道说」，不要念来源发表日期；只有具体评论、引语或有争议的说法才交代必要归属。\
一般用三到八轮把这个点聊完整，具体展开由你决定，不要用空话凑数。\

A、B 要接住对方的话：追问、补一个具体细节、换个理解角度，别轮流播报材料，也别用空泛赞同凑轮次。\
个人生活信息只有确实帮助理解音乐时才讲，讲清它为什么值得放在这里；与主题无关就舍弃。\
怎么说由你定：可以用一个真实的问题带出下一句，但问题里的事实前提也要在 fact_refs 里列出。\
不要在文字里写「A：」「B：」，不要念出事实 id。口语、自然、有来有回，每轮不超过 {max_turn_chars} 字。

节目日期：{today}。旧材料不能沿用「最近、上个月、今年、目前、如今」等相对时间，\
也不能把旧作品称为今天的「新专辑」或「最新」；明确历史语境如「2006年发行的新专辑」可以。\
先把材料里的时间理解清楚：报道日期不是事件日期，旧报道里的「上个月」不能直接沿用。\
只有时间影响理解时才说证据支持的年份，不必给每个事实报日期。无法确定的时序不讲，不能只删「最近」还称「新专辑」。\
素材确认人物已经离世时，不要描述成他现在仍在创作或开展活动；遗作发行也必须有素材支持。\
前文只用于衔接，人物状态等事实仍以素材为准。主持人不要编造自己的经历或查资料的过程。

口播名称规则：{speech_guidance}
没有中文名称的巡演、专辑等，用上下文清楚的中文指代自然讲述，别照抄外文专名。

本节目里主持人此前已经说过的话（原文，按先后顺序；只用来让这一段接得上、不重复、不与它矛盾；事实依据仍然只来自下面的素材）：
{previous}

下面是这一段的任务和素材。
本期编辑意图（不是事实证据）：{programme_brief}
本段要推进的内容：{editorial_goal}
把本段接到全期脉络里，不要每段都重新开场，也不要预告未经确认的后续曲目。
这是一段 {purpose} 用途的对话，位置：{placement}。
篇幅目标约 {min_s}–{max_s} 秒（约 {min_chars}–{max_chars} 字）。这是目标，不是下限：素材不够就写短，\
不要为了凑长度重复或加料。

相邻歌曲的展示名与口播名（只用于称呼，不是事实证据）：{names}

素材（JSON）：
{material}"""

def _material_json(material: StoryMaterial) -> str:
    """What the Writer sees: facts with their ids and statements, the angle, the limits.

    Quotes and evidence ids stay out of the Writer's view; code has verified them already.
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
            speech_guidance=SPOKEN_NAME_GUIDANCE,
            names=json.dumps(
                [
                    {
                        "display": f"{track.artist} - {track.title}",
                        "spoken_artist": spoken_artist(track.artist),
                        "spoken_title": track.spoken_title or spoken_title(track.title),
                    }
                    for track in slot.tracks
                ],
                ensure_ascii=False,
            ),
            today=programme_date(),
            programme_brief=slot.programme_brief or "围绕本期主题展开",
            editorial_goal=slot.editorial_goal or "讲清一个值得听的点",
            previous=slot.previous_context or "（无：节目刚开始）",
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

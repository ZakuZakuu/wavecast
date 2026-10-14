"""Fixed material and fixed model responses for the offline dialogue path.

The evidence below is a *reconstructed fixture* in the shape of the accepted Fang Datong
sample (docs/research/dialogue-radio-2026-10): the facts follow the statements the experiment's
Lite draft rests on, and the draft is that experiment's Lite text with its lyric excerpt
replaced.  It is not the original frozen search output (which is not in the repository), and no
model produced any of it here.
"""

from __future__ import annotations

import re
from typing import Any

from wavecast.intelligence.dialogue_check import DialogueCheck, SentenceFinding
from wavecast.intelligence.dialogue_writer import DialogueRepair, TurnFix
from wavecast.intelligence.fact_support import split_sentences
from wavecast.intelligence.models import Evidence
from wavecast.intelligence.story_material import DraftFact, StoryMaterialDraft
from wavecast.models.dialogue import DialogueDraft, DraftTurn
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.errors import ProviderError

STORY_ID = "fdt"
TRACK_REF = "netease:track-ai-ai-ai"


def evidence() -> list[Evidence]:
    def item(evidence_id: str, text: str, refs: list[str] | None = None) -> Evidence:
        return Evidence(
            id=evidence_id,
            claim_or_excerpt=text,
            source_url=f"https://example.test/{evidence_id}",
            source_provider="exa",
            confidence=0.8,
            query="方大同",
            track_refs=refs or [],
        )

    return [
        item("E1", "《我们能不能》的歌词意象，把“爱”的边界拉到了更宽的地方，不只是两个人之间的小心思。"),
        item(
            "E2",
            "方大同解释，前三张专辑唱国语，是因为成长的语文环境以国语为主，国语也可以让更多亚洲地区的听众听懂。"
            "他没有专门学过创作，写法都是自己摸索出来的，把白话歌词和 Nu-Soul 里融入 rap 的写法联系起来。",
        ),
        item("E3", "方大同说，他理解的爱不只是男女之间的爱情，音乐是沟通。"),
        item(
            "E4",
            "2006年的第二张专辑《爱爱爱》以 Soul 和 R&B 为主导，方大同包办了作曲、编曲、制作和和声。"
            "同名单曲《爱爱爱》由方大同作曲，周耀辉作词，方大同编曲。"
            "方大同与周耀辉的第一次合作是第一张专辑《Soulboy》里的《春风吹》，方大同看到周耀辉的词后，觉得与自己的曲很贴切。",
            [TRACK_REF],
        ),
    ]


def _fact(statement: str, evidence_id: str, quote: str, scope: str, version: str | None = None) -> DraftFact:
    return DraftFact(
        statement=statement,
        evidence_id=evidence_id,
        quote=quote,
        scope=scope,  # type: ignore[arg-type]
        subject="方大同",
        version_scope=version,
    )


def material_draft() -> StoryMaterialDraft:
    return StoryMaterialDraft(
        subject="方大同的创作与语言选择",
        scope="background",
        central_question="一个做 Soul 的人，为什么早期用国语唱？",
        facts=[
            _fact("《我们能不能》的歌词把爱的边界拉得更宽。", "E1", "把“爱”的边界拉到了更宽的地方", "recording"),
            _fact(
                "前三张专辑唱国语，是因为成长的语文环境以国语为主，国语也能让更多亚洲听众听懂。",
                "E2",
                "是因为成长的语文环境以国语为主，国语也可以让更多亚洲地区的听众听懂",
                "background",
            ),
            _fact(
                "他没有专门学过创作，写法是自己摸索出来的。",
                "E2",
                "没有专门学过创作，写法都是自己摸索出来的",
                "background",
            ),
            _fact("方大同说，他理解的爱不只是男女之间的爱情。", "E3", "方大同说，他理解的爱不只是男女之间的爱情", "background"),
            _fact(
                "第二张专辑《爱爱爱》以 Soul 和 R&B 为主导，方大同包办了作曲、编曲、制作和和声。",
                "E4",
                "以 Soul 和 R&B 为主导，方大同包办了作曲、编曲、制作和和声",
                "album",
            ),
            _fact(
                "同名单曲《爱爱爱》由方大同作曲，周耀辉作词。",
                "E4",
                "同名单曲《爱爱爱》由方大同作曲，周耀辉作词",
                "recording",
                TRACK_REF,
            ),
            _fact(
                "方大同与周耀辉的第一次合作是《Soulboy》里的《春风吹》。",
                "E4",
                "方大同与周耀辉的第一次合作是第一张专辑《Soulboy》里的《春风吹》",
                "album",
            ),
        ],
        editorial_angle="可以从“爱的多种样貌”这个角度去听。",
        do_not_infer=["不要说他的创作因此更成熟", "不要说他一直坚持国语"],
        backstage=["资料来自网页摘录"],
    )


def f(n: int) -> str:
    return f"{STORY_ID}-F{n}"


def _turn(speaker: str, text: str, refs: list[str]) -> DraftTurn:
    return DraftTurn(speaker=speaker, text=text, fact_refs=refs)  # type: ignore[arg-type]


def draft_with_two_problems() -> DialogueDraft:
    """The experiment's Lite text: turn 1 says 一直坚持, turn 4 says 更成熟 - neither is in the facts."""
    return DialogueDraft(
        turns=[
            _turn("A", "刚听完《我们能不能》，不知道你有没有注意到歌词意象，已经把“爱”的边界拉到了更宽的地方。", [f(1)]),
            _turn("B", "方大同自己也说过，他理解的爱不只是男女之间的爱情。那你有没有好奇过，他为什么早期一直坚持用国语唱歌？", [f(4), f(2)]),
            _turn("A", "他的解释很直白：成长的语文环境本来就是以国语为主，而且国语可以让更多亚洲地区的听众听懂。", [f(2)]),
            _turn("B", "但有意思的是，他并没有专门学过创作，写法都是自己摸索出来的。", [f(3)]),
            _turn("A", "这种摸索到了2006年的第二张专辑《爱爱爱》里就更成熟了，整张专辑以Soul和R&B为主导，他一个人包办了作曲、编曲、制作还有和声。", [f(5)]),
            _turn("B", "同名单曲《爱爱爱》由方大同作曲，周耀辉作词。其实他们的第一次合作，在第一张专辑《Soulboy》的《春风吹》里就已经开始了。", [f(6), f(7)]),
            _turn("A", "所以等下这首《爱爱爱》，你可以试着从“爱的多种样貌”这个角度去听。", [f(4), f(6)]),
        ]
    )


def clean_draft() -> DialogueDraft:
    draft = draft_with_two_problems()
    turns = list(draft.turns)
    turns[1] = _turn("B", "方大同自己也说过，他理解的爱不只是男女之间的爱情。那你有没有好奇过，他为什么早期选择用国语唱歌？", [f(4), f(2)])
    turns[4] = _turn("A", "2006年的第二张专辑《爱爱爱》以Soul和R&B为主导，方大同包办了作曲、编曲、制作和和声。", [f(5)])
    return DialogueDraft(turns=turns)


def good_repair() -> DialogueRepair:
    clean = clean_draft()
    return DialogueRepair(
        fixes=[
            TurnFix(turn=1, text=clean.turns[1].text, fact_refs=clean.turns[1].fact_refs),
            TurnFix(turn=4, text=clean.turns[4].text, fact_refs=clean.turns[4].fact_refs),
        ]
    )


class ScriptedLLM:
    """Returns queued responses per output type; an exception in the queue is raised."""

    def __init__(self, *responses: Any) -> None:
        self.queues: dict[type, list[Any]] = {}
        for response in responses:
            self.queues.setdefault(type(response) if not isinstance(response, BaseException) else BaseException, []).append(response)
        self.calls: list[tuple[str, str | None]] = []

    def queue(self, output_type: type, *responses: Any) -> ScriptedLLM:
        self.queues.setdefault(output_type, []).extend(responses)
        return self

    async def structured(self, prompt: str, output_type: type, *, transport: Any, profile: Any, stage: str | None = None) -> Any:
        self.calls.append((output_type.__name__, stage))
        queue = self.queues.get(output_type) or self.queues.get(BaseException)
        if not queue:
            raise AssertionError(f"no scripted response for {output_type.__name__}")
        response = queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class JudgingLLM(ScriptedLLM):
    """A fact-check model that judges from the prompt: it says 'supported' for any sentence
    that sits in a turn with fact references, citing the first one with that fact's own quote,
    unless an override says otherwise.  (It is deliberately over-agreeable: code must still
    catch what a lax model lets through.)"""

    def __init__(
        self,
        material: StoryMaterial,
        known: list[DialogueDraft | DialogueRepair],
        insufficient: tuple[str, ...] = (),
        not_factual: tuple[str, ...] = ("这个角度去听",),
    ) -> None:
        super().__init__()
        self.material = material
        self.refs_for: dict[str, list[str]] = {}
        for item in known:
            turns = item.turns if isinstance(item, DialogueDraft) else []
            for turn in turns:
                for sentence in split_sentences(turn.text):
                    self.refs_for[sentence.strip()] = turn.fact_refs
            if isinstance(item, DialogueRepair):
                for fix in item.fixes:
                    for sentence in split_sentences(fix.text):
                        self.refs_for[sentence.strip()] = fix.fact_refs
        self.insufficient = insufficient
        self.not_factual = not_factual
        self.fail: BaseException | None = None

    async def structured(self, prompt: str, output_type: type, *, transport: Any, profile: Any, stage: str | None = None) -> Any:
        self.calls.append((output_type.__name__, stage))
        if self.fail is not None:
            raise self.fail
        findings = []
        for number, text in re.findall(r"^\s+(\d+)\. (.*)$", prompt.split("Dialogue:")[1], re.MULTILINE):
            refs = self.refs_for.get(text.strip(), [])
            facts = [fact for ref in refs if (fact := self.material.fact(ref)) is not None]
            # Cite the declared fact whose text overlaps the sentence most.
            fact = max(facts, key=lambda item: len(set(text) & set(item.quote)), default=None)
            if fact is None or any(marker in text for marker in self.not_factual):
                findings.append(SentenceFinding(sentence=int(number), verdict="not_factual", fact_ids=[], quote=""))
            elif any(marker in text for marker in self.insufficient):
                findings.append(SentenceFinding(sentence=int(number), verdict="insufficient", fact_ids=[], quote=""))
            else:
                findings.append(SentenceFinding(sentence=int(number), verdict="supported", fact_ids=[fact.fact_id], quote=fact.quote[:60]))
        return DialogueCheck(findings=findings)


def unavailable() -> ProviderError:
    return ProviderError("down")

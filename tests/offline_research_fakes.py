"""Scripted stand-ins for the offline run of scripts/live_research_dialogue_probe.py.

No network and no model: they only exercise the wiring (planner -> capped search -> material ->
writer -> check -> voice -> HLS).  The text is invented for the wiring; it is not a sample.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from wavecast.intelligence.dialogue_check import DialogueCheck, SentenceFinding
from wavecast.intelligence.fact_support import split_sentences
from wavecast.intelligence.models import (
    PlannedResearchQuery,
    ResearchFacet,
    ResearchPlan,
    SearchIntent,
)
from wavecast.intelligence.story_material import DraftFact, StoryMaterialDraft
from wavecast.models.dialogue import DialogueDraft, DraftTurn
from wavecast.providers.contracts import SearchResult


class FakeSearch:
    def __init__(self, label: str, fail: bool = False) -> None:
        self.label, self.fail, self.queries = label, fail, []

    async def search(self, query: str, *, limit: int = 5, stage: str | None = None) -> list[SearchResult]:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("scripted search failure")
        n = len(self.queries)
        return [
            SearchResult(
                title=f"{self.label} 资料 {n}-{i}", url=f"https://example.test/{self.label}/{n}/{i}",
                snippet="片段", provider=self.label.split("_")[0], query=query,
                content=f"资料{n}-{i}：方大同在创作里习惯先写旋律再反复调整编曲，并且长期和固定的合作者讨论细节，这是资料{n}-{i}的说法。",
            )
            for i in range(2)
        ]


class OfflineLLM:
    def __init__(self, role: str) -> None:
        self.role, self.calls = role, 0

    async def structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        self.calls += 1
        if output_type is ResearchPlan:
            queries = [
                PlannedResearchQuery(query=f"方大同 {topic}", intent=intent, facet_ids=["bio"], rationale="scripted")
                for topic, intent in (
                    ("创作经历", SearchIntent.RESEARCH), ("作品风格", SearchIntent.DISCOVERY),
                    ("合作者", SearchIntent.RESEARCH), ("采访", SearchIntent.RESEARCH),
                )
            ]
            return ResearchPlan(
                central_question="方大同是怎样创作的？",
                facets=[ResearchFacet(id="bio", label="创作", question="他怎样写歌？", priority=90)],
                background_queries=queries,
            )
        if output_type is StoryMaterialDraft:
            items = re.findall(r"^\[(.+?)\]: (.*)$", prompt, re.MULTILINE)
            facts = []
            for evidence_id, text in items[:4]:
                quote = text.split("，")[0][-20:] if "，" in text else text[:20]
                facts.append(DraftFact(
                    statement=quote, evidence_id=evidence_id, quote=quote, scope="background",
                    subject="方大同", version_scope=None,
                ))
            return StoryMaterialDraft(
                subject="方大同的创作方式", scope="background", central_question="他怎样写歌？",
                facts=facts, editorial_angle=None, do_not_infer=[], backstage=[],
            )
        if output_type is DialogueDraft:
            ids = sorted(set(re.findall(r"live-research-F\d+", prompt)))[:4]
            refs = ids or ["live-research-F1"]
            turns = [
                DraftTurn(speaker="A" if i % 2 == 0 else "B", fact_refs=refs, text=text)  # type: ignore[arg-type]
                for i, text in enumerate([
                    "今天想聊聊方大同是怎么写歌的，资料里提到过他的创作习惯。",
                    "对，他习惯先写旋律，再反复调整编曲，这是资料里写到的。",
                    "而且他长期和固定的合作者一起讨论细节，也是资料里的说法。",
                    "听起来很像一个慢慢打磨的过程，细节是一点点磨出来的。",
                    "是的，资料里说他会反复调整，直到整体的感觉对了为止。",
                    "这一点放到他的作品里，能听出很稳的质感，我们接着往下听。",
                ])
            ]
            return DialogueDraft(turns=turns)
        if output_type is DialogueCheck:
            facts = re.findall(r"^\[(\S+)\] gist: .*\n(?:    source title: .*\n)?    source text: (.*)$", prompt, re.MULTILINE)
            first_id, first_quote = facts[0]
            findings = []
            for number, text in re.findall(r"^\s+(\d+)\. (.*)$", prompt.split("Dialogue:")[1], re.MULTILINE):
                factual = "资料" in text or "习惯" in text or "合作者" in text
                findings.append(
                    SentenceFinding(sentence=int(number), verdict="supported", fact_ids=[first_id], quote=first_quote[:20])
                    if factual else SentenceFinding(sentence=int(number), verdict="not_factual", fact_ids=[], quote="")
                )
            return DialogueCheck(findings=findings)
        raise AssertionError(f"no scripted answer for {output_type.__name__}")


def offline_clients(budget: Any) -> SimpleNamespace:
    assert split_sentences  # imported for parity with the real checker's sentence splitting
    return SimpleNamespace(
        planner=OfflineLLM("research_plan"), material=OfflineLLM("material"),
        writer=OfflineLLM("writer"), checker=OfflineLLM("fact_check"),
        exa=FakeSearch("exa"), tavily=FakeSearch("tavily"), tavily_deep=FakeSearch("tavily_advanced"),
    )

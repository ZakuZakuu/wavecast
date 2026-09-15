"""In-memory progressive planning state, separate from the persisted audio timeline."""

from dataclasses import dataclass, field

from .models import ChapterPlan, ProgramSkeleton


@dataclass
class PlanningSession:
    committed_chapters: list[ChapterPlan] = field(default_factory=list)
    speculative_chapters: list[ChapterPlan] = field(default_factory=list)

    def apply_skeleton(self, skeleton: ProgramSkeleton) -> None:
        committed_ids = {chapter.index for chapter in self.committed_chapters}
        incoming_by_index = {chapter.index: chapter for chapter in skeleton.chapters}
        for chapter in self.committed_chapters:
            incoming = incoming_by_index.get(chapter.index)
            if incoming is None:
                raise ValueError("committed chapter cannot be removed")
            if incoming != chapter:
                raise ValueError("committed chapter cannot be rewritten")
        self.speculative_chapters = [
            chapter for chapter in skeleton.chapters if chapter.index not in committed_ids
        ]

    def commit_next(self) -> ChapterPlan:
        if not self.speculative_chapters:
            raise ValueError("no speculative chapter is available")
        chapter = self.speculative_chapters.pop(0)
        self.committed_chapters.append(chapter)
        return chapter

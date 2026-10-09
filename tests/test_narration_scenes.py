import asyncio

import pytest
from wavecast.evals.narration_scenes import SCENES
from wavecast.intelligence.models import RadioScript, RadioScriptBlock
from wavecast.intelligence.writer import WriterService

from tests.test_intelligence_services import StructuredFixture


def test_scene_ids_are_unique() -> None:
    ids = [scene.scene_id for scene in SCENES]

    assert len(ids) == len(set(ids))
    assert len(SCENES) >= 8


@pytest.mark.parametrize("scene", SCENES, ids=lambda scene: scene.scene_id)
def test_every_scene_builds_a_valid_writer_request(scene) -> None:
    block = RadioScriptBlock(kind=scene.kind, text="一句话。", duration_seconds=5)
    fixture = StructuredFixture(RadioScript(blocks=[block]))

    result = asyncio.run(
        WriterService(fixture).write(
            scene.chapter(),
            scene.evidence(),
            slot_context=scene.slot(),
            target_duration_seconds=scene.window_seconds,
            topic=scene.topic,
        )
    )

    assert [item.text for item in result.blocks] == ["一句话。"]
    assert scene.kind.value in fixture.prompts[0]
    if scene.is_final:
        assert '"is_final": true' in fixture.prompts[0]
    for track in (scene.just_played, scene.upcoming):
        if track is not None:
            assert track.canonical_title in fixture.prompts[0]

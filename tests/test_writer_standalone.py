"""Each narration block is written to stand on its own.

A real run's host said the next song "延续了他音乐里的这种人文色彩" after the host line that explained
that character was skipped.  The Writer is told, in one short instruction, that earlier host lines may
not have been heard; nothing here inspects or rewrites the text it returns.
"""

from tests.test_voice import Sequenced, _script, _write


def test_the_writer_is_told_earlier_host_lines_may_not_have_been_heard() -> None:
    llm = Sequenced(_script("接下来这首歌，来自他的第二张专辑。"))

    _write(llm)

    prompt = llm.prompts[0]
    assert "Each block must make sense on its own" in prompt
    assert "Use earlier host lines for a continuous story" in prompt
    assert "understandable even if an earlier passage was skipped" in prompt
    assert "just_played_track" in prompt  # the one thing it may assume was heard

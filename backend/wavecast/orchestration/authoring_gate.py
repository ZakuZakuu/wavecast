"""Whether a chapter's narration is still worth spending money on.

``author_pending_narration`` opens the gate around each chapter's authoring with a check that
reads the *current* episode (playback may have reached the chapter, the seam may have been
skipped for continuity, the listener may be gone).  Work that is optional and expensive - the
Writer fallback after a failed two-host passage - asks the gate first.  With no gate open (other
callers, tests) the answer is "yes": nothing changes for them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_gate: ContextVar[Callable[[], bool] | None] = ContextVar("wavecast_authoring_gate", default=None)


@contextmanager
def authoring_gate(check: Callable[[], bool]) -> Iterator[None]:
    token = _gate.set(check)
    try:
        yield
    finally:
        _gate.reset(token)


async def authoring_still_open() -> bool:
    check = _gate.get()
    if check is None:
        return True
    return await asyncio.to_thread(check)

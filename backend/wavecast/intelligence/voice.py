"""How each station's host talks: a voice per station and a varied "move" per narration block.

Two things keep programmes from sounding alike.  A station sets the register and the mix of
things a host does; and within a programme the move for each block is drawn deterministically
from the programme's seed, never the same one twice in a row, so different programmes (and
different blocks) open differently.  Nothing here is a phrase template: moves say what a block
should *do*, not how to word it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from wavecast.narration_quality import CHARS_PER_SECOND, FIGURATIVE_PHRASES
from wavecast.stations import STATION_PROFILES, StationId


class Move(StrEnum):
    FACT = "fact"
    LISTEN = "listen"
    LINK = "link"
    REASON = "reason"
    ASK = "ask"
    PLAIN = "plain"


MOVE_INSTRUCTIONS: dict[Move, str] = {
    Move.FACT: (
        "Give one concrete, checkable fact from the evidence (a name, a year, a place, who "
        "played what, which release), then connect it to the next track in a few words."
    ),
    Move.LISTEN: (
        "Point to one specific thing the listener can hear near the start of the next track, "
        "but only if the evidence says something about the sound; if it does not, do something "
        "else."
    ),
    Move.LINK: (
        "Say plainly how the next track relates to the one just played (same artist, another "
        "version, another decade, the same idea) and why it follows."
    ),
    Move.REASON: (
        "Say why the programme goes to this track at this point: the editorial reason, in one "
        "or two plain sentences."
    ),
    Move.ASK: (
        "Open with one natural question a listener might have, then answer it in the next "
        "sentence. Use it sparingly."
    ),
    Move.PLAIN: (
        "Say what comes next in one short, plain sentence. No commentary, no description."
    ),
}


@dataclass(frozen=True)
class StationVoice:
    station: StationId
    tone: str
    weights: dict[Move, int]
    examples: tuple[str, ...]


# Register samples only.  Their facts are invented; the model is told not to reuse them.
STATION_VOICES: dict[StationId, StationVoice] = {
    StationId.CASUAL: StationVoice(
        StationId.CASUAL,
        "A friend in the passenger seat: relaxed, brief, says one thing and stops. Short "
        "sentences; no lecture; allowed to be a little wry.",
        {Move.FACT: 3, Move.LISTEN: 3, Move.LINK: 3, Move.PLAIN: 3, Move.REASON: 1},
        (
            "这首前奏就一把吉他，二十秒左右鼓才进来。",
            "下一首是同一支乐队五年后的歌，换了鼓手，听得出来。",
            "这张专辑一共九首，我们挑了最短的一首，不到三分钟。",
            "上一首放完，歇口气。接着是一首老歌。",
        ),
    ),
    StationId.CRATE: StationVoice(
        StationId.CRATE,
        "A friend who digs through record shops and shares a find: pleased but restrained. "
        "Says why this record is worth the listener's time, never oversells.",
        {Move.FACT: 3, Move.LISTEN: 3, Move.LINK: 3, Move.REASON: 2, Move.ASK: 1},
        (
            "要是你喜欢刚才那个鼓点，下面这位鼓手值得记一下，他还给另外两支乐队打过鼓。",
            "这首是翻唱，原曲更早，我们后面会放。",
            "同一个制作人做的，所以你会觉得两首的人声离得很近。",
        ),
    ),
    StationId.PORTRAIT: StationVoice(
        StationId.PORTRAIT,
        "Steady and exact, like a well-written profile: dates, albums, turning points, who "
        "worked with whom. No flattery, no biography dump; one point per block.",
        {Move.FACT: 5, Move.LINK: 3, Move.REASON: 2, Move.LISTEN: 1},
        (
            "一九九八年她出了第二张专辑，这首是里面的主打。那一年她刚搬去台北。",
            "到这张专辑，词基本都是她自己写的。",
            "上一首还是乐队时期的歌，这首是她单飞以后第一首发行的。",
        ),
    ),
    StationId.LINEAGE: StationVoice(
        StationId.LINEAGE,
        "Clear and opinionated, explains where things came from and who influenced whom; "
        "may ask a question, may take a position (marked as a view, not a fact). Never "
        "lectures at length.",
        {Move.FACT: 4, Move.LINK: 4, Move.REASON: 3, Move.ASK: 1, Move.LISTEN: 1},
        (
            "要说这种节奏的来历，得从六十年代的底特律说起，下一首是那一批里最早的录音之一。",
            "这首和上一首隔了十年，中间发生了一件事：合成器变便宜了。",
            "放这首是因为它是最早用这种鼓机的唱片，一九八一年。",
        ),
    ),
    StationId.NIGHT: StationVoice(
        StationId.NIGHT,
        "Almost silent: very short, low and slow. Only a name or one quiet fact.",
        {Move.PLAIN: 1},
        ("下一首。",),
    ),
}


def _roll(seed: str, station: StationId, index: int, salt: str = "") -> int:
    digest = hashlib.sha256(f"{seed}|{station.value}|{index}|{salt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _voice(station: StationId | None) -> StationVoice:
    return STATION_VOICES[station or StationId.CASUAL]


def move_for(seed: str, station: StationId | None, index: int) -> Move:
    """The move for block ``index`` of a programme; never the same as the block before it."""

    voice = _voice(station)
    previous: Move | None = None
    chosen = next(iter(voice.weights))
    for step in range(index + 1):
        pool = [(m, w) for m, w in voice.weights.items() if m is not previous] or list(
            voice.weights.items()
        )
        total = sum(weight for _, weight in pool)
        point = _roll(seed, voice.station, step) % total
        for move, weight in pool:
            if point < weight:
                chosen = move
                break
            point -= weight
        previous = chosen
    return chosen


def pick_examples(seed: str, station: StationId | None, index: int, count: int = 2) -> list[str]:
    voice = _voice(station)
    ranked = sorted(
        voice.examples, key=lambda text: _roll(seed, voice.station, index, salt=text)
    )
    return ranked[:count]


def max_characters(window_seconds: float | None) -> int | None:
    if window_seconds is None:
        return None
    return max(12, int(window_seconds * CHARS_PER_SECOND))


# The longest a station's host speaks in one block, whatever the programme timing plan offers.
# The plan budgets FULL hosting generously (40-50 s), which reads as a lecture.
MAX_SECONDS: dict[StationId, int] = {
    StationId.CASUAL: 15,
    StationId.CRATE: 20,
    StationId.PORTRAIT: 30,
    StationId.LINEAGE: 30,
    StationId.NIGHT: 8,
}


def window_for(station: StationId | None, planned_seconds: float | None) -> float | None:
    """The spoken window to write for: the plan's, capped by what the station's host does."""

    if planned_seconds is None or station is None:
        return planned_seconds
    return min(planned_seconds, MAX_SECONDS[station])


# Share of the window a station's block should use at least; a data-sheet reading of three
# short facts is as unnatural as a lecture.
MIN_FILL: dict[StationId, float] = {
    StationId.CASUAL: 0.45,
    StationId.CRATE: 0.6,
    StationId.PORTRAIT: 0.65,
    StationId.LINEAGE: 0.65,
    StationId.NIGHT: 0.0,
}


NEVER_START = ("刚才", "接下来", "我们先从", "下一首")


def voice_instructions(
    *,
    station: StationId | None,
    seed: str,
    index: int,
    window_seconds: float | None,
    used_openers: Sequence[str] = (),
    is_opening: bool = False,
    is_final: bool = False,
) -> str:
    """The voice section of the Writer prompt for one block."""

    voice = _voice(station)
    profile = STATION_PROFILES[voice.station]
    lines = [f"Station: {profile.name} - {profile.positioning}", f"Voice: {voice.tone}"]
    if is_final:
        lines.append(
            "This block closes the programme in one or two short sentences: say where the "
            "route ended, naming at most the last track. Never list the tracks played, do not "
            "repeat anything an earlier block already said, say nothing about what comes next, "
            "and stop plainly."
        )
    elif is_opening:
        lines.append(
            "This is the opening: say what we begin with and one reason to begin there, in "
            "one or two plain sentences. No greeting, no description of the sound."
        )
    else:
        move = move_for(seed, station, index)
        lines.append(f"This block's move ({move.value}): {MOVE_INSTRUCTIONS[move]}")
    limit = max_characters(window_seconds)
    if limit is not None:
        floor = int(limit * MIN_FILL[voice.station])
        lines.append(
            f"Length: between {floor} and {limit} Chinese characters (up to about "
            f"{window_seconds:.0f} seconds spoken). Stop when the move is done."
        )
    never = "、".join(NEVER_START)
    lines.append(
        f"Begin with the subject itself (a name, a year, the thing heard), never with {never}. "
        "A block may begin with the track title only if the move is plain."
    )
    if used_openers:
        lines.append(
            "Openers already used in this programme (do not begin like any of them): "
            + "、".join(used_openers[-6:])
        )
    lines.append(
        "Do not repeat a fact, a date or a name's backstory that the previous context already "
        "told; say something new or say less."
    )
    lines.append(
        "Write plain spoken Chinese for the ear, as a person talks, not as notes: complete "
        "sentences, everyday verbs, one idea per sentence, ordinary connectives (其实, 不过, "
        "因为, 所以) used sparingly. Concrete things (names, years, versions, who played) "
        "instead of adjectives. Every factual statement must come from the evidence or the "
        "track names; do not describe tempo, mood, volume or instrumentation unless the "
        "evidence says so. Do not claim personal memories or feelings you cannot have. Do not "
        "talk about evidence or certainty."
    )
    lines.append(
        "Never write: stock figurative phrases such as "
        + "、".join(FIGURATIVE_PHRASES[:12])
        + "; the frame “不是……而是……” or “更像……”; closing morals such as “这也提醒我们”; "
        "lists of three adjectives or examples; “下期再见” or other podcast sign-offs."
    )
    examples = pick_examples(seed, station, index)
    if examples and voice.station is not StationId.NIGHT:
        lines.append(
            "Register samples (their facts are invented; do not reuse their wording or facts): "
            + " / ".join(f"“{text}”" for text in examples)
        )
    return "\n".join(lines) + "\n"

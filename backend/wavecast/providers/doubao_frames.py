"""Binary frames of the Doubao podcast WebSocket protocol (client builders, server parser).

Derived from the protocol helper in bytedance/agentkit-samples (Apache-2.0, copy of the license
in ``docs/third-party/agentkit-samples-LICENSE``).  The frame layout and event numbers follow
that helper as it was used by the successful 2026-10-14 experiment; this module is a
re-implementation for application use, not a copy: it carries no logging, never puts a payload
into an exception message, and refuses what it does not understand (compression, a layout it
has not seen, bytes left over) instead of guessing.  The upstream commit was not recorded.

Only what the verified fixed-script exchange uses is here.  Nothing else of the service is
claimed to work.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from wavecast.providers.errors import ProviderInvalidResponseError


class MsgType(IntEnum):
    FULL_CLIENT_REQUEST = 0b0001
    AUDIO_ONLY_CLIENT = 0b0010
    FULL_SERVER_RESPONSE = 0b1001
    AUDIO_ONLY_SERVER = 0b1011
    FRONT_END_RESULT_SERVER = 0b1100
    ERROR = 0b1111


class Flag(IntEnum):
    NO_SEQ = 0
    POSITIVE_SEQ = 0b1
    LAST_NO_SEQ = 0b10
    NEGATIVE_SEQ = 0b11
    WITH_EVENT = 0b100


class Event(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    CANCEL_SESSION = 101
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_CANCELED = 151
    SESSION_FINISHED = 152
    SESSION_FAILED = 153
    USAGE_RESPONSE = 154
    PODCAST_ROUND_START = 360
    PODCAST_ROUND_RESPONSE = 361
    PODCAST_ROUND_END = 362
    PODCAST_END = 363


_SERIALIZATION_JSON = 0b0001
_COMPRESSION_NONE = 0
_HEADER_UNITS = 1  # four bytes
_VERSION = 1
# Events whose frames carry no session id (connection level).
_NO_SESSION = {
    Event.START_CONNECTION,
    Event.FINISH_CONNECTION,
    Event.CONNECTION_STARTED,
    Event.CONNECTION_FAILED,
    Event.CONNECTION_FINISHED,
}
_CONNECT_ID = {Event.CONNECTION_STARTED, Event.CONNECTION_FAILED, Event.CONNECTION_FINISHED}
_SEQUENCED = {Flag.POSITIVE_SEQ, Flag.NEGATIVE_SEQ}
_WITH_PAYLOAD_TYPES = {
    MsgType.FULL_CLIENT_REQUEST,
    MsgType.AUDIO_ONLY_CLIENT,
    MsgType.FULL_SERVER_RESPONSE,
    MsgType.AUDIO_ONLY_SERVER,
    MsgType.FRONT_END_RESULT_SERVER,
}


@dataclass(frozen=True)
class Frame:
    type: MsgType
    flag: Flag
    event: Event | int | None = None
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""


def build_frame(
    event: Event,
    *,
    session_id: str = "",
    payload: bytes = b"{}",
    type_: MsgType = MsgType.FULL_CLIENT_REQUEST,
) -> bytes:
    """One event frame, in the layout the service expects from a client (and tests send back)."""

    out = bytearray(
        [
            (_VERSION << 4) | _HEADER_UNITS,
            (type_ << 4) | Flag.WITH_EVENT,
            (_SERIALIZATION_JSON << 4) | _COMPRESSION_NONE,
            0,
        ]
    )
    out += struct.pack(">i", int(event))
    if event not in _NO_SESSION:
        encoded = session_id.encode("utf-8")
        out += struct.pack(">I", len(encoded)) + encoded
    elif event in _CONNECT_ID and type_ is not MsgType.FULL_CLIENT_REQUEST:
        out += struct.pack(">I", 0)
    out += struct.pack(">I", len(payload)) + payload
    return bytes(out)


def start_connection() -> bytes:
    return build_frame(Event.START_CONNECTION)


def finish_connection() -> bytes:
    return build_frame(Event.FINISH_CONNECTION)


def start_session(session_id: str, payload: bytes) -> bytes:
    return build_frame(Event.START_SESSION, session_id=session_id, payload=payload)


def finish_session(session_id: str) -> bytes:
    return build_frame(Event.FINISH_SESSION, session_id=session_id)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self._at + size > len(self._data):
            raise ProviderInvalidResponseError("doubao frame is truncated")
        chunk = self._data[self._at : self._at + size]
        self._at += size
        return chunk

    def int32(self) -> int:
        return int(struct.unpack(">i", self.take(4))[0])

    def uint32(self) -> int:
        return int(struct.unpack(">I", self.take(4))[0])

    def finished(self) -> bool:
        return self._at == len(self._data)


def parse_server_frame(data: bytes) -> Frame:
    """Decode one server frame; anything unexpected raises ``ProviderInvalidResponseError``."""

    if len(data) < 4:
        raise ProviderInvalidResponseError("doubao frame is too short")
    header_units = data[0] & 0x0F
    if data[0] >> 4 != _VERSION or header_units < 1:
        raise ProviderInvalidResponseError("doubao frame has an unknown header")
    try:
        msg_type = MsgType(data[1] >> 4)
        flag = Flag(data[1] & 0x0F)
    except ValueError as error:
        raise ProviderInvalidResponseError("doubao frame has an unknown type") from error
    if data[2] & 0x0F != _COMPRESSION_NONE:
        raise ProviderInvalidResponseError("doubao frame is compressed, which is not supported")
    reader = _Reader(data)
    reader.take(4 * header_units)

    sequence = error_code = 0
    if msg_type in _WITH_PAYLOAD_TYPES:
        if flag in _SEQUENCED:
            sequence = reader.int32()
    elif msg_type is MsgType.ERROR:
        error_code = reader.uint32()
    else:  # pragma: no cover - the enum has no other members
        raise ProviderInvalidResponseError("doubao frame has an unsupported type")

    event: Event | int | None = None
    session_id = connect_id = ""
    if flag is Flag.WITH_EVENT:
        raw_event = reader.int32()
        try:
            event = Event(raw_event)
        except ValueError:
            event = raw_event
        if event not in _NO_SESSION:
            size = reader.uint32()
            session_id = reader.take(size).decode("utf-8", errors="replace") if size else ""
        if event in _CONNECT_ID:
            size = reader.uint32()
            connect_id = reader.take(size).decode("utf-8", errors="replace") if size else ""
    size = reader.uint32()
    payload = reader.take(size) if size else b""
    if not reader.finished():
        raise ProviderInvalidResponseError("doubao frame has unexpected trailing data")
    return Frame(msg_type, flag, event, session_id, connect_id, sequence, error_code, payload)

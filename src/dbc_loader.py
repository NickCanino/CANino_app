# -----------------------------------------------------------------------------
#  Project: CANinoApp
#  Author: Nicasio Canino <nicasio.canino@phd.unipi.it>
#  Organization: Department of Information Engineering (DII), University of Pisa
#  Collaborators: Sergio Saponara <sergio.saponara@unipi.it>, Daniele Rossi <daniele.rossi1@unipi.it>
#  Copyright 2025 Nicasio Canino
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -----------------------------------------------------------------------------

import struct

import cantools
import cantools.database
from cantools.database.can.message import Message

from typing import Optional

# Physical range of a float signal without a DBC [min|max]
FLOAT_FALLBACK_RANGE = (-1000.0, 1000.0)


class DBCSignal:
    def __init__(
        self,
        name: str,
        start_bit: int,
        length: int,
        byte_order: str,
        is_signed: bool,
        factor: float,
        offset: float,
        minimum: Optional[float],
        maximum: Optional[float],
        unit: str,
        is_float: bool = False,
        choices: Optional[dict] = None,
    ):
        self.name = name
        self.start_bit = start_bit
        self.length = length
        self.byte_order = byte_order
        self.is_signed = is_signed
        self.factor = factor
        self.offset = offset
        self.minimum = minimum
        self.maximum = maximum
        self.unit = unit
        self.is_float = is_float
        self.choices = choices or {}  # raw value -> enum text


class DBCMessage:
    def __init__(
        self,
        frame_id: int,
        name: str,
        cycle_time: int | None,
        signals: list["DBCSignal"],
        payload_length: int,
        is_fd: bool = False,
        is_extended_frame: bool = False,
    ):
        self.frame_id = frame_id
        self.name = name
        self.cycle_time = cycle_time
        self.signals = signals
        self.payload_length = payload_length  # lunghezza in byte del payload
        self.is_fd = is_fd
        self.is_extended_frame = is_extended_frame


class DBCLoader:
    def __init__(self, filename: str):
        self.dbc_filename = filename
        self.db = cantools.database.load_file(filename)

        if not hasattr(self.db, "messages"):
            raise AttributeError(
                "Loaded database does not have 'messages' attribute. Ensure the file is a valid CAN DBC file."
            )

        self.messages: list[DBCMessage] = []
        self._load_messages()

    def _load_messages(self):
        for msg in self.db.messages:  # type: ignore[attr-defined]
            if not isinstance(msg, Message):
                continue

            cycle = getattr(msg, "cycle_time", None)
            signals: list[DBCSignal] = []

            for s in msg.signals:
                sig = DBCSignal(
                    s.name,
                    s.start,
                    s.length,
                    s.byte_order,
                    s.is_signed,
                    s.scale,
                    s.offset,
                    s.minimum,
                    s.maximum,
                    s.unit if s.unit is not None else "",
                    is_float=bool(s.is_float),
                    choices={int(k): str(v) for k, v in (s.choices or {}).items()},
                )
                signals.append(sig)

            payload_len = msg.length  # <-- Ecco la lunghezza del payload
            self.messages.append(
                DBCMessage(
                    msg.frame_id,
                    msg.name,
                    cycle,
                    signals,
                    payload_len,
                    is_fd=bool(msg.is_fd),
                    is_extended_frame=bool(msg.is_extended_frame),
                )
            )


def load_dbc(filename: str) -> DBCLoader:
    return DBCLoader(filename)


# --- Single-signal codec -------------------------------------------------------
# Sliders write one signal into the payload that is about to be sent. Decoding
# the whole message and encoding it again (the old way) dropped every bit not
# covered by a signal, raised on any other signal outside its DBC [min|max] -
# frame not sent (TODO 4.5) - and zeroed all other signals when the payload did
# not decode (TODO 4.6). Writing only the signal's own bits avoids all three,
# and needs no frame-number lookup, which is ambiguous for std/ext (TODO 4.11).


def signal_bit_positions(sig) -> list[int]:
    """Payload bit positions of a signal, value MSB first.

    Bit p is bit p % 8 (LSB = 0) of byte p // 8; `start_bit` is the DBC start
    bit, as cantools gives it: the LSB for Intel, the MSB for Motorola.
    """
    n = sig.length
    if sig.byte_order == "little_endian":
        return [sig.start_bit + i for i in reversed(range(n))]
    positions, pos = [], sig.start_bit
    for _ in range(n):
        positions.append(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return positions


def raw_limits(sig) -> tuple[int, int]:
    if sig.is_signed:
        return -(1 << (sig.length - 1)), (1 << (sig.length - 1)) - 1
    return 0, (1 << sig.length) - 1


def signal_range(sig) -> tuple[float, float]:
    """Slider range: the DBC [min|max] when it is set, else every raw value (TODO 4.7)."""
    factor = sig.factor or 1.0
    has_dbc = (
        sig.minimum is not None
        and sig.maximum is not None
        and sig.minimum < sig.maximum
    )
    if sig.is_float:
        return (sig.minimum, sig.maximum) if has_dbc else FLOAT_FALLBACK_RANGE
    raw_lo, raw_hi = raw_limits(sig)
    lo, hi = sorted((raw_lo * factor + sig.offset, raw_hi * factor + sig.offset))
    if has_dbc and sig.minimum <= hi and sig.maximum >= lo:
        lo, hi = max(lo, sig.minimum), min(hi, sig.maximum)
    return lo, hi


def _physical_to_raw(sig, value: float) -> int:
    scaled = (value - sig.offset) / (sig.factor or 1.0)
    if sig.is_float:
        fmt = ">d" if sig.length == 64 else ">f"
        ifmt = ">Q" if sig.length == 64 else ">I"
        return struct.unpack(ifmt, struct.pack(fmt, scaled))[0]
    lo, hi = raw_limits(sig)
    raw = min(max(round(scaled), lo), hi)  # clamp: never wrap into other bits
    return raw & ((1 << sig.length) - 1)  # two's complement for signed


def encode_signal(payload: bytes, sig, value: float) -> bytes:
    """`payload` with `sig` set to the physical `value`, every other bit unchanged.

    Bits beyond the payload (DLC shorter than the DBC message) are dropped.
    """
    raw = _physical_to_raw(sig, value)
    out = bytearray(payload)
    n = sig.length
    for i, pos in enumerate(signal_bit_positions(sig)):
        byte, bit = divmod(pos, 8)
        if byte >= len(out):
            continue
        if (raw >> (n - 1 - i)) & 1:
            out[byte] |= 1 << bit
        else:
            out[byte] &= ~(1 << bit) & 0xFF
    return bytes(out)


def decode_signal(payload: bytes, sig) -> float:
    """Physical value of `sig` in `payload` (missing bytes read as 0)."""
    raw = 0
    for pos in signal_bit_positions(sig):
        byte, bit = divmod(pos, 8)
        raw = (raw << 1) | ((payload[byte] >> bit) & 1 if byte < len(payload) else 0)
    if sig.is_float:
        fmt, ifmt = (">d", ">Q") if sig.length == 64 else (">f", ">I")
        scaled = struct.unpack(fmt, struct.pack(ifmt, raw))[0]
    else:
        if sig.is_signed and raw & (1 << (sig.length - 1)):
            raw -= 1 << sig.length
        scaled = raw
    return scaled * (sig.factor or 1.0) + sig.offset


def dbc_bit_label(sig) -> str:
    """DBC notation, e.g. "7|12@0-": start bit | length @ byte order sign (TODO 4.7)."""
    order = "1" if sig.byte_order == "little_endian" else "0"
    return f"{sig.start_bit}|{sig.length}@{order}{'-' if sig.is_signed else '+'}"

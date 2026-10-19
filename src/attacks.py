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
"""Attack modes for reproducible CAN-IDS datasets (TODO 13.1).

These formalise what `*_setup_with_attacks.json` and the templates do by hand:
each mode is described once, with explicit parameters, and the controller turns
it into ordinary TX rows driven by the existing scheduler. Nothing new sends
frames — an attack is a set of `TxEntry` rows (and/or suspended target rows)
applied while it runs and withdrawn when it stops.

The module is Qt-free and holds no reference to the TX engine: the controller
talks to an adapter the caller supplies (the GUI, or a bench script), so the
same attack definitions run under unittest, on the bench and in the app.

Reproducibility: every random payload is drawn from a `random.Random(seed)`
seeded by the spec, so the same spec sends the same bytes. Start/stop are
recorded as `AttackEvent`s with the spec's parameters, to be written into the
trace as out-of-band labels (TODO 13.2) — the in-band `0xA7` marker cannot
label flood, suspension or replays of benign sequences.

Mapping to the standard CAN-IDS taxonomy (Car-Hacking / Survival / ROAD):
  FLOOD       one high-priority ID at the minimum period — denial of service.
  FUZZING     random payloads on one or more target IDs.
  SPOOFING    a legitimate ID injected with a falsified payload, faster than
              the genuine node (masquerade).
  REPLAY      a recorded payload sequence for an ID, re-injected in order.
  SUSPENSION  a target ID silenced (its TX row disabled) — a missing node.

Known limit of staying "thin over TxEntry": a row has one fixed ID, so random-
*ID* fuzzing is expressed as several rows over an explicit ID list, not a single
row that changes ID every frame. That needs a raw injector (declined for 13.1).
"""

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from src.tx_model import (
    CAN_FD_LENGTHS,
    CAN_MAX_EXT_ID,
    CAN_MAX_STD_ID,
    PERIOD_MAX_MS,
    PERIOD_MIN_MS,
    payload_text,
)


class AttackMode(Enum):
    FLOOD = "flood"
    FUZZING = "fuzzing"
    SPOOFING = "spoofing"
    REPLAY = "replay"
    SUSPENSION = "suspension"


# payload_fn(dlc, frame_id) -> bytes | None, like the script API; None on a row
# with a fixed payload. The adapter sends `payload` when payload_fn returns None.
PayloadFn = Callable[[int, int], Optional[bytes]]


@dataclass(eq=False)
class AttackRow:
    """One injected TX row. Mirrors the TxEntry fields the engine needs; the
    adapter builds the real TxEntry from it so this module imports no Qt."""

    frame_id: int
    is_ext: bool = False
    is_fd: bool = False
    dlc: int = 8
    period: int = PERIOD_MIN_MS
    payload: bytes = b""
    payload_fn: Optional[PayloadFn] = None
    name: str = ""


def _clamp_id(frame_id: int, is_ext: bool) -> int:
    hi = CAN_MAX_EXT_ID if is_ext else CAN_MAX_STD_ID
    return max(0, min(int(frame_id), hi))


def _fixed_dlc(dlc: int, is_fd: bool) -> int:
    dlc = int(dlc)
    if not is_fd:
        return min(max(dlc, 1), 8)
    return next((n for n in CAN_FD_LENGTHS if n >= dlc), 64)


def _random_payload_fn(seed: int, marker: Optional[int]):
    """A fresh RNG per instance: the sequence depends only on the seed, not on
    how many other rows drew before it. `marker` sets byte 1 (the 0xA7 in-band
    marker) when > 1 byte; None leaves the payload unmarked."""
    rng = random.Random(seed)

    def get_payload(dlc: int, frame_id: int):
        data = bytearray(rng.randrange(256) for _ in range(dlc))
        if marker is not None and dlc > 1:
            data[1] = marker & 0xFF
        return bytes(data)

    return get_payload


def _replay_fn(payloads):
    """Cycle through recorded payloads, padded/truncated to the row DLC."""
    seq = [bytes(p) for p in payloads]
    i = [0]

    def get_payload(dlc: int, frame_id: int):
        if not seq:
            return None
        p = seq[i[0] % len(seq)]
        i[0] += 1
        return p[:dlc] + bytes(max(0, dlc - len(p)))

    return get_payload


@dataclass
class AttackSpec:
    """An attack, fully described and reproducible. `build()` is pure."""

    mode: AttackMode
    # FLOOD/FUZZING/SPOOFING/REPLAY injected IDs; SUSPENSION silenced IDs
    target_ids: tuple = ()
    is_ext: bool = False
    is_fd: bool = False
    dlc: int = 8
    period: int = PERIOD_MIN_MS
    payload: bytes = b""  # FLOOD/SPOOFING fixed payload
    replay_payloads: tuple = ()  # REPLAY: the recorded sequence for one ID
    seed: int = 0  # FUZZING
    marker: Optional[int] = 0xA7  # FUZZING in-band byte-1 marker; None = off
    name: str = ""

    def __post_init__(self):
        self.target_ids = tuple(_clamp_id(i, self.is_ext) for i in self.target_ids)
        self.dlc = _fixed_dlc(self.dlc, self.is_fd)
        self.period = max(PERIOD_MIN_MS, min(int(self.period), PERIOD_MAX_MS))

    def build(self) -> tuple[list[AttackRow], list[tuple[int, bool]]]:
        """(rows to inject, (id, is_ext) keys to suspend)."""
        if self.mode is AttackMode.SUSPENSION:
            return [], [(i, self.is_ext) for i in self.target_ids]

        rows = []
        for n, frame_id in enumerate(self.target_ids):
            if self.mode is AttackMode.FUZZING:
                fn = _random_payload_fn(self.seed + n, self.marker)
                payload = b""
            elif self.mode is AttackMode.REPLAY:
                fn = _replay_fn(self.replay_payloads)
                payload = b""
            else:  # FLOOD, SPOOFING: a fixed falsified payload
                fn = None
                payload = bytes(self.payload[: self.dlc]) + bytes(
                    max(0, self.dlc - len(self.payload))
                )
            rows.append(
                AttackRow(
                    frame_id=frame_id,
                    is_ext=self.is_ext,
                    is_fd=self.is_fd,
                    dlc=self.dlc,
                    period=self.period,
                    payload=payload,
                    payload_fn=fn,
                    name=self.name or f"attack_{self.mode.value}",
                )
            )
        return rows, []

    def describe(self) -> str:
        """One-line label for the trace / logs (TODO 13.2)."""
        ids = ",".join(
            f"0x{i:08X}" if self.is_ext else f"0x{i:03X}" for i in self.target_ids
        )
        parts = [self.mode.value, f"ids={ids}", f"T={self.period}ms", f"dlc={self.dlc}"]
        if self.mode is AttackMode.FUZZING:
            parts.append(f"seed={self.seed}")
            parts.append(
                f"marker={'off' if self.marker is None else f'0x{self.marker:02X}'}"
            )
        elif self.mode in (AttackMode.FLOOD, AttackMode.SPOOFING):
            parts.append(f"payload={payload_text(self.payload[: self.dlc])}")
        elif self.mode is AttackMode.REPLAY:
            parts.append(f"frames={len(self.replay_payloads)}")
        return " ".join(parts)


@dataclass
class AttackEvent:
    label: str
    mode: str
    action: str  # "start" | "stop"
    timestamp: float
    spec: AttackSpec = field(repr=False, default=None)


class AttackController:
    """Starts and stops one attack at a time through a caller-supplied adapter.

    The adapter provides:
      inject(row: AttackRow) -> handle   schedule a TX row; returns an opaque
                                         handle used later to withdraw it.
      withdraw(handle)                   unschedule and drop that row.
      set_suspended(key, suspended)      disable (True) / restore (False) a
                                         normal TX row by (id, is_ext).
    A missing method is simply not used (suspension-only or inject-only callers).
    """

    def __init__(self, adapter, clock: Callable[[], float] = time.time):
        self._adapter = adapter
        self._clock = clock
        self._spec: Optional[AttackSpec] = None
        self._handles: list = []
        self._suspended: list[tuple[int, bool]] = []
        self.events: list[AttackEvent] = []

    @property
    def active(self) -> bool:
        return self._spec is not None

    @property
    def spec(self) -> Optional[AttackSpec]:
        return self._spec

    def start(self, spec: AttackSpec) -> AttackEvent:
        if self._spec is not None:
            raise RuntimeError("an attack is already running; stop it first")
        rows, suspend = spec.build()
        self._handles = [self._adapter.inject(row) for row in rows]
        for key in suspend:
            self._adapter.set_suspended(key, True)
        self._suspended = list(suspend)
        self._spec = spec
        event = AttackEvent(
            spec.describe(), spec.mode.value, "start", self._clock(), spec
        )
        self.events.append(event)
        return event

    def stop(self) -> Optional[AttackEvent]:
        if self._spec is None:
            return None
        for handle in self._handles:
            self._adapter.withdraw(handle)
        for key in self._suspended:
            self._adapter.set_suspended(key, False)
        spec, self._spec = self._spec, None
        self._handles = []
        self._suspended = []
        event = AttackEvent(
            spec.describe(), spec.mode.value, "stop", self._clock(), spec
        )
        self.events.append(event)
        return event

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

# Global payload script for CANino App: one instance serves every TX ID that has
# no per-ID script, so keep any state keyed by `id`. It must define
#     get_payload(dlc: int, id: int) -> bytes | None
# returning exactly `dlc` bytes (1-8 classic CAN, up to 64 CAN FD), or None to
# send the row's manual payload instead. DBC sliders are applied afterwards.

import csv
import logging
import os

# Replay files: payload_sequence_ID_<hex ID>.csv, header "Index,B7,...,B0", one
# frame per row, the last column is byte 0. Bytes are decimal (0-255); a cell
# written as 0x.. is read as hex. Before 1.5.0 any 1-2 character cell was read
# as hex, so 10-99 went out as 0x10-0x99 (16-153).
# The directory is relative to this script, not to the CWD CANino started in.
CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp")

# Intentional attack marker: byte 1 of every frame is 0xA7. Frames with DLC 1
# have no byte 1 and carry no marker.
ATTACK_MARKER = 0xA7

log = logging.getLogger("canino.scripts")
_payloads = {}  # id -> list of frames; [] = no replay file, manual payload
_counters = {}


def _parse_byte(cell: str) -> int:
    cell = cell.strip()
    value = int(cell, 16) if cell.lower().startswith("0x") else int(cell, 10)
    if not 0 <= value <= 255:
        raise ValueError(f"byte out of range 0..255: {value}")
    return value


def _row_to_bytes(row: list[str]) -> bytes:
    # Columns after Index are B7..B0: reversed, byte 0 comes first
    return bytes(_parse_byte(c) for c in reversed(row[1:]) if c.strip())


def _replay_file(arbid: int) -> str | None:
    for name in (
        f"payload_sequence_ID_{arbid:03X}.csv",
        f"payload_sequence_ID_{arbid:03x}.csv",
    ):
        path = os.path.join(CSV_DIR, name)
        if os.path.exists(path):
            return path
    return None


def _load_payloads_for_id(arbid: int) -> list[bytes]:
    path = _replay_file(arbid)
    if path is None:
        log.warning(
            "No replay file for ID 0x%03X in %s: its manual payload is sent",
            arbid,
            os.path.abspath(CSV_DIR),
        )
        return []
    payloads, bad = [], 0
    with open(path, newline="") as csvfile:
        for line_num, row in enumerate(csv.reader(csvfile), start=1):
            if not any(cell.strip() for cell in row):
                continue
            try:
                payloads.append(_row_to_bytes(row))
            except ValueError:
                bad += line_num > 1  # line 1 is the header
    if bad:
        log.warning("%s: %d unreadable rows skipped", path, bad)
    return payloads


def get_payload(dlc: int = 8, id: int = None) -> bytes | None:
    """Next frame of this ID's replay file, cycling; None if the ID has no file."""
    if id is None:
        return None
    if id not in _payloads:
        _payloads[id] = _load_payloads_for_id(id)  # read once, also when missing
        _counters[id] = 0
    seq = _payloads[id]
    if not seq:
        return None
    frame = bytearray(seq[_counters[id] % len(seq)][:dlc])
    _counters[id] += 1
    frame += bytes(dlc - len(frame))  # short rows are zero-padded
    if dlc > 1:
        frame[1] = ATTACK_MARKER
    return bytes(frame)


def set_csv_dir(path: str) -> None:
    """Change the CSV directory and clear the cache."""
    global CSV_DIR
    CSV_DIR = path
    _payloads.clear()
    _counters.clear()

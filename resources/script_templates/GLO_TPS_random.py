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

import random

# Intentional attack marker: byte 1 of every frame is 0xA7. Frames with DLC 1
# have no byte 1 and carry no marker. Set it to None to send the bytes unmarked
# (e.g. an exact replay of a benign sequence).
ATTACK_MARKER = 0xA7


def get_payload(dlc: int = 8, id: int = None) -> bytes:
    """A fresh random payload for every frame of every ID, marker in byte 1."""
    payload = bytearray(random.randint(0, 255) for _ in range(dlc))
    if ATTACK_MARKER is not None and dlc > 1:
        payload[1] = ATTACK_MARKER
    return bytes(payload)

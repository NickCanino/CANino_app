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

# Per-ID payload script for CANino App: linked to one TX row, loaded as its own
# instance for that ID (two IDs linking this file get two independent copies).
# It must define
#     get_payload(dlc: int, id: int) -> bytes | None
# returning exactly `dlc` bytes (1-8 classic CAN, up to 64 CAN FD), or None to
# send the row's manual payload instead. DBC sliders are applied afterwards.
# It may also return (payload, label): a non-empty str label marks the frame as
# anomalous and the Signal Plot highlights it (payload None = manual payload).

# Optional state variables (e.g., to keep track of time or a counter)
counter = 0


def get_payload(dlc: int = 8, id: int = None) -> bytes:
    global counter
    counter = (counter + 1) % 256  # sawtooth on 1 byte (0-255)

    # All bytes 0x00; edit payload[0] ... payload[dlc - 1] as needed
    payload = [0x00] * dlc
    payload[dlc - 1] = counter  # sawtooth on the last byte

    return bytes(payload)

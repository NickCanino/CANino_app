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
#
# A sine on one DBC signal (DBC_SIGNAL_SPEC), centred in the signal's range;
# every other bit stays 0. The phase advances by DT per transmitted frame.

import math
import re

# Persistent state across calls: the sine's time (s)
time = 0.0

# Configuration
AMPL = 1.0  # in [0.0, 1.0] (1.0 = full scale, 0.5 = half scale)
FREQ = 10.0  # in (0.0, MAX_FREQ] [Hz]
MAX_FREQ = 1000.0  # [Hz]
DT = 1.0 / (MAX_FREQ * 10.0)

# The signal, copied from the DBC: "start_bit|length@byte_order sign"
# @0 = Motorola (big endian, start_bit is the MSB)
# @1 = Intel    (little endian, start_bit is the LSB)
DBC_SIGNAL_SPEC = "7|14@0+"


def _parse_dbc_spec(spec: str) -> tuple[int, int, int, bool]:
    """(start_bit, length, byte_order, is_signed) from a spec like '7|14@0+'."""
    m = re.match(r"^\s*(\d+)\|(\d+)@([01])([+-])\s*$", spec)
    if not m:
        raise ValueError(f"Invalid DBC spec: '{spec}'. Use 'x|y@0+' or 'x|y@1+'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), (m.group(4) == "-")


def _pack_dbc_signal(
    payload: list[int], raw_val: int, start_bit: int, length: int, endian: int
) -> bool:
    """Write raw_val into payload by the DBC Motorola (@0) or Intel (@1) rules.

    False if the signal does not fit the payload.
    """
    total_bits = len(payload) * 8

    if endian == 1:
        # Intel (little endian): start_bit is the LSB, bits go up linearly
        if start_bit + length > total_bits:
            return False
        for i in range(length):
            if (raw_val >> i) & 1:
                bit_pos = start_bit + i
                payload[bit_pos // 8] |= 1 << (bit_pos % 8)
    else:
        # Motorola (big endian): start_bit is the MSB, bits go down inside a
        # byte and continue at the MSB of the next byte
        curr_bit = start_bit
        for i in range(length):
            if curr_bit < 0 or curr_bit >= total_bits:
                return False
            if (raw_val >> (length - 1 - i)) & 1:  # from the value's MSB
                payload[curr_bit // 8] |= 1 << (curr_bit % 8)
            if curr_bit % 8 == 0:
                curr_bit = (curr_bit // 8 + 1) * 8 + 7  # MSB of the next byte
            else:
                curr_bit -= 1

    return True


def get_payload(dlc: int = 8, id: int = None) -> bytes | None:
    global time

    start_bit, num_bits, endian, is_signed = _parse_dbc_spec(DBC_SIGNAL_SPEC)

    # 1. Signal range (unsigned '+', or signed '-' in two's complement)
    if is_signed:
        min_val = -(1 << (num_bits - 1))
        max_val = (1 << (num_bits - 1)) - 1
    else:
        min_val = 0
        max_val = (1 << num_bits) - 1

    mid_val = (max_val + min_val) / 2.0
    half_span = (max_val - min_val) / 2.0

    # 2. The sine, centred in the range
    ampl = max(0.0, min(1.0, AMPL))
    sine_t = mid_val + half_span * ampl * math.sin(2.0 * math.pi * FREQ * time)

    # 3. To an integer, masked to the signal's bits (two's complement)
    sine_int = max(min_val, min(max_val, round(sine_t)))
    raw_val = sine_int & ((1 << num_bits) - 1)

    # 4. Pack it as DBC_SIGNAL_SPEC says; a DLC too short for the signal gets
    # all zeros (exactly `dlc` bytes, never a silent fall back to the manual
    # payload) and does not advance the sine
    payload = [0x00] * dlc
    if num_bits <= 0 or not _pack_dbc_signal(
        payload, raw_val, start_bit, num_bits, endian
    ):
        return bytes(dlc)

    time += DT  # advance for the next frame
    return bytes(payload)

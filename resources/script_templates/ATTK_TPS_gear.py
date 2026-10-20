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

import math
import random
import re

# -----------------------------------------------------------------------------
# 1. DBC & Polynomial Time-Series Configuration
# -----------------------------------------------------------------------------
DBC_SIGNAL_SPEC = "7|14@0+"  # "start_bit|length@endian+-" (@0=Motorola, @1=Intel)

CYCLE_FRAMES = 1000          # Frames for one full polynomial driving cycle
EXP_RATE = 4.0               # Steepness factor (alpha) for exponential anomalies

# 10th-order polynomial coefficients [c10, c9, ..., c1, c0] evaluated on x in [-1, 1]
# P(x) = c10*x^10 + c9*x^9 + ... + c0 (C1-continuous at boundaries x = -1 and x = +1)
POLY_COEFFS_10 = [
    -12.00,   # x^10
      0.50,   # x^9
     48.00,   # x^8
     -1.30,   # x^7
    -64.50,   # x^6
      1.25,   # x^5
     33.55,   # x^4
     -0.60,   # x^3
     -5.60,   # x^2
      0.15,   # x^1
      0.63,   # x^0
]

# -----------------------------------------------------------------------------
# 2. Anomaly Timing Configuration (Normal ~ 4x Anomaly duration)
# -----------------------------------------------------------------------------
ANOMALY_FRAMES_RANGE = (60, 100)   # Avg: 80 frames
NORMAL_FRAMES_RANGE = (240, 400)   # Avg: 320 frames (4x anomaly duration)
RAND_HOLD_RANGE = (1, 10)          # Hold duration (1-10 frames) for each random step

# -----------------------------------------------------------------------------
# 3. Persistent State Across Application Calls
# -----------------------------------------------------------------------------
global_frame = 0
state = "NORMAL"                   # "NORMAL" or "ANOMALY"
next_anomaly_idx = 0               # 0: Random steps, 1: Stuck, 2: Exp+ Max, 3: Exp- Min
frames_left = random.randint(*NORMAL_FRAMES_RANGE)

anom_total_frames = 1
anom_elapsed_frames = 0
last_normal_val = 0
attack_start_val = 0

rand_step_val = 0
rand_step_frames_left = 0


def _parse_dbc_spec(spec: str) -> tuple[int, int, int, bool]:
    m = re.match(r"^\s*(\d+)\|(\d+)@([01])([+-])\s*$", spec)
    if not m:
        raise ValueError(f"Invalid DBC format: '{spec}'. Use 'x|y@0+' or 'x|y@1+'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), (m.group(4) == "-")


def _pack_dbc_signal(payload: list[int], raw_val: int, start_bit: int, length: int, endian: int) -> bool:
    total_bits = len(payload) * 8

    if endian == 1:
        # INTEL (Little Endian): start_bit is LSB
        if start_bit + length > total_bits:
            return False
        for i in range(length):
            if (raw_val >> i) & 1:
                bit_pos = start_bit + i
                payload[bit_pos // 8] |= (1 << (bit_pos % 8))
    else:
        # MOTOROLA (Big Endian): start_bit is MSB
        curr_bit = start_bit
        for i in range(length):
            if curr_bit < 0 or curr_bit >= total_bits:
                return False
            if (raw_val >> (length - 1 - i)) & 1:
                payload[curr_bit // 8] |= (1 << (curr_bit % 8))

            if (curr_bit % 8) == 0:
                curr_bit = ((curr_bit // 8) + 1) * 8 + 7
            else:
                curr_bit -= 1

    return True


def _eval_poly_rpm(frame_idx: int, min_val: int, max_val: int) -> int:
    """Evaluates the 10th-order polynomial on normalized cycle coordinate x in [-1, 1]."""
    x = 2.0 * ((frame_idx % CYCLE_FRAMES) / float(CYCLE_FRAMES)) - 1.0

    # Horner's method for P(x)
    norm_val = 0.0
    for c in POLY_COEFFS_10:
        norm_val = norm_val * x + c

    norm_val = max(0.0, min(1.0, norm_val))
    scaled = min_val + norm_val * (max_val - min_val)
    return max(min_val, min(max_val, round(scaled)))


def _start_anomaly() -> None:
    """Initializes the next anomaly in circular order: 0 -> 1 -> 2 -> 3."""
    global frames_left, anom_total_frames, anom_elapsed_frames
    global attack_start_val, rand_step_frames_left

    anom_total_frames = random.randint(*ANOMALY_FRAMES_RANGE)
    frames_left = anom_total_frames
    anom_elapsed_frames = 0
    attack_start_val = last_normal_val
    rand_step_frames_left = 0


def get_payload(dlc: int = 8, id: int = None) -> bytes | None:
    global global_frame, state, next_anomaly_idx, frames_left
    global anom_elapsed_frames, last_normal_val
    global rand_step_val, rand_step_frames_left

    try:
        start_bit, num_bits, endian, is_signed = _parse_dbc_spec(DBC_SIGNAL_SPEC)
    except ValueError:
        return None

    if num_bits <= 0 or num_bits > dlc * 8:
        return None

    # 1. Signal range boundaries
    if is_signed:
        min_val = -(1 << (num_bits - 1))
        max_val = (1 << (num_bits - 1)) - 1
    else:
        min_val = 0
        max_val = (1 << num_bits) - 1

    # 2. Always compute the physical polynomial value in background (time keeps moving)
    true_poly_val = _eval_poly_rpm(global_frame, min_val, max_val)
    global_frame += 1

    # 3. State machine transition check
    if frames_left <= 0:
        if state == "NORMAL":
            state = "ANOMALY"
            _start_anomaly()
        else:
            state = "NORMAL"
            next_anomaly_idx = (next_anomaly_idx + 1) % 4
            frames_left = random.randint(*NORMAL_FRAMES_RANGE)

    frames_left -= 1

    # 4. Compute output value according to active state
    if state == "NORMAL":
        out_val = true_poly_val
        last_normal_val = out_val
    else:
        # Normalized progress tau in [0.0, 1.0] across the anomaly window
        denom = max(1, anom_total_frames - 1)
        tau = min(1.0, anom_elapsed_frames / float(denom))
        anom_elapsed_frames += 1

        if next_anomaly_idx == 0:
            # 0: Sequence of random values held for 1-10 frames each
            if rand_step_frames_left <= 0:
                rand_step_val = random.randint(min_val, max_val)
                rand_step_frames_left = random.randint(*RAND_HOLD_RANGE)
            rand_step_frames_left -= 1
            out_val = rand_step_val

        elif next_anomaly_idx == 1:
            # 1: Stuck at the last normal value before the attack
            out_val = attack_start_val

        elif next_anomaly_idx == 2:
            # 2: Positive exponential variation from attack_start_val up to max_val
            exp_factor = (math.exp(EXP_RATE * tau) - 1.0) / (math.exp(EXP_RATE) - 1.0)
            val = attack_start_val + (max_val - attack_start_val) * exp_factor
            out_val = max(min_val, min(max_val, round(val)))

        else:
            # 3: Negative exponential variation from attack_start_val down to min_val (0 rpm)
            exp_factor = (math.exp(-EXP_RATE * tau) - math.exp(-EXP_RATE)) / (1.0 - math.exp(-EXP_RATE))
            val = min_val + (attack_start_val - min_val) * exp_factor
            out_val = max(min_val, min(max_val, round(val)))

    # 5. Pack into CAN payload according to DBC_SIGNAL_SPEC
    raw_val = out_val & ((1 << num_bits) - 1)
    payload = [0x00] * dlc
    if not _pack_dbc_signal(payload, raw_val, start_bit, num_bits, endian):
        return None

    return bytes(payload)
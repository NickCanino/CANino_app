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
# 1. Base Signal & DBC Configuration
# -----------------------------------------------------------------------------
DBC_SIGNAL_SPEC = "7|14@0+"  # "start_bit|length@endian+-" (@0=Motorola, @1=Intel)

AMPL = 0.6          # Nominal amplitude in [0.0, 1.0] (e.g., 0.6 leaves headroom for +delta)
FREQ = 50.0         # Nominal frequency in (0.0, MAX_FREQ] [Hz]
MAX_FREQ = 1000.0   # [Hz]
DT = 1.0 / (MAX_FREQ * 10.0)

# -----------------------------------------------------------------------------
# 2. Anomaly Injection Configuration (Circular: Freq -> Ampl -> Stuck -> Spike)
# -----------------------------------------------------------------------------
NORMAL_FRAMES_RANGE = (200, 400)   # Frames of normal behavior between anomalies
ANOMALY_FRAMES_RANGE = (50, 150)   # Duration in frames for Freq, Ampl, and Stuck anomalies
SPIKE_FRAMES_RANGE = (1, 5)        # Duration in frames for Spike anomaly (1 to 5 frames)

DELTA_FREQ = 30.0                  # +/- frequency shift [Hz]
DELTA_AMPL = 0.35                  # +/- amplitude shift [0.0, 1.0]

# -----------------------------------------------------------------------------
# 3. Persistent State Across Application Calls
# -----------------------------------------------------------------------------
phase = 0.0
state = "NORMAL"                   # "NORMAL" or "ANOMALY"
next_anomaly_idx = 0               # 0: Freq, 1: Ampl, 2: Stuck, 3: Spike
frames_left = random.randint(*NORMAL_FRAMES_RANGE)

active_freq = FREQ
active_ampl = AMPL
stuck_val = 0
spike_val = 0
last_normal_val = 0


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


def _trigger_next_anomaly(min_val: int, max_val: int) -> None:
    """Initializes the next anomaly in the circular sequence 0 -> 1 -> 2 -> 3."""
    global active_freq, active_ampl, stuck_val, spike_val, frames_left

    sign = random.choice([-1.0, 1.0])

    if next_anomaly_idx == 0:
        # 0: Frequency delta increase or decrease
        active_freq = max(0.1, min(MAX_FREQ, FREQ + sign * DELTA_FREQ))
        frames_left = random.randint(*ANOMALY_FRAMES_RANGE)

    elif next_anomaly_idx == 1:
        # 1: Amplitude delta increase or decrease
        active_ampl = max(0.0, min(1.0, AMPL + sign * DELTA_AMPL))
        frames_left = random.randint(*ANOMALY_FRAMES_RANGE)

    elif next_anomaly_idx == 2:
        # 2: Stuck at a value (freezes on the last generated value)
        stuck_val = last_normal_val
        frames_left = random.randint(*ANOMALY_FRAMES_RANGE)

    elif next_anomaly_idx == 3:
        # 3: Spike to a near-extreme value for 1 to 5 consecutive frames
        span = max_val - min_val
        if random.choice([True, False]):
            spike_val = random.randint(int(max_val - 0.1 * span), max_val)
        else:
            spike_val = random.randint(min_val, int(min_val + 0.1 * span))
        frames_left = random.randint(*SPIKE_FRAMES_RANGE)


def get_payload(dlc: int = 8, id: int = None) -> bytes | None:
    global phase, state, next_anomaly_idx, frames_left
    global active_freq, active_ampl, last_normal_val

    try:
        start_bit, num_bits, endian, is_signed = _parse_dbc_spec(DBC_SIGNAL_SPEC)
    except ValueError:
        return None

    if num_bits <= 0 or num_bits > dlc * 8:
        return None

    # 1. Signal boundaries
    if is_signed:
        min_val = -(1 << (num_bits - 1))
        max_val = (1 << (num_bits - 1)) - 1
    else:
        min_val = 0
        max_val = (1 << num_bits) - 1

    mid_val = (max_val + min_val) / 2.0
    half_span = (max_val - min_val) / 2.0

    # 2. State machine transition check
    if frames_left <= 0:
        if state == "NORMAL":
            state = "ANOMALY"
            _trigger_next_anomaly(min_val, max_val)
        else:
            # Return to normal behavior and advance circular index
            state = "NORMAL"
            active_freq = FREQ
            active_ampl = AMPL
            next_anomaly_idx = (next_anomaly_idx + 1) % 4
            frames_left = random.randint(*NORMAL_FRAMES_RANGE)

    frames_left -= 1

    # 3. Compute signal value based on current state
    ampl = max(0.0, min(1.0, active_ampl))
    sine_t = mid_val + half_span * ampl * math.sin(phase)
    phase = (phase + 2.0 * math.pi * active_freq * DT) % (2.0 * math.pi)

    sine_int = max(min_val, min(max_val, round(sine_t)))

    if state == "NORMAL" or next_anomaly_idx in (0, 1):
        # Normal, Frequency anomaly, or Amplitude anomaly
        out_val = sine_int
        last_normal_val = out_val
    elif next_anomaly_idx == 2:
        # Stuck at value
        out_val = stuck_val
    else:
        # Spike value (1 to 5 consecutive frames)
        out_val = spike_val

    # 4. Two's complement mask & DBC bit packing
    raw_val = out_val & ((1 << num_bits) - 1)
    payload = [0x00] * dlc
    if not _pack_dbc_signal(payload, raw_val, start_bit, num_bits, endian):
        return None

    return bytes(payload)
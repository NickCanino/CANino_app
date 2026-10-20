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
import re

# Persistent state across application calls
time = 0.0

# Configuration parameters
AMPL = 1.0         # Configurable in [0.0, 1.0] (1.0 = full scale, 0.5 = half scale)
FREQ = 10.0        # Configurable in (0.0, MAX_FREQ] [Hz]
MAX_FREQ = 1000.0  # [Hz]
DT = 1.0 / (MAX_FREQ * 10.0)

# Copia qui direttamente la specifica dal file DBC: "start_bit|length@endian+-"
# @0 = Motorola (Big Endian, start_bit è MSB)
# @1 = Intel    (Little Endian, start_bit è LSB)
DBC_SIGNAL_SPEC = "7|14@0+"


def _parse_dbc_spec(spec: str) -> tuple[int, int, int, bool]:
    """Estrae (start_bit, length, endianness, is_signed) da stringhe tipo '7|14@0+'."""
    m = re.match(r"^\s*(\d+)\|(\d+)@([01])([+-])\s*$", spec)
    if not m:
        raise ValueError(f"Formato DBC non valido: '{spec}'. Usa 'x|y@0+' o 'x|y@1+'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), (m.group(4) == "-")


def _pack_dbc_signal(payload: list[int], raw_val: int, start_bit: int, length: int, endian: int) -> bool:
    """Impacchetta raw_val nel payload seguendo le regole DBC Motorola (@0) o Intel (@1)."""
    total_bits = len(payload) * 8

    if endian == 1:
        # INTEL (Little Endian): start_bit è l'LSB, cresce linearmente (start_bit + i)
        if start_bit + length > total_bits:
            return False
        for i in range(length):
            bit_val = (raw_val >> i) & 1
            bit_pos = start_bit + i
            byte_idx = bit_pos // 8
            bit_in_byte = bit_pos % 8
            if bit_val:
                payload[byte_idx] |= (1 << bit_in_byte)
    else:
        # MOTOROLA (Big Endian): start_bit è l'MSB, scende dentro il byte e salta al byte successivo
        curr_bit = start_bit
        for i in range(length):
            if curr_bit < 0 or curr_bit >= total_bits:
                return False
            # Estrae a partire dall'MSB del valore (indice length - 1 - i)
            bit_val = (raw_val >> (length - 1 - i)) & 1
            byte_idx = curr_bit // 8
            bit_in_byte = curr_bit % 8
            if bit_val:
                payload[byte_idx] |= (1 << bit_in_byte)

            # Calcola il prossimo bit secondo la griglia DBC Motorola Forward
            if bit_in_byte == 0:
                curr_bit = (byte_idx + 1) * 8 + 7  # Salta all'MSB del byte successivo
            else:
                curr_bit -= 1

    return True


def get_payload(dlc: int = 8, id: int = None) -> bytes | None:
    global time

    try:
        start_bit, num_bits, endian, is_signed = _parse_dbc_spec(DBC_SIGNAL_SPEC)
    except ValueError:
        return None

    if num_bits <= 0 or num_bits > dlc * 8:
        return None

    # 1. Range del segnale (gestisce sia unsigned '+' che signed '-' in complemento a 2)
    if is_signed:
        min_val = -(1 << (num_bits - 1))
        max_val = (1 << (num_bits - 1)) - 1
    else:
        min_val = 0
        max_val = (1 << num_bits) - 1

    mid_val = (max_val + min_val) / 2.0
    half_span = (max_val - min_val) / 2.0

    # 2. Calcolo sinusoide centrata nel range
    ampl = max(0.0, min(1.0, AMPL))
    sine_t = mid_val + half_span * ampl * math.sin(2.0 * math.pi * FREQ * time)

    # Advance time for the next call
    time += DT

    # 3. Conversione in intero e mascheratura bit (per eventuali negativi in C2)
    sine_int = max(min_val, min(max_val, round(sine_t)))
    raw_val = sine_int & ((1 << num_bits) - 1)

    # 4. Impacchettamento nel payload secondo DBC_SIGNAL_SPEC
    payload = [0x00] * dlc
    if not _pack_dbc_signal(payload, raw_val, start_bit, num_bits, endian):
        return None

    return bytes(payload)
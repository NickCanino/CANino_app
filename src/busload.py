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
"""Bits a frame occupies on the wire, stuff bits included (TODO 9.8).

Classic CAN: dynamic stuffing from SOF to the end of the CRC, with the real
CRC-15. CAN FD (ISO 11898-1:2015): dynamic stuffing up to the end of the data
field, then stuff count + CRC-17/21 with fixed stuff bits. Every frame ends
with CRC delimiter, ACK slot, ACK delimiter, EOF (7) and intermission (3).
A remote frame counts as a data frame with its (empty) data.
"""

TAIL_BITS = 1 + 1 + 1 + 7 + 3  # CRC delimiter, ACK, ACK delimiter, EOF, IFS
CRC15_POLY = 0x4599
FD_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)  # index = DLC
# CAN FD CRC field after the data: stuff count (4) + CRC + fixed stuff bits
FD_CRC_FIELD = {17: 4 + 17 + 6, 21: 4 + 21 + 7}


def _stuff_step(last, run, bit):
    """One bit through the stuffing rule; returns (last, run, stuff bits)."""
    if bit == last:
        run += 1
    else:
        last, run = bit, 1
    if run == 5:  # the complement is inserted and starts the next run
        return 1 - last, 1, 1
    return last, run, 0


def _build_stuff_table():
    """[state][byte] -> (state, stuff bits); state = last bit * 6 + run length."""
    table = []
    for state in range(12):
        row = []
        for byte in range(256):
            last, run = divmod(state, 6)
            stuffed = 0
            for i in range(7, -1, -1):
                last, run, s = _stuff_step(last, run, (byte >> i) & 1)
                stuffed += s
            row.append((last * 6 + run, stuffed))
        table.append(row)
    return table


def _build_crc15_table():
    table = []
    for byte in range(256):
        crc = byte << 7
        for _ in range(8):
            crc = (crc << 1) ^ CRC15_POLY if crc & 0x4000 else crc << 1
        table.append(crc & 0x7FFF)
    return table


_STUFF = _build_stuff_table()
_CRC15 = _build_crc15_table()
_IDLE = 1 * 6 + 0  # before SOF: no run yet


def stuff_bits(value, nbits, state=_IDLE):
    """Stuff bits in `nbits` bits (MSB first) following `state`; returns (count, state)."""
    count = 0
    head = nbits % 8
    last, run = divmod(state, 6)
    for i in range(nbits - 1, nbits - 1 - head, -1):
        last, run, s = _stuff_step(last, run, (value >> i) & 1)
        count += s
    state = last * 6 + run
    for shift in range(nbits - head - 8, -1, -8):
        state, s = _STUFF[state][(value >> shift) & 0xFF]
        count += s
    return count, state


def crc15(value, nbits):
    """Classic CAN CRC of `nbits` bits (MSB first)."""
    crc = 0
    head = nbits % 8
    for i in range(nbits - 1, nbits - 1 - head, -1):
        bit = ((value >> i) & 1) ^ (crc >> 14)
        crc = ((crc << 1) ^ (CRC15_POLY if bit else 0)) & 0x7FFF
    for shift in range(nbits - head - 8, -1, -8):
        crc = ((crc << 8) & 0x7FFF) ^ _CRC15[((crc >> 7) ^ (value >> shift)) & 0xFF]
    return crc


def _arbitration(frame_id, is_ext):
    """SOF up to and including RTR/RRS, as (value, nbits)."""
    if is_ext:
        # SOF, base ID (11), SRR = 1, IDE = 1, ID extension (18), RTR/RRS = 0
        value = ((frame_id >> 18) << 2 | 0b11) << 18 | (frame_id & 0x3FFFF)
        return value << 1, 1 + 11 + 2 + 18 + 1
    # SOF, ID (11), RTR/RRS = 0 (IDE follows in the control field)
    return frame_id << 1, 1 + 11 + 1


def frame_bits(frame_id, data, is_fd=False, is_ext=False, brs=None):
    """(bits at the nominal rate, bits at the data rate) of one frame.

    Only a CAN FD frame with bit-rate switch has data-rate bits, from ESI to
    the end of the CRC field; `brs` defaults to `is_fd`.
    """
    data = bytes(data)
    length = len(data)
    payload = int.from_bytes(data, "big")
    value, nbits = _arbitration(frame_id, is_ext)

    if not is_fd:
        # std: IDE = 0, r0 = 0; ext: r1 = 0, r0 = 0; then DLC (4)
        value = (value << 2 << 4 | min(length, 8)) << 8 * length | payload
        nbits += 2 + 4 + 8 * length
        value = value << 15 | crc15(value, nbits)
        nbits += 15
        stuffed, _ = stuff_bits(value, nbits)
        return nbits + stuffed + TAIL_BITS, 0

    if brs is None:
        brs = True
    dlc = next(i for i, n in enumerate(FD_LENGTHS) if n >= length)
    # std: IDE = 0; both: FDF = 1, res = 0, BRS -> the rate switches after BRS
    control = (0b10 << 1 | bool(brs)) if is_ext else (0b010 << 1 | bool(brs))
    extra = 3 if is_ext else 4
    value = value << extra | control
    nbits += extra
    stuffed_nominal, state = stuff_bits(value, nbits)
    # ESI = 0, DLC (4), data (padded to the DLC length)
    data_bits = 1 + 4 + 8 * FD_LENGTHS[dlc]
    data_value = (dlc << 8 * FD_LENGTHS[dlc]) | payload << 8 * (
        FD_LENGTHS[dlc] - length
    )
    stuffed_data, _ = stuff_bits(data_value, data_bits, state)
    data_bits += stuffed_data + FD_CRC_FIELD[17 if FD_LENGTHS[dlc] <= 16 else 21]
    nominal = nbits + stuffed_nominal + TAIL_BITS
    return (nominal, data_bits) if brs else (nominal + data_bits, 0)

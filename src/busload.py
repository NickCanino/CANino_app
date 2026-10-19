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
"""Bit counts for the busload estimate, shared by TX and RX."""


def frame_bits(dlc, is_fd, is_ext):
    """(bits at the nominal rate, bits at the data rate) of one frame.

    arbitration = SOF(1) + ID(11|29) + RTR/IDE/RES(~3) + DLC(4)
    data phase = data(8*dlc) + CRC(+delimiter); ACK/EOF/IFS go at the nominal
    rate, so in CAN FD they count with the arbitration bits.
    """
    dlc = max(0, min(int(dlc), 64))
    arbitration_bits = 1 + (29 if is_ext else 11) + 3 + 4
    if not is_fd:
        data_phase_bits = 8 * dlc + (15 + 1) + 2 + 7 + 3
    else:
        crc_total = (17 + 1) if dlc <= 16 else (21 + 1)
        data_phase_bits = 8 * dlc + crc_total
        arbitration_bits += 2 + 7 + 3
    return arbitration_bits, data_phase_bits

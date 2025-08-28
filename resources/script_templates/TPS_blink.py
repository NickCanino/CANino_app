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

# This script is dynamically loaded by the main program.
# It must define the function: get_payload() -> bytes

# Optional state variables (e.g., to keep track of time or a counter)
counter = 0


def get_payload(dlc: int = 8, id: int = None) -> bytes:
    global counter
    counter += 1  # useful to vary the bytes over time, if you want

    # Initialize all 8 bytes to 0xFF
    payload = [0xFF] * 8

    # Modifiable section for each byte of the payload
    # payload[0] = ...
    # payload[1] = ...
    # payload[2] = ...
    # payload[3] = ...
    # payload[4] = ...
    # payload[5] = ...
    # payload[6] = ...
    # payload[7] = ...

    # Example: make the first byte toggle between 0xFF/0x00 every 10 calls
    if counter % 20 < 10:
        payload[0] = 0xFF
    else:
        payload[0] = 0x00

    return bytes(payload[:dlc])  # Return only the bytes requested by the DLC

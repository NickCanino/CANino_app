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

import csv
import os

# Optional state variables
counter = 0
payloads = []

# Load payloads from CSV file (provide the path here)
CSV_PATH = "../resources/tmp/payload_sequence_ID_140.csv"  # <-- Set your CSV file path


def _load_payloads():
    global payloads
    payloads.clear()
    abs_path = os.path.abspath(CSV_PATH)
    print(f"[DEBUG] Trying to load CSV from: {abs_path}")
    if not os.path.exists(abs_path):
        print(f"[ERROR] File does not exist: {abs_path}")
        return

    with open(abs_path, newline="") as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader, None)  # Skip header
        for line_num, row in enumerate(reader, start=2):
            # Skip empty or invalid rows
            if not row or all(cell.strip() == "" for cell in row):
                continue
            try:
                # Try to convert all columns except the first (Index) to int
                payload = [int(val) for val in row if val.strip() != ""]
                if payload:
                    payloads.append(payload)
            except Exception as e:
                print(f"[ERROR] Line {line_num}: {e} | Row: {row}")
                continue

    print(f"[DEBUG] Loaded {len(payloads)} payloads from {abs_path}")


# Load once at import
_load_payloads()


def get_payload(dlc: int = 8) -> bytes:
    global counter
    counter += 1

    if not payloads:
        _load_payloads()  # Reload payloads if empty for some reason
        if not payloads:
            raise ValueError("Payload list is still empty after attempting to load.")

    # Loop through payloads, restart if at end
    idx = (counter - 1) % len(payloads)
    payload = payloads[idx][:dlc]
    # payload = payloads[idx][:dlc] + [0xFF] * (dlc - len(payloads[idx]))

    # print(f"[DEBUG] TX payload : {[f'{b:02X}' for b in payload[:dlc]]}")
    print(f"[DEBUG] TX payload : {payload}")
    return bytes(payload[:dlc])  # Return the payload for the current counter value

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
loaded_id = None # Tracks which ID has been loaded

# Load payloads from CSV file (provide the path here)
CSV_DIR = "../CANino_app/resources/tmp/"  # <-- Set your CSV file path


def _load_payloads(arbid: int):
    """Load payloads for a given arbitration ID (hex)."""
    global payloads, loaded_id
    payloads.clear()
    loaded_id = arbid

    filename = f"payload_sequence_ID_{arbid:03X}.csv"
    abs_path = os.path.abspath(os.path.join(CSV_DIR, filename))
    print(f"[DEBUG] Trying to load CSV for ID {arbid:03X} from: {abs_path}")

    if not os.path.exists(abs_path):
        print(f"[ERROR] File does not exist: {abs_path}")
        return

    with open(abs_path, newline="") as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)  # Skip header if present
        for line_num, row in enumerate(reader, start=2):
            if not row or all(cell.strip() == "" for cell in row):
                continue
            try:
                payload = [int(val) for val in row if val.strip() != ""]
                if payload:
                    payloads.append(payload)
            except Exception as e:
                print(f"[ERROR] Line {line_num}: {e} | Row: {row}")
                continue

    print(f"[DEBUG] Loaded {len(payloads)} payloads for ID {arbid:03X}")
    

def get_payload(dlc: int = 8, id: int = None) -> bytes:
    """Return the next payload for the given arbitration ID."""
    global counter, payloads, loaded_id
    if id is None:
        raise ValueError("Must provide arbitration ID (id parameter)")

    # Reload if ID changed or not loaded yet
    if loaded_id != id or not payloads:
        _load_payloads(id)
        if not payloads:
            raise ValueError(f"No payloads found for ID {id:03X}")

    counter += 1
    idx = (counter - 1) % len(payloads)
    payload = payloads[idx][:dlc]

    print(f"[DEBUG] TX payload for ID {id:03X}: {payload}")
    return bytes(payload[:dlc])

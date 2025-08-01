# This script is dynamically loaded by the main program.
# It must define the function: get_payload() -> bytes

import csv

# Optional state variables
counter = 0
payloads = []

# Load payloads from CSV file (provide the path here)
CSV_PATH = "payload_sequence.csv"  # <-- Set your CSV file path

def _load_payloads():
    global payloads
    with open(CSV_PATH, newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            # Convert each value to int, ignore empty strings
            payload = [int(val) for val in row if val.strip() != '']
            payloads.append(payload)

# Load once at import
_load_payloads()

def get_payload(dlc: int = 8) -> bytes:
    global counter
    counter += 1

    # Loop through payloads, restart if at end
    idx = (counter - 1) % len(payloads)
    payload = payloads[idx][:dlc] + [0xFF] * (dlc - len(payloads[idx]))

    return bytes(payload)  # Return the payload for the current counter value

# This script is dynamically loaded by the main program.
# It must define the function: get_payload() -> bytes

# Optional state variables (e.g., to keep track of time or a counter)
counter = 0


def get_payload(dlc: int = 8) -> bytes:
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

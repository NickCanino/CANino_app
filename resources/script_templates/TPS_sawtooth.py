# This script is dynamically loaded by the main program.
# It must define the function: get_payload() -> bytes

# Optional state variables (e.g., to keep track of time or a counter)
counter = 0


def get_payload(dlc: int = 8) -> bytes:
    global counter
    counter = (counter + 1) % 256  # sawtooth on 1 byte (0–255)

    # Payload base: all bytes set to 0xFF
    payload = [0xFF] * 8

    # Modifiable section for each byte of the payload
    # payload[0] = ...
    # ...
    payload[dlc - 1] = counter  # sawtooth on byte 7

    return bytes(payload[:dlc])  # Return only the bytes requested by the DLC

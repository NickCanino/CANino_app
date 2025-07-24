# Questo script viene eseguito dal software per generare il payload CAN.
# Deve definire una funzione: get_payload() -> bytes

counter = 0  # stato globale

def get_payload(dlc: int = 8) -> bytes:
    global counter
    counter = (counter + 1) % 256  # dente di sega su 1 byte (0–255)

    # Payload base: tutti i byte a 0xFF
    payload = [0xFF] * 8

    # Sezione di modifica byte-per-byte
    # payload[0] = ...
    # ...
    payload[dlc-1] = counter  # dente di sega sul byte 7

    return bytes(payload[:dlc])  # Ritorna solo i byte richiesti dal DLC

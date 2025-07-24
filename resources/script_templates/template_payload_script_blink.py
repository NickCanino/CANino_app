# Questo script viene caricato dinamicamente dal programma principale.
# Deve definire la funzione: get_payload() -> bytes

# Variabili di stato opzionali (es. per tenere traccia del tempo o del contatore)
counter = 0

def get_payload(dlc: int = 8) -> bytes:
    global counter
    counter += 1  # utile per variare i byte nel tempo, se vuoi

    # Inizializza tutti gli 8 byte a 0xFF
    payload = [0xFF] * 8

    # Sezione modificabile per ogni byte del payload
    # payload[0] = ...
    # payload[1] = ...
    # payload[2] = ...
    # payload[3] = ...
    # payload[4] = ...
    # payload[5] = ...
    # payload[6] = ...
    # payload[7] = ...

    # Esempio: fai lampeggiare il primo byte 0xFF/0x00 ogni 10 chiamate
    if counter % 20 < 10:
        payload[0] = 0xFF
    else:
        payload[0] = 0x00

    return bytes(payload[:dlc])  # Ritorna solo i byte richiesti dal DLC

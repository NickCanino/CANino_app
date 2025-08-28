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
from collections import OrderedDict

# -------- Settings --------
CSV_DIR = "../resources/tmp"  # Cartella dei CSV
# CSV_DIR = "../CANino_app/resources/tmp"   # Cartella valida solo in fase di test su VS Code
CACHE_MAX_IDS = (
    None  # opzionale: limite al numero di ID in cache (es. 8). None = senza limite.
)
PAD_WITH_ZEROES = True  # se True, pad fino a dlc con 0x00 se la riga è più corta

# -------- State --------
# Cache: ID -> list[bytes] (ogni payload è già bytes per risparmiare memoria)
_payload_cache: "OrderedDict[int, list[bytes]]" = OrderedDict()
# Contatori per ID (indice corrente per ciascun ID)
_counters: dict[int, int] = {}


# -------- Helpers --------
def _id_filename(arbid: int) -> str:
    # Nomi tipo: payload_sequence_ID_XXX.csv con XXX in esadecimale a 3 cifre, maiuscolo
    return f"payload_sequence_ID_{arbid:03X}.csv"


def _is_int_like(s: str) -> bool:
    try:
        int(s.strip(), 0)  # supporta "255", "0xFF", "037", ecc.
        return True
    except Exception:
        return False


def _row_to_bytes(row: list[str]) -> bytes:
    vals = []
    # ignora SEMPRE la prima cella (indice riga)
    for cell in row[1:]:
        cell = cell.strip()
        if cell == "":
            continue
        try:
            if all(ch in "0123456789abcdefABCDEF" for ch in cell) and len(cell) <= 2:
                v = int(cell, 16)
            else:
                v = int(cell, 0)
        except Exception:
            continue
        if not (0 <= v <= 255):
            raise ValueError(f"byte fuori range 0..255: {v}")
        vals.append(v)
    return bytes(vals)


def _load_payloads_for_id(arbid: int) -> list[bytes]:
    filename = _id_filename(arbid)
    abs_path = os.path.abspath(os.path.join(CSV_DIR, filename))
    print(f"[DEBUG] Trying to load CSV for ID {arbid:03X} from: {abs_path}")

    if not os.path.exists(abs_path):
        print(f"[ERROR] File does not exist: {abs_path}")
        return []

    payloads: list[bytes] = []
    with open(abs_path, newline="") as csvfile:
        reader = csv.reader(csvfile)

        # Gestione header opzionale: se la prima riga contiene testo non numerico, trattala da header
        first = next(reader, None)
        start_line_num = 2
        if first is not None:
            has_text = any((c.strip() != "" and not _is_int_like(c)) for c in first)
            if not has_text:
                # la prima riga è già dati
                try:
                    b = _row_to_bytes(first)
                    if b:
                        payloads.append(b)
                except Exception as e:
                    print(f"[ERROR] Line 1: {e} | Row: {first}")
            else:
                # era header, i dati partono dalla riga 2
                pass
        # processa il resto
        for line_num, row in enumerate(reader, start=start_line_num):
            if not row or all(cell.strip() == "" for cell in row):
                continue
            try:
                b = _row_to_bytes(row)
                if b:
                    payloads.append(b)
            except Exception as e:
                print(f"[ERROR] Line {line_num}: {e} | Row: {row}")
                continue

    print(f"[DEBUG] Loaded {len(payloads)} payloads for ID {arbid:03X}")
    return payloads


def _ensure_in_cache(arbid: int) -> None:
    # se già in cache, aggiorna LRU e basta
    if arbid in _payload_cache:
        _payload_cache.move_to_end(arbid, last=True)
        return
    # eventualmente applica politica LRU
    if CACHE_MAX_IDS is not None and len(_payload_cache) >= CACHE_MAX_IDS:
        evicted_id, _ = _payload_cache.popitem(last=False)
        _counters.pop(evicted_id, None)
        print(f"[DEBUG] Evicted ID {evicted_id:03X} from cache (LRU)")

    payloads = _load_payloads_for_id(arbid)
    if not payloads:
        raise ValueError(f"No payloads found for ID {arbid:03X}")
    _payload_cache[arbid] = payloads
    _counters.setdefault(arbid, 0)


# -------- Public API --------
def get_payload(dlc: int = 8, id: int = None) -> bytes:
    """Return the next payload for the given arbitration ID, without reloading CSV if already cached."""
    if id is None:
        raise ValueError("Must provide arbitration ID (id parameter)")

    _ensure_in_cache(id)

    idx = _counters.get(id, 0)
    seq = _payload_cache[id]
    base = seq[idx % len(seq)]  # base è bytes
    _counters[id] = idx + 1

    # Applica dlc
    if dlc is not None:
        frame = base[:dlc]
        if PAD_WITH_ZEROES and len(frame) < dlc:
            frame = frame + bytes(dlc - len(frame))
    else:
        frame = base

    print(f"[DEBUG] TX payload for ID {id:03X}: {list(frame)}")
    return frame


# -------- Opzionali --------
def set_csv_dir(path: str) -> None:
    """Cambia la directory dei CSV e svuota la cache."""
    global CSV_DIR
    CSV_DIR = path
    _payload_cache.clear()
    _counters.clear()
    print(f"[DEBUG] CSV_DIR set to: {os.path.abspath(CSV_DIR)}; cache cleared.")

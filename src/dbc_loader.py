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

import cantools
import cantools.database
from cantools.database.can.message import Message

from typing import Optional


class DBCSignal:
    def __init__(
        self,
        name: str,
        start_bit: int,
        length: int,
        byte_order: str,
        is_signed: bool,
        factor: float,
        offset: float,
        minimum: Optional[float],
        maximum: Optional[float],
        unit: str,
    ):
        self.name = name
        self.start_bit = start_bit
        self.length = length
        self.byte_order = byte_order
        self.is_signed = is_signed
        self.factor = factor
        self.offset = offset
        self.minimum = minimum
        self.maximum = maximum
        self.unit = unit


class DBCMessage:
    def __init__(
        self,
        frame_id: int,
        name: str,
        cycle_time: int | None,
        signals: list["DBCSignal"],
        payload_length: int,
    ):
        self.frame_id = frame_id
        self.name = name
        self.cycle_time = cycle_time
        self.signals = signals
        self.payload_length = payload_length  # lunghezza in byte del payload


class DBCLoader:
    def __init__(self, filename: str):
        self.dbc_filename = filename
        self.db = cantools.database.load_file(filename)

        if not hasattr(self.db, "messages"):
            raise AttributeError(
                "Loaded database does not have 'messages' attribute. Ensure the file is a valid CAN DBC file."
            )

        self.messages: list[DBCMessage] = []
        self._load_messages()

    def _load_messages(self):
        for msg in self.db.messages:  # type: ignore[attr-defined]
            print(f"{msg}")
            if not isinstance(msg, Message):
                continue

            cycle = getattr(msg, "cycle_time", None)
            signals: list[DBCSignal] = []

            for s in msg.signals:
                sig = DBCSignal(
                    s.name,
                    s.start,
                    s.length,
                    s.byte_order,
                    s.is_signed,
                    s.scale,
                    s.offset,
                    s.minimum,
                    s.maximum,
                    s.unit if s.unit is not None else "",
                )
                signals.append(sig)

            payload_len = msg.length  # <-- Ecco la lunghezza del payload
            self.messages.append(
                DBCMessage(msg.frame_id, msg.name, cycle, signals, payload_len)
            )


def load_dbc(filename: str) -> DBCLoader:
    return DBCLoader(filename)

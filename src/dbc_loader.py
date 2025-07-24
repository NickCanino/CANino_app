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
        unit: str
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
        signals: list['DBCSignal'],
        payload_length: int
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
            raise AttributeError("Loaded database does not have 'messages' attribute. Ensure the file is a valid CAN DBC file.")
        
        self.messages: list[DBCMessage] = []
        self._load_messages()

    def _load_messages(self):
        for msg in self.db.messages:  # type: ignore[attr-defined]
            if not isinstance(msg, Message):
                continue

            cycle = getattr(msg, 'cycle_time', None)
            signals: list[DBCSignal] = []

            for s in msg.signals:
                sig = DBCSignal(
                    s.name, s.start, s.length, s.byte_order, s.is_signed,
                    s.scale, s.offset, s.minimum, s.maximum, s.unit if s.unit is not None else ""
                )
                signals.append(sig)

            payload_len = msg.length  # <-- Ecco la lunghezza del payload
            self.messages.append(DBCMessage(msg.frame_id, msg.name, cycle, signals, payload_len))

def load_dbc(filename: str) -> DBCLoader:
    return DBCLoader(filename)

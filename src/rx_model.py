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
"""RX table model: per-(ID, ext) statistics, owned by the GUI thread (TODO 5.8).

Only the GUI thread touches it: the RX thread queues frames and the GUI drains
the queue, so there is no lock, and a refresh only signals the rows it touched
instead of rebuilding every cell (TODO 5.1, 5.2, 5.6).
"""

import re
import time
from collections import deque

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont

from src.utils import format_can_id

# "id/mask" filter, hex with or without 0x, e.g. "100/700" or "0x18DAF1/0x1FFFFF"
_ID_MASK = re.compile(r"^\s*(0x)?([0-9a-fA-F]+)\s*/\s*(0x)?([0-9a-fA-F]+)\s*$")


def parse_id_mask(text):
    """(value, mask) if `text` is an `id/mask` hex filter, else None."""
    m = _ID_MASK.match(text or "")
    if not m:
        return None
    return int(m.group(2), 16), int(m.group(4), 16)


COLUMNS = (
    "ID",
    "Name",
    "DLC",
    "Payload",
    "Count",
    "Period (ms)",
    "Min (ms)",
    "Max (ms)",
    "Dev. Std (ms)",
    "Last Received",
)
(
    RX_COL_0_id,
    RX_COL_1_name,
    RX_COL_2_dlc,
    RX_COL_3_payload,
    RX_COL_4_count,
    RX_COL_5_period,
    RX_COL_6_min,
    RX_COL_7_max,
    RX_COL_8_dev_std,
    RX_COL_9_last_received,
) = range(len(COLUMNS))

# Numeric values for sorting (the display text would sort "10" before "9")
SORT_ROLE = Qt.ItemDataRole.UserRole
PERIOD_WINDOW = 20  # periods kept for the std-dev
STD_DEV_FROM = 4  # the periods before this frame count stay out of the std-dev


def _ms(value):
    return "-" if value is None else f"{value:.1f}"


class RxRow:
    """Statistics of one received frame (ID + ID format)."""

    __slots__ = (
        "frame_id",
        "is_ext",
        "id_text",
        "name",
        "dlc",
        "data",
        "count",
        "last_time",
        "avg",
        "min",
        "max",
        "periods",
    )

    def __init__(self, frame_id, is_ext, name=""):
        self.frame_id = frame_id
        self.is_ext = is_ext
        self.id_text = format_can_id(frame_id, is_ext)
        self.name = name
        self.dlc = 0
        self.data = b""
        self.count = 0
        self.last_time = None
        self.avg = None  # EMA of the period, ms
        self.min = None
        self.max = None
        self.periods = deque(maxlen=PERIOD_WINDOW)

    def add(self, data, dlc, timestamp):
        self.count += 1
        if self.last_time is not None:
            period = (timestamp - self.last_time) * 1000
            self.min = period if self.min is None else min(self.min, period)
            self.max = period if self.max is None else max(self.max, period)
            self.avg = period if self.avg is None else 0.1 * period + 0.9 * self.avg
            if self.count >= STD_DEV_FROM:
                self.periods.append(period)
        self.last_time = timestamp
        self.dlc = dlc
        self.data = data

    def std_dev(self):
        n = len(self.periods)
        if n < 2:
            return None
        mean = sum(self.periods) / n
        return (sum((p - mean) ** 2 for p in self.periods) / n) ** 0.5

    def payload_text(self):
        return " ".join(f"{b:02X}" for b in self.data)


class RxTableModel(QAbstractTableModel):
    """Rows in arrival order; sorting is left to a QSortFilterProxyModel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._index = {}  # (frame_id, is_ext) -> RxRow
        self._pos = {}  # (frame_id, is_ext) -> row number in the model
        self._new = []  # rows created since the last commit()
        self._dirty = set()  # row numbers updated since the last commit()
        self._names = {}
        self._mono = QFont("Courier New", 10)
        self._mono.setStyleHint(QFont.StyleHint.Monospace)

    # --- updates, GUI thread only ---

    def row_for(self, frame_id, is_ext):
        """The row of this frame, created (pending until commit()) if new."""
        key = (frame_id, is_ext)
        row = self._index.get(key)
        if row is None:
            row = self._index[key] = RxRow(frame_id, is_ext, self._names.get(key, ""))
            self._new.append(row)
        else:
            pos = self._pos.get(key)
            if pos is not None:
                self._dirty.add(pos)
        return row

    def commit(self):
        """Show the rows created and updated since the last commit."""
        if self._new:
            first = len(self._rows)
            self.beginInsertRows(QModelIndex(), first, first + len(self._new) - 1)
            for i, row in enumerate(self._new, first):
                self._pos[(row.frame_id, row.is_ext)] = i
            self._rows.extend(self._new)
            self._new.clear()
            self.endInsertRows()
        if self._dirty:
            # One signal for the touched span: cheaper for the proxy than one per row
            self.dataChanged.emit(
                self.index(min(self._dirty), RX_COL_2_dlc),
                self.index(max(self._dirty), len(COLUMNS) - 1),
            )
            self._dirty.clear()

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self._index.clear()
        self._pos.clear()
        self._new.clear()
        self._dirty.clear()
        self.endResetModel()

    def set_names(self, names):
        """(frame_id, is_ext) -> DBC message name; renames the existing rows (TODO 5.7)."""
        self._names = names
        for row in self._index.values():
            row.name = names.get((row.frame_id, row.is_ext), "")
        if self._rows:
            self.dataChanged.emit(
                self.index(0, RX_COL_1_name),
                self.index(len(self._rows) - 1, RX_COL_1_name),
            )

    def rows(self):
        return list(self._rows)

    def row_at(self, i):
        """The RxRow at source position `i` (used by the filter proxy)."""
        return self._rows[i]

    # --- Qt model interface ---

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return COLUMNS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(row, col)
        if role == SORT_ROLE:
            return self._sort_value(row, col)
        if role == Qt.ItemDataRole.FontRole and col <= RX_COL_3_payload:
            return self._mono
        return None

    @staticmethod
    def _text(row, col):
        if col == RX_COL_0_id:
            return row.id_text
        if col == RX_COL_1_name:
            return row.name
        if col == RX_COL_2_dlc:
            return str(row.dlc)
        if col == RX_COL_3_payload:
            return row.payload_text()
        if col == RX_COL_4_count:
            return str(row.count)
        if col == RX_COL_5_period:
            return _ms(row.avg)
        if col == RX_COL_6_min:
            return _ms(row.min)
        if col == RX_COL_7_max:
            return _ms(row.max)
        if col == RX_COL_8_dev_std:
            return _ms(row.std_dev())
        if col == RX_COL_9_last_received:
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(row.last_time))
        return None

    @staticmethod
    def _sort_value(row, col):
        if col == RX_COL_0_id:  # standard IDs first, then extended, numeric
            return float(row.frame_id + (1 << 32 if row.is_ext else 0))
        if col == RX_COL_1_name:
            return row.name
        if col == RX_COL_2_dlc:
            return row.dlc
        if col == RX_COL_3_payload:
            return row.payload_text()
        if col == RX_COL_4_count:
            return row.count
        value = {
            RX_COL_5_period: row.avg,
            RX_COL_6_min: row.min,
            RX_COL_7_max: row.max,
            RX_COL_8_dev_std: row.std_dev(),
            RX_COL_9_last_received: row.last_time,
        }.get(col)
        return -1.0 if value is None else float(value)


class RxFilterProxy(QSortFilterProxyModel):
    """Sorts (numeric SORT_ROLE) and filters the RX rows by a user query.

    An `id/mask` query (e.g. "100/700") keeps the rows whose ID matches the
    masked value; any other text is a case-insensitive substring match against
    the ID, the DBC name and the payload. Capture is untouched: filtering only
    hides rows in the view (TODO 5.12).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self._query = ""
        self._id_mask = None

    def set_query(self, text):
        self._query = (text or "").strip().lower()
        self._id_mask = parse_id_mask(text)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, parent):
        if not self._query:
            return True
        row = self.sourceModel().row_at(source_row)
        if self._id_mask is not None:
            value, mask = self._id_mask
            return (row.frame_id & mask) == (value & mask)
        hay = f"{row.id_text} {row.name} {row.payload_text()}".lower()
        return self._query in hay

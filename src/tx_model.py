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
"""TX table: one TxEntry per row is the single source of truth (TODO 2.13).

The view never holds state: enable, period, payload, script link and error
live in the entry, the model shows them, delegates edit them. The TX thread
writes payloads and errors through set_payload()/set_error(), which only mark
the row under a lock; flush(), in the GUI thread, repaints the marked rows
(~10 Hz, TODO 2.12).
"""

import os
import re
import threading
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
)

from src.utils import format_can_id

# Columns
TX_COL_0_del = 0
TX_COL_1_enable = 1
TX_COL_2_id = 2
TX_COL_3_fd = 3
TX_COL_4_name = 4
TX_COL_5_period = 5
TX_COL_6_payload = 6
TX_COL_7_script = 7
HEADERS = (
    "",
    "En",
    "ID",
    "FD",
    "Name",
    "Period (ms)",
    "Payload",
    "Script for Specific ID",
)

SORT_ROLE = Qt.ItemDataRole.UserRole  # numbers sort as numbers
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1  # the TxEntry of a row, for delegates

CAN_MAX_STD_ID = 0x7FF
CAN_MAX_EXT_ID = 0x1FFFFFFF
# Payload lengths a CAN FD frame can carry (DLC codes 1-15)
CAN_FD_LENGTHS = (1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)
PERIOD_MIN_MS, PERIOD_MAX_MS = 1, 10000
ROW_ERROR_COLOR = "#E53935"
SCRIPT_LINKED_COLOR = "#4CAF50"
_HEX_PAIR = re.compile(r"[0-9a-fA-F]{2}")


def valid_dlc(dlc, is_fd: bool) -> int:
    """Clamp a stored DLC to a length the frame type can carry."""
    try:
        dlc = int(dlc)
    except (TypeError, ValueError):
        return 8
    if not is_fd:
        return min(max(dlc, 1), 8)
    return next((n for n in CAN_FD_LENGTHS if n >= dlc), 64)


def parse_payload(text, dlc) -> Optional[bytes]:
    """`dlc` hex byte pairs separated by blanks, e.g. "00 1A ..."; None if not."""
    parts = (text or "").split()
    if len(parts) != dlc or not all(_HEX_PAIR.fullmatch(p) for p in parts):
        return None
    return bytes(int(p, 16) for p in parts)


def payload_text(payload: bytes) -> str:
    return " ".join(f"{b:02X}" for b in payload)


@dataclass(eq=False)
class TxEntry:
    """One TX row. Identity matters: the engine keys its timers on the object."""

    frame_id: int
    name: str = ""
    is_ext: bool = False
    is_fd: bool = False
    dlc: int = 8
    period: int = 100
    payload: bytes = b""
    enabled: bool = True
    script_path: Optional[str] = None
    is_rtr: bool = False  # remote frame: no data, requests the DLC (TODO 2.15)
    error: Optional[str] = None  # why the last frame was not sent; None = sent

    def __post_init__(self):
        self.is_fd = bool(self.is_fd)
        # CAN FD has no remote frames; a remote frame is always classic CAN
        self.is_rtr = bool(self.is_rtr) and not self.is_fd
        # An ID above 0x7FF only exists as a 29-bit ID (TODO 1.6)
        self.is_ext = bool(self.is_ext) or self.frame_id > CAN_MAX_STD_ID
        self.dlc = valid_dlc(self.dlc, self.is_fd)
        self.period = clamp_period(self.period)
        if isinstance(self.payload, str):
            self.payload = parse_payload(self.payload, self.dlc) or b""
        if len(self.payload) != self.dlc:
            self.payload = bytes(self.dlc)

    @property
    def key(self):
        """(ID, is_ext): std 0x123 and ext 0x123 are distinct frames."""
        return self.frame_id, self.is_ext

    @property
    def id_text(self):
        return format_can_id(self.frame_id, self.is_ext)


def clamp_period(period) -> int:
    try:
        period = int(period)
    except (TypeError, ValueError):
        return 100
    return min(max(period, PERIOD_MIN_MS), PERIOD_MAX_MS)


class TxTableModel(QAbstractTableModel):
    """Entries in insertion order; a QSortFilterProxyModel sorts the view."""

    enabled_changed = Signal(object)  # the user ticked/unticked a row's En
    period_changed = Signal(object)  # the user changed a row's period
    payload_changed = Signal(object)  # the user edited a row's payload cell
    payload_rejected = Signal(object, str)  # entry, the text that did not parse

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._rows = {}  # id(entry) -> row
        # id(entry) -> entry sent/failed since the last flush, filled by the TX thread
        self._dirty = {}
        self._dirty_lock = threading.Lock()
        self._mono = QFont("Courier New", 10)
        self._mono.setStyleHint(QFont.StyleHint.Monospace)
        self._error_color = QColor(ROW_ERROR_COLOR)

    # --- entries ---

    def entries(self):
        return list(self._entries)

    def find(self, frame_id, is_ext):
        key = (frame_id, bool(is_ext))
        return next((e for e in self._entries if e.key == key), None)

    def add(self, entry):
        row = len(self._entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self._entries.append(entry)
        self._rows[id(entry)] = row
        self.endInsertRows()
        return entry

    def remove(self, entry):
        row = self._rows.get(id(entry))
        if row is None:
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._entries[row]
        self._reindex()
        self.endRemoveRows()

    def clear(self):
        self.beginResetModel()
        self._entries.clear()
        self._reindex()
        self.endResetModel()

    def _reindex(self):
        self._rows = {id(e): i for i, e in enumerate(self._entries)}

    def row_of(self, entry):
        return self._rows.get(id(entry))

    # --- programmatic changes (no user-edit signals) ---

    def set_all_enabled(self, enabled):
        for e in self._entries:
            e.enabled = bool(enabled)
        self._changed(0, len(self._entries) - 1, TX_COL_1_enable, TX_COL_1_enable)

    def set_script(self, entry, path):
        entry.script_path = path or None
        self._changed_entry(entry, TX_COL_7_script, TX_COL_7_script)

    def set_properties(self, entry, name, period):
        """Edit Properties, same frame: only the name and the period change."""
        entry.name = name
        entry.period = clamp_period(period)
        self._changed_entry(entry, TX_COL_4_name, TX_COL_5_period)

    def replace(self, old, new):
        """Edit Properties, another frame: `new` takes `old`'s row; None if gone."""
        row = self._rows.get(id(old))
        if row is None:
            return None
        self._entries[row] = new
        self._reindex()
        self._changed(row, row, 0, len(HEADERS) - 1)
        return new

    def set_payload(self, entry, payload):
        """Any thread: the payload just sent; repainted at the next flush()."""
        with self._dirty_lock:
            entry.payload = payload
            self._dirty[id(entry)] = entry

    def set_error(self, entry, message):
        """Any thread: why the row is not sent (None = it is); repainted at flush()."""
        with self._dirty_lock:
            if entry.error != message:
                entry.error = message
                self._dirty[id(entry)] = entry

    def flush(self):
        """GUI thread: repaint the rows sent/failed since the last flush.

        Returns their entries (the XMetro gauges follow transmitted frames).
        """
        with self._dirty_lock:
            dirty, self._dirty = list(self._dirty.values()), {}
        rows = [r for r in (self._rows.get(id(e)) for e in dirty) if r is not None]
        if rows:
            self._changed(min(rows), max(rows), TX_COL_6_payload, TX_COL_7_script)
        return dirty

    def _changed_entry(self, entry, first_col, last_col):
        row = self._rows.get(id(entry))
        if row is not None:
            self._changed(row, row, first_col, last_col)

    def _changed(self, first_row, last_row, first_col, last_col):
        if first_row <= last_row:
            self.dataChanged.emit(
                self.index(first_row, first_col), self.index(last_row, last_col)
            )

    # --- Qt model interface ---

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignCenter
        return super().headerData(section, orientation, role)

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col = index.column()
        if col == TX_COL_1_enable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        elif col == TX_COL_5_period:
            flags |= Qt.ItemFlag.ItemIsEditable
        elif col == TX_COL_6_payload and not self._entries[index.row()].is_rtr:
            flags |= Qt.ItemFlag.ItemIsEditable  # a remote frame has no payload
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self._entries[index.row()]
        col = index.column()
        if role == ENTRY_ROLE:
            return e
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == TX_COL_2_id:
                return e.id_text
            if col == TX_COL_3_fd:
                return "RTR" if e.is_rtr else ("Y" if e.is_fd else "n")
            if col == TX_COL_4_name:
                return e.name
            if col == TX_COL_5_period:
                return e.period if role == Qt.ItemDataRole.EditRole else str(e.period)
            if col == TX_COL_6_payload:
                # A remote frame carries no data, only the requested DLC
                return f"(RTR, DLC {e.dlc})" if e.is_rtr else payload_text(e.payload)
            if col == TX_COL_7_script:
                return os.path.basename(e.script_path) if e.script_path else ""
            return None
        if role == Qt.ItemDataRole.CheckStateRole and col == TX_COL_1_enable:
            return Qt.CheckState.Checked if e.enabled else Qt.CheckState.Unchecked
        if role == SORT_ROLE:
            return self._sort_value(e, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == TX_COL_2_id:
                return "29-bit extended ID" if e.is_ext else "11-bit standard ID"
            if col == TX_COL_6_payload:
                return f"Not sent - {e.error}" if e.error else ""
            if col == TX_COL_7_script:
                if e.script_path and e.error:
                    return f"Script: {e.script_path}\nError: {e.error}"
                if e.script_path:
                    return f"Script: {e.script_path}"
                return (
                    "Link a Payload Script to be used for THIS transmitted CAN frame."
                )
            return None
        if role == Qt.ItemDataRole.ForegroundRole and col == TX_COL_6_payload:
            return self._error_color if e.error else None
        if role == Qt.ItemDataRole.FontRole and col in (
            TX_COL_2_id,
            TX_COL_4_name,
            TX_COL_6_payload,
        ):
            return self._mono
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (
            TX_COL_3_fd,
            TX_COL_5_period,
        ):
            return Qt.AlignmentFlag.AlignCenter
        return None

    @staticmethod
    def _sort_value(e, col):
        if col == TX_COL_1_enable:
            return int(e.enabled)
        if col == TX_COL_2_id:  # standard IDs first, then extended, numeric
            return float(e.frame_id + (1 << 32 if e.is_ext else 0))
        if col == TX_COL_3_fd:
            return int(e.is_fd)
        if col == TX_COL_4_name:
            return e.name.lower()
        if col == TX_COL_5_period:
            return e.period
        if col == TX_COL_6_payload:
            return payload_text(e.payload)
        if col == TX_COL_7_script:
            return (e.script_path or "").lower()
        return 0

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """User edits from the view: En checkbox, Period, Payload."""
        if not index.isValid():
            return False
        e = self._entries[index.row()]
        col = index.column()
        if col == TX_COL_1_enable and role == Qt.ItemDataRole.CheckStateRole:
            enabled = Qt.CheckState(value) == Qt.CheckState.Checked
            if enabled != e.enabled:
                e.enabled = enabled
                self._changed_entry(e, col, col)
                self.enabled_changed.emit(e)
            return True
        if role != Qt.ItemDataRole.EditRole:
            return False
        if col == TX_COL_5_period:
            period = clamp_period(value)
            if period != e.period:
                e.period = period
                self._changed_entry(e, col, col)
                self.period_changed.emit(e)
            return True
        if col == TX_COL_6_payload:
            payload = parse_payload(str(value).strip(), e.dlc)
            if payload is None:
                self.payload_rejected.emit(e, str(value))
                return False
            e.payload = payload
            self._changed_entry(e, col, col)
            self.payload_changed.emit(e)
            return True
        return False


class PeriodDelegate(QStyledItemDelegate):
    """Period column: a spin box limited to the valid periods."""

    def createEditor(self, parent, option, index):
        spin = QSpinBox(parent)
        spin.setRange(PERIOD_MIN_MS, PERIOD_MAX_MS)
        spin.setSuffix(" ms")
        spin.setFrame(False)
        return spin

    def setEditorData(self, editor, index):
        editor.setValue(int(index.data(Qt.ItemDataRole.EditRole)))

    def setModelData(self, editor, model, index):
        editor.interpretText()
        model.setData(index, editor.value(), Qt.ItemDataRole.EditRole)


class TxButtonDelegate(QStyledItemDelegate):
    """Painted buttons instead of per-row widgets: Delete, Link / Unlink Script."""

    delete_clicked = Signal(object)
    link_clicked = Signal(object)
    unlink_clicked = Signal(object)

    UNLINK_WIDTH = 28
    SCRIPT_WIDTH_FACTOR = 1.3
    # Longer names are elided in the middle (full path in the tooltip)
    SCRIPT_MAX_WIDTH = round(320 * SCRIPT_WIDTH_FACTOR)

    def script_column_width(self, metrics, names):
        """Width of the script column: the "Link Script" button or the longest name."""
        text = max(
            [metrics.horizontalAdvance("Link Script") + 16 + 6]  # + icon and gap
            + [metrics.horizontalAdvance(n) for n in names]
        )
        # + link-button text margins (8), button padding (4), gap + unlink button
        width = text + 8 + 4 + 16 + 3 + self.UNLINK_WIDTH
        # 30 % of air around the name (asked 2026-10-21)
        return min(round(width * self.SCRIPT_WIDTH_FACTOR), self.SCRIPT_MAX_WIDTH)

    def _rects(self, rect):
        rect = rect.adjusted(2, 2, -2, -2)
        unlink = QRect(
            rect.right() - self.UNLINK_WIDTH + 1,
            rect.top(),
            self.UNLINK_WIDTH,
            rect.height(),
        )
        link = QRect(
            rect.left(), rect.top(), rect.width() - self.UNLINK_WIDTH - 3, rect.height()
        )
        return link, unlink

    def _button(
        self, painter, widget, rect, text="", icon=None, enabled=True, color=None
    ):
        style = widget.style() if widget else QApplication.style()
        opt = QStyleOptionButton()
        opt.rect = rect
        opt.text = text
        if icon is not None:
            opt.icon = icon
            opt.iconSize = QSize(16, 16)
        opt.state = QStyle.StateFlag.State_Raised
        if enabled:
            opt.state |= QStyle.StateFlag.State_Enabled
        if color is not None:  # linked / failing script: colored like before
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor("white"))
            painter.drawText(
                rect.adjusted(4, 0, -4, 0),
                Qt.AlignmentFlag.AlignCenter,
                painter.fontMetrics().elidedText(
                    text, Qt.TextElideMode.ElideMiddle, rect.width() - 8
                ),
            )
            painter.restore()
            return
        style.drawControl(QStyle.ControlElement.CE_PushButton, opt, painter, widget)

    def paint(self, painter, option, index):
        entry = index.data(ENTRY_ROLE)
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        if index.column() == TX_COL_0_del:
            self._button(
                painter,
                widget,
                option.rect.adjusted(2, 2, -2, -2),
                icon=style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
            )
            return
        link, unlink = self._rects(option.rect)
        if entry.script_path:
            color = ROW_ERROR_COLOR if entry.error else SCRIPT_LINKED_COLOR
            self._button(
                painter, widget, link, os.path.basename(entry.script_path), color=color
            )
        else:
            self._button(
                painter,
                widget,
                link,
                "Link Script",
                icon=style.standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                ),
            )
        self._button(
            painter,
            widget,
            unlink,
            icon=style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton),
            enabled=bool(entry.script_path),
        )

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.Type.MouseButtonRelease:
            # Swallow the press too, so a click never starts an edit or a drag
            return event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            )
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        entry = index.data(ENTRY_ROLE)
        pos = event.position().toPoint()
        if index.column() == TX_COL_0_del:
            if option.rect.contains(pos):
                self.delete_clicked.emit(entry)
            return True
        link, unlink = self._rects(option.rect)
        if link.contains(pos):
            self.link_clicked.emit(entry)
        elif unlink.contains(pos) and entry.script_path:
            self.unlink_clicked.emit(entry)
        return True

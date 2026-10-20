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

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QFrame,
    QScrollArea,
    QApplication,
    QStyle,
    QMessageBox,
)
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QIcon
from PySide6.QtCore import Qt, QPointF

from src.dbc_loader import decode_signal, signal_range, dbc_bit_label
from src.utils import resource_path, format_can_id
import math
import os


class XMetroWindow(QWidget):
    def __init__(self, dbc_loader):
        super().__init__()
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"XMetro Gauges - {name}" if name else "XMetro Gauges")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setMinimumSize(800, 600)

        self.dbc = dbc_loader

        # Main layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Add Gauge button at the top
        btn_add_gauge = QPushButton("Add Gauge")
        btn_add_gauge.setToolTip(
            "Add a gauge for one DBC signal. Gauges follow received and transmitted\n"
            "frames; drag a gauge to move it on the grid."
        )
        btn_add_gauge.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        btn_add_gauge.setFixedSize(120, 30)
        btn_add_gauge.clicked.connect(self.add_gauge)
        layout.addWidget(btn_add_gauge)

        # Scroll area for gauges
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        layout.addWidget(self.scroll_area)

        # Occupancy grid (4x5)
        self.grid_rows = 4
        self.grid_cols = 5
        self.grid = [[0 for _ in range(self.grid_cols)] for _ in range(self.grid_rows)]
        # Box size and spacing
        self.gauge_size = (400, 280)  # Size of one DraggableGaugeBox
        self.grid_spacing = 10  # Spacing between grid cells
        self.gauges = []

        # Container widget for gauges
        self.gauge_container = QWidget()
        self.gauge_container.setStyleSheet("background-color: #1e1e1e;")
        self.gauge_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.gauge_container.setMinimumSize(
            (self.gauge_size[0] + self.grid_spacing) * self.grid_cols,
            (self.gauge_size[1] + self.grid_spacing) * self.grid_rows,
        )  # Initial size
        self.scroll_area.setWidget(self.gauge_container)

    def add_gauge(self):
        # First free cell of the grid
        pos = self.find_first_free_position()
        if pos is None:
            QMessageBox.warning(
                self, "XMetro Gauges", "No free position available for new gauge."
            )
            return

        row, col = pos
        gauge_widget = DraggableGaugeBox(
            self.gauge_container,
            self.dbc,
            self.gauge_size,
            self.grid_spacing,
            self,
            row,
            col,
        )
        gauge_widget.move(
            col * (self.gauge_size[0] + self.grid_spacing),
            row * (self.gauge_size[1] + self.grid_spacing),
        )
        gauge_widget.show()

        self.gauges.append(gauge_widget)
        self.grid[row][col] = 1  # Mark the cell as taken

    def set_dbc(self, dbc_loader):
        """Follow a DBC change after the window was opened (TODO 7.8).

        Each gauge rebuilds its message list, keeping its message and signal
        selection if they still exist; a selection that is gone is cleared.
        """
        self.dbc = dbc_loader
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"XMetro Gauges - {name}" if name else "XMetro Gauges")
        for gauge in self.gauges:
            gauge.reload_dbc(dbc_loader)

    def remove_gauge(self, gauge):
        """Free the gauge's grid cell and delete it (TODO 7.4)."""
        if gauge in self.gauges:
            self.gauges.remove(gauge)
            self.grid[gauge.row][gauge.col] = 0
        gauge.hide()
        gauge.deleteLater()

    def find_first_free_position(self):
        # Look for the first free cell
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                if self.grid[row][col] == 0:
                    return row, col
        return None  # No free cell

    def update_grid(self, old_row, old_col, new_row, new_col):
        # Update the occupancy grid
        self.grid[old_row][old_col] = 0  # Free the old cell
        self.grid[new_row][new_col] = 1  # Take the new cell

    def feed(self, frame_id, is_ext, payload):
        """Update every gauge showing this frame (std and ext kept apart)."""
        for gauge in self.gauges:
            if gauge.frame_key() == (frame_id, bool(is_ext)):
                gauge.update_gauge(payload)


class DraggableGaugeBox(QFrame):
    def __init__(self, parent, dbc_loader, gauge_size, grid_spacing, xmetro, row, col):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        self.setFixedSize(*gauge_size)

        self.dbc = dbc_loader
        self.grid_spacing = grid_spacing
        self.gauge_size = gauge_size
        # The XMetro window; `self.window` shadowed QWidget.window() (TODO 7.4)
        self.xmetro = xmetro
        self.row = row  # Current grid row
        self.col = col  # Current grid column
        self.drag_start_position = None
        # DBC messages by combo index: std and ext may share a number (TODO 4.11)
        self.messages = [m for m in self.dbc.messages if m.signals]

        layout = QVBoxLayout(self)

        # Add controls
        top_layout = QHBoxLayout()
        self.cb_messages = QComboBox()
        self.cb_messages.setFixedSize(160, 30)
        self.cb_messages.setToolTip("DBC message whose frames drive this gauge.")
        self.cb_signals = QComboBox()
        self.cb_signals.setFixedSize(140, 30)
        self.cb_signals.setToolTip("Signal shown by the needle.")
        btn_remove = QPushButton()
        btn_remove.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_remove.setFixedSize(30, 30)
        btn_remove.setToolTip("Remove this gauge.")
        btn_remove.clicked.connect(lambda: self.xmetro.remove_gauge(self))

        # Populate messages from DBC
        for msg in self.messages:
            label = f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
            self.cb_messages.addItem(label, msg.frame_id)

        top_layout.addWidget(QLabel("Message:"))
        top_layout.addWidget(self.cb_messages)
        top_layout.addWidget(QLabel("Signal:"))
        top_layout.addWidget(self.cb_signals)
        top_layout.addWidget(btn_remove)
        layout.addLayout(top_layout)

        self.gauge = SemiCircularGauge()
        layout.addWidget(self.gauge)

        self.cb_messages.currentIndexChanged.connect(self.populate_signals)
        self.cb_signals.currentIndexChanged.connect(self.update_signal_range)

        self.populate_signals()

    def reload_dbc(self, dbc_loader):
        """Repopulate the message/signal combos from a new DBC (TODO 7.8)."""
        want_msg = self.cb_messages.currentText()
        want_sig = self.cb_signals.currentText()
        self.dbc = dbc_loader
        self.messages = [m for m in getattr(dbc_loader, "messages", []) if m.signals]
        self.cb_messages.blockSignals(True)
        self.cb_messages.clear()
        for msg in self.messages:
            label = f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
            self.cb_messages.addItem(label, msg.frame_id)
        restored = self.cb_messages.findText(want_msg)
        self.cb_messages.setCurrentIndex(max(0, restored))
        self.cb_messages.blockSignals(False)
        self.populate_signals()
        sig_idx = self.cb_signals.findText(want_sig)
        if sig_idx >= 0:
            self.cb_signals.setCurrentIndex(sig_idx)

    def current_message(self):
        idx = self.cb_messages.currentIndex()
        return self.messages[idx] if 0 <= idx < len(self.messages) else None

    def current_signal(self):
        msg = self.current_message()
        idx = self.cb_signals.currentIndex()
        if msg is None or not 0 <= idx < len(msg.signals):
            return None
        return msg.signals[idx]

    def frame_key(self):
        msg = self.current_message()
        return None if msg is None else (msg.frame_id, bool(msg.is_extended_frame))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()

    def mouseMoveEvent(self, event):
        if self.drag_start_position is None:
            return

        if (
            event.pos() - self.drag_start_position
        ).manhattanLength() < QApplication.startDragDistance():
            return

        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        new_pos = self.mapToParent(event.pos() - self.drag_start_position)
        self.snap_to_grid(new_pos)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.drag_start_position = None

    def snap_to_grid(self, new_pos):
        # Grid cell under the drop position
        col = round(new_pos.x() / (self.gauge_size[0] + self.grid_spacing))
        row = round(new_pos.y() / (self.gauge_size[1] + self.grid_spacing))

        # Is the new cell valid and free?
        if (
            0 <= row < self.xmetro.grid_rows
            and 0 <= col < self.xmetro.grid_cols
            and self.xmetro.grid[row][col] == 0
        ):
            # Move to the new cell
            self.xmetro.update_grid(self.row, self.col, row, col)
            self.row, self.col = row, col
            self.move(
                col * (self.gauge_size[0] + self.grid_spacing),
                row * (self.gauge_size[1] + self.grid_spacing),
            )
        else:
            # Back to the previous cell
            self.move(
                self.col * (self.gauge_size[0] + self.grid_spacing),
                self.row * (self.gauge_size[1] + self.grid_spacing),
            )

    def populate_signals(self):
        self.cb_signals.blockSignals(True)
        self.cb_signals.clear()
        msg = self.current_message()
        for sig in msg.signals if msg is not None else []:
            self.cb_signals.addItem(sig.name)
        self.cb_signals.blockSignals(False)
        self.update_signal_range()

    def update_signal_range(self):
        """Scale = the DBC [min|max] when set, else the raw range, as for sliders."""
        sig = self.current_signal()
        if sig is None:
            return
        lo, hi = signal_range(sig)
        unit = sig.unit or ""
        self.gauge.setRange(lo, hi)
        self.gauge.setValue(lo, unit)
        msg = self.current_message()
        self.setToolTip(
            f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})\n"
            f"{sig.name} [{dbc_bit_label(sig)}], {lo:g} .. {hi:g} {unit}"
        )

    def update_gauge(self, payload):
        """Decode only this signal: no whole-message decode that can fail (TODO 7.3)."""
        sig = self.current_signal()
        if sig is None:
            return
        value = decode_signal(bytes(payload), sig)
        label = (getattr(sig, "choices", None) or {}).get(int(value))
        self.gauge.setValue(value, sig.unit or "", label)


class SemiCircularGauge(QWidget):
    def __init__(self):
        super().__init__()
        self.min_val = 0
        self.max_val = 180
        self.value = 0
        self.unit = ""
        self.label = None

    def setRange(self, min_val, max_val):
        self.min_val = min_val if min_val is not None else 0
        self.max_val = max_val if max_val is not None else 180

    def setValue(self, value, unit="", label=None):
        self.value = value
        self.unit = unit
        self.label = label  # enum text of the value, if the signal has choices
        self.update()

    def needle_ratio(self):
        """Needle position 0..1, clamped: out-of-range values stop at the ends (TODO 7.3)."""
        span = self.max_val - self.min_val
        if not span:
            return 0.0
        return min(max((self.value - self.min_val) / span, 0.0), 1.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        center = QPointF(w / 2, h * 0.85)
        radius = min(w, h) * 0.8 / 1

        # Background
        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawEllipse(center, radius, radius)

        # Scale arc
        painter.setPen(QPen(QColor(200, 200, 200), 4))
        arc_rect = (
            int(center.x() - radius),
            int(center.y() - radius),
            int(2 * radius),
            int(2 * radius),
        )
        painter.drawArc(*arc_rect, 0 * 16, 180 * 16)

        # Major ticks
        tick_count = 6
        for i in range(tick_count + 1):
            ratio = i / tick_count
            angle_deg = 180 * ratio
            angle_rad = math.radians(180 - angle_deg)
            x_outer = center.x() + radius * math.cos(angle_rad)
            y_outer = center.y() - radius * math.sin(angle_rad)
            x_inner = center.x() + (radius - 20) * math.cos(angle_rad)
            y_inner = center.y() - (radius - 20) * math.sin(angle_rad)
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(QPointF(x_inner, y_inner), QPointF(x_outer, y_outer))

            val_label = self.min_val + ratio * (self.max_val - self.min_val)
            val_label = (
                int(round(val_label))
                if abs(self.max_val - self.min_val) >= 12
                else round(val_label, 2)
            )
            typewriter_font = QFont("Courier New", 16)
            typewriter_font.setStyleHint(QFont.StyleHint.TypeWriter)
            painter.setFont(typewriter_font)

            # Tick label position
            label_distance = radius - 25  # distance from the centre
            offset_towards_center = 15  # inset towards the centre
            # Base position of the label
            label_x = center.x() + label_distance * math.cos(angle_rad)
            label_y = center.y() - label_distance * math.sin(angle_rad)
            # Unit vector towards the centre
            dx = center.x() - label_x
            dy = center.y() - label_y
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length  # normalised direction
            # Apply the inset
            label_x += ux * offset_towards_center
            label_y += uy * offset_towards_center
            # Centre the text on the point
            text = str(val_label)
            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(text)
            text_height = metrics.height()
            # Draw the text
            painter.drawText(
                QPointF(label_x - text_width / 2, label_y + text_height / 4), text
            )

        # Minor ticks: 4 between two major ones
        for i in range(tick_count):
            for j in range(1, 5):  # 4 sub-ticks
                ratio = (i + j / 5) / tick_count
                angle_deg = 180 * ratio
                angle_rad = math.radians(180 - angle_deg)

                x_outer = center.x() + radius * math.cos(angle_rad)
                y_outer = center.y() - radius * math.sin(angle_rad)
                x_inner = center.x() + (radius - 10) * math.cos(angle_rad)
                y_inner = center.y() - (radius - 10) * math.sin(angle_rad)

                painter.setPen(QPen(Qt.GlobalColor.gray, 1))  # thin
                painter.drawLine(QPointF(x_inner, y_inner), QPointF(x_outer, y_outer))

        # Needle
        needle_ratio = self.needle_ratio()
        needle_angle = math.radians(180 - needle_ratio * 180)
        needle_x = center.x() + radius * 0.7 * math.cos(needle_angle)
        needle_y = center.y() - radius * 0.7 * math.sin(needle_angle)

        painter.setPen(QPen(QColor(255, 128, 0), 4))
        painter.drawLine(center, QPointF(needle_x, needle_y))

        # Current value
        instant_font = QFont("Courier New", 18, QFont.Weight.Bold)
        instant_font.setStyleHint(QFont.StyleHint.TypeWriter)
        painter.setFont(instant_font)
        painter.setPen(QPen(Qt.GlobalColor.white))

        text = f"{self.value:.2f} {self.unit}"
        if self.label:
            text += f" ({self.label})"
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        painter.drawText(QPointF(center.x() - text_width / 2, center.y() + 30), text)

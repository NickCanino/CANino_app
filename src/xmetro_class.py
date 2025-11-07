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

#TODO: add tooltips in XMETRO window

from PyQt6.QtWidgets import (
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
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QIcon
from PyQt6.QtCore import Qt, QPointF

# from cantools.database.can.signal import NamedSignalValue
# from src.exceptions_logger import log_exception
from src.utils import resource_path
import math


class XMetroWindow(QWidget):
    def __init__(self, dbc_loader):
        print("Initializing XMetro window...")
        super().__init__()
        self.setWindowTitle("XMetro Gauges")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setMinimumSize(800, 600)

        self.dbc = dbc_loader

        # Main layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Add Gauge button at the top
        btn_add_gauge = QPushButton("Add Gauge")
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

        # Griglia di flag (4x5)
        self.grid_rows = 4
        self.grid_cols = 5
        self.grid = [[0 for _ in range(self.grid_cols)] for _ in range(self.grid_rows)]
        # Dimensioni dei box e spaziatura
        self.gauge_size = (400, 280)  # Dimensioni standard di un DraggableGaugeBox
        self.grid_spacing = 10  # Spaziatura tra le celle della griglia
        self.gauges = []

        # Container widget for gauges
        self.gauge_container = QWidget()
        self.gauge_container.setStyleSheet("background-color: #1e1e1e;")
        self.gauge_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.gauge_container.setMinimumSize(
            (self.gauge_size[0] + self.grid_spacing) * self.grid_cols,
            (self.gauge_size[1] + self.grid_spacing) * self.grid_rows,
        )  # Dimensione iniziale
        self.scroll_area.setWidget(self.gauge_container)
        print("XMetro window initialized successfully")

    def add_gauge(self):
        # Trova la prima posizione libera nella griglia
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
        self.grid[row][col] = 1  # Segna la cella come occupata

    def find_first_free_position(self):
        # Cerca la prima cella libera nella griglia
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                if self.grid[row][col] == 0:
                    return row, col
        return None  # Nessuna posizione libera trovata

    def update_grid(self, old_row, old_col, new_row, new_col):
        # Aggiorna la matrice di flag
        self.grid[old_row][old_col] = 0  # Libera la vecchia posizione
        self.grid[new_row][new_col] = 1  # Occupa la nuova posizione


class DraggableGaugeBox(QFrame):
    def __init__(self, parent, dbc_loader, gauge_size, grid_spacing, window, row, col):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        self.setFixedSize(*gauge_size)

        self.dbc = dbc_loader
        self.grid_spacing = grid_spacing
        self.gauge_size = gauge_size
        self.window = window  # Riferimento alla finestra principale
        self.row = row  # Riga corrente nella griglia
        self.col = col  # Colonna corrente nella griglia
        self.drag_start_position = None

        layout = QVBoxLayout(self)

        # Add controls
        top_layout = QHBoxLayout()
        self.cb_messages = QComboBox()
        self.cb_messages.setFixedSize(180, 30)
        self.cb_signals = QComboBox()
        self.cb_signals.setFixedSize(180, 30)

        # Populate messages from DBC
        for msg in self.dbc.db.messages:
            label = f"{msg.name} (0x{msg.frame_id:X})"
            self.cb_messages.addItem(label, msg.frame_id)

        top_layout.addWidget(QLabel("Message:"))
        top_layout.addWidget(self.cb_messages)
        top_layout.addWidget(QLabel("Signal:"))
        top_layout.addWidget(self.cb_signals)
        layout.addLayout(top_layout)

        self.gauge = SemiCircularGauge()
        layout.addWidget(self.gauge)

        self.last_payload = bytes([0x00] * 8)

        self.cb_messages.currentIndexChanged.connect(self.populate_signals)
        self.cb_signals.currentIndexChanged.connect(self.update_signal_range)

        self.populate_signals()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()

    def mouseMoveEvent(self, event):
        if not hasattr(self, "drag_start_position"):
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
        if hasattr(self, "drag_start_position"):
            del self.drag_start_position

    def snap_to_grid(self, new_pos):
        # Calcola la posizione nella griglia
        col = round(new_pos.x() / (self.gauge_size[0] + self.grid_spacing))
        row = round(new_pos.y() / (self.gauge_size[1] + self.grid_spacing))

        # Controlla se la nuova posizione è valida
        if (
            0 <= row < self.window.grid_rows
            and 0 <= col < self.window.grid_cols
            and self.window.grid[row][col] == 0
        ):
            # Aggiorna la posizione nella griglia
            self.window.update_grid(self.row, self.col, row, col)
            self.row, self.col = row, col
            self.move(
                col * (self.gauge_size[0] + self.grid_spacing),
                row * (self.gauge_size[1] + self.grid_spacing),
            )
        else:
            # Torna alla posizione precedente
            self.move(
                self.col * (self.gauge_size[0] + self.grid_spacing),
                self.row * (self.gauge_size[1] + self.grid_spacing),
            )

    def populate_signals(self):
        self.cb_signals.clear()
        frame_id = self.cb_messages.currentData()
        if frame_id is not None and self.dbc:
            try:
                msg = self.dbc.db.get_message_by_frame_id(frame_id)
                if msg and msg.signals:
                    for sig in msg.signals:
                        self.cb_signals.addItem(sig.name, sig)
            except Exception as e:
                print(f"Error populating signals: {e}")
        self.update_signal_range()

    def update_signal_range(self):
        signal = self.cb_signals.currentData()
        if signal:
            factor = getattr(signal, "factor", getattr(signal, "scale", 1.0)) or 1.0
            offset = getattr(signal, "offset", 0.0)
            bit_length = getattr(signal, "length", 8)
            is_signed = getattr(signal, "is_signed", False)

            if is_signed:
                raw_min = -(2 ** (bit_length - 1))
                raw_max = 2 ** (bit_length - 1) - 1
            else:
                raw_min = 0
                raw_max = 2**bit_length - 1

            min_val = raw_min * factor + offset
            max_val = raw_max * factor + offset

            self.gauge.setRange(min_val, max_val)
            self.gauge.setValue(min_val, signal.unit if signal.unit else "")

    def update_gauge(self, payload):
        frame_id = self.cb_messages.currentData()
        signal = self.cb_signals.currentData()

        if frame_id is None or signal is None:
            return

        try:
            msg = self.dbc.db.get_message_by_frame_id(frame_id)
            if msg:
                decoded = msg.decode(payload)
                if signal.name in decoded:
                    value = decoded[signal.name]
                    self.gauge.setValue(value, signal.unit if signal.unit else "")
        except Exception as e:
            print(f"Error updating gauge: {e}")


class SemiCircularGauge(QWidget):
    def __init__(self):
        super().__init__()
        self.min_val = 0
        self.max_val = 180
        self.value = 0
        self.unit = ""

    def setRange(self, min_val, max_val):
        self.min_val = min_val if min_val is not None else 0
        self.max_val = max_val if max_val is not None else 180

    def setValue(self, value, unit=""):
        self.value = value
        self.unit = unit
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        center = QPointF(w / 2, h * 0.85)
        radius = min(w, h) * 0.8 / 1

        # Sfondo
        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawEllipse(center, radius, radius)

        # Semicerchio di riferimento
        painter.setPen(QPen(QColor(200, 200, 200), 4))
        arc_rect = (
            int(center.x() - radius),
            int(center.y() - radius),
            int(2 * radius),
            int(2 * radius),
        )
        painter.drawArc(*arc_rect, 0 * 16, 180 * 16)

        # Tacche principali
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

            val_label = int(self.min_val + ratio * (self.max_val - self.min_val))
            typewriter_font = QFont("Courier New", 16)
            typewriter_font.setStyleHint(QFont.StyleHint.TypeWriter)
            painter.setFont(typewriter_font)

            # Calcoli per posizionamento label nei tick
            label_distance = radius - 25  # distanza dal centro
            offset_towards_center = 15  # quanto rientrare in direzione del centro
            # Calcola la posizione base della label
            label_x = center.x() + label_distance * math.cos(angle_rad)
            label_y = center.y() - label_distance * math.sin(angle_rad)
            # Calcola direzione vettoriale verso il centro
            dx = center.x() - label_x
            dy = center.y() - label_y
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length  # direzione normalizzata
            # Applica offset verso il centro
            label_x += ux * offset_towards_center
            label_y += uy * offset_towards_center
            # Centra il testo rispetto al punto
            text = str(val_label)
            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(text)
            text_height = metrics.height()
            # Aggiunge il testo effettivamente
            painter.drawText(
                QPointF(label_x - text_width / 2, label_y + text_height / 4), text
            )

        # Sub-tick: 4 tra ogni coppia principale
        for i in range(tick_count):
            for j in range(1, 5):  # 4 sub-ticks
                ratio = (i + j / 5) / tick_count
                angle_deg = 180 * ratio
                angle_rad = math.radians(180 - angle_deg)

                x_outer = center.x() + radius * math.cos(angle_rad)
                y_outer = center.y() - radius * math.sin(angle_rad)
                x_inner = center.x() + (radius - 10) * math.cos(angle_rad)
                y_inner = center.y() - (radius - 10) * math.sin(angle_rad)

                painter.setPen(QPen(Qt.GlobalColor.gray, 1))  # sottile
                painter.drawLine(QPointF(x_inner, y_inner), QPointF(x_outer, y_outer))

        # Lancetta
        needle_ratio = (self.value - self.min_val) / (self.max_val - self.min_val)
        needle_angle = math.radians(180 - needle_ratio * 180)
        needle_x = center.x() + radius * 0.7 * math.cos(needle_angle)
        needle_y = center.y() - radius * 0.7 * math.sin(needle_angle)

        painter.setPen(QPen(QColor(255, 128, 0), 4))
        painter.drawLine(center, QPointF(needle_x, needle_y))

        # Valore istantaneo
        instant_font = QFont("Courier New", 18, QFont.Weight.Bold)
        instant_font.setStyleHint(QFont.StyleHint.TypeWriter)
        painter.setFont(instant_font)
        painter.setPen(QPen(Qt.GlobalColor.white))

        text = f"{self.value:.2f} {self.unit}"
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        painter.drawText(QPointF(center.x() - text_width / 2, center.y() + 30), text)

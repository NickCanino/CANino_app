from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QPointF
import math
from cantools.database.can.signal import NamedSignalValue
from src.exceptions_logger import log_exception


class XMetroWindow(QWidget):
    def __init__(self, dbc_loader, tx_items):
        super().__init__()
        self.setWindowTitle("XMetro Gauge")
        self.setFixedSize(500, 300)

        layout = QVBoxLayout()
        self.setLayout(layout)

        top_layout = QHBoxLayout()
        self.cb_messages = QComboBox()
        self.cb_messages.setFixedSize(180, 30)
        self.cb_signals = QComboBox()
        self.cb_signals.setFixedSize(180, 30)

        for item in tx_items:
            frame_id = int(item.text(2), 16)
            name = item.text(3)
            label = f"{name} (0x{frame_id:X})"
            self.cb_messages.addItem(label, frame_id)

        self.last_payload = bytes(
            [0x00] * 8
        )  # Inizializza con un payload di 8 byte a zero
        self.cb_messages.currentIndexChanged.connect(self.populate_signals)
        self.cb_signals.currentIndexChanged.connect(
            lambda _: self.update_gauge(self.last_payload)
        )

        top_layout.addWidget(QLabel("Messaggio:"), alignment=Qt.AlignmentFlag.AlignLeft)
        top_layout.addWidget(self.cb_messages, alignment=Qt.AlignmentFlag.AlignLeft)

        top_layout.addWidget(QLabel("Segnale:"), alignment=Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.cb_signals, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(top_layout)

        self.gauge = SemiCircularGauge()
        layout.addWidget(self.gauge)

        self.dbc = dbc_loader
        self.populate_signals()

    def populate_signals(self):
        frame_id = self.cb_messages.currentData()
        msg = self.dbc.db.get_message_by_frame_id(frame_id)
        self.cb_signals.clear()

        for sig in msg.signals:
            self.cb_signals.addItem(sig.name)

        # Crea payload a 0 coerente con DLC del messaggio
        dlc = msg.length  # usa .length o .size
        self.last_payload = bytes([0x00] * dlc)

        self.update_gauge(self.last_payload)

    def update_gauge(self, payload: bytes):
        print(f"[XMetro] Payload passato al gauge: 0x{payload.hex(' ').upper()}")

        frame_id = self.cb_messages.currentData()
        signal_name = self.cb_signals.currentText()
        msg = self.dbc.db.get_message_by_frame_id(frame_id)
        sig = next((s for s in msg.signals if s.name == signal_name), None)

        if not sig or not payload or not isinstance(payload, bytes):
            print("[XMetro] Segnale non valido o payload non valido.")
            return

        # --- DEBUG: Dettagli segnale selezionato ---
        # print(f"[XMetro] Segnale selezionato: {signal_name}")
        # print(f"  start: {sig.start}")
        # print(f"  length: {sig.length}")
        # print(f"  byte_order: {sig.byte_order}")
        # print(f"  is_signed: {sig.is_signed}")
        # print(f"  scale: {getattr(sig, 'factor', getattr(sig, 'scale', 1.0))}")
        # print(f"  offset: {getattr(sig, 'offset', 0.0)}")
        # print(f"  min: {getattr(sig, 'minimum', 0)}")
        # print(f"  max: {getattr(sig, 'maximum', 100)}")
        # print(f"  unit: {getattr(sig, 'unit', '')}")

        # Decodifica fisica diretta con cantools
        dlc = msg.length
        if len(payload) != dlc:
            payload = payload[:dlc] + bytes([0x00] * max(0, dlc - len(payload)))

        try:
            decoded = msg.decode(payload)
            physical_val = decoded[sig.name]
            print(f"[XMetro] Valore fisico calcolato (cantools): {physical_val}")
            if isinstance(physical_val, NamedSignalValue):
                physical_val = int(physical_val)
        except Exception as e:
            log_exception(e)
            physical_val = 0

        # Calcolo min/max SEMPRE da bit_length, offset, scale, signed/unsigned, endianess
        factor = getattr(sig, "factor", getattr(sig, "scale", 1.0)) or 1.0
        offset = getattr(sig, "offset", 0.0)
        bit_length = getattr(sig, "length", 8)
        is_signed = getattr(sig, "is_signed", False)
        # endianess non influisce su min/max, ma la includo per completezza
        # byte_order = getattr(sig, 'byte_order', 'little_endian')
        if is_signed:
            raw_min = -(2 ** (bit_length - 1))
            raw_max = 2 ** (bit_length - 1) - 1
        else:
            raw_min = 0
            raw_max = 2**bit_length - 1
        min_val = raw_min * factor + offset
        max_val = raw_max * factor + offset
        self.gauge.setRange(min_val, max_val)
        self.gauge.setValue(physical_val, unit=getattr(sig, "unit", ""))


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

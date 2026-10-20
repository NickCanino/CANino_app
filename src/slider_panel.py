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

"""Slider panel: one slider per DBC signal, applied to the TX frames (TODO 9.7)."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QMessageBox,
    QInputDialog,
    QStyle,
    QSlider,
    QComboBox,
    QScrollArea,
)
from PySide6.QtCore import Qt

from src.dbc_loader import (
    decode_signal,
    signal_range,
    dbc_bit_label,
)
from src.utils import format_can_id


# Slider positions; QSlider ranges are int32, 32/64-bit raw ranges are not
SLIDER_MAX_STEPS = 10000


class SliderPanelMixin:
    def _build_slider_panel(self):
        """Slider state and widgets; returns the slider group box."""
        # (frame_id, is_ext) -> ((signal, physical value), ...): what the sliders
        # set, rebuilt in the GUI thread, read by the TX thread
        self._slider_overrides = {}
        # --- SLIDER GROUP ---
        slider_group = QGroupBox()
        slider_group.setStyleSheet(
            "QGroupBox { border: 2px solid #FF9800; border-radius: 5px; }"
        )
        slider_group.setMinimumWidth(260)

        slider_layout = QVBoxLayout()
        slider_group.setLayout(slider_layout)

        self.btn_add_slider = QPushButton("Add Slider")
        self.btn_add_slider.setToolTip(
            "Add a new slider for the selected CAN signal, from the linked DBC file."
        )
        self.btn_add_slider.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.btn_add_slider.setFixedSize(150, 30)
        slider_layout.addWidget(self.btn_add_slider)

        # Scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        slider_scroll_widget = QWidget()
        self.slider_container = QVBoxLayout()
        slider_scroll_widget.setLayout(self.slider_container)
        scroll_area.setWidget(slider_scroll_widget)
        slider_layout.addWidget(scroll_area)
        self.slider_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.added_sliders = set()
        self.slider_widgets = []

        self.btn_add_slider.clicked.connect(self.add_slider)
        return slider_group

    def add_slider(self):
        if self.dbc is None:
            QMessageBox.warning(self, "DBC", "Load a DBC file first!")
            return

        # Only consider checked TX rows
        checked = {e.key for e in self._tx_entries() if e.enabled}
        if not checked:
            QMessageBox.warning(self, "Slider", "No TX messages enabled.")
            return
        msgs = [
            m
            for m in self.dbc.messages
            if (m.frame_id, m.is_extended_frame) in checked and m.signals
        ]
        if not msgs:
            QMessageBox.warning(
                self, "Slider", "No checked DBC messages found in TX table."
            )
            return

        labels = [
            f"{m.name} ({format_can_id(m.frame_id, m.is_extended_frame)})" for m in msgs
        ]
        label, ok = QInputDialog.getItem(
            self, "Select Message", "Message:", labels, 0, False
        )
        if not ok:
            return
        msg = msgs[labels.index(label)]
        sig_names = [sig.name for sig in msg.signals]
        sig_name, ok = QInputDialog.getItem(
            self, "Select Signal", "Signal:", sig_names, 0, False
        )
        if not ok:
            return
        sig = msg.signals[sig_names.index(sig_name)]
        if (msg.name, sig.name) in self.added_sliders:
            QMessageBox.warning(
                self,
                "Slider already exists",
                f"Slider already exists for {msg.name} → {sig.name}",
            )
            return

        # Start from the value the row is sending now: no jump on the bus
        entry = self._find_entry(msg.frame_id, msg.is_extended_frame)
        value = None
        if entry is not None:
            try:
                value = decode_signal(entry.payload, sig)
            except ValueError:
                value = None
        self._add_slider_widget(msg, sig, value)

    def _add_slider_widget(self, msg, sig, value=None):
        """The one slider builder, for Add Slider and workspace load (TODO 4.9).

        Range = DBC [min|max] when set, else every raw value (TODO 4.7); at most
        SLIDER_MAX_STEPS positions, so 32/64-bit signals fit QSlider's int32
        (TODO 4.4). `value` (physical) is clamped into the range.
        """
        key = (msg.name, sig.name)
        if key in self.added_sliders:
            return None

        if getattr(sig, "choices", None):  # enum signal -> a combo box (TODO 4.10)
            return self._add_enum_widget(msg, sig, key, value)
        self.added_sliders.add(key)

        min_val, max_val = signal_range(sig)
        factor = abs(sig.factor or 1.0)
        span = max_val - min_val
        if sig.is_float:
            steps = SLIDER_MAX_STEPS
        else:
            steps = int(min(SLIDER_MAX_STEPS, max(0, round(span / factor))))
        step = span / steps if steps else 0.0
        integral = (
            not sig.is_float
            and float(step).is_integer()
            and float(min_val).is_integer()
        )
        unit = sig.unit or ""

        slider_widget = QGroupBox()
        slider_widget.setFixedHeight(100)
        slider_widget.setStyleSheet(
            "QGroupBox { margin-top: 10px; border: 1px solid gray; border-radius: 5px; }"
        )
        inner = QVBoxLayout()
        slider_widget.setLayout(inner)
        inner.addWidget(
            QLabel(
                f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
                f" → {sig.name} [{dbc_bit_label(sig)}]"
            )
        )

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, steps)
        slider.setSingleStep(1)
        inner.addWidget(slider)

        def fmt(v):
            return f"{int(round(v))}" if integral else f"{v:.3f}"

        info_layout = QHBoxLayout()
        lbl_value = QLabel()
        btn_remove = QPushButton()
        btn_remove.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_remove.setFixedWidth(30)
        info_layout.addWidget(QLabel(f"Min: {fmt(min_val)}"))
        info_layout.addStretch()
        info_layout.addWidget(lbl_value)
        info_layout.addStretch()
        info_layout.addWidget(QLabel(f"Max: {fmt(max_val)}"))
        info_layout.addWidget(btn_remove)
        inner.addLayout(info_layout)

        slider_widget.key = key
        slider_widget.msg_name = msg.name
        slider_widget.frame_id = msg.frame_id
        slider_widget.is_ext = msg.is_extended_frame
        slider_widget.signal = sig
        slider_widget.slider = slider
        slider_widget.min_val = min_val
        slider_widget.max_val = max_val
        slider_widget.step = step
        slider_widget.unit = unit
        slider_widget.value = lambda: min_val + slider.value() * step
        slider_widget.set_enabled = slider.setEnabled

        # Connected before setValue, so the label shows the restored value (TODO 4.3)
        slider.valueChanged.connect(
            lambda i: lbl_value.setText(f"Val: {fmt(min_val + i * step)} {unit}")
        )
        if value is None or not steps:
            index = 0
        else:
            index = round((min(max(value, min_val), max_val) - min_val) / step)
        slider.setValue(index)
        lbl_value.setText(f"Val: {fmt(slider_widget.value())} {unit}")
        btn_remove.clicked.connect(
            lambda _=False, w=slider_widget: self.remove_slider_widget(w)
        )

        entry = self._find_entry(msg.frame_id, msg.is_extended_frame)
        if entry is not None:
            slider.setEnabled(entry.enabled)
        self.slider_container.addWidget(slider_widget)
        self.slider_widgets.append(slider_widget)
        slider.valueChanged.connect(self._refresh_slider_overrides)
        slider.valueChanged.connect(self._mark_dirty)  # guarded during load
        self._refresh_slider_overrides()
        self._mark_dirty()
        return slider_widget

    def _add_enum_widget(self, msg, sig, key, value):
        """An enum (value-table) signal: a combo box of named values (TODO 4.10).

        Exposes the same interface as a slider widget (value() = the physical
        value, set_enabled, key/signal/names), so save, overrides and enable
        sync treat both the same.
        """
        self.added_sliders.add(key)
        factor = sig.factor or 1.0
        offset = sig.offset or 0.0
        unit = sig.unit or ""

        box = QGroupBox()
        box.setFixedHeight(100)
        box.setStyleSheet(
            "QGroupBox { margin-top: 10px; border: 1px solid gray; border-radius: 5px; }"
        )
        inner = QVBoxLayout()
        box.setLayout(inner)
        inner.addWidget(
            QLabel(
                f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
                f" → {sig.name} [{dbc_bit_label(sig)}]"
            )
        )

        combo = QComboBox()
        for raw in sorted(sig.choices):  # raw value -> physical value as data
            combo.addItem(f"{raw}: {sig.choices[raw]}", raw * factor + offset)
        row = QHBoxLayout()
        row.addWidget(combo, 1)
        btn_remove = QPushButton()
        btn_remove.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_remove.setFixedWidth(30)
        row.addWidget(btn_remove)
        inner.addLayout(row)

        box.key = key
        box.msg_name = msg.name
        box.frame_id = msg.frame_id
        box.is_ext = msg.is_extended_frame
        box.signal = sig
        box.unit = unit
        box.combo = combo
        box.value = lambda: combo.currentData()
        box.set_enabled = combo.setEnabled

        if value is not None:  # restore: the choice whose physical value is closest
            best = min(
                range(combo.count()),
                key=lambda i: abs(combo.itemData(i) - value),
                default=0,
            )
            combo.setCurrentIndex(best)

        entry = self._find_entry(msg.frame_id, msg.is_extended_frame)
        if entry is not None:
            combo.setEnabled(entry.enabled)
        btn_remove.clicked.connect(lambda _=False, w=box: self.remove_slider_widget(w))
        self.slider_container.addWidget(box)
        self.slider_widgets.append(box)
        combo.currentIndexChanged.connect(self._refresh_slider_overrides)
        combo.currentIndexChanged.connect(self._mark_dirty)  # guarded during load
        self._refresh_slider_overrides()
        self._mark_dirty()
        return box

    def remove_slider_widget(self, widget):
        # Remove the widget from the slider_container and update the slider list
        widget.setParent(None)
        if hasattr(widget, "key"):
            self.added_sliders.discard(widget.key)

        self.slider_widgets = [w for w in self.slider_widgets if w != widget]
        self._refresh_slider_overrides()
        self._mark_dirty()  # guarded during load

    def _refresh_slider_overrides(self, *_):
        """Snapshot of the slider values for the TX thread, which never reads widgets."""
        overrides = {}
        for w in self.slider_widgets:
            key = (w.frame_id, bool(getattr(w, "is_ext", False)))
            overrides.setdefault(key, []).append((w.signal, w.value()))
        # One assignment: the TX thread sees the old or the new dict, never half
        self._slider_overrides = {k: tuple(v) for k, v in overrides.items()}

    def _find_slider_message(self, meta):
        """DBC message of a saved slider: by name (1.5+), else by frame number."""
        by_name = {m.name: m for m in self.dbc.messages}
        if meta.get("msg_name") in by_name:
            return by_name[meta["msg_name"]]
        # Before 1.5 "msg_name" held the signal name (TODO 4.8)
        candidates = [
            m for m in self.dbc.messages if m.frame_id == meta.get("frame_id")
        ]
        if "is_ext" in meta:
            candidates = [
                m for m in candidates if m.is_extended_frame == bool(meta["is_ext"])
            ]
        return min(candidates, key=lambda m: m.is_extended_frame, default=None)

    def _update_slider_enabled(self, entry):
        """Sliders of a disabled row are greyed out."""
        for w in self.slider_widgets:
            if (w.frame_id, bool(getattr(w, "is_ext", False))) == entry.key:
                w.set_enabled(entry.enabled)

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
"""Signal time plots (TODO 7.7): a scrolling line chart of DBC signals.

A separate window, like XMetro. Each added signal is a QtCharts line series fed
from the same received and transmitted frames XMetro uses; the X axis is time
in seconds, kept to the last `window` seconds. QtCharts ships with PySide6, so
no extra dependency is added.
"""

import os
import time

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.dbc_loader import decode_signal
from src.utils import format_can_id, resource_path

MAX_POINTS = 4000  # per series, a hard cap on memory


class PlotSeries:
    """One plotted signal: its QLineSeries and the (frame_id, is_ext) it reads."""

    __slots__ = ("series", "frame_id", "is_ext", "signal", "label")

    def __init__(self, series, frame_id, is_ext, signal, label):
        self.series = series
        self.frame_id = frame_id
        self.is_ext = is_ext
        self.signal = signal
        self.label = label

    def key(self):
        return (self.frame_id, self.is_ext)


class SignalPlotWindow(QWidget):
    def __init__(self, dbc_loader):
        super().__init__()
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"Signal Plot - {name}" if name else "Signal Plot")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setMinimumSize(700, 450)

        self.dbc = dbc_loader
        self.plots = []  # list[PlotSeries]
        self._t0 = None  # time.monotonic() of the first fed point

        layout = QVBoxLayout(self)

        # --- controls ---
        controls = QHBoxLayout()
        self.cb_messages = QComboBox()
        self.cb_messages.setToolTip("DBC message whose frames carry the signal.")
        self.cb_signals = QComboBox()
        self.cb_signals.setToolTip("Signal to plot over time.")
        self.btn_add = QPushButton("Add")
        self.btn_add.setToolTip("Plot the selected signal.")
        self.btn_add.clicked.connect(self.add_selected)
        self.cb_active = QComboBox()
        self.cb_active.setToolTip("Plotted signals.")
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setToolTip("Stop plotting the selected signal.")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.sp_window = QSpinBox()
        self.sp_window.setRange(2, 600)
        self.sp_window.setValue(30)
        self.sp_window.setSuffix(" s")
        self.sp_window.setToolTip("How many seconds of history to keep on screen.")
        controls.addWidget(QLabel("Message:"))
        controls.addWidget(self.cb_messages)
        controls.addWidget(QLabel("Signal:"))
        controls.addWidget(self.cb_signals)
        controls.addWidget(self.btn_add)
        controls.addStretch(1)
        controls.addWidget(QLabel("Window:"))
        controls.addWidget(self.sp_window)
        controls.addWidget(self.cb_active)
        controls.addWidget(self.btn_remove)
        layout.addLayout(controls)

        # --- chart ---
        self.chart = QChart()
        self.chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        self.chart.legend().setVisible(True)
        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Time (s)")
        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("Value")
        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.axis_x.setRange(0, self.sp_window.value())
        self.axis_y.setRange(0, 1)
        view = QChartView(self.chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(view)

        self._fill_messages()
        self.cb_messages.currentIndexChanged.connect(self._fill_signals)
        self._fill_signals()

    # --- DBC combos ---

    def _messages(self):
        return [m for m in getattr(self.dbc, "messages", []) if m.signals]

    def _fill_messages(self):
        self.cb_messages.blockSignals(True)
        self.cb_messages.clear()
        for msg in self._messages():
            label = f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
            self.cb_messages.addItem(label, (msg.frame_id, msg.is_extended_frame))
        self.cb_messages.blockSignals(False)

    def _fill_signals(self):
        self.cb_signals.clear()
        msg = self._current_message()
        for sig in msg.signals if msg else []:
            self.cb_signals.addItem(sig.name)

    def _current_message(self):
        idx = self.cb_messages.currentIndex()
        msgs = self._messages()
        return msgs[idx] if 0 <= idx < len(msgs) else None

    # --- series ---

    def add_selected(self):
        msg = self._current_message()
        if msg is None:
            return
        sig_name = self.cb_signals.currentText()
        sig = next((s for s in msg.signals if s.name == sig_name), None)
        if sig is None:
            return
        label = f"{sig.name} @ {format_can_id(msg.frame_id, msg.is_extended_frame)}"
        if any(p.label == label for p in self.plots):
            return  # already plotted
        series = QLineSeries()
        series.setName(label)
        self.chart.addSeries(series)
        series.attachAxis(self.axis_x)
        series.attachAxis(self.axis_y)
        plot = PlotSeries(series, msg.frame_id, bool(msg.is_extended_frame), sig, label)
        self.plots.append(plot)
        self.cb_active.addItem(label)

    def remove_selected(self):
        label = self.cb_active.currentText()
        plot = next((p for p in self.plots if p.label == label), None)
        if plot is None:
            return
        self.chart.removeSeries(plot.series)
        self.plots.remove(plot)
        self.cb_active.removeItem(self.cb_active.currentIndex())

    def clear(self):
        for plot in self.plots:
            self.chart.removeSeries(plot.series)
        self.plots.clear()
        self.cb_active.clear()

    def set_dbc(self, dbc_loader):
        """Follow a DBC change (TODO 7.8 parallel): drop series, refill combos."""
        self.clear()
        self.dbc = dbc_loader
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"Signal Plot - {name}" if name else "Signal Plot")
        self._fill_messages()
        self._fill_signals()

    # --- feed (GUI thread) ---

    def feed(self, frame_id, is_ext, data):
        """Append the decoded value of every series reading this frame."""
        key = (frame_id, bool(is_ext))
        matched = [p for p in self.plots if p.key() == key]
        if not matched:
            return
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        for plot in matched:
            try:
                value = decode_signal(bytes(data), plot.signal)
            except Exception:
                continue
            plot.series.append(t, float(value))
            if plot.series.count() > MAX_POINTS:
                plot.series.removePoints(0, plot.series.count() - MAX_POINTS)
        self._rescale(t)

    def _rescale(self, t):
        window = self.sp_window.value()
        x_lo = max(0.0, t - window)
        self.axis_x.setRange(x_lo, max(window, t))
        # Trim points older than the window and find the Y extent of what's shown
        lo = hi = None
        for plot in self.plots:
            points = plot.series.points()
            drop = 0
            for p in points:
                if p.x() < x_lo:
                    drop += 1
                else:
                    break
            if drop:
                plot.series.removePoints(0, drop)
                points = points[drop:]
            for p in points:
                lo = p.y() if lo is None else min(lo, p.y())
                hi = p.y() if hi is None else max(hi, p.y())
        if lo is None:
            return
        if lo == hi:
            lo, hi = lo - 1, hi + 1
        margin = (hi - lo) * 0.05
        self.axis_y.setRange(lo - margin, hi + margin)

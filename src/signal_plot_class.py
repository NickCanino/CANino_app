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
with every received and transmitted frame that carries it (TODO 7.10), each
value at its own frame time; the X axis is time in seconds, kept to the last
`window` seconds. QtCharts ships with PySide6, so no extra dependency is added.

The X axis is labelled with the computer's local clock (hh:mm:ss): it starts at
the first sample's time and has a label on every multiple of 5 s of the clock
(a wider multiple when 5 s labels would overlap). Internally X stays in seconds
since that first sample, so the values keep their precision.

The line is drawn from time buckets (M4 decimation): the window is split into
PLOT_BUCKETS slots and each slot draws its first, lowest, highest and last
sample. A polyline through those covers the same pixels as one through every
sample, so no spike is lost, while Qt holds at most ~4 points per slot at any
frame rate (redrawing every point of a 1 ms signal costs tens of ms a refresh).

Anomaly intervals (TODO 7.11): a TX script may label its frames (TODO 3.17);
each run of equally labelled frames of a plotted frame ID is an interval, from
its first to its last labelled sample, painted over the plot area as a red band
with a line at the onset and the label at the top.
"""

import math
import os
import time
from bisect import bisect_left
from datetime import datetime

from PySide6.QtCharts import (
    QCategoryAxis,
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src.dbc_loader import decode_signal
from src.utils import format_can_id, resource_path

# Time slots across the window (about one per pixel of a full-HD plot)
PLOT_BUCKETS = 1500
# Raw samples kept per series, to re-bucket when the window changes: a memory cap
MAX_SAMPLES = 200_000

# Anomaly bands (TODO 7.11): fill, onset line + label, narrowest band (px)
ANOMALY_FILL = QColor(229, 57, 53, 70)
ANOMALY_LINE = QColor(239, 83, 80)
ANOMALY_MIN_PX = 2.0

# Clock labels on the X axis: every 5 s, or the first wider step whose labels
# are at least TICK_MIN_GAP_PX apart beyond their own width
TICK_STEPS_S = (5, 10, 15, 30, 60, 120, 300, 600)
TICK_MIN_GAP_PX = 16
TIME_TITLE = "Time (hh:mm:ss)"


def tick_times(t_lo, t_hi, step):
    """Clock times (epoch s) of the multiples of `step` in [t_lo, t_hi]."""
    k = math.ceil(t_lo / step)
    ticks = []
    while k * step <= t_hi:
        ticks.append(k * step)
        k += 1
    return ticks


def clock_label(t):
    """Local time of an epoch timestamp as hh:mm:ss."""
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


class Bucket:
    """One time slot of a series, reduced to the samples that draw it."""

    __slots__ = ("idx", "first", "low", "high", "last", "n_pts")

    def __init__(self, idx, x, y):
        self.idx = idx  # slot number: int(x // slot width)
        self.first = self.low = self.high = self.last = (x, y)
        self.n_pts = 0  # points of this slot now in the QLineSeries

    def add(self, x, y):
        self.last = (x, y)
        if y < self.low[1]:
            self.low = (x, y)
        elif y > self.high[1]:
            self.high = (x, y)

    def points(self):
        """First, lowest, highest and last sample in time order, each once."""
        return [
            QPointF(x, y)
            for x, y in sorted({self.first, self.low, self.high, self.last})
        ]


class Anomaly:
    """One labelled interval of a frame: its first..last labelled sample (plot s)."""

    __slots__ = ("start", "end", "label", "open")

    def __init__(self, t, label):
        self.start = self.end = t
        self.label = label
        self.open = True  # the latest sample of the frame carried this label


class AnomalyChartView(QChartView):
    """A QChartView that paints the anomaly intervals over the plot area.

    Painted by the view rather than as chart series: no legend entries, no
    effect on the axes, and the bands scroll with the X axis for free. Band
    and onset line go in drawBackground, under the curves (a one-frame spike
    sits exactly on its onset line); the chart's own background is moved to
    the view so it does not cover them. The label goes on top.
    """

    def __init__(self, chart, axis_x, bands):
        super().__init__(chart)
        self._axis_x = axis_x
        self._bands = bands  # () -> [(start, end, text)] in plot seconds
        self.setBackgroundBrush(chart.backgroundBrush())
        chart.setBackgroundVisible(False)

    def _layout(self):
        """(bands, plot area in scene coordinates, px per second) or None."""
        bands = self._bands()
        if not bands:
            return None
        chart = self.chart()
        area = chart.mapRectToScene(chart.plotArea())
        lo, hi = self._axis_x.min(), self._axis_x.max()
        if hi <= lo or area.width() <= 0:
            return None
        return bands, area, lo, area.width() / (hi - lo)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        layout = self._layout()
        if layout is None:
            return
        bands, area, lo, scale = layout
        painter.save()
        painter.setClipRect(area)
        painter.setPen(QPen(ANOMALY_LINE, 1.5))
        for start, end, _ in bands:
            x0 = area.left() + (start - lo) * scale
            width = max((end - start) * scale, ANOMALY_MIN_PX)
            painter.fillRect(QRectF(x0, area.top(), width, area.height()), ANOMALY_FILL)
            painter.drawLine(QPointF(x0, area.top()), QPointF(x0, area.bottom()))
        painter.restore()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        layout = self._layout()
        if layout is None:
            return
        bands, area, lo, scale = layout
        painter.save()
        painter.setClipRect(area)
        painter.setPen(ANOMALY_LINE)
        for start, _, text in bands:
            x0 = area.left() + (start - lo) * scale
            painter.drawText(QPointF(x0 + 4, area.top() + 14), text)
        painter.restore()


class PlotSeries:
    """One plotted signal: its QLineSeries and the (frame_id, is_ext) it reads.

    `xs`/`ys` hold every sample in the window (raw, up to MAX_SAMPLES); the
    series holds the points of `buckets`, `count` of them, so trimming and the
    Y range never read the points back from Qt.
    """

    __slots__ = (
        "series",
        "frame_id",
        "is_ext",
        "signal",
        "label",
        "xs",
        "ys",
        "buckets",
        "count",
    )

    def __init__(self, series, frame_id, is_ext, signal, label):
        self.series = series
        self.frame_id = frame_id
        self.is_ext = is_ext
        self.signal = signal
        self.label = label
        self.xs = []
        self.ys = []
        self.buckets = []
        self.count = 0

    def key(self):
        return (self.frame_id, self.is_ext)


class SignalPlotWindow(QWidget):
    # The set of plotted frames changed: the RX drain and the TX thread collect
    # every sample of these frames only (keys())
    keys_changed = Signal()

    def __init__(self, dbc_loader):
        super().__init__()
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"Signal Plot - {name}" if name else "Signal Plot")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setMinimumSize(700, 450)

        self.dbc = dbc_loader
        self.plots = []  # list[PlotSeries]
        self._t0 = None  # frame time of the first fed sample: X = 0
        self._ticks = None  # (step, tick times) now on the X axis
        self._t_last = 0.0  # X of the newest sample: the axis ends there
        # (frame_id, is_ext) -> [Anomaly] in time order (TODO 7.11)
        self.anomalies = {}

        layout = QVBoxLayout(self)

        # --- controls ---
        controls = QHBoxLayout()
        self.cb_messages = QComboBox()
        self.cb_messages.setToolTip("DBC message whose frames carry the signal.")
        self.cb_signals = QComboBox()
        self.cb_signals.setToolTip("Signal to plot over time.")
        self.btn_add = QPushButton("Add")
        self.btn_add.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.btn_add.setToolTip("Plot the selected signal.")
        self.btn_add.clicked.connect(self.add_selected)
        self.cb_active = QComboBox()
        self.cb_active.setMinimumWidth(220)
        self.cb_active.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.cb_active.setToolTip("Plotted signals.")
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
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
        # A category axis = labels at chosen values: the clock ticks
        self.axis_x = QCategoryAxis()
        self.axis_x.setLabelsPosition(
            QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue
        )
        self.axis_x.setTitleText(TIME_TITLE)
        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("Value")
        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.axis_x.setRange(0, self.sp_window.value())
        self.axis_y.setRange(0, 1)
        self.view = AnomalyChartView(self.chart, self.axis_x, self.anomaly_bands)
        # The clock-label step depends on the plot width
        self.chart.plotAreaChanged.connect(self._update_ticks)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.view)

        self._fill_messages()
        self.cb_messages.currentIndexChanged.connect(self._fill_signals)
        self._fill_signals()
        self._bucket_w = self.sp_window.value() / PLOT_BUCKETS  # slot width (s)
        self.sp_window.valueChanged.connect(self._window_changed)

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
        self.keys_changed.emit()

    def remove_selected(self):
        label = self.cb_active.currentText()
        plot = next((p for p in self.plots if p.label == label), None)
        if plot is None:
            return
        self.chart.removeSeries(plot.series)
        self.plots.remove(plot)
        self.cb_active.removeItem(self.cb_active.currentIndex())
        keys = self.keys()
        self.anomalies = {k: v for k, v in self.anomalies.items() if k in keys}
        self.view.viewport().update()
        self.keys_changed.emit()

    def clear(self):
        for plot in self.plots:
            self.chart.removeSeries(plot.series)
        self.plots.clear()
        self.cb_active.clear()
        self.anomalies = {}
        self.view.viewport().update()
        self.keys_changed.emit()

    def keys(self):
        """The (frame_id, is_ext) of every plotted signal."""
        return {p.key() for p in self.plots}

    def set_dbc(self, dbc_loader):
        """Follow a DBC change (TODO 7.8 parallel): drop series, refill combos."""
        self.clear()
        self.dbc = dbc_loader
        name = os.path.basename(getattr(dbc_loader, "dbc_filename", "") or "")
        self.setWindowTitle(f"Signal Plot - {name}" if name else "Signal Plot")
        self._fill_messages()
        self._fill_signals()

    # --- feed (GUI thread) ---

    def feed(self, frame_id, is_ext, data, timestamp=None):
        """One frame (now, unless `timestamp` is given); see feed_samples."""
        ts = time.time() if timestamp is None else timestamp
        self.feed_samples([(frame_id, is_ext, data, ts)])

    def feed_samples(self, samples):
        """Append every sample of a plotted frame (TODO 7.10).

        `samples` = [(frame_id, is_ext, data, timestamp[, label])], timestamp
        in seconds on the time.time() scale (PCAN hardware time is a constant
        offset from it). Each value is placed at its own time, so none is lost
        between two refreshes; the axes are rescaled once per batch. `label`
        (TX samples only) = the script's anomaly label or None: it opens,
        extends or closes the frame's anomaly interval (TODO 7.11).
        """
        if not self.plots:
            return
        by_key = {}
        for plot in self.plots:
            by_key.setdefault(plot.key(), []).append(plot)
        new = {}  # id(plot) -> [(t, value)] of this batch
        t_last = None
        for frame_id, is_ext, data, ts, *label in samples:
            key = (frame_id, bool(is_ext))
            matched = by_key.get(key)
            if not matched:
                continue
            if self._t0 is None:
                self._t0 = ts
            t = ts - self._t0
            t_last = t if t_last is None else max(t_last, t)
            if label:
                self._mark(key, t, label[0])
            payload = bytes(data)
            for plot in matched:
                try:
                    value = float(decode_signal(payload, plot.signal))
                except Exception:
                    continue
                new.setdefault(id(plot), []).append((t, value))
        if t_last is None:
            return
        changed = set()
        for plot in self.plots:
            batch = new.get(id(plot))
            if not batch:
                continue
            plot.xs.extend(t for t, _ in batch)
            plot.ys.extend(v for _, v in batch)
            excess = len(plot.xs) - MAX_SAMPLES
            if excess > 0:
                del plot.xs[:excess]
                del plot.ys[:excess]
            self._bucket(plot, batch)
            changed.add(id(plot))
        self._t_last = max(self._t_last, t_last)
        self._rescale(self._t_last, changed)
        if self.anomalies:
            self.view.viewport().update()  # bands are not part of the scene

    def _mark(self, key, t, label):
        """One TX sample of a frame: extend, close or open its anomaly interval."""
        intervals = self.anomalies.get(key)
        cur = intervals[-1] if intervals and intervals[-1].open else None
        if cur is not None and label == cur.label:
            cur.end = t
            return
        if cur is not None:
            cur.open = False  # ends at its last labelled sample
        if label:
            self.anomalies.setdefault(key, []).append(Anomaly(t, label))

    def anomaly_bands(self):
        """[(start, end, text)] of the intervals still in view. The text names
        the frame when more than one frame is plotted."""
        lo = self.axis_x.min()
        many = len(self.keys()) > 1
        bands = []
        for (frame_id, is_ext), intervals in self.anomalies.items():
            name = f" @ {format_can_id(frame_id, is_ext)}" if many else ""
            bands.extend(
                (a.start, a.end, a.label + name) for a in intervals if a.end >= lo
            )
        return bands

    def _bucket(self, plot, samples):
        """Fold samples (time order) into the plot's slots and replace, silently,
        the series points of every slot they touched (the last one and new ones).

        QtCharts rebuilds the whole line on every point signal, so the points
        change with signals blocked and _rescale redraws once per batch.
        """
        w = self._bucket_w
        buckets = plot.buckets
        last = buckets[-1] if buckets else None
        first = len(buckets)  # first slot whose points change
        if last is not None and int(samples[0][0] // w) <= last.idx:
            first -= 1
        for x, y in samples:
            idx = int(x // w)
            if last is not None and idx <= last.idx:  # same slot (or late sample)
                last.add(x, y)
            else:
                last = Bucket(idx, x, y)
                buckets.append(last)
        old = 0
        points = []
        for b in buckets[first:]:
            old += b.n_pts
            pts = b.points()
            b.n_pts = len(pts)
            points.extend(pts)
        series = plot.series
        series.blockSignals(True)
        if old:
            series.removePoints(plot.count - old, old)
        series.append(points)
        series.blockSignals(False)
        plot.count += len(points) - old

    def _rebuild(self, plot):
        """Re-slot every kept sample: the slot width changed with the window."""
        plot.buckets = []
        plot.count = 0
        plot.series.blockSignals(True)
        plot.series.clear()
        plot.series.blockSignals(False)
        if plot.xs:
            self._bucket(plot, list(zip(plot.xs, plot.ys)))

    def _window_changed(self):
        self._bucket_w = self.sp_window.value() / PLOT_BUCKETS
        for plot in self.plots:
            self._rebuild(plot)
        self._rescale(self._t_last, {id(p) for p in self.plots})

    def _rescale(self, t, changed=()):
        """Scroll X to end at `t`, trim what left the window, fit Y.

        `changed` = ids of the plots whose points were changed silently: an
        axis change redraws every series, otherwise they are redrawn here.
        """
        changed = set(changed)
        window = self.sp_window.value()
        x_lo = max(0.0, t - window)
        # Trim samples, slots and anomaly intervals older than the window, find
        # the Y extent
        for key, intervals in list(self.anomalies.items()):
            keep = [a for a in intervals if a.end >= x_lo]
            if keep:
                self.anomalies[key] = keep
            else:
                del self.anomalies[key]
        lo = hi = None
        for plot in self.plots:
            drop = bisect_left(plot.xs, x_lo)
            if drop:
                del plot.xs[:drop]
                del plot.ys[:drop]
            n = pts = 0
            for b in plot.buckets:
                if b.last[0] >= x_lo:
                    break
                n += 1
                pts += b.n_pts
            if n:
                del plot.buckets[:n]
                plot.series.blockSignals(True)
                plot.series.removePoints(0, pts)
                plot.series.blockSignals(False)
                plot.count -= pts
                changed.add(id(plot))
            if plot.buckets:
                p_lo = min(b.low[1] for b in plot.buckets)
                p_hi = max(b.high[1] for b in plot.buckets)
                lo = p_lo if lo is None else min(lo, p_lo)
                hi = p_hi if hi is None else max(hi, p_hi)
        before = self._ranges()
        self.axis_x.setRange(x_lo, max(window, t))
        self._update_ticks()
        if lo is not None:
            if lo == hi:
                lo, hi = lo - 1, hi + 1
            margin = (hi - lo) * 0.05
            self.axis_y.setRange(lo - margin, hi + margin)
        if changed and self._ranges() == before:
            for plot in self.plots:
                if id(plot) in changed:
                    plot.series.pointsReplaced.emit()  # one redraw from all points

    def _update_ticks(self, *_):
        """Put a clock label on every step-multiple of the local time in view.

        Rebuilt only when the step or the set of ticks in view changes (a tick
        entered or left the window), not on every scroll: the category values
        are in plot seconds, so they move with the axis by themselves.
        """
        axis = self.axis_x
        if self._t0 is None:
            return
        lo, hi = self._t0 + axis.min(), self._t0 + axis.max()
        width = self.chart.plotArea().width()  # 0 until the chart is laid out
        label_px = QFontMetrics(axis.labelsFont()).horizontalAdvance("00:00:00")
        step = TICK_STEPS_S[0] if width <= 0 else TICK_STEPS_S[-1]
        for s in TICK_STEPS_S if width > 0 else ():
            if (hi - lo) / s * (label_px + TICK_MIN_GAP_PX) <= width:
                step = s
                break
        ticks = tick_times(lo, hi, step)
        if self._ticks == (step, ticks):
            return
        self._ticks = (step, ticks)
        for label in axis.categoriesLabels():
            axis.remove(label)
        axis.setStartValue(axis.min() - 1.0)  # below every tick, out of view
        for t in ticks:
            axis.append(clock_label(t), t - self._t0)
        start = datetime.fromtimestamp(self._t0).strftime("%H:%M:%S.%f")[:-3]
        axis.setTitleText(f"{TIME_TITLE} - first sample {start}")

    def _ranges(self):
        return (
            self.axis_x.min(),
            self.axis_x.max(),
            self.axis_y.min(),
            self.axis_y.max(),
        )

"""v1.7.2 / sub-task 2 — TODO 3.17: a payload script labels its anomalous frames.
v1.7.2 / sub-task 3 — TODO 7.11: the Signal Plot paints the labelled intervals.

`get_payload` may return (payload, label); the label travels with the frame's
Signal Plot sample. Run from the repo root:
    python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import QPointF  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.signal_plot_class import SignalPlotWindow  # noqa: E402
from src.tx_panel import split_script_result  # noqa: E402
from test_signal_plot import frame, make_dbc, plot_signal  # noqa: E402

# Byte 0 counts the calls; frames 3 and 4 are labelled "spike", 6 returns
# (None, "drift") = the manual payload, labelled; the rest are plain bytes
LABEL_SCRIPT = """n = 0


def get_payload(dlc, id):
    global n
    n += 1
    payload = bytes([n]) + bytes(dlc - 1)
    if n in (3, 4):
        return payload, "spike"
    if n == 6:
        return None, "drift"
    if n == 7:
        return payload, ""
    return payload
"""


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class SplitResultTests(unittest.TestCase):
    def test_plain_results(self):
        self.assertEqual(split_script_result(b"\x01\x02"), (b"\x01\x02", None))
        self.assertEqual(split_script_result(None), (None, None))

    def test_pair(self):
        self.assertEqual(split_script_result((b"\x01", "spike")), (b"\x01", "spike"))
        self.assertEqual(split_script_result((None, "drift")), (None, "drift"))

    def test_empty_or_none_label_is_a_normal_frame(self):
        self.assertEqual(split_script_result((b"\x01", "")), (b"\x01", None))
        self.assertEqual(split_script_result((b"\x01", None)), (b"\x01", None))

    def test_bad_shapes_raise(self):
        with self.assertRaises(ValueError):
            split_script_result((b"\x01", "a", "b"))
        with self.assertRaises(ValueError):
            split_script_result((b"\x01", 3))


class FakeIf:
    is_fd = False
    bus = None

    def __init__(self):
        self.sent = []

    def send_frame(
        self, frame_id, data, dlc=None, is_fd=False, is_ext=False, is_rtr=False
    ):
        self.sent.append((frame_id, bytes(data)))
        return True

    def flush_tx(self):
        return True

    def close(self):
        pass


class ScriptLabelTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw.can_if = FakeIf()
        self.path = os.path.join(h.WORKDIR, "labelled.py")
        write(self.path, LABEL_SCRIPT)

    def tearDown(self):
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def row(self, **kw):
        entry = self.mw._add_tx_row(0x100, "A", dlc=2, **kw)
        entry.payload = b"\xee\xee"
        self.mw._plot_tx_keys = frozenset({entry.key})  # as an open plot would
        return entry

    def send(self, entry, n):
        for _ in range(n):
            self.mw._send_row(entry)
        return list(self.mw._tx_samples)

    def test_labels_travel_with_the_samples(self):
        entry = self.row(script_path=self.path)
        samples = self.send(entry, 8)
        self.assertEqual(
            [(s[2], s[4]) for s in samples],
            [
                (b"\x01\x00", None),
                (b"\x02\x00", None),
                (b"\x03\x00", "spike"),
                (b"\x04\x00", "spike"),
                (b"\x05\x00", None),
                # None = the manual payload, labelled: the row's payload cell,
                # which holds the last frame sent (written back each send)
                (b"\x05\x00", "drift"),
                (b"\x07\x00", None),  # "" = normal
                (b"\x08\x00", None),
            ],
        )
        self.assertEqual([f for f, _ in self.mw.can_if.sent], [0x100] * 8)

    def test_global_script_labels_too(self):
        self.mw.global_script_path = self.path
        entry = self.row()
        samples = self.send(entry, 4)
        self.assertEqual([s[4] for s in samples], [None, None, "spike", "spike"])

    def test_bad_label_blocks_the_frame(self):
        write(self.path, "def get_payload(dlc, id):\n    return bytes(dlc), 42\n")
        entry = self.row(script_path=self.path)
        self.send(entry, 1)
        self.assertEqual(self.mw.can_if.sent, [])
        self.assertIn("label is int", entry.error)

    def test_sliders_still_apply_to_labelled_frames(self):
        entry = self.row(script_path=self.path)
        self.send(entry, 2)  # n = 1, 2
        sig = make_dbc().messages[0].signals[0]  # SIG_X: byte 0, factor 2
        self.mw._slider_overrides = {entry.key: [(sig, 20)]}
        samples = self.send(entry, 1)  # n = 3: "spike"
        self.assertEqual(samples[-1][4], "spike")
        self.assertEqual(samples[-1][2], b"\x0a\x00")  # the slider wins byte 0

    def test_label_reaches_the_plot_feed(self):
        entry = self.row(script_path=self.path)
        got = []
        self.mw._feed_plots = got.extend
        self.send(entry, 3)
        self.mw._tx_refresh()
        self.assertEqual([s[4] for s in got], [None, None, "spike"])


def tx(i, label, fid=0x100, value=50):
    """A TX sample of frame `fid` at 10 + i/10 s (plot time i/10 s)."""
    return (fid, False, frame(value), 10.0 + i / 10, label)


class IntervalTests(unittest.TestCase):
    """7.11: runs of equally labelled TX frames become intervals."""

    def setUp(self):
        self.w = SignalPlotWindow(make_dbc())
        plot_signal(self.w, "MSG_A", "SIG_X")  # 0x100

    def tearDown(self):
        h.dispose(self.w)

    def spans(self, fid=0x100):
        return [
            (round(a.start, 6), round(a.end, 6), a.label, a.open)
            for a in self.w.anomalies.get((fid, False), [])
        ]

    def test_runs_become_intervals(self):
        labels = [None, "spike", "spike", None, "drift", None, "x", "y", "y"]
        self.w.feed_samples([tx(i, lab) for i, lab in enumerate(labels)])
        self.assertEqual(
            self.spans(),
            [
                (0.1, 0.2, "spike", False),  # first..last labelled sample
                (0.4, 0.4, "drift", False),  # one frame: zero width
                (0.6, 0.6, "x", False),  # a new label closes the previous one
                (0.7, 0.8, "y", True),  # still running
            ],
        )

    def test_open_interval_extends_across_batches(self):
        self.w.feed_samples([tx(0, "spike"), tx(1, "spike")])
        self.w.feed_samples([tx(2, "spike")])
        self.assertEqual(self.spans(), [(0.0, 0.2, "spike", True)])
        self.w.feed_samples([tx(3, None)])
        self.assertEqual(self.spans(), [(0.0, 0.2, "spike", False)])

    def test_rx_samples_leave_intervals_alone(self):
        self.w.feed_samples([tx(0, "spike")])
        self.w.feed_samples([(0x100, False, frame(1), 10.1)])  # RX: no label field
        self.assertEqual(self.spans(), [(0.0, 0.0, "spike", True)])

    def test_unplotted_frames_make_no_interval(self):
        self.w.feed_samples([tx(0, "spike", fid=0x120)])
        self.assertEqual(self.w.anomalies, {})

    def test_intervals_leave_with_the_window(self):
        self.w.sp_window.setValue(5)
        self.w.feed_samples([tx(0, "old"), tx(1, None), tx(30, "new")])
        self.w.feed_samples([tx(100, None)])  # t = 10 s: window 5..10
        self.assertEqual(self.spans(), [])
        self.w.feed_samples([tx(101, "now")])
        self.assertEqual([b[2] for b in self.w.anomaly_bands()], ["now"])

    def test_remove_and_clear_drop_intervals(self):
        plot_signal(self.w, "MSG_B", "SIG_Y")  # 0x120
        self.w.feed_samples([tx(0, "a"), tx(1, "b", fid=0x120)])
        self.assertEqual(
            sorted(b[2] for b in self.w.anomaly_bands()), ["a @ 0x100", "b @ 0x120"]
        )  # two frames plotted: the text names the frame
        self.w.cb_active.setCurrentIndex(0)  # SIG_X @ 0x100
        self.w.remove_selected()
        self.assertEqual(list(self.w.anomalies), [(0x120, False)])
        self.assertEqual([b[2] for b in self.w.anomaly_bands()], ["b"])
        self.w.clear()
        self.assertEqual(self.w.anomalies, {})

    def test_band_is_painted_under_the_curve(self):
        """Pixels inside the band are red-tinted, outside they are not."""
        self.w.resize(900, 450)
        self.w.show()
        samples = [tx(i, "spike" if 40 <= i < 60 else None) for i in range(100)]
        self.w.feed_samples(samples)  # constant value: the curve is mid-height
        h.app.processEvents()
        view = self.w.view
        chart = self.w.chart
        area = chart.mapRectToScene(chart.plotArea())
        image = view.grab().toImage()

        def pixel(t):
            x = chart.mapToPosition(QPointF(t, 0), self.w.plots[0].series).x()
            scene = QPointF(chart.mapToScene(QPointF(x, 0)).x(), area.bottom() - 10)
            return image.pixelColor(view.mapFromScene(scene))

        inside, outside = pixel(5.0), pixel(8.0)
        self.assertGreater(inside.red() - inside.blue(), 20)
        self.assertLess(abs(outside.red() - outside.blue()), 15)


class PlotIntervalGuiTests(unittest.TestCase):
    """End to end: a labelled TX script draws its interval in an open plot."""

    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw.can_if = FakeIf()
        self.mw._apply_dbc(make_dbc())
        self.mw.open_signal_plot_window()
        self.w = self.mw.signal_plot_windows[-1]
        plot_signal(self.w, "MSG_A", "SIG_X")
        self.path = os.path.join(h.WORKDIR, "labelled_gui.py")
        write(self.path, LABEL_SCRIPT)

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_tx_script_label_draws_an_interval(self):
        entry = self.mw._add_tx_row(0x100, "A", dlc=8, script_path=self.path)
        self.mw.start_stop_transmission()
        for _ in range(5):
            self.mw.tx_scheduler.fire_all()
        self.mw._tx_refresh()
        intervals = self.w.anomalies[entry.key]
        self.assertEqual([(a.label, a.open) for a in intervals], [("spike", False)])
        self.assertEqual(self.w.plots[0].ys, [2.0, 4.0, 6.0, 8.0, 10.0])


if __name__ == "__main__":
    unittest.main()

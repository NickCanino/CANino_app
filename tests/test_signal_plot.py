"""Phase 3 / sub-task 7 — TODO 7.7: signal time plots (QtCharts).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402
import src.gui as gui  # noqa: E402
from src.signal_plot_class import SignalPlotWindow  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (2,0) [0|510] "rpm" ECU
BO_ 288 MSG_B: 8 ECU
 SG_ SIG_Y : 0|8@1+ (1,0) [0|255] "" ECU
"""


def make_dbc(name="plot.dbc"):
    path = os.path.join(h.WORKDIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(DBC)
    return dbc_loader.load_dbc(path)


class PlotWindowTests(unittest.TestCase):
    def setUp(self):
        self.w = SignalPlotWindow(make_dbc())

    def tearDown(self):
        h.dispose(self.w)

    def add(self, msg_name, sig_name):
        self.w.cb_messages.setCurrentIndex(
            next(
                i
                for i in range(self.w.cb_messages.count())
                if msg_name in self.w.cb_messages.itemText(i)
            )
        )
        self.w._fill_signals()
        self.w.cb_signals.setCurrentIndex(self.w.cb_signals.findText(sig_name))
        self.w.add_selected()

    def test_add_creates_a_series(self):
        self.add("MSG_A", "SIG_X")
        self.assertEqual(len(self.w.plots), 1)
        self.assertEqual(len(self.chart_series()), 1)

    def chart_series(self):
        return self.w.chart.series()

    def test_feed_appends_decoded_points(self):
        self.add("MSG_A", "SIG_X")
        self.w.feed(0x100, False, bytes([10, 0, 0, 0, 0, 0, 0, 0]))
        self.w.feed(0x100, False, bytes([20, 0, 0, 0, 0, 0, 0, 0]))
        pts = self.w.plots[0].series.points()
        self.assertEqual([p.y() for p in pts], [20.0, 40.0])  # factor 2

    def test_feed_ignores_other_frames(self):
        self.add("MSG_A", "SIG_X")
        self.w.feed(0x200, False, bytes(8))  # different ID
        self.assertEqual(self.w.plots[0].series.count(), 0)

    def test_two_signals_two_series(self):
        self.add("MSG_A", "SIG_X")
        self.add("MSG_B", "SIG_Y")
        self.assertEqual(len(self.w.plots), 2)
        self.w.feed(0x100, False, bytes([1, 0, 0, 0, 0, 0, 0, 0]))
        self.w.feed(0x120, False, bytes([7, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(self.w.plots[0].series.count(), 1)
        self.assertEqual(self.w.plots[1].series.count(), 1)

    def test_duplicate_add_is_ignored(self):
        self.add("MSG_A", "SIG_X")
        self.add("MSG_A", "SIG_X")
        self.assertEqual(len(self.w.plots), 1)

    def test_remove_drops_the_series(self):
        self.add("MSG_A", "SIG_X")
        self.w.cb_active.setCurrentIndex(0)
        self.w.remove_selected()
        self.assertEqual(len(self.w.plots), 0)
        self.assertEqual(len(self.chart_series()), 0)

    def test_window_trims_old_points(self):
        self.add("MSG_A", "SIG_X")
        p = self.w.plots[0]
        self.w.sp_window.setValue(5)
        # Points spanning 0..10 s; after a feed at t~10 only the last 5 s remain
        for i in range(11):
            p.series.append(float(i), float(i))
        self.w._rescale(10.0)
        xs = [pt.x() for pt in p.series.points()]
        self.assertTrue(all(x >= 5.0 for x in xs))

    def test_set_dbc_clears_and_refills(self):
        self.add("MSG_A", "SIG_X")
        other = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 512 OTHER: 8 ECU
 SG_ OSIG : 0|8@1+ (1,0) [0|255] "" ECU
"""
        p = os.path.join(h.WORKDIR, "other_plot.dbc")
        with open(p, "w", encoding="utf-8") as f:
            f.write(other)
        self.w.set_dbc(dbc_loader.load_dbc(p))
        self.assertEqual(len(self.w.plots), 0)
        names = [
            self.w.cb_messages.itemText(i) for i in range(self.w.cb_messages.count())
        ]
        self.assertTrue(any("OTHER" in n for n in names))


class PlotGuiTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_open_requires_dbc(self):
        h.DIALOGS.clear()
        self.mw.dbc = None
        self.mw.open_signal_plot_window()
        self.assertEqual(self.mw.signal_plot_windows, [])
        self.assertEqual([d[0] for d in h.DIALOGS][-1], "warning")

    def test_rx_frames_reach_an_open_plot(self):
        self.mw._apply_dbc(make_dbc())
        self.mw.open_signal_plot_window()
        w = self.mw.signal_plot_windows[-1]
        w.cb_messages.setCurrentIndex(0)
        w._fill_signals()
        w.cb_signals.setCurrentIndex(0)
        w.add_selected()
        # Feed through the RX window -> _feed_latest -> plot
        self.mw.rx_window.push_frame(0x100, bytes([30, 0, 0, 0, 0, 0, 0, 0]), 8, False)
        self.mw.rx_window.drain()
        self.assertEqual(w.plots[0].series.count(), 1)
        self.assertEqual(w.plots[0].series.points()[0].y(), 60.0)

    def test_dbc_change_reaches_open_plot(self):
        self.mw._apply_dbc(make_dbc("a.dbc"))
        self.mw.open_signal_plot_window()
        w = self.mw.signal_plot_windows[-1]
        w.cb_messages.setCurrentIndex(0)
        w._fill_signals()
        w.cb_signals.setCurrentIndex(0)
        w.add_selected()
        self.assertEqual(len(w.plots), 1)
        self.mw._apply_dbc(None)
        self.assertEqual(len(w.plots), 0)  # DBC gone -> series cleared


if __name__ == "__main__":
    unittest.main()

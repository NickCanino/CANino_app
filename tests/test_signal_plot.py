"""Phase 3 / sub-task 7 — TODO 7.7: signal time plots (QtCharts).
v1.7.2 / sub-task 1 — TODO 7.10: every RX/TX value of a plotted signal.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402
import src.gui as gui  # noqa: E402
import src.signal_plot_class as signal_plot_class  # noqa: E402
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


def plot_signal(w, msg_name, sig_name):
    """Pick a message and a signal in the combos and press Add."""
    w.cb_messages.setCurrentIndex(
        next(
            i
            for i in range(w.cb_messages.count())
            if msg_name in w.cb_messages.itemText(i)
        )
    )
    w._fill_signals()
    w.cb_signals.setCurrentIndex(w.cb_signals.findText(sig_name))
    w.add_selected()


def frame(value):
    return bytes([value, 0, 0, 0, 0, 0, 0, 0])


def ys(plot):
    return [p.y() for p in plot.series.points()]


def xs(plot):
    return [p.x() for p in plot.series.points()]


class PlotWindowTests(unittest.TestCase):
    def setUp(self):
        self.w = SignalPlotWindow(make_dbc())

    def tearDown(self):
        h.dispose(self.w)

    def add(self, msg_name, sig_name):
        plot_signal(self.w, msg_name, sig_name)

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
        # One sample per second over 0..10 s: only the last 5 s remain
        self.w.feed_samples([(0x100, False, frame(i), 50.0 + i) for i in range(11)])
        self.assertEqual(xs(p), [5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        self.assertEqual(p.xs, xs(p))  # one sample per slot: series = raw samples
        self.assertEqual(p.ys, ys(p))
        self.assert_consistent(p)

    def test_every_sample_at_its_own_time(self):
        """7.10: a batch keeps every value, each at its frame time."""
        self.add("MSG_A", "SIG_X")
        batch = [(0x100, False, frame(i), 100.0 + i * 0.01) for i in range(1, 6)]
        self.w.feed_samples(batch)
        p = self.w.plots[0]
        self.assertEqual(p.ys, [2.0, 4.0, 6.0, 8.0, 10.0])
        for got, want in zip(p.xs, [0.0, 0.01, 0.02, 0.03, 0.04]):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(self.w.axis_x.max(), 30.0)  # window not yet full
        self.assert_consistent(p)

    def test_x_axis_shows_the_clock_every_5_s(self):
        """7.12: X labels = local hh:mm:ss on every multiple of 5 s of the clock."""
        self.w.resize(1100, 500)
        self.add("MSG_A", "SIG_X")
        t0 = 1_800_000_002.4  # epoch s, not on a 5 s boundary
        self.w.feed_samples([(0x100, False, frame(1), t0 + i) for i in range(41)])
        lo, hi = t0 + self.w.axis_x.min(), t0 + self.w.axis_x.max()  # last 30 s
        want = signal_plot_class.tick_times(lo, hi, 5)
        self.assertEqual(len(want), 6)
        self.assertTrue(all(t % 5 == 0 for t in want))
        self.assertEqual(
            self.w.axis_x.categoriesLabels(),
            [signal_plot_class.clock_label(t) for t in want],
        )
        for label, t in zip(self.w.axis_x.categoriesLabels(), want):
            self.assertAlmostEqual(self.w.axis_x.endValue(label), t - t0)
        self.assertRegex(self.w.axis_x.categoriesLabels()[0], r"^\d\d:\d\d:\d\d$")
        self.assertIn(
            signal_plot_class.clock_label(t0), self.w.axis_x.titleText()
        )  # the first sample's time

    def test_x_axis_wider_step_when_5_s_labels_overlap(self):
        self.w.resize(1100, 500)
        self.w.show()
        h.app.processEvents()  # lay the chart out: the step needs its width
        self.add("MSG_A", "SIG_X")
        self.w.sp_window.setValue(600)
        self.w.feed_samples(
            [(0x100, False, frame(1), 1_800_000_000.0 + i) for i in range(700)]
        )
        step, ticks = self.w._ticks
        self.assertGreater(step, 5)
        self.assertEqual(len(self.w.axis_x.categoriesLabels()), len(ticks))

    def test_dashed_sub_grid_every_second(self):
        """7.13: a dashed line every 1 s between the 5 s labels; dashed Y grid."""
        self.w.resize(1100, 500)
        self.w.show()
        h.app.processEvents()  # lay the chart out: the sub-step needs its width
        self.add("MSG_A", "SIG_X")
        t0 = 1_800_000_002.4
        self.w.feed_samples([(0x100, False, frame(1), t0 + i) for i in range(41)])
        self.assertEqual(self.w._minor_step, 1)
        minor = [round(x + t0) for x in self.w.minor_grid_xs()]
        self.assertEqual(len(minor), 24)  # 30 s, minus the 6 labelled ticks
        self.assertTrue(all(t % 5 for t in minor))  # never on a label
        self.assertEqual(
            self.w.axis_y.gridLinePen().style(),
            signal_plot_class.Qt.PenStyle.CustomDashLine,
        )
        self.w.sp_window.setValue(600)  # 1 s lines would crowd: wider sub-step
        self.assertNotEqual(self.w._minor_step, 1)

    def assert_consistent(self, p):
        """The series holds exactly the points of the plot's slots, in time order."""
        self.assertEqual(p.series.count(), p.count)
        self.assertEqual(p.count, sum(b.n_pts for b in p.buckets))
        want = [pt for b in p.buckets for pt in b.points()]
        self.assertEqual([(q.x(), q.y()) for q in want], list(zip(xs(p), ys(p))))
        self.assertEqual(xs(p), sorted(xs(p)))

    def test_spikes_survive_decimation(self):
        """7.10: 1 kHz into 20 ms slots: far fewer points, every extreme kept."""
        self.add("MSG_A", "SIG_X")
        values = [10] * 2000
        values[700] = 200  # one-frame spike up
        values[1300] = 0  # one-frame spike down
        self.w.feed_samples(
            [(0x100, False, frame(v), 5.0 + i * 0.001) for i, v in enumerate(values)]
        )
        p = self.w.plots[0]
        self.assertEqual(len(p.ys), 2000)  # every raw value kept
        self.assertLess(p.series.count(), 400)  # 100 slots, <= 4 points each
        self.assertIn(400.0, ys(p))  # factor 2
        self.assertIn(0.0, ys(p))
        self.assertAlmostEqual(self.w.axis_y.max(), 420.0)  # 5 % margin
        self.assert_consistent(p)

    def test_batches_extend_the_last_slot(self):
        """Samples split over many feeds land as if fed at once."""
        self.add("MSG_A", "SIG_X")
        p = self.w.plots[0]
        samples = [(0x100, False, frame(i % 50), 1.0 + i * 0.003) for i in range(600)]
        for k in range(0, 600, 7):
            self.w.feed_samples(samples[k : k + 7])
        split = (xs(p), ys(p))
        self.assert_consistent(p)
        self.w.clear()
        self.add("MSG_A", "SIG_X")
        self.w._t0 = None
        self.w.feed_samples(samples)
        self.assertEqual((xs(self.w.plots[0]), ys(self.w.plots[0])), split)

    def test_window_change_reslots(self):
        self.add("MSG_A", "SIG_X")
        p = self.w.plots[0]
        self.w.feed_samples(
            [(0x100, False, frame(i % 7), 1.0 + i * 0.001) for i in range(1000)]
        )
        coarse = p.series.count()
        self.w.sp_window.setValue(2)  # 20 ms -> 1.3 ms slots
        self.assertGreater(p.series.count(), coarse)
        self.assertEqual(len(p.ys), 1000)
        self.assert_consistent(p)

    def test_batch_feeds_only_matching_series(self):
        self.add("MSG_A", "SIG_X")
        self.add("MSG_B", "SIG_Y")
        self.w.feed_samples(
            [
                (0x100, False, frame(1), 1.0),
                (0x120, False, frame(7), 1.1),
                (0x100, False, frame(2), 1.2),
                (0x100, True, frame(9), 1.3),  # extended 0x00000100: other frame
            ]
        )
        self.assertEqual(ys(self.w.plots[0]), [2.0, 4.0])
        self.assertEqual(ys(self.w.plots[1]), [7.0])

    def test_sample_cap_drops_the_oldest(self):
        self.add("MSG_A", "SIG_X")
        orig = signal_plot_class.MAX_SAMPLES
        signal_plot_class.MAX_SAMPLES = 50
        try:
            self.w.feed_samples(
                [(0x100, False, frame(i), 1.0 + i * 0.001) for i in range(80)]
            )
        finally:
            signal_plot_class.MAX_SAMPLES = orig
        p = self.w.plots[0]
        self.assertEqual(len(p.xs), 50)
        self.assertEqual(p.ys[0], 60.0)  # samples 30..79 kept (factor 2)

    def test_keys_follow_the_series(self):
        changes = []
        self.w.keys_changed.connect(lambda: changes.append(self.w.keys()))
        self.add("MSG_A", "SIG_X")
        self.add("MSG_B", "SIG_Y")
        self.assertEqual(changes[-1], {(0x100, False), (0x120, False)})
        self.w.cb_active.setCurrentIndex(0)
        self.w.remove_selected()
        self.assertEqual(changes[-1], {(0x120, False)})
        self.w.clear()
        self.assertEqual(changes[-1], set())

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


COUNTER_SCRIPT = """counter = 0


def get_payload(dlc, id):
    global counter
    counter += 1
    return bytes([counter]) + bytes(dlc - 1)
"""


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


def tx_row(fid, script):
    return {
        "enabled": True,
        "id": f"0x{fid:03X}",
        "fd": "n",
        "name": f"M{fid:X}",
        "period": 100,
        "payload": "00 00 00 00 00 00 00 00",
        "dlc": 8,
        "script_path": script,
    }


class PlotEveryValueTests(unittest.TestCase):
    """7.10: every RX and TX value of a plotted frame reaches the plot, not
    only the newest one per 100 ms refresh."""

    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        with open("counter.py", "w", encoding="utf-8") as f:
            f.write(COUNTER_SCRIPT)
        with open("ws_plot.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dbc_file": None,
                    "global_script": None,
                    "sliders": [],
                    "signals": [
                        tx_row(0x100, "counter.py"),
                        tx_row(0x120, "counter.py"),
                    ],
                },
                f,
            )
        self.mw = gui.MainWindow()
        self.mw.CONFIG_FILE = "ws_plot.json"
        self.mw.load_config(auto=True)
        self.mw._apply_dbc(make_dbc())
        self.mw.can_if = FakeIf()
        self.mw.open_signal_plot_window()
        self.w = self.mw.signal_plot_windows[-1]
        plot_signal(self.w, "MSG_A", "SIG_X")  # 0x100 only

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_plotted_keys_reach_rx_and_tx(self):
        self.assertEqual(self.mw.rx_window.sample_keys, {(0x100, False)})
        self.assertEqual(self.mw._plot_tx_keys, {(0x100, False)})

    def test_every_rx_frame_is_plotted(self):
        rx = self.mw.rx_window
        for i in range(1, 6):
            rx.push_frame(0x100, frame(i), 8, False, timestamp=10.0 + i * 0.01)
            rx.push_frame(0x120, frame(i), 8, False, timestamp=10.0 + i * 0.01)
        rx.drain()  # one drain, five frames of 0x100
        p = self.w.plots[0]
        self.assertEqual(p.ys, [2.0, 4.0, 6.0, 8.0, 10.0])
        for got, want in zip(p.xs, [0.0, 0.01, 0.02, 0.03, 0.04]):
            self.assertAlmostEqual(got, want, places=9)

    def test_rx_echoes_are_not_plotted(self):
        rx = self.mw.rx_window
        rx.push_frame(0x100, frame(3), 8, False, timestamp=1.0, is_echo=True)
        rx.drain()
        self.assertEqual(self.w.plots[0].series.count(), 0)

    def test_every_tx_frame_is_plotted(self):
        self.mw.start_stop_transmission()
        for _ in range(4):
            self.mw.tx_scheduler.fire_all()
        # Only the plotted row is queued; four ticks = four samples
        self.assertEqual([s[:2] for s in self.mw._tx_samples], [(0x100, False)] * 4)
        self.mw._tx_refresh()
        self.assertEqual(self.w.plots[0].ys, [2.0, 4.0, 6.0, 8.0])
        self.assertEqual(len(self.mw._tx_samples), 0)

    def test_replayed_frames_are_plotted(self):
        def msg(fid):
            return can.Message(arbitration_id=fid, data=frame(9), is_extended_id=False)

        self.mw._replay_send(msg(0x100))
        self.mw._replay_send(msg(0x120))
        self.mw._tx_refresh()
        self.assertEqual(ys(self.w.plots[0]), [18.0])

    def test_closing_the_plot_stops_collecting(self):
        h.dispose(self.w)
        self.assertEqual(self.mw.signal_plot_windows, [])
        self.assertEqual(self.mw.rx_window.sample_keys, frozenset())
        self.assertEqual(self.mw._plot_tx_keys, frozenset())


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

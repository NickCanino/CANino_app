"""Phase 0 / sub-task 4 — TODO 5.1, 5.2, 5.3, 5.4, 5.5, 7.1, 1.9.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import csv
import json
import os
import threading
import time
import unittest
from datetime import datetime

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|255] "" ECU
 SG_ SIG_MODE : 8|8@1+ (1,0) [0|3] "" ECU
VAL_ 256 SIG_MODE 0 "OFF" 1 "ON" 2 "AUTO" ;
"""


class Base(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.rx = self.mw.rx_window

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()


class RxTableTests(Base):
    def test_sorted_table_keeps_rows_consistent(self):
        """5.1: sorted by DLC (all equal), every row still shows its own ID's data."""
        for fid, byte in ((0x300, 0x33), (0x200, 0x22), (0x100, 0x11)):
            for _ in range(fid >> 8):
                self.rx.push_frame(fid, bytes([byte] * 8), 8, False)
        self.rx.drain()
        self.rx.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.rx.push_frame(0x100, bytes([0x44] * 8), 8, False)
        self.rx.drain()
        rows = {r[0]: (r[3], r[4]) for r in h.rx_view_rows(self.rx)}
        self.assertEqual(
            rows,
            {
                "0x100": (" ".join(["44"] * 8), "2"),
                "0x200": (" ".join(["22"] * 8), "2"),
                "0x300": (" ".join(["33"] * 8), "3"),
            },
        )

    def test_numeric_sort(self):
        """5.8: Count sorts as a number (9 before 10), ID std before ext."""
        for _ in range(10):
            self.rx.push_frame(0x100, bytes(8), 8, False)
        for _ in range(9):
            self.rx.push_frame(0x200, bytes(8), 8, False)
        self.rx.push_frame(0x050, bytes(8), 8, False, None, True)
        self.rx.drain()
        self.rx.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        self.assertEqual([r[4] for r in h.rx_view_rows(self.rx)], ["1", "9", "10"])
        self.rx.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [r[0] for r in h.rx_view_rows(self.rx)], ["0x100", "0x200", "0x00000050"]
        )

    def test_period_statistics(self):
        """Period min/max and std-dev from the frames' own timestamps."""
        t = 1000.0
        for dt in (0, 0.010, 0.010, 0.010, 0.020, 0.010):
            t += dt
            self.rx.push_frame(0x123, bytes(8), 8, False, t)
        self.rx.drain()
        (row,) = h.rx_view_rows(self.rx)
        self.assertEqual((row[6], row[7]), ("10.0", "20.0"))
        self.assertEqual(row[8], "4.7")  # pstdev(10, 20, 10)

    def test_refresh_survives_concurrent_new_ids(self):
        """5.2: the RX thread adding IDs during a drain must not raise."""

        # A bounded burst: an unpaced loop outruns any real bus and the drain
        def writer():
            for i in range(100_000):
                self.rx.push_frame(0x400 + i % 2000, bytes(8), 8, False)
                if i % 1000 == 0:
                    time.sleep(0.001)  # let the GUI thread drain meanwhile

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        drains = 0
        while t.is_alive():
            self.rx.drain()
            drains += 1
        t.join()
        self.rx.drain()
        self.assertGreater(drains, 1)
        self.assertEqual(self.rx.model.rowCount(), 2000)

    @unittest.skipIf(
        os.environ.get("CI"), "measures the machine's timing, not the code"
    )
    def test_refresh_cost_with_many_rows(self):
        """5.6: 1,000 IDs updated per drain stay far below the old 465 ms rebuild."""
        self.rx.resize(1000, 600)
        self.rx.show()
        for fid in range(1000):
            self.rx.push_frame(fid, bytes(8), 8, False)
        self.rx.drain()
        self.rx.table.sortByColumn(4, Qt.SortOrder.DescendingOrder)
        worst = 0.0
        for _ in range(10):
            for fid in range(1000):
                self.rx.push_frame(fid, bytes([fid & 0xFF] * 8), 8, False)
            t0 = time.perf_counter()
            self.rx.drain()
            QCoreApplication.processEvents()
            worst = max(worst, time.perf_counter() - t0)
        self.assertLess(worst, 0.1)

    def test_set_dbc_names_existing_rows(self):
        """5.7: rows already listed get their name when a DBC arrives."""
        with open("names.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.rx.push_frame(0x100, bytes(8), 8, False)
        self.rx.drain()
        self.rx.set_dbc(dbc_loader.load_dbc("names.dbc"))
        self.assertEqual(h.rx_view_rows(self.rx)[0][1], "MSG_A")
        self.rx.set_dbc(None)
        self.assertEqual(h.rx_view_rows(self.rx)[0][1], "")

    def test_rx_callback_only_queues(self):
        """1.8: the RX-thread callback touches no statistics, the GUI drain does."""
        self.rx.push_frame(0x100, bytes(8), 8, False)
        self.assertEqual(self.rx.model.rowCount(), 0)
        self.assertEqual(self.rx.busload_nominal_bits, 0)
        self.rx.drain()
        self.assertEqual(self.rx.model.rowCount(), 1)
        self.assertGreater(self.rx.busload_nominal_bits, 0)

    def test_clear_drops_rows_and_queue(self):
        self.rx.push_frame(0x100, bytes(8), 8, False)
        self.rx.drain()
        self.rx.push_frame(0x200, bytes(8), 8, False)
        self.rx.clear_rx_table()
        self.rx.drain()
        self.assertEqual(h.rx_view_rows(self.rx), [])

    def test_csv_logs_every_frame_with_its_own_time(self):
        """5.3 + 5.4: one row per frame, stamped with the frame's own time."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "rx.csv")
        self.rx.push_frame(0x7FE, b"\x00" * 8, 8, False)  # before Start: not logged
        self.rx.start_log()
        base = time.time()
        sent = [
            (0x123, b"\x01" * 8, base),
            (0x123, b"\x02" * 8, base + 0.1),
            (0x7FF, b"\x09" * 8, base + 0.2),
        ]
        for fid, data, ts in sent:
            self.rx.push_frame(fid, data, 8, False, ts)
        self.rx.stop_log()  # queued frames are logged before the file closes
        with open(self.rx.csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))[1:]
        self.assertEqual(
            [(r[1], r[4][:2]) for r in rows],
            [("0x123", "01"), ("0x123", "02"), ("0x7FF", "09")],
        )
        for row, (_, _, ts) in zip(rows, sent):
            logged = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
            self.assertAlmostEqual(logged, ts, places=3)

    def test_stop_log_while_frames_arrive(self):
        """5.5: frames keep arriving from the RX thread across start/stop cycles."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "rx_race.csv")
        stop = threading.Event()
        errors = []

        def writer():  # ~10k frames/s, a busy real bus
            while not stop.is_set():
                for _ in range(10):
                    self.rx.push_frame(0x321, bytes(8), 8, False)
                time.sleep(0.001)

        import src.received_frames_class as rfc

        orig = rfc.log_throttled
        rfc.log_throttled = lambda *a: errors.append(a[-1])
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            for _ in range(200):
                self.rx.start_log()
                self.rx.drain()
                self.rx.stop_log()
        finally:
            stop.set()
            t.join()
            rfc.log_throttled = orig
        self.assertEqual(errors, [])


class XMetroAndShutdownTests(Base):
    def setUp(self):
        super().setUp()
        with open("probe_x.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        with open("ws_x.json", "w", encoding="utf-8") as f:
            json.dump({"dbc_file": "probe_x.dbc", "signals": [], "sliders": []}, f)
        self.mw.CONFIG_FILE = "ws_x.json"
        self.mw.load_config(auto=True)

    def open_gauge(self, signal):
        self.mw.open_xmetro_window()
        window = self.mw.xmetro_windows[-1]
        window.add_gauge()
        g = window.gauges[-1]
        g.cb_messages.setCurrentIndex(g.cb_messages.findData(0x100))
        g.cb_signals.setCurrentIndex(g.cb_signals.findText(signal))
        return window, g

    def feed_from_rx_thread(self, data):
        t = threading.Thread(
            target=self.mw.rx_window.push_frame, args=(0x100, data, 8, False)
        )
        t.start()
        t.join()
        self.mw.rx_window.drain()

    def test_gauge_follows_received_frames(self):
        """7.1: frames received in the RX thread reach the gauge."""
        _, g = self.open_gauge("SIG_X")
        self.feed_from_rx_thread(bytes([77, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(g.gauge.value, 77)

    def test_enum_signal_gauge_gets_a_number(self):
        """7.1 side effect: enum signals must not reach paintEvent as NamedSignalValue."""
        _, g = self.open_gauge("SIG_MODE")
        self.feed_from_rx_thread(bytes([0, 2, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(g.gauge.value, 2)
        self.assertIsInstance(g.gauge.value, (int, float))

    def test_close_releases_channel_and_windows(self):
        """1.9: closing the main window closes the CAN interface and XMetro."""
        closed = []

        class FakeIf:
            is_fd = False

            def close(self):
                closed.append(True)

        self.mw.can_if = FakeIf()
        self.open_gauge("SIG_X")
        self.mw.close()
        self.assertEqual(closed, [True])
        self.assertIsNone(self.mw.can_if)
        self.assertEqual(self.mw.xmetro_windows, [])


if __name__ == "__main__":
    unittest.main()

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
                self.rx.update_frame(fid, bytes([byte] * 8), 8, False)
        self.rx.refresh_table()
        self.rx.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.rx.refresh_table()
        self.rx.refresh_table()
        for r in range(self.rx.table.rowCount()):
            fid = int(self.rx.table.item(r, 0).text(), 16)
            f = self.rx._rx_buffer[fid]
            self.assertEqual(
                self.rx.table.item(r, 3).text(), " ".join(f"{b:02X}" for b in f["data"])
            )
            self.assertEqual(self.rx.table.item(r, 4).text(), str(f["count"]))

    def test_refresh_survives_concurrent_new_ids(self):
        """5.2: the RX thread adding IDs during a refresh must not raise."""
        stop = threading.Event()

        def writer():
            fid = 0x400
            while not stop.is_set():
                self.rx.update_frame(fid, bytes(8), 8, False)
                fid = 0x400 + ((fid - 0x400 + 1) % 2000)

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            t_end = time.time() + 3
            while time.time() < t_end:
                self.rx.refresh_table()  # raised "dictionary changed size" before
        finally:
            stop.set()
            t.join()

    def test_csv_logs_every_frame_with_its_own_time(self):
        """5.3 + 5.4: one row per frame, stamped with the frame's own time."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "rx.csv")
        self.rx.start_log()
        base = time.time()
        sent = [
            (0x123, b"\x01" * 8, base),
            (0x123, b"\x02" * 8, base + 0.1),
            (0x7FF, b"\x09" * 8, base + 0.2),
        ]
        for fid, data, ts in sent:
            self.rx.update_frame(fid, data, 8, False, ts)
        self.rx.stop_log()
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
        """5.5: closing the CSV from the GUI thread while the RX thread writes."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "rx_race.csv")
        stop = threading.Event()
        errors = []
        orig = gui.log_exception

        def writer():
            while not stop.is_set():
                self.rx.update_frame(0x321, bytes(8), 8, False)

        import src.received_frames_class as rfc

        rfc.log_exception = lambda *a: errors.append(a[-1])
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            for _ in range(200):
                self.rx.start_log()
                self.rx.stop_log()
        finally:
            stop.set()
            t.join()
            rfc.log_exception = orig
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
            target=self.mw.process_received_frame, args=(0x100, data, 8, False)
        )
        t.start()
        t.join()
        for _ in range(20):
            QCoreApplication.processEvents()

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

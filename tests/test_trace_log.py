"""Phase 3 / sub-task 1 — TODO 5.9: standard traces (.trc/.asc/.blf/.log).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import csv
import os
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.received_frames_class as rfc  # noqa: E402
from src.trace_log import TRACE_FORMATS, TraceLog  # noqa: E402

T0 = 1_760_000_000.123456  # a PCAN hardware timestamp (epoch-based)

# (frame_id, data, is_fd, timestamp, is_ext, brs, is_echo)
FRAMES = [
    (0x123, bytes(range(8)), False, T0, False, False, False),
    (0x123, b"\xaa\xbb", False, T0 + 0.000043, False, False, True),  # own TX
    (0x18FF0001, bytes(range(4)), False, T0 + 0.010, True, False, False),
    (0x00000123, b"", False, T0 + 0.020, True, False, True),  # ext, DLC 0
    (0x7FF, bytes(range(12)), True, T0 + 0.030, False, True, False),  # FD + BRS
    (0x456, bytes(range(64)), True, T0 + 1.5, False, False, True),  # FD, no BRS
]


def read_back(path):
    with can.LogReader(path) as reader:
        return list(reader)


class TraceFormatTests(unittest.TestCase):
    def write(self, ext):
        path = os.path.join(h.WORKDIR, f"formats{ext}")
        log = TraceLog(path)
        for frame in FRAMES:
            log.write(*frame)
        log.close()
        return path

    def check_frames(self, msgs, ext):
        self.assertEqual(len(msgs), len(FRAMES), ext)
        for msg, (fid, data, is_fd, ts, is_ext, brs, echo) in zip(msgs, FRAMES):
            where = f"{ext} 0x{fid:X}"
            self.assertEqual(msg.arbitration_id, fid, where)
            self.assertEqual(bytes(msg.data), data, where)
            self.assertEqual(msg.is_extended_id, is_ext, where)
            self.assertEqual(msg.is_fd, is_fd, where)
            self.assertEqual(msg.is_rx, not echo, where)
            if is_fd:
                self.assertEqual(msg.bitrate_switch, brs, where)
        # Spacing kept to the µs: what IDS timing features are computed on
        for msg, frame in zip(msgs[1:], FRAMES[1:]):
            self.assertAlmostEqual(
                msg.timestamp - msgs[0].timestamp, frame[3] - T0, delta=2e-6
            )

    def test_every_format_round_trips(self):
        """5.9: RX and own TX, std/ext, DLC 0, classic and FD (BRS on/off)."""
        for ext in TRACE_FORMATS:
            with self.subTest(ext=ext):
                self.check_frames(read_back(self.write(ext)), ext)

    def test_trc_absolute_time_and_layout(self):
        """TRC: absolute start time within ~1 µs; PCAN-View layout."""
        path = self.write(".trc")
        msgs = read_back(path)
        self.assertAlmostEqual(msgs[0].timestamp, T0, delta=2e-6)
        with open(path, encoding="ascii") as f:
            lines = [ln.rstrip("\n") for ln in f if not ln.startswith(";")]
        self.assertEqual(
            lines[0],
            "      1         0.000 DT  1     0123 Rx -  8   00 01 02 03 04 05 06 07",
        )
        self.assertEqual(lines[1].split()[5:8], ["Tx", "-", "2"])
        self.assertEqual(lines[2].split()[4], "18FF0001")  # 8 digits extended
        self.assertEqual(lines[3].split()[4:], ["00000123", "Tx", "-", "0"])
        self.assertEqual(lines[4].split()[2], "FB")  # FD with bit-rate switch
        self.assertEqual(lines[4].split()[7], "9")  # DLC code of 12 bytes
        self.assertEqual(lines[5].split()[2], "FD")
        self.assertEqual(lines[5].split()[7], "15")

    def test_unknown_extension_is_refused(self):
        with self.assertRaises(ValueError):
            TraceLog(os.path.join(h.WORKDIR, "x.txt"))
        self.assertFalse(TraceLog.is_trace("x.csv"))
        self.assertTrue(TraceLog.is_trace("C:/a/b.BLF"))


class RxWindowTraceTests(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.rx = self.mw.rx_window

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def push(self, fid, ts, echo=False, data=b"\x01" * 8):
        self.rx.push_frame(fid, data, len(data), False, ts, False, False, echo)

    def test_trace_holds_rx_and_own_tx_in_wire_order(self):
        """5.9: echoes go to the trace as Tx (they stay out of the RX table)."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "rx_tx.trc")
        self.push(0x7FE, T0 - 1)  # before Start: not logged
        self.rx.start_log()
        self.push(0x100, T0)
        self.push(0x200, T0 + 0.001, echo=True)
        self.push(0x100, T0 + 0.002)
        self.rx.stop_log()
        msgs = read_back(self.rx.csv_path)
        self.assertEqual(
            [(m.arbitration_id, m.is_rx) for m in msgs],
            [(0x100, True), (0x200, False), (0x100, True)],
        )
        self.assertEqual([r[0] for r in h.rx_view_rows(self.rx)], ["0x100", "0x7FE"])
        self.assertFalse(self.rx.log_open)

    def test_pause_skips_and_restart_starts_over(self):
        path = os.path.join(h.WORKDIR, "pause.asc")
        self.rx.csv_path = path
        self.rx.start_log()
        self.push(0x100, T0)
        self.rx.pause_log()
        self.push(0x200, T0 + 0.1)  # paused: not in the file
        self.rx.start_log()  # resume, same file
        self.push(0x300, T0 + 0.2)
        self.rx.stop_log()
        self.assertEqual([m.arbitration_id for m in read_back(path)], [0x100, 0x300])
        self.rx.start_log()  # restart after Stop: a new file
        self.push(0x400, T0 + 0.3)
        self.rx.stop_log()
        self.assertEqual([m.arbitration_id for m in read_back(path)], [0x400])

    def test_csv_stays_rx_statistics_only(self):
        """The CSV format is unchanged: own echoes are not received frames."""
        self.rx.csv_path = os.path.join(h.WORKDIR, "stats.csv")
        self.rx.start_log()
        self.push(0x100, T0)
        self.push(0x200, T0 + 0.001, echo=True)
        self.rx.stop_log()
        with open(self.rx.csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual([r[1] for r in rows[1:]], ["0x100"])

    def test_link_appends_the_selected_format(self):
        """A name typed without extension gets the selected filter's one."""
        from PySide6.QtWidgets import QFileDialog

        trc_filter = next(f for f in rfc.LOG_FILTERS if "*.trc" in f)
        base = os.path.join(h.WORKDIR, "typed")
        orig = QFileDialog.getSaveFileName
        try:
            QFileDialog.getSaveFileName = staticmethod(
                lambda *a, **k: (base, trc_filter)
            )
            self.rx.link_csv_file()
            self.assertEqual(self.rx.csv_path, base + ".trc")
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (base, ""))
            self.rx.link_csv_file()
            self.assertEqual(self.rx.csv_path, base + ".csv")
        finally:
            QFileDialog.getSaveFileName = orig
        self.assertTrue(self.rx.btn_start_log.isEnabled())

    def test_relink_finishes_the_open_file(self):
        """Linking another file while logging closes the first one cleanly."""
        from PySide6.QtWidgets import QFileDialog

        first = os.path.join(h.WORKDIR, "first.blf")
        self.rx.csv_path = first
        self.rx.start_log()
        self.push(0x100, T0)
        orig = QFileDialog.getSaveFileName
        try:
            QFileDialog.getSaveFileName = staticmethod(
                lambda *a, **k: (os.path.join(h.WORKDIR, "second.trc"), "")
            )
            self.rx.link_csv_file()
        finally:
            QFileDialog.getSaveFileName = orig
        self.assertFalse(self.rx.log_open)
        self.assertEqual([m.arbitration_id for m in read_back(first)], [0x100])

    def test_close_finishes_a_blf_trace(self):
        """1.9 for traces: closing CANino writes the BLF container and header."""
        path = os.path.join(h.WORKDIR, "closing.blf")
        self.rx.csv_path = path
        self.rx.start_log()
        for i in range(100):
            self.push(0x100 + i, T0 + i * 0.001)
        self.mw.close()
        self.assertEqual(len(read_back(path)), 100)

    def test_unwritable_trace_warns(self):
        h.DIALOGS.clear()
        self.rx.csv_path = os.path.join(h.WORKDIR, "no_such_dir", "x.trc")
        self.rx.start_log()
        self.assertFalse(self.rx.log_open)
        self.assertFalse(self.rx.log_active)
        self.assertEqual([d[0] for d in h.DIALOGS], ["warning"])

    @unittest.skipIf(os.environ.get("CI"), "measures this machine's speed")
    def test_drain_keeps_up_with_a_saturated_bus(self):
        """~8k frames/s (1 Mbit/s classic, 8 B): one 100 ms drain = 800 frames."""
        for ext in TRACE_FORMATS:
            self.rx.csv_path = os.path.join(h.WORKDIR, f"speed{ext}")
            self.rx.start_log()
            for i in range(800):
                self.push(0x100 + (i % 50), T0 + i * 125e-6, echo=bool(i % 2))
            t = time.perf_counter()
            self.rx.drain()
            cost = time.perf_counter() - t
            self.rx.stop_log()
            self.assertLess(cost, 0.05, ext)  # half the drain period


if __name__ == "__main__":
    unittest.main()

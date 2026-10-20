"""Phase 3 / sub-task 6 — TODO 5.10 (trace replay), 2.15 (send-once/burst/RTR).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import threading
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.tx_model import TX_COL_3_fd, TX_COL_6_payload, TxEntry  # noqa: E402
from src.trace_log import TraceLog  # noqa: E402
from src.trace_replay import TraceReplayer, load_trace  # noqa: E402


class RecordIf:
    """Fake CANInterface recording every send_frame call."""

    is_fd = False
    listen_only = False

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def send_frame(
        self, frame_id, data, dlc=None, is_fd=False, is_ext=False, is_rtr=False
    ):
        with self._lock:
            self.calls.append((frame_id, bytes(data), dlc, is_fd, is_ext, is_rtr))
        return True

    def flush_tx(self):
        return True

    def close(self):
        pass


class RtrTests(unittest.TestCase):
    def test_entry_rtr_excludes_fd_and_sends_remote(self):
        e = TxEntry(0x123, "R", is_rtr=True, dlc=8)
        self.assertTrue(e.is_rtr)
        e_fd = TxEntry(0x123, "R", is_rtr=True, is_fd=True)
        self.assertFalse(e_fd.is_rtr)  # FD has no remote frame

    def test_send_frame_builds_remote_message(self):
        sent = []
        iface = ci.CANInterface.__new__(ci.CANInterface)
        iface.bus = type("Bus", (), {"send": lambda self, m: sent.append(m)})()
        iface._send_lock = threading.Lock()
        iface.send_frame(0x123, b"\xff" * 8, 8, is_rtr=True)
        self.assertTrue(sent[0].is_remote_frame)
        self.assertEqual(sent[0].dlc, 8)
        self.assertEqual(bytes(sent[0].data), b"")  # a remote frame carries no data


class SendNowTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw.can_if = RecordIf()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def select(self, entry):
        idx = self.mw.tx_proxy.mapFromSource(
            self.mw.tx_model.index(self.mw.tx_model.row_of(entry), 0)
        )
        self.mw.tx_view.selectionModel().select(
            idx,
            self.mw.tx_view.selectionModel().SelectionFlag.Select
            | self.mw.tx_view.selectionModel().SelectionFlag.Rows,
        )

    def test_send_once(self):
        e = self.mw._add_tx_row(0x100, "A", dlc=2, payload="11 22")
        self.select(e)
        self.mw.sp_burst.setValue(1)
        self.mw.send_selected_now()
        self.assertEqual(len(self.mw.can_if.calls), 1)
        self.assertEqual(self.mw.can_if.calls[0][:2], (0x100, b"\x11\x22"))

    def test_send_burst(self):
        e = self.mw._add_tx_row(0x100, "A", dlc=1, payload="05")
        self.select(e)
        self.mw.sp_burst.setValue(10)
        self.mw.send_selected_now()
        self.assertEqual(len(self.mw.can_if.calls), 10)

    def test_send_rtr_row_sends_remote(self):
        e = self.mw._add_tx_row(0x200, "R", dlc=4, is_rtr=True)
        self.select(e)
        self.mw.send_selected_now()
        fid, data, dlc, is_fd, is_ext, is_rtr = self.mw.can_if.calls[0]
        self.assertTrue(is_rtr)
        self.assertEqual(data, b"")

    def test_no_selection_warns_sends_nothing(self):
        h.DIALOGS.clear()
        self.mw.send_selected_now()
        self.assertEqual(self.mw.can_if.calls, [])
        self.assertEqual([d[0] for d in h.DIALOGS][-1], "warning")

    def test_rtr_shown_and_payload_not_editable(self):
        e = self.mw._add_tx_row(0x200, "R", dlc=4, is_rtr=True)
        row = self.mw.tx_model.row_of(e)
        from PySide6.QtCore import Qt

        self.assertEqual(self.mw.tx_model.index(row, TX_COL_3_fd).data(), "RTR")
        flags = self.mw.tx_model.flags(self.mw.tx_model.index(row, TX_COL_6_payload))
        self.assertFalse(flags & Qt.ItemFlag.ItemIsEditable)


class ReplayTests(unittest.TestCase):
    def make_trace(self, ext=".asc"):
        path = os.path.join(h.WORKDIR, "rec" + ext)
        log = TraceLog(path)
        t0 = 1_000_000.0
        for i in range(5):
            log.write(
                0x100 + i, bytes([i, i]), False, t0 + i * 0.01, False, False, False
            )
        log.write(0x300, b"", False, t0 + 0.05, False, False, False)  # dlc 0
        log.close()
        return path

    def test_load_trace_reads_all_frames(self):
        msgs = load_trace(self.make_trace())
        self.assertEqual(
            [m.arbitration_id for m in msgs], [0x100, 0x101, 0x102, 0x103, 0x104, 0x300]
        )

    def test_replayer_sends_every_frame_in_order(self):
        msgs = load_trace(self.make_trace())
        sent = []
        r = TraceReplayer(msgs, lambda m: sent.append(m.arbitration_id))
        r.start()
        for _ in range(200):  # wait for completion
            if not r.running:
                break
            time.sleep(0.02)
        r.stop()
        self.assertEqual(sent, [0x100, 0x101, 0x102, 0x103, 0x104, 0x300])
        self.assertIsNone(r.error)

    def test_replay_preserves_relative_timing(self):
        # Two frames 100 ms apart replay at least ~80 ms apart
        path = os.path.join(h.WORKDIR, "timed.asc")
        log = TraceLog(path)
        log.write(0x10, b"\x00", False, 5000.0, False, False, False)
        log.write(0x11, b"\x00", False, 5000.1, False, False, False)
        log.close()
        stamps = []
        r = TraceReplayer(
            load_trace(path), lambda m: stamps.append(time.perf_counter())
        )
        r.start()
        for _ in range(100):
            if not r.running:
                break
            time.sleep(0.02)
        r.stop()
        self.assertEqual(len(stamps), 2)
        self.assertGreater(stamps[1] - stamps[0], 0.08)

    def test_stop_halts_a_loop(self):
        r = TraceReplayer(load_trace(self.make_trace()), lambda m: None, loop=True)
        r.start()
        time.sleep(0.1)
        self.assertTrue(r.running)
        r.stop()
        self.assertFalse(r.running)

    def test_is_trace_extension(self):
        self.assertTrue(TraceReplayer.is_trace("x.blf"))
        self.assertFalse(TraceReplayer.is_trace("x.csv"))


class ReplayGuiTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_replay_puts_recorded_frames_on_the_bus(self):
        # Record a trace, then replay it through the GUI onto a fake interface
        path = os.path.join(h.WORKDIR, "gui.asc")
        log = TraceLog(path)
        for i in range(4):
            log.write(
                0x200 + i, bytes([i]), False, 2000.0 + i * 0.005, False, False, False
            )
        log.close()

        self.mw.can_if = RecordIf()
        from PySide6.QtWidgets import QFileDialog

        orig = QFileDialog.getOpenFileName
        try:
            QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
            self.mw.replay_trace()
        finally:
            QFileDialog.getOpenFileName = orig
        self.assertEqual(self.mw.btn_replay.text(), "Stop Replay")
        for _ in range(200):
            if self.mw._replayer is None or not self.mw._replayer.running:
                break
            time.sleep(0.02)
        self.mw._poll_replay()
        ids = [c[0] for c in self.mw.can_if.calls]
        self.assertEqual(ids, [0x200, 0x201, 0x202, 0x203])
        self.assertEqual(self.mw.btn_replay.text(), "Replay Trace")

    def test_replay_needs_connection(self):
        h.DIALOGS.clear()
        self.mw.can_if = None
        self.mw.replay_trace()
        self.assertEqual([d[0] for d in h.DIALOGS][-1], "warning")


if __name__ == "__main__":
    unittest.main()

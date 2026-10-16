"""Phase 0 / sub-task 3 — TODO 3.1, 3.2, 2.10, 1.13, 1.14.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import shutil
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.utils import resource_path  # noqa: E402


class FakeIf:
    is_fd = False
    bus = None

    def __init__(self):
        self.sent = []
        self.flushes = 0

    def send_frame(self, frame_id, data, dlc=None, is_fd=False):
        self.sent.append((frame_id, bytes(data)))

    def flush_tx(self):
        self.flushes += 1
        return True

    def close(self):
        pass


def row(fid, script):
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


class TxEngineTests(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        shutil.copy(
            resource_path("resources/script_templates/TPS_sawtooth.py"), "sawtooth.py"
        )
        with open("ws_tx.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dbc_file": None,
                    "global_script": None,
                    "sliders": [],
                    "signals": [
                        row(0x100, "sawtooth.py"),
                        row(0x200, "sawtooth.py"),
                        row(0x300, None),
                    ],
                },
                f,
            )
        self.mw = gui.MainWindow()
        self.mw.CONFIG_FILE = "ws_tx.json"
        self.mw.load_config(auto=True)
        self.mw.can_if = FakeIf()

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def tick(self, n=1):
        for _ in range(n):
            for t in list(self.mw.timers):
                t.timeout.emit()

    def last_bytes(self, fid):
        return [d[-1] for f, d in self.mw.can_if.sent if f == fid]

    def item(self, fid):
        for i in range(self.mw.signal_tree.topLevelItemCount()):
            it = self.mw.signal_tree.topLevelItem(i)
            if it.text(gui.TX_COL_2_id) == f"0x{fid:03X}":
                return it

    def test_same_script_runs_independently_per_id(self):
        """3.1: two IDs on one sawtooth file both count 1, 2, 3."""
        self.mw.start_stop_transmission()
        self.tick(3)
        self.assertEqual(self.last_bytes(0x100), [1, 2, 3])
        self.assertEqual(self.last_bytes(0x200), [1, 2, 3])

    def test_toggling_another_row_keeps_script_state(self):
        """3.2: an internal TX restart must not reset running scripts."""
        self.mw.start_stop_transmission()
        self.tick(3)
        self.item(0x300).setCheckState(gui.TX_COL_1_enable, Qt.CheckState.Unchecked)
        self.item(0x300).setCheckState(gui.TX_COL_1_enable, Qt.CheckState.Checked)
        self.tick(2)
        self.assertEqual(self.last_bytes(0x100), [1, 2, 3, 4, 5])

    def test_start_tx_restarts_scripts(self):
        """3.2 (decided): each Start TX begins from the script's initial state."""
        self.mw.start_stop_transmission()
        self.tick(3)
        self.mw.start_stop_transmission()  # Stop TX
        self.mw.can_if.sent.clear()
        self.mw.start_stop_transmission()  # Start TX
        self.tick(2)
        self.assertEqual(self.last_bytes(0x100), [1, 2])

    def test_timers_are_precise(self):
        """2.10: CoarseTimer would round 50/100 ms to 15.625 ms ticks."""
        self.mw.start_stop_transmission()
        self.assertTrue(self.mw.timers)
        for t in self.mw.timers:
            self.assertEqual(t.timerType(), Qt.TimerType.PreciseTimer)

    def test_user_stop_flushes_the_tx_queue(self):
        """1.14: Stop TX drops what the driver could not send yet."""
        self.mw.start_stop_transmission()
        self.mw.start_stop_transmission()
        self.assertEqual(self.mw.can_if.flushes, 1)


class ErrorFrameTests(unittest.TestCase):
    def test_error_frames_do_not_reach_rx(self):
        """1.13: PCAN error frames are counted, not shown as data frames."""
        frames = [
            can.Message(
                arbitration_id=0x008, data=b"\x00\x19\x87\x10", is_error_frame=True
            ),
            can.Message(arbitration_id=0x123, data=b"\x01" * 8, is_extended_id=False),
        ]

        iface = ci.CANInterface.__new__(ci.CANInterface)
        iface.error_frames = 0
        iface.running = True
        received = []

        class Bus:
            def recv(self, timeout):
                if frames:
                    return frames.pop(0)
                iface.running = False
                return None

        iface.bus = Bus()
        iface.receive_callback = lambda fid, *rest: received.append(fid)
        iface._receive_loop()
        self.assertEqual(received, [0x123])
        self.assertEqual(iface.error_frames, 1)


if __name__ == "__main__":
    unittest.main()

"""Phase 1 / sub-task 2 — TODO 1.5 (bus errors), 1.12 (listen-only).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import logging
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402
from can.interfaces.pcan.basic import (  # noqa: E402
    PCAN_ERROR_BUSHEAVY,
    PCAN_ERROR_BUSOFF,
    PCAN_ERROR_BUSPASSIVE,
    PCAN_ERROR_OVERRUN,
    PCAN_ERROR_QXMTFULL,
    PCAN_LISTEN_ONLY,
    PCAN_PARAMETER_ON,
)

import src.can_interface as ci  # noqa: E402
import src.exceptions_logger as el  # noqa: E402
import src.gui as gui  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

CHANNEL = 0x51


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.cap = Capture()
        self.logger = logging.getLogger("canino.test_throttle")
        self.logger.addHandler(self.cap)
        self.logger.propagate = False
        self.filter = el.ThrottleFilter(interval=1.0)
        self.logger.addFilter(self.filter)

    def tearDown(self):
        self.logger.removeHandler(self.cap)
        self.logger.removeFilter(self.filter)

    def test_one_line_per_distinct_message_per_interval(self):
        """1.5: a burst of identical errors logs once; a different one still logs."""
        for _ in range(500):
            self.logger.error("queue full")
        self.logger.error("bus-off")
        self.assertEqual(self.cap.records, ["queue full", "bus-off"])

    def test_dropped_count_is_reported(self):
        """1.5: the next line after the interval says how many were dropped."""
        for _ in range(10):
            self.logger.error("queue full")
        self.filter._seen = {k: (v[0] - 2, v[1]) for k, v in self.filter._seen.items()}
        self.logger.error("queue full")
        self.assertEqual(self.cap.records[-1], "queue full (+9 identical, not logged)")


class SendErrorTests(unittest.TestCase):
    def test_failing_send_is_throttled_and_reported(self):
        """1.5: 1,000 refused frames -> False each time, one log line, no traceback."""
        cap = Capture()
        el.bus_logger.addHandler(cap)
        try:

            class Bus:
                def send(self, msg):
                    raise can.CanOperationError(
                        "Failed to send: transmit queue is full"
                    )

            iface = ci.CANInterface.__new__(ci.CANInterface)
            iface.bus = Bus()
            results = {iface.send_frame(0x100, bytes(8), 8) for _ in range(1000)}
        finally:
            el.bus_logger.removeHandler(cap)
        self.assertEqual(results, {False})
        self.assertEqual(len(cap.records), 1)
        self.assertIn("transmit queue is full", cap.records[0])

    def test_pcan_library_warnings_are_throttled(self):
        """1.5: python-can warns on every recv() in error-warning — 23,553 lines in 7 s on the bench."""
        cap = Capture()
        lib = logging.getLogger("can.pcan")
        lib.addHandler(cap)
        try:
            for _ in range(1000):
                lib.warning(
                    "Bus error: an error counter reached the 'heavy'/'warning' limit"
                )
        finally:
            lib.removeHandler(cap)
        self.assertEqual(len(cap.records), 1)


class ClassifyTests(unittest.TestCase):
    def test_levels(self):
        """1.5: what each PCAN status means for transmission."""
        cases = {
            0: "ok",
            PCAN_ERROR_BUSOFF: "severe",
            PCAN_ERROR_QXMTFULL: "severe",
            PCAN_ERROR_BUSHEAVY | PCAN_ERROR_QXMTFULL: "severe",
            PCAN_ERROR_BUSHEAVY: "warn",
            PCAN_ERROR_BUSPASSIVE: "warn",
            PCAN_ERROR_OVERRUN: "info",
        }
        for code, level in cases.items():
            with self.subTest(code=hex(code)):
                self.assertEqual(ci.classify_status(code).level, level)


class StatusIf(FakeIf):
    def __init__(self, code=0):
        super().__init__()
        self.code = code

    def bus_status(self):
        return ci.classify_status(self.code)


class AutoStopTests(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw._add_tx_row(0x100, "M100")
        self.mw.can_if = StatusIf()
        self.mw.start_stop_transmission()
        self.assertTrue(self.mw.tx_running)

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def warnings(self):
        return [d for d in h.DIALOGS if d[0] == "warning"]

    def test_ok_bus_keeps_transmitting(self):
        self.mw.poll_bus_status()
        self.assertTrue(self.mw.tx_running)
        self.assertEqual(self.mw.lbl_bus_status.text(), "Bus: OK")

    def test_bus_off_stops_tx_at_once_and_flushes(self):
        """1.5: bus-off -> TX stopped like the user's Stop TX (queue flushed), one warning."""
        self.mw.can_if.code = PCAN_ERROR_BUSOFF
        self.mw.poll_bus_status()
        self.assertFalse(self.mw.tx_running)
        self.assertEqual(self.mw.can_if.flushes, 1)
        self.assertEqual(len(self.warnings()), 1)
        self.assertIn("BUS-OFF", self.warnings()[0][2])
        self.mw.poll_bus_status()
        self.assertEqual(len(self.warnings()), 1)

    def test_queue_full_stops_tx_at_once(self):
        self.mw.can_if.code = PCAN_ERROR_QXMTFULL
        self.mw.poll_bus_status()
        self.assertFalse(self.mw.tx_running)

    def test_persistent_warning_stops_tx_after_grace(self):
        """1.5: error-warning (node alone / wrong bitrate) stops TX after the grace time."""
        self.mw.can_if.code = PCAN_ERROR_BUSHEAVY
        self.mw.poll_bus_status()
        self.assertTrue(self.mw.tx_running)
        self.assertIn("error warning", self.mw.lbl_bus_status.text())
        self.mw._bus_bad_since -= gui.TX_ERROR_GRACE_S
        self.mw.poll_bus_status()
        self.assertFalse(self.mw.tx_running)
        self.assertEqual(len(self.warnings()), 1)

    def test_transient_warning_does_not_stop_tx(self):
        """1.5: a warning that clears within the grace time is only shown."""
        self.mw.can_if.code = PCAN_ERROR_BUSHEAVY
        self.mw.poll_bus_status()
        self.mw.can_if.code = 0
        self.mw.poll_bus_status()
        self.mw.can_if.code = PCAN_ERROR_BUSHEAVY
        self.mw.poll_bus_status()
        self.assertTrue(self.mw.tx_running)


class ListenOnlyTests(unittest.TestCase):
    def setUp(self):
        h.install_fake_pcan()
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(
            lambda: [("fake USB 1", CHANNEL)]
        )
        self.mw = gui.MainWindow()

    def tearDown(self):
        if self.mw.can_if:
            self.mw.can_if.close()
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def connect(self, listen_only):
        h.FakePCAN.calls.clear()
        self.mw.cb_listen_only.setChecked(listen_only)
        self.mw.btn_connect.setChecked(True)
        self.mw.toggle_connection()

    def listen_only_calls(self):
        return [
            c[2]
            for c in h.FakePCAN.calls
            if c[0] == "SetValue" and c[1] == PCAN_LISTEN_ONLY.value
        ]

    def test_listen_only_sets_the_pcan_parameter_and_blocks_tx(self):
        """1.12: PCAN_LISTEN_ONLY on, Start TX disabled, mode in the label."""
        self.connect(True)
        self.assertIsNotNone(self.mw.can_if)
        self.assertEqual(self.listen_only_calls(), [PCAN_PARAMETER_ON])
        self.assertFalse(self.mw.btn_start_tx.isEnabled())
        self.assertFalse(self.mw.cb_listen_only.isEnabled())
        self.assertIn("listen only", self.mw.lbl_bus_status.text())
        self.mw.start_stop_transmission()
        self.assertFalse(self.mw.tx_running)

    def test_normal_connect_is_active(self):
        """1.12: unchecked -> listen-only explicitly off, Start TX enabled."""
        self.connect(False)
        self.assertEqual(self.listen_only_calls(), [0])
        self.assertTrue(self.mw.btn_start_tx.isEnabled())
        self.assertEqual(self.mw.lbl_bus_status.text(), "Bus: OK")

    def test_reopen_after_stop_keeps_listen_only(self):
        """1.12: flush_tx() reopens the channel in the same mode."""
        self.connect(True)
        h.FakePCAN.status_result = PCAN_ERROR_BUSHEAVY  # forces the reopen
        h.FakePCAN.calls.clear()
        self.assertTrue(self.mw.can_if.flush_tx())
        self.assertEqual(self.listen_only_calls(), [PCAN_PARAMETER_ON])

    def test_disconnect_resets_status(self):
        self.connect(True)
        self.mw.btn_connect.setChecked(False)
        self.mw.toggle_connection()
        self.assertEqual(self.mw.lbl_bus_status.text(), "Bus: -")
        self.assertTrue(self.mw.cb_listen_only.isEnabled())
        self.assertFalse(self.mw.timer_bus_status.isActive())


if __name__ == "__main__":
    unittest.main()

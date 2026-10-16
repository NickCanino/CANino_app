"""Phase 0 / sub-task 1 — TODO 1.1, 1.2, 1.3, 1.4 (no hardware needed).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.PCANBasic as vendor  # noqa: E402

CHANNEL = 0x51


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        h.install_fake_pcan()
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        self._orig_fd = ci.CANInterface.is_fd_capable
        ci.CANInterface.get_available_channels = staticmethod(
            lambda: [("fake USB 1", CHANNEL)]
        )
        ci.CANInterface.is_fd_capable = staticmethod(lambda ch: False)
        self.mw = gui.MainWindow()

    def tearDown(self):
        if self.mw.can_if:
            self.mw.can_if.close()
        ci.CANInterface.get_available_channels = self._orig_scan
        ci.CANInterface.is_fd_capable = self._orig_fd
        self.mw.close()

    def connect(self, label):
        h.FakePCAN.calls.clear()
        self.mw.cb_baudrate.setCurrentIndex(self.mw.cb_baudrate.findText(label))
        self.mw.btn_connect.setChecked(True)
        self.mw.toggle_connection()

    def disconnect(self):
        self.mw.btn_connect.setChecked(False)
        self.mw.toggle_connection()

    def test_every_classic_label_opens_its_own_rate(self):
        """1.1: each GUI label must initialise the PCAN with that label's register."""
        for label, timing, rate, arb in self.mw.baudrate_values:
            if arb:  # CAN FD entry, covered below
                continue
            with self.subTest(label=label):
                self.connect(label)
                kind, btr = h.init_calls()[0]
                self.assertEqual(kind, "Initialize")
                self.assertEqual(btr, timing.btr0 << 8 | timing.btr1)
                self.assertEqual(timing.bitrate, rate)
                self.disconnect()

    def test_odd_rates_match_the_peak_constants(self):
        """1.1: 95.238/83.333/47.619/33.333k come from PEAK's registers, not a 500k fallback."""
        for label, const in (
            ("95.238 kBit/s", vendor.PCAN_BAUD_95K),
            ("83.333 kBit/s", vendor.PCAN_BAUD_83K),
            ("47.619 kBit/s", vendor.PCAN_BAUD_47K),
            ("33.333 kBit/s", vendor.PCAN_BAUD_33K),
        ):
            with self.subTest(label=label):
                self.connect(label)
                self.assertEqual(h.init_calls()[0], ("Initialize", const.value))
                self.disconnect()

    def test_fd_entry_initialises_fd_on_capable_channel(self):
        """1.2: the CAN FD entry must reach InitializeFD."""
        ci.CANInterface.is_fd_capable = staticmethod(lambda ch: True)
        self.connect("2 MBit/s (CANFD)")
        self.assertEqual(h.init_calls()[0][0], "InitializeFD")
        self.assertIn("data_brp=4", h.init_calls()[0][1])
        self.assertTrue(self.mw.can_if.is_fd)

    def test_fd_entry_refused_on_classic_channel(self):
        """1.2: no silent fallback on adapters without CAN FD."""
        self.connect("2 MBit/s (CANFD)")
        self.assertEqual(h.FakePCAN.calls, [])
        self.assertIsNone(self.mw.can_if)
        self.assertFalse(self.mw.btn_connect.isChecked())
        self.assertEqual(h.DIALOGS[-1][0], "warning")

    def test_init_failure_is_reported(self):
        """1.3: a failed init must not look like a connection."""
        from can.interfaces.pcan.basic import PCAN_ERROR_ILLOPERATION

        h.FakePCAN.init_result = PCAN_ERROR_ILLOPERATION
        self.connect("500 kBit/s")
        self.assertIsNone(self.mw.can_if)
        self.assertFalse(self.mw.btn_connect.isChecked())
        self.assertFalse(self.mw.btn_start_tx.isEnabled())
        self.assertEqual(h.DIALOGS[-1][0], "critical")
        self.assertNotIn("information", [d[0] for d in h.DIALOGS])

    def test_caninterface_rejects_non_timing(self):
        """1.1: a label string must never reach python-can again."""
        with self.assertRaises(TypeError):
            ci.CANInterface(CHANNEL, timing="500 kBit/s")


class MissingDriverTests(unittest.TestCase):
    def test_scan_without_driver_does_not_raise(self):
        """1.4: no PEAK DLL -> empty list + message, and the window still opens."""

        class NoDll:
            def LoadLibrary(self, name):
                raise OSError(f"{name} not found")

        orig = vendor.windll
        vendor.windll = NoDll()
        try:
            self.assertEqual(ci.CANInterface.get_available_channels(), [])
            self.assertIn("driver", ci.CANInterface.scan_error)
            mw = gui.MainWindow()
            self.assertEqual(mw.cb_bus_tx.count(), 1)
            self.assertIsNone(mw.cb_bus_tx.currentData())
            mw.close()
        finally:
            vendor.windll = orig


if __name__ == "__main__":
    unittest.main()

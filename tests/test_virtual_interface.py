"""Phase 3 / sub-task 8 — TODO 1.11: the `virtual` python-can interface.

The virtual loopback is an in-process bus, so these run with no hardware and
with the real VirtualBus (not FakePCAN).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402

TIMING = can.BitTiming(f_clock=8_000_000, brp=1, tseg1=12, tseg2=3, sjw=1)
TIMING_FD = can.BitTimingFd(
    f_clock=80_000_000,
    nom_brp=1,
    nom_tseg1=63,
    nom_tseg2=16,
    nom_sjw=16,
    data_brp=1,
    data_tseg1=15,
    data_tseg2=4,
    data_sjw=4,
)


class VirtualInterfaceTests(unittest.TestCase):
    def test_echo_status_and_flush(self):
        got = []
        c = ci.CANInterface("virtual0", timing=TIMING, interface="virtual")
        c.set_receive_callback(lambda *a: got.append(a))
        self.assertTrue(c.send_frame(0x123, b"\x11\x22", 2))
        for _ in range(50):
            if got:
                break
            time.sleep(0.01)
        c_status = c.bus_status()
        self.assertEqual((c_status.text, c_status.level), ("OK", "ok"))
        self.assertTrue(c.flush_tx())  # no HW queue: a no-op that keeps the bus
        self.assertIsNotNone(c.bus)
        c.close()
        self.assertEqual(got[0][0], 0x123)  # frame_id
        self.assertTrue(got[0][7])  # is_echo

    def test_two_buses_on_one_channel_see_each_other(self):
        rx = []
        a = ci.CANInterface("shared", timing=TIMING, interface="virtual")
        b = can.Bus(interface="virtual", channel="shared", receive_own_messages=False)
        a.set_receive_callback(lambda *args: rx.append(args))
        b.send(can.Message(arbitration_id=0x321, data=b"\x09", is_extended_id=False))
        for _ in range(50):
            if any(not g[7] for g in rx):  # a non-echo (from b)
                break
            time.sleep(0.01)
        b.shutdown()
        a.close()
        self.assertTrue(any(g[0] == 0x321 and not g[7] for g in rx))

    def test_fd_frame_on_virtual(self):
        got = []
        c = ci.CANInterface("vfd", timing=TIMING_FD, interface="virtual")
        self.assertTrue(c.is_fd)
        c.set_receive_callback(lambda *a: got.append(a))
        c.send_frame(0x1, bytes(16), 16, is_fd=True)
        for _ in range(50):
            if got:
                break
            time.sleep(0.01)
        c.close()
        self.assertTrue(got and got[0][3])  # is_fd


class VirtualGuiTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        if self.mw.can_if is not None:
            self.mw.btn_connect.setChecked(False)
            self.mw.toggle_connection()
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def select_virtual(self):
        self.mw.cb_interface.setCurrentIndex(self.mw.cb_interface.findData("virtual"))

    def test_interface_combo_lists_virtual_channel(self):
        self.select_virtual()
        self.assertEqual(
            [self.mw.cb_bus_tx.itemData(i) for i in range(self.mw.cb_bus_tx.count())],
            ["virtual0"],
        )

    def test_connect_and_transmit_on_virtual(self):
        self.select_virtual()
        self.mw.btn_connect.setChecked(True)
        self.mw.toggle_connection()
        self.assertIsNotNone(self.mw.can_if)
        self.assertEqual(self.mw.can_if.interface, "virtual")
        # TX a row; its echo must come back and feed the busload (not an RX row)
        self.mw._add_tx_row(0x100, "V", period=10, dlc=2, payload="AB CD")
        self.mw.start_stop_transmission()
        h.fire_tx(self.mw, times=3)
        rx = self.mw.rx_window
        for _ in range(50):
            rx.drain()
            if rx.frames_tx > 0:
                break
            time.sleep(0.01)
        self.mw.start_stop_transmission()  # stop
        self.assertGreater(rx.frames_tx, 0)  # echoes counted
        self.assertEqual(rx.model.rowCount(), 0)  # echoes are not RX rows
        self.assertGreater(rx.busload_nominal_bits + rx.busload_data_bits, 0)

    def test_bus_status_ok_on_virtual(self):
        self.select_virtual()
        self.mw.btn_connect.setChecked(True)
        self.mw.toggle_connection()
        self.mw.poll_bus_status()
        self.assertIn("OK", self.mw.lbl_bus_status.text())


if __name__ == "__main__":
    unittest.main()

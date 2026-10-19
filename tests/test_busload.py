"""Phase 2 / sub-task 2 — TODO 9.8: busload from exact frame lengths.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import random
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.busload import frame_bits  # noqa: E402

FD_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


# --- bit-by-bit reference, written straight from ISO 11898-1 ---


def bits_of(value, n):
    return [(value >> i) & 1 for i in range(n - 1, -1, -1)]


def crc15(bits):
    crc = 0
    for b in bits:
        nxt = b ^ (crc >> 14)
        crc = (crc << 1) & 0x7FFF
        if nxt:
            crc ^= 0x4599
    return crc


def stuffed(bits, last=None, run=0):
    """Stuff bits in `bits`; returns (count, last, run)."""
    count = 0
    for b in bits:
        if b == last:
            run += 1
        else:
            last, run = b, 1
        if run == 5:
            count += 1
            last, run = 1 - last, 1
    return count, last, run


def arbitration(frame_id, is_ext):
    if is_ext:
        return (
            [0] + bits_of(frame_id >> 18, 11) + [1, 1] + bits_of(frame_id & 0x3FFFF, 18)
        ) + [0]
    return [0] + bits_of(frame_id, 11) + [0]


def classic_ref(frame_id, data, is_ext):
    bits = arbitration(frame_id, is_ext) + [0, 0] + bits_of(len(data), 4)
    bits += [b for byte in data for b in bits_of(byte, 8)]
    bits += bits_of(crc15(bits), 15)
    return len(bits) + stuffed(bits)[0] + 13


def fd_ref(frame_id, data, is_ext, brs):
    dlc = next(i for i, n in enumerate(FD_LENGTHS) if n >= len(data))
    data = bytes(data) + bytes(FD_LENGTHS[dlc] - len(data))
    nominal = arbitration(frame_id, is_ext) + ([] if is_ext else [0]) + [1, 0, brs]
    count_nominal, last, run = stuffed(nominal)
    data_phase = [0] + bits_of(dlc, 4) + [b for byte in data for b in bits_of(byte, 8)]
    count_data = stuffed(data_phase, last, run)[0]
    crc_field = 4 + 17 + 6 if len(data) <= 16 else 4 + 21 + 7
    n_nominal = len(nominal) + count_nominal + 13
    n_data = len(data_phase) + count_data + crc_field
    return (n_nominal, n_data) if brs else (n_nominal + n_data, 0)


class FrameBitsTests(unittest.TestCase):
    def test_classic_matches_the_bitwise_reference(self):
        rnd = random.Random(1)
        for _ in range(5000):
            is_ext = rnd.random() < 0.5
            fid = rnd.getrandbits(29 if is_ext else 11)
            data = bytes(
                rnd.choice((0x00, 0xFF, rnd.getrandbits(8)))
                for _ in range(rnd.randint(0, 8))
            )
            self.assertEqual(
                frame_bits(fid, data, False, is_ext),
                (classic_ref(fid, data, is_ext), 0),
                (hex(fid), data.hex(), is_ext),
            )

    def test_fd_matches_the_bitwise_reference(self):
        rnd = random.Random(2)
        for _ in range(2000):
            is_ext = rnd.random() < 0.5
            brs = rnd.random() < 0.7
            fid = rnd.getrandbits(29 if is_ext else 11)
            data = bytes(
                rnd.choice((0x00, 0xFF, rnd.getrandbits(8)))
                for _ in range(rnd.choice(FD_LENGTHS))
            )
            self.assertEqual(
                frame_bits(fid, data, True, is_ext, brs),
                fd_ref(fid, data, is_ext, brs),
            )

    def test_known_lengths(self):
        # 34 dominant bits SOF..CRC: one stuff bit per 5 -> 34 + 6 + 13
        self.assertEqual(frame_bits(0x000, b""), (53, 0))
        # Unstuffed: std 47 + 8n, ext 67 + 8n (the old estimate had ext 2 bits short)
        rnd = random.Random(3)
        for _ in range(500):
            data = bytes(rnd.getrandbits(8) for _ in range(8))
            std = frame_bits(rnd.getrandbits(11), data)[0]
            ext = frame_bits(rnd.getrandbits(29), data, is_ext=True)[0]
            self.assertTrue(111 <= std <= 135, std)  # 135 = worst-case stuffing
            self.assertTrue(131 <= ext <= 160, ext)

    def test_fd_without_brs_is_all_nominal(self):
        self.assertEqual(frame_bits(0x123, bytes(64), True, False, False)[1], 0)
        nominal, data = frame_bits(0x123, bytes(64), True, False, True)
        self.assertGreater(data, 512)
        self.assertLess(nominal, 40)

    def test_short_fd_payload_is_padded_to_its_dlc(self):
        self.assertEqual(
            frame_bits(0x123, bytes(10), True), frame_bits(0x123, bytes(12), True)
        )


class FakeIf:
    is_fd = False
    listen_only = False

    def __init__(self, timing):
        self.timing = timing

    def send_frame(self, *a, **k):
        return True

    def bus_status(self):
        return ci.BusStatus(0, "OK", "ok")

    def close(self):
        pass


class BusloadLabelTests(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.rx = self.mw.rx_window

    def tearDown(self):
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def load_after(self, seconds):
        self.mw._busload_since = time.monotonic() - seconds
        self.mw.timer_busload_elapsed()
        return float(self.mw.lbl_busload.text().split()[1].rstrip("%"))

    def test_echo_counts_for_the_busload_but_is_no_rx_row(self):
        """9.8: own frames count once they reached the wire, as echoes."""
        self.rx.push_frame(0x100, bytes(8), 8, False, None, False, None, True)
        self.rx.drain()
        self.assertEqual(self.rx.model.rowCount(), 0)
        self.assertGreater(self.rx.busload_nominal_bits, 0)

    def test_failed_sends_do_not_count(self):
        """9.8: a send that never reaches the wire adds nothing."""
        self.mw.can_if = FakeIf(gui.pcan_timing(gui.PCAN_BAUD_500K))
        self.mw.send_can_message(0x100, bytes(8), 8)
        self.assertEqual(self.rx.take_busload_bits(), (0, 0))

    def test_load_from_exact_bits_over_elapsed_time(self):
        """9.8: 1,000 all-zero 0x000 frames (53 bits) in 1 s at 500k = 10.6 %."""
        self.mw.can_if = FakeIf(gui.pcan_timing(gui.PCAN_BAUD_500K))
        for _ in range(1000):
            self.rx.push_frame(0x000, b"", 0, False)
        self.assertAlmostEqual(
            self.load_after(1.0), 10.6, delta=0.1
        )  # the label has 0.1 % steps
        for _ in range(1000):
            self.rx.push_frame(0x000, b"", 0, False)
        self.assertAlmostEqual(
            self.load_after(2.0), 5.3, delta=0.1
        )  # the label has 0.1 % steps

    def test_rate_comes_from_the_channel_not_the_combo(self):
        """9.8: changing the combo after connecting does not rescale the load."""
        self.mw.can_if = FakeIf(gui.pcan_timing(gui.PCAN_BAUD_500K))
        self.mw.cb_baudrate.setCurrentIndex(4)  # 250 kBit/s
        for _ in range(1000):
            self.rx.push_frame(0x000, b"", 0, False)
        self.assertAlmostEqual(
            self.load_after(1.0), 10.6, delta=0.1
        )  # the label has 0.1 % steps

    def test_fd_data_phase_at_the_data_rate(self):
        self.mw.can_if = FakeIf(gui.PCAN_BAUD_FD_2M)
        for _ in range(100):
            self.rx.push_frame(0x123, bytes(64), 64, True)
        nominal, data = frame_bits(0x123, bytes(64), True)
        expected = 100 * (nominal / 500_000 + data / 2_000_000) * 100
        self.assertAlmostEqual(
            self.load_after(1.0), expected, delta=0.1
        )  # the label has 0.1 % steps

    def test_disconnected_shows_no_load(self):
        self.rx.push_frame(0x000, b"", 0, False)
        self.mw.timer_busload_elapsed()
        self.assertEqual(self.mw.lbl_busload.text(), "BusLoad: -")


class EchoTests(unittest.TestCase):
    def test_channel_opens_with_echo_frames(self):
        """9.8: the PCAN channel echoes own frames (PCAN_ALLOW_ECHO_FRAMES)."""
        from can.interfaces.pcan.basic import PCAN_ALLOW_ECHO_FRAMES, PCAN_PARAMETER_ON

        h.install_fake_pcan()
        iface = ci.CANInterface(0x51, gui.pcan_timing(gui.PCAN_BAUD_500K))
        try:
            self.assertIn(
                (
                    "SetValue",
                    PCAN_ALLOW_ECHO_FRAMES.value,
                    getattr(PCAN_PARAMETER_ON, "value", PCAN_PARAMETER_ON),
                ),
                h.FakePCAN.calls,
            )
        finally:
            iface.close()

    def test_receive_loop_flags_echoes_and_brs(self):
        iface = ci.CANInterface.__new__(ci.CANInterface)
        frames = [
            can.Message(arbitration_id=1, data=b"\x01", is_rx=True),
            can.Message(
                arbitration_id=2,
                data=bytes(12),
                is_fd=True,
                bitrate_switch=True,
                is_rx=False,
            ),
        ]
        got = []
        iface.running = True
        iface.error_frames = 0

        class Bus:
            def recv(self, timeout):
                if frames:
                    return frames.pop(0)
                iface.running = False

        iface.bus = Bus()
        iface.receive_callback = lambda *a: got.append(a)
        iface._receive_loop()
        self.assertEqual(
            [(a[0], a[6], a[7]) for a in got], [(1, False, False), (2, True, True)]
        )


if __name__ == "__main__":
    unittest.main()

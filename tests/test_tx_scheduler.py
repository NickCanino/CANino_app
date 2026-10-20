"""Phase 2 / sub-task 4 — TODO 2.11, 2.16: TX thread with absolute deadlines.

These tests run the real thread against the wall clock; tolerances are wide
enough for a loaded PC. Run from the repo root:
    python -m unittest discover -s tests -v
"""

import os
import threading
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.tx_model import TxEntry  # noqa: E402
from src.tx_scheduler import TxScheduler  # noqa: E402


class Recorder:
    def __init__(self):
        self.ticks = {}
        self.lock = threading.Lock()
        self.stall = {}  # entry id -> seconds to block once

    def __call__(self, entry):
        with self.lock:
            self.ticks.setdefault(entry.frame_id, []).append(time.perf_counter())
        delay = self.stall.pop(entry.frame_id, 0)
        if delay:
            time.sleep(delay)

    def periods_ms(self, fid):
        t = self.ticks.get(fid, [])
        return [(b - a) * 1000 for a, b in zip(t, t[1:])]


def threaded(on_tick):
    s = TxScheduler(on_tick)
    s.threaded = True  # the harness turns the thread off by default
    return s


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.s = threaded(self.rec)

    def tearDown(self):
        self.s.stop()

    @unittest.skipIf(
        os.environ.get("CI"), "measures the machine's timing, not the code"
    )
    def test_periods_without_drift(self):
        """2.11: absolute deadlines: N ticks span exactly (N-1) periods."""
        entries = [TxEntry(0x100 + i, period=p) for i, p in enumerate((10, 20, 50))]
        self.s.start()
        for e in entries:
            self.s.add(e)
        time.sleep(1.05)
        self.s.stop()
        for e in entries:
            t = self.rec.ticks[e.frame_id]
            self.assertAlmostEqual(len(t), 1050 / e.period, delta=3)
            span_ms = (t[-1] - t[0]) * 1000
            # Drift would grow with every tick; here only the last tick's jitter counts
            self.assertAlmostEqual(span_ms, (len(t) - 1) * e.period, delta=3)

    def test_late_deadlines_are_skipped_not_burst(self):
        """2.16: after a 55 ms stall a 10 ms row resumes on its phase, no catch-up burst."""
        slow, fast = TxEntry(0x100, period=200), TxEntry(0x200, period=10)
        self.rec.stall[0x100] = 0.055
        self.s.start()
        self.s.add(fast)
        self.s.add(slow)
        time.sleep(0.6)
        self.s.stop()
        gaps = self.rec.periods_ms(0x200)
        self.assertTrue(any(g > 45 for g in gaps), gaps)  # the stall happened
        # A burst would show several ticks well below the period right after it
        self.assertLessEqual(sum(g < 4 for g in gaps), 1, gaps)

    def test_remove_and_retime(self):
        a, b = TxEntry(0x100, period=10), TxEntry(0x200, period=10)
        self.s.start()
        self.s.add(a)
        self.s.add(b)
        time.sleep(0.2)
        self.s.remove(a)
        b.period = 50
        self.s.retime(b)
        n_a = len(self.rec.ticks[0x100])
        n_b = len(self.rec.ticks[0x200])
        time.sleep(0.5)
        self.s.stop()
        self.assertLessEqual(len(self.rec.ticks[0x100]) - n_a, 1)
        self.assertAlmostEqual(len(self.rec.ticks[0x200]) - n_b, 10, delta=2)

    def test_stop_means_no_more_ticks(self):
        self.s.start()
        self.s.add(TxEntry(0x100, period=5))
        time.sleep(0.1)
        self.s.stop()
        n = len(self.rec.ticks[0x100])
        time.sleep(0.05)
        self.assertEqual(len(self.rec.ticks[0x100]), n)
        self.assertEqual(self.s.entries(), [])


class SkipCounterTests(unittest.TestCase):
    def test_skipped_counter(self):
        """2.16: the deadlines dropped during a stall are counted on the job."""
        rec = Recorder()
        s = threaded(rec)
        slow, fast = TxEntry(0x100, period=200), TxEntry(0x200, period=10)
        rec.stall[0x100] = 0.055
        s.start()
        fast_job = s.add(fast)
        s.add(slow)
        time.sleep(0.4)
        skipped = fast_job.skipped
        s.stop()
        self.assertGreaterEqual(skipped, 3)


class FakeIf:
    is_fd = False
    listen_only = False

    def __init__(self):
        self.sent = []

    def send_frame(
        self, frame_id, data, dlc=None, is_fd=False, is_ext=False, is_rtr=False
    ):
        self.sent.append((time.perf_counter(), frame_id))
        return True

    def bus_status(self):
        return ci.BusStatus(0, "OK", "ok")

    def flush_tx(self):
        return True

    def close(self):
        pass


class GuiStarvationTests(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw.tx_scheduler.threaded = True

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    @unittest.skipIf(
        os.environ.get("CI"), "measures the machine's timing, not the code"
    )
    def test_tx_keeps_going_while_the_gui_thread_is_busy(self):
        """2.16: 300 ms of Python work in the GUI thread no longer stops TX."""
        self.mw._add_tx_row(0x100, "T", period=10)
        self.mw.can_if = FakeIf()
        self.mw.start_stop_transmission()
        time.sleep(0.05)
        t0 = time.perf_counter()
        x = 0
        while time.perf_counter() - t0 < 0.3:  # holds the GIL like a long slot
            x += 1
        t1 = time.perf_counter()
        self.mw.stop_tx()
        during = [t for t, _ in self.mw.can_if.sent if t0 <= t <= t1]
        self.assertGreaterEqual(len(during), 20)
        gaps = [(b - a) * 1000 for a, b in zip(during, during[1:])]
        self.assertLess(max(gaps), 25, gaps)

    def test_payload_and_sliders_reach_the_wire_from_the_thread(self):
        """2.11: the TX thread sends the manual payload; the row shows it after refresh."""
        entry = self.mw._add_tx_row(
            0x100, "T", period=5, payload="AB 00 00 00 00 00 00 00"
        )
        sent = []
        fake = FakeIf()
        fake.send_frame = lambda fid, data, *a, **k: sent.append(bytes(data)) or True
        self.mw.can_if = fake
        self.mw.start_stop_transmission()
        time.sleep(0.1)
        self.mw.stop_tx()
        self.assertGreater(len(sent), 10)
        self.assertEqual(set(sent), {bytes([0xAB] + [0] * 7)})
        self.assertIsNone(entry.error)


if __name__ == "__main__":
    unittest.main()

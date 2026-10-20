"""Phase 3 / sub-task 3 — TODO 13.2: labelled capture (attack windows tagged).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import csv
import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402

from src.attacks import AttackController, AttackMode, AttackSpec  # noqa: E402
from src.received_frames_class import ReceivedFramesWindow  # noqa: E402
from src.trace_log import TRACE_FORMATS, TraceLog, label_path  # noqa: E402

T0 = 1_760_000_000.0


def frames_of(path):
    with can.LogReader(path) as r:
        return list(r)


def sidecar_rows(path):
    with open(label_path(path), newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


class TraceLabelTests(unittest.TestCase):
    def run_one(self, ext):
        path = os.path.join(h.WORKDIR, f"lbl{ext}")
        log = TraceLog(path)
        log.write(0x100, b"\x01\x02", False, T0, False, False, False)
        log.log_label(T0 + 0.05, "start", "flood", "flood ids=0x000 T=2ms")
        log.write(0x000, b"\xff" * 8, False, T0 + 0.1, False, False, False)
        log.log_label(T0 + 0.2, "stop", "flood", "flood ids=0x000 T=2ms")
        log.write(0x100, b"\x03\x04", False, T0 + 0.25, False, False, False)
        log.close()
        return path

    def test_labels_do_not_corrupt_frame_readback(self):
        """A trace with labels still reads back as exactly its frames."""
        for ext in TRACE_FORMATS:
            with self.subTest(ext=ext):
                path = self.run_one(ext)
                ids = [m.arbitration_id for m in frames_of(path)]
                self.assertEqual(ids, [0x100, 0x000, 0x100], ext)

    def test_sidecar_records_every_boundary(self):
        for ext in TRACE_FORMATS:
            with self.subTest(ext=ext):
                path = self.run_one(ext)
                rows = sidecar_rows(path)
                self.assertEqual(
                    rows[0], ["Timestamp", "Epoch", "Action", "Mode", "Label"]
                )
                self.assertEqual(
                    [(r[2], r[3]) for r in rows[1:]],
                    [("start", "flood"), ("stop", "flood")],
                )
                self.assertAlmostEqual(float(rows[1][1]), T0 + 0.05, places=5)
                self.assertAlmostEqual(float(rows[2][1]), T0 + 0.2, places=5)

    def test_trc_marker_is_a_comment_line(self):
        path = self.run_one(".trc")
        with open(path, encoding="ascii") as f:
            labels = [ln.strip() for ln in f if ln.startswith(";LABEL")]
        self.assertEqual(len(labels), 2)
        self.assertIn("start flood", labels[0])
        # positioned after the previous frame (T0+0.0 -> offset ~100 ms for the stop)
        self.assertTrue(labels[0].split()[1].replace(".", "").isdigit())

    def test_asc_marker_line_present(self):
        path = self.run_one(".asc")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("CANino LABEL start flood", text)
        self.assertIn("CANino LABEL stop flood", text)

    def test_no_sidecar_without_labels(self):
        path = os.path.join(h.WORKDIR, "nolabel.trc")
        log = TraceLog(path)
        log.write(0x100, b"\x01", False, T0, False, False, False)
        log.close()
        self.assertFalse(os.path.exists(label_path(path)))

    def test_label_before_any_frame(self):
        """A label fired before the first frame still writes header + sidecar."""
        path = os.path.join(h.WORKDIR, "early.trc")
        log = TraceLog(path)
        log.log_label(T0, "start", "flood", "x")
        log.write(0x100, b"\x01", False, T0 + 0.01, False, False, False)
        log.close()
        self.assertEqual([m.arbitration_id for m in frames_of(path)], [0x100])
        self.assertEqual(len(sidecar_rows(path)), 2)


class RxWindowLabelTests(unittest.TestCase):
    # write_label lives on ReceivedFramesWindow: no MainWindow needed
    def setUp(self):
        self.rx = ReceivedFramesWindow()

    def tearDown(self):
        h.dispose(self.rx)

    def push(self, fid, ts, echo=False):
        self.rx.push_frame(fid, b"\x01" * 8, 8, False, ts, False, False, echo)

    def test_label_only_while_a_trace_logs(self):
        # CSV stats log: labels are ignored (no trace)
        self.rx.csv_path = os.path.join(h.WORKDIR, "stats.csv")
        self.rx.start_log()
        self.rx.write_label(T0, "start", "flood", "x")  # no-op
        self.rx.stop_log()
        self.assertFalse(os.path.exists(os.path.join(h.WORKDIR, "stats.labels.csv")))

    def test_label_no_op_when_paused_or_idle(self):
        path = os.path.join(h.WORKDIR, "paused.trc")
        self.rx.csv_path = path
        self.rx.write_label(T0, "start", "flood", "x")  # idle: no-op
        self.rx.start_log()
        self.rx.pause_log()
        self.rx.write_label(T0, "start", "flood", "x")  # paused: no-op
        self.rx.stop_log()
        self.assertFalse(os.path.exists(label_path(path)))

    def test_label_brackets_injected_frames(self):
        path = os.path.join(h.WORKDIR, "window.trc")
        self.rx.csv_path = path
        self.rx.start_log()
        self.push(0x100, T0)  # benign, before
        self.rx.write_label(T0 + 0.01, "start", "flood", "flood ids=0x000")
        self.push(0x000, T0 + 0.02, echo=True)  # the attack frame (own TX)
        self.push(0x000, T0 + 0.03, echo=True)
        self.rx.write_label(T0 + 0.04, "stop", "flood", "flood ids=0x000")
        self.push(0x100, T0 + 0.05)  # benign, after
        self.rx.stop_log()
        rows = sidecar_rows(path)
        self.assertEqual(
            [(r[2], r[3]) for r in rows[1:]], [("start", "flood"), ("stop", "flood")]
        )
        # the flood frames reached the trace as Tx and sit inside the window
        msgs = frames_of(path)
        self.assertEqual([m.arbitration_id for m in msgs], [0x100, 0x000, 0x000, 0x100])


class EndToEndTests(unittest.TestCase):
    """The glue the GUI will use: controller events -> trace labels."""

    def test_controller_events_tag_the_trace(self):
        path = os.path.join(h.WORKDIR, "e2e.asc")
        trace = TraceLog(path)
        trace.write(0x100, b"\x00" * 8, False, T0, False, False, False)

        injected = []

        class Adapter:
            def inject(self, row):
                injected.append(row)
                return row

            def withdraw(self, row):
                injected.remove(row)

            def set_suspended(self, key, s):
                pass

        ctl = AttackController(Adapter(), clock=lambda: T0 + 1.0)
        # GUI glue: forward each event to the trace
        ev = ctl.start(AttackSpec(AttackMode.FUZZING, target_ids=(0x200,), seed=1))
        trace.log_label(ev.timestamp, ev.action, ev.mode, ev.label)
        self.assertEqual(len(injected), 1)
        ev = ctl.stop()
        trace.log_label(ev.timestamp, ev.action, ev.mode, ev.label)
        trace.close()

        rows = sidecar_rows(path)
        self.assertEqual([r[2] for r in rows[1:]], ["start", "stop"])
        self.assertIn("fuzzing", rows[1][4])
        self.assertIn("seed=1", rows[1][4])


if __name__ == "__main__":
    unittest.main()

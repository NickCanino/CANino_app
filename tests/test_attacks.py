"""Phase 3 / sub-task 2 — TODO 13.1: attack modes over the TX engine.

Qt-free: the controller is driven against a fake adapter. The on-bus behaviour
is checked separately on the bench (PLAN.md §6).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import unittest

from src.attacks import (
    AttackController,
    AttackMode,
    AttackSpec,
)


class FakeAdapter:
    """Records what the controller injects / withdraws / suspends."""

    def __init__(self):
        self.rows = []  # live injected rows
        self.withdrawn = []
        self.suspended = {}  # key -> bool

    def inject(self, row):
        self.rows.append(row)
        return row  # the handle is the row itself

    def withdraw(self, handle):
        self.rows.remove(handle)
        self.withdrawn.append(handle)

    def set_suspended(self, key, suspended):
        self.suspended[key] = suspended


class SpecBuildTests(unittest.TestCase):
    def test_flood_one_fast_fixed_row(self):
        spec = AttackSpec(
            AttackMode.FLOOD, target_ids=(0x000,), period=1, payload=b"\xff" * 8
        )
        rows, suspend = spec.build()
        self.assertEqual(suspend, [])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r.frame_id, r.is_ext, r.period), (0x000, False, 1))
        self.assertIsNone(r.payload_fn)
        self.assertEqual(r.payload, b"\xff" * 8)

    def test_fuzzing_is_reproducible_and_marked(self):
        spec = AttackSpec(
            AttackMode.FUZZING, target_ids=(0x200,), dlc=8, seed=42, marker=0xA7
        )
        fn1 = spec.build()[0][0].payload_fn
        fn2 = spec.build()[0][0].payload_fn  # a second build, same seed
        a = [fn1(8, 0x200) for _ in range(5)]
        b = [fn2(8, 0x200) for _ in range(5)]
        self.assertEqual(a, b)  # same seed -> same bytes
        self.assertTrue(all(len(p) == 8 for p in a))
        self.assertTrue(all(p[1] == 0xA7 for p in a))  # in-band marker
        self.assertGreater(len({bytes(p) for p in a}), 1)  # actually varying

    def test_fuzzing_marker_off_and_dlc1(self):
        spec = AttackSpec(
            AttackMode.FUZZING, target_ids=(0x200,), dlc=1, seed=1, marker=None
        )
        fn = spec.build()[0][0].payload_fn
        p = fn(1, 0x200)
        self.assertEqual(len(p), 1)  # DLC 1: no byte 1 to mark anyway

    def test_fuzzing_several_ids_differ(self):
        spec = AttackSpec(
            AttackMode.FUZZING, target_ids=(0x100, 0x101), seed=7, marker=None
        )
        rows = spec.build()[0]
        self.assertEqual(len(rows), 2)
        s0 = [rows[0].payload_fn(8, 0x100) for _ in range(4)]
        s1 = [rows[1].payload_fn(8, 0x101) for _ in range(4)]
        self.assertNotEqual(s0, s1)  # per-row seed offset

    def test_spoofing_fixed_falsified_payload(self):
        spec = AttackSpec(
            AttackMode.SPOOFING,
            target_ids=(0x153,),
            dlc=4,
            period=5,
            payload=b"\xde\xad",
        )
        r = spec.build()[0][0]
        self.assertIsNone(r.payload_fn)
        self.assertEqual(r.payload, b"\xde\xad\x00\x00")  # padded to DLC

    def test_replay_cycles_recorded_sequence(self):
        spec = AttackSpec(
            AttackMode.REPLAY,
            target_ids=(0x130,),
            dlc=3,
            replay_payloads=(b"\x01\x02\x03", b"\x04\x05\x06"),
        )
        fn = spec.build()[0][0].payload_fn
        out = [fn(3, 0x130) for _ in range(5)]
        self.assertEqual(
            out,
            [
                b"\x01\x02\x03",
                b"\x04\x05\x06",
                b"\x01\x02\x03",
                b"\x04\x05\x06",
                b"\x01\x02\x03",
            ],
        )

    def test_replay_pads_short_and_truncates_long(self):
        spec = AttackSpec(
            AttackMode.REPLAY,
            target_ids=(1,),
            dlc=4,
            replay_payloads=(b"\xaa", b"\x11\x22\x33\x44\x55"),
        )
        fn = spec.build()[0][0].payload_fn
        self.assertEqual(fn(4, 1), b"\xaa\x00\x00\x00")
        self.assertEqual(fn(4, 1), b"\x11\x22\x33\x44")

    def test_suspension_targets_no_rows(self):
        spec = AttackSpec(AttackMode.SUSPENSION, target_ids=(0x316, 0x153))
        rows, suspend = spec.build()
        self.assertEqual(rows, [])
        self.assertEqual(suspend, [(0x316, False), (0x153, False)])

    def test_ext_id_forces_extended(self):
        spec = AttackSpec(AttackMode.FLOOD, target_ids=(0x18DAF110,), is_ext=True)
        r = spec.build()[0][0]
        self.assertTrue(r.is_ext)
        self.assertEqual(r.frame_id, 0x18DAF110)

    def test_describe_is_stable_and_informative(self):
        spec = AttackSpec(AttackMode.FUZZING, target_ids=(0x200,), seed=5, marker=0xA7)
        d = spec.describe()
        self.assertIn("fuzzing", d)
        self.assertIn("0x200", d)
        self.assertIn("seed=5", d)
        self.assertIn("marker=0xA7", d)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.ad = FakeAdapter()
        self.t = [1000.0]
        self.ctl = AttackController(self.ad, clock=lambda: self.t[0])

    def test_start_injects_and_stop_withdraws(self):
        spec = AttackSpec(AttackMode.FLOOD, target_ids=(0x000,), payload=b"\x00" * 8)
        self.assertFalse(self.ctl.active)
        self.ctl.start(spec)
        self.assertTrue(self.ctl.active)
        self.assertEqual(len(self.ad.rows), 1)
        self.ctl.stop()
        self.assertFalse(self.ctl.active)
        self.assertEqual(self.ad.rows, [])
        self.assertEqual(len(self.ad.withdrawn), 1)

    def test_suspension_restores_on_stop(self):
        spec = AttackSpec(AttackMode.SUSPENSION, target_ids=(0x153,))
        self.ctl.start(spec)
        self.assertEqual(self.ad.suspended, {(0x153, False): True})
        self.ctl.stop()
        self.assertEqual(self.ad.suspended, {(0x153, False): False})

    def test_only_one_attack_at_a_time(self):
        self.ctl.start(AttackSpec(AttackMode.FLOOD, target_ids=(1,)))
        with self.assertRaises(RuntimeError):
            self.ctl.start(AttackSpec(AttackMode.FLOOD, target_ids=(2,)))

    def test_stop_when_idle_is_noop(self):
        self.assertIsNone(self.ctl.stop())

    def test_events_record_start_and_stop_times(self):
        spec = AttackSpec(AttackMode.SPOOFING, target_ids=(0x153,), payload=b"\x01")
        self.t[0] = 1000.0
        e1 = self.ctl.start(spec)
        self.t[0] = 1003.5
        e2 = self.ctl.stop()
        self.assertEqual((e1.action, e1.timestamp), ("start", 1000.0))
        self.assertEqual((e2.action, e2.timestamp), ("stop", 1003.5))
        self.assertEqual(e1.label, spec.describe())
        self.assertEqual([e.action for e in self.ctl.events], ["start", "stop"])


if __name__ == "__main__":
    unittest.main()

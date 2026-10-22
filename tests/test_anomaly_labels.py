"""v1.7.2 / sub-task 2 — TODO 3.17: a payload script labels its anomalous frames.

`get_payload` may return (payload, label); the label travels with the frame's
Signal Plot sample. Run from the repo root:
    python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.tx_panel import split_script_result  # noqa: E402
from test_signal_plot import make_dbc  # noqa: E402

# Byte 0 counts the calls; frames 3 and 4 are labelled "spike", 6 returns
# (None, "drift") = the manual payload, labelled; the rest are plain bytes
LABEL_SCRIPT = """n = 0


def get_payload(dlc, id):
    global n
    n += 1
    payload = bytes([n]) + bytes(dlc - 1)
    if n in (3, 4):
        return payload, "spike"
    if n == 6:
        return None, "drift"
    if n == 7:
        return payload, ""
    return payload
"""


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class SplitResultTests(unittest.TestCase):
    def test_plain_results(self):
        self.assertEqual(split_script_result(b"\x01\x02"), (b"\x01\x02", None))
        self.assertEqual(split_script_result(None), (None, None))

    def test_pair(self):
        self.assertEqual(split_script_result((b"\x01", "spike")), (b"\x01", "spike"))
        self.assertEqual(split_script_result((None, "drift")), (None, "drift"))

    def test_empty_or_none_label_is_a_normal_frame(self):
        self.assertEqual(split_script_result((b"\x01", "")), (b"\x01", None))
        self.assertEqual(split_script_result((b"\x01", None)), (b"\x01", None))

    def test_bad_shapes_raise(self):
        with self.assertRaises(ValueError):
            split_script_result((b"\x01", "a", "b"))
        with self.assertRaises(ValueError):
            split_script_result((b"\x01", 3))


class FakeIf:
    is_fd = False
    bus = None

    def __init__(self):
        self.sent = []

    def send_frame(
        self, frame_id, data, dlc=None, is_fd=False, is_ext=False, is_rtr=False
    ):
        self.sent.append((frame_id, bytes(data)))
        return True

    def flush_tx(self):
        return True

    def close(self):
        pass


class ScriptLabelTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.mw.can_if = FakeIf()
        self.path = os.path.join(h.WORKDIR, "labelled.py")
        write(self.path, LABEL_SCRIPT)

    def tearDown(self):
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def row(self, **kw):
        entry = self.mw._add_tx_row(0x100, "A", dlc=2, **kw)
        entry.payload = b"\xee\xee"
        self.mw._plot_tx_keys = frozenset({entry.key})  # as an open plot would
        return entry

    def send(self, entry, n):
        for _ in range(n):
            self.mw._send_row(entry)
        return list(self.mw._tx_samples)

    def test_labels_travel_with_the_samples(self):
        entry = self.row(script_path=self.path)
        samples = self.send(entry, 8)
        self.assertEqual(
            [(s[2], s[4]) for s in samples],
            [
                (b"\x01\x00", None),
                (b"\x02\x00", None),
                (b"\x03\x00", "spike"),
                (b"\x04\x00", "spike"),
                (b"\x05\x00", None),
                # None = the manual payload, labelled: the row's payload cell,
                # which holds the last frame sent (written back each send)
                (b"\x05\x00", "drift"),
                (b"\x07\x00", None),  # "" = normal
                (b"\x08\x00", None),
            ],
        )
        self.assertEqual([f for f, _ in self.mw.can_if.sent], [0x100] * 8)

    def test_global_script_labels_too(self):
        self.mw.global_script_path = self.path
        entry = self.row()
        samples = self.send(entry, 4)
        self.assertEqual([s[4] for s in samples], [None, None, "spike", "spike"])

    def test_bad_label_blocks_the_frame(self):
        write(self.path, "def get_payload(dlc, id):\n    return bytes(dlc), 42\n")
        entry = self.row(script_path=self.path)
        self.send(entry, 1)
        self.assertEqual(self.mw.can_if.sent, [])
        self.assertIn("label is int", entry.error)

    def test_sliders_still_apply_to_labelled_frames(self):
        entry = self.row(script_path=self.path)
        self.send(entry, 2)  # n = 1, 2
        sig = make_dbc().messages[0].signals[0]  # SIG_X: byte 0, factor 2
        self.mw._slider_overrides = {entry.key: [(sig, 20)]}
        samples = self.send(entry, 1)  # n = 3: "spike"
        self.assertEqual(samples[-1][4], "spike")
        self.assertEqual(samples[-1][2], b"\x0a\x00")  # the slider wins byte 0

    def test_label_reaches_the_plot_feed(self):
        entry = self.row(script_path=self.path)
        got = []
        self.mw._feed_plots = got.extend
        self.send(entry, 3)
        self.mw._tx_refresh()
        self.assertEqual([s[4] for s in got], [None, None, "spike"])


if __name__ == "__main__":
    unittest.main()

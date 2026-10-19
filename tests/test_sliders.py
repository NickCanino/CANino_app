"""Phase 1 / sub-task 5 — TODO 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.11 (sliders).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import cantools  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QLabel  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

# MSG_A and EXT_A share the number 0x100 (std / ext)
DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|100] "" ECU
 SG_ SIG_BIG : 16|32@1+ (1,0) [0|0] "" ECU
 SG_ SIG_MOT : 55|12@0- (0.5,-10) [0|0] "deg" ECU
BO_ 512 MSG_B: 8 ECU
 SG_ SIG_K : 0|8@1+ (1,0) [0|10] "" ECU
 SG_ SIG_L : 8|8@1+ (1,0) [0|255] "" ECU
BO_ 2147483904 EXT_A: 8 ECU
 SG_ SIG_E : 0|8@1+ (1,0) [0|255] "" ECU
"""


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        with open("sliders.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.mw = gui.MainWindow()
        self.mw.dbc = gui.load_dbc("sliders.dbc")
        self.db = cantools.database.load_file("sliders.dbc")
        self.rows = {
            (0x100, False): self.mw._add_tx_row(0x100, "MSG_A"),
            (0x200, False): self.mw._add_tx_row(
                0x200, "MSG_B", payload="FF 22 33 44 55 66 77 88"
            ),
            (0x100, True): self.mw._add_tx_row(0x100, "EXT_A", is_ext=True),
        }
        self.mw.can_if = FakeIf()

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def msg(self, name):
        return next(m for m in self.mw.dbc.messages if m.name == name)

    def slider(self, msg_name, sig_name, value=None):
        msg = self.msg(msg_name)
        sig = next(s for s in msg.signals if s.name == sig_name)
        return self.mw._add_slider_widget(msg, sig, value)

    def send_once(self):
        self.mw.can_if.sent.clear()
        self.mw.can_if.flags.clear()
        self.mw.start_stop_transmission()
        for t in list(self.mw.timers):
            t.timeout.emit()
        self.mw.stop_tx()
        return {
            (f, x): d
            for (f, x, _, _), (_, d) in zip(self.mw.can_if.flags, self.mw.can_if.sent)
        }


class RangeTests(Base):
    def test_dbc_min_max_is_the_range(self):
        """4.7: SIG_X [0|100] -> 0..100, not the raw 0..255."""
        w = self.slider("MSG_A", "SIG_X")
        self.assertEqual((w.min_val, w.max_val), (0, 100))
        self.assertEqual(w.slider.maximum(), 100)

    def test_32_bit_signal_fits_qslider(self):
        """4.4: a 32-bit raw range no longer overflows QSlider.setMaximum."""
        w = self.slider("MSG_A", "SIG_BIG")
        self.assertEqual(w.slider.maximum(), gui.SLIDER_MAX_STEPS)
        self.assertEqual(w.max_val, 2**32 - 1)
        w.slider.setValue(w.slider.maximum())
        data = self.send_once()[(0x100, False)]
        self.assertEqual(int.from_bytes(data[2:6], "little"), 2**32 - 1)

    def test_bit_label_is_dbc_notation(self):
        """4.7: Motorola signals no longer get an Intel-style bit range."""
        w = self.slider("MSG_A", "SIG_MOT")
        texts = [lbl.text() for lbl in w.findChildren(QLabel)]
        self.assertTrue(any("[55|12@0-]" in t for t in texts), texts)
        self.assertTrue(any("(0x100)" in t for t in texts), texts)


class EncodeTests(Base):
    def test_out_of_range_other_signal_no_longer_blocks_the_frame(self):
        """4.5 + 4.6: SIG_K = 255 (DBC max 10) in the payload; the SIG_L slider still sends,
        and every byte it does not own is unchanged."""
        w = self.slider("MSG_B", "SIG_L", 7)
        self.assertEqual(w.slider.value(), 7)
        data = self.send_once()[(0x200, False)]
        self.assertEqual(data, bytes.fromhex("FF 07 33 44 55 66 77 88"))

    def test_motorola_scaled_signed_matches_cantools(self):
        """4.6: the slider writes its own bits as cantools reads them."""
        self.slider("MSG_A", "SIG_MOT", -7.5)
        self.slider("MSG_A", "SIG_X", 42)
        data = self.send_once()[(0x100, False)]
        decoded = self.db.get_message_by_name("MSG_A").decode(data)
        self.assertEqual(decoded["SIG_MOT"], -7.5)
        self.assertEqual(decoded["SIG_X"], 42)
        self.assertEqual(decoded["SIG_BIG"], 0)

    def test_value_clamped_to_the_range(self):
        """4.5: a value beyond the DBC max is clamped, the frame is sent."""
        w = self.slider("MSG_A", "SIG_X", 150)
        self.assertEqual(w.value(), 100)
        self.assertEqual(self.send_once()[(0x100, False)][0], 100)

    def test_ext_slider_applies_to_the_ext_row_only(self):
        """4.11: EXT_A (ext 0x100) never writes into MSG_A (std 0x100)."""
        self.slider("EXT_A", "SIG_E", 0x5A)
        sent = self.send_once()
        self.assertEqual(sent[(0x100, True)][0], 0x5A)
        self.assertEqual(sent[(0x100, False)][0], 0x00)


class WorkspaceTests(Base):
    def roundtrip(self):
        self.mw._save_config_to_file("ws_sliders.json")
        with open("ws_sliders.json", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["dbc_file"] = "sliders.dbc"
        with open("ws_sliders.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        mw2 = gui.MainWindow()
        mw2.CONFIG_FILE = "ws_sliders.json"
        mw2.load_config(auto=True)
        self.addCleanup(mw2.close)
        return cfg, mw2

    def test_saved_slider_names_its_message(self):
        """4.8: msg_name is the message name, not the signal name."""
        self.slider("MSG_A", "SIG_X", 10)
        self.mw.dbc.dbc_filename = "sliders.dbc"
        cfg, _ = self.roundtrip()
        self.assertEqual(cfg["sliders"][0]["msg_name"], "MSG_A")
        self.assertEqual(cfg["sliders"][0]["value"], 10)

    def test_round_trip_keeps_value_and_id_format(self):
        """4.9 + 4.11: physical value and ext flag survive Save/Load."""
        self.slider("MSG_A", "SIG_MOT", 12.5)
        self.slider("EXT_A", "SIG_E", 99)
        self.mw.dbc.dbc_filename = "sliders.dbc"
        _, mw2 = self.roundtrip()
        got = {(w.msg_name, w.is_ext): w.value() for w in mw2.slider_widgets}
        self.assertEqual(got, {("MSG_A", False): 12.5, ("EXT_A", True): 99})

    def test_legacy_slider_entry_restores_its_value(self):
        """Pre-1.5 files: msg_name = signal name, value_index into min_val/step."""
        legacy = {
            "msg_name": "SIG_X",
            "signal_name": "SIG_X",
            "frame_id": 256,
            "min_val": 0,
            "max_val": 255,
            "step": 1,
            "unit": "",
            "value_index": 30,
        }
        with open("ws_legacy.json", "w", encoding="utf-8") as f:
            json.dump(
                {"dbc_file": "sliders.dbc", "signals": [], "sliders": [legacy]}, f
            )
        self.mw.CONFIG_FILE = "ws_legacy.json"
        self.mw.load_config(auto=True)
        (w,) = self.mw.slider_widgets
        self.assertEqual((w.msg_name, w.is_ext, w.value()), ("MSG_A", False, 30))


class AddSliderDialogTests(Base):
    def test_add_slider_starts_from_the_current_payload(self):
        """4.9: Add Slider picks message + signal and starts at the value being sent."""
        h.tx_edit(
            self.mw,
            self.rows[(0x200, False)],
            gui.TX_COL_6_payload,
            "05 2A 00 00 00 00 00 00",
        )
        answers = iter(["MSG_B (0x200)", "SIG_L"])
        orig = QInputDialog.getItem
        QInputDialog.getItem = staticmethod(lambda *a, **k: (next(answers), True))
        try:
            self.mw.add_slider()
        finally:
            QInputDialog.getItem = orig
        (w,) = self.mw.slider_widgets
        self.assertEqual(
            (w.msg_name, w.signal.name, w.value()), ("MSG_B", "SIG_L", 0x2A)
        )

    def test_messages_offered_with_their_id_format(self):
        """4.11: std and ext 0x100 are both offered, told apart by the ID."""
        offered = []

        def get_item(parent, title, label, items, *a, **k):
            offered.extend(items)
            return "", False

        orig = QInputDialog.getItem
        QInputDialog.getItem = staticmethod(get_item)
        try:
            self.mw.add_slider()
        finally:
            QInputDialog.getItem = orig
        self.assertIn("MSG_A (0x100)", offered)
        self.assertIn("EXT_A (0x00000100)", offered)


if __name__ == "__main__":
    unittest.main()

"""Phase 3 / sub-task 5 — TODO 5.12 (RX filter), 5.11 (decoded view), 7.8 (XMetro DBC).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402
import src.gui as gui  # noqa: E402
from src.received_frames_class import ReceivedFramesWindow  # noqa: E402
from src.rx_model import parse_id_mask  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (2,0) [0|510] "rpm" ECU
 SG_ SIG_MODE : 8|8@1+ (1,0) [0|3] "" ECU
BO_ 288 MSG_B: 8 ECU
 SG_ SIG_Y : 0|8@1+ (1,0) [0|255] "" ECU
VAL_ 256 SIG_MODE 0 "OFF" 1 "ON" 2 "AUTO" ;
"""


def make_dbc(name="f.dbc"):
    path = os.path.join(h.WORKDIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(DBC)
    return dbc_loader.load_dbc(path)


class ParseIdMaskTests(unittest.TestCase):
    def test_parses_hex_with_and_without_prefix(self):
        self.assertEqual(parse_id_mask("100/700"), (0x100, 0x700))
        self.assertEqual(parse_id_mask("0x18DAF1/0x1FFFFF"), (0x18DAF1, 0x1FFFFF))

    def test_rejects_non_mask_text(self):
        self.assertIsNone(parse_id_mask("ESP"))
        self.assertIsNone(parse_id_mask("0x100"))
        self.assertIsNone(parse_id_mask(""))


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.rx = ReceivedFramesWindow(make_dbc())

    def tearDown(self):
        h.dispose(self.rx)

    def seed(self):
        for fid in (0x100, 0x120, 0x200, 0x18DAF110):
            self.rx.push_frame(
                fid, b"\xaa\x02" + b"\x00" * 6, 8, False, None, fid > 0x7FF
            )
        self.rx.drain()

    def view_ids(self):
        return [r[0] for r in h.rx_view_rows(self.rx)]

    def test_no_filter_shows_all(self):
        self.seed()
        self.assertEqual(len(self.view_ids()), 4)

    def test_substring_filter_on_id(self):
        self.seed()
        self.rx.filter_edit.setText("0x1")  # 0x100, 0x120 (std shown 0x120), ext 0x...
        ids = self.view_ids()
        self.assertIn("0x100", ids)
        self.assertNotIn("0x200", ids)

    def test_name_filter(self):
        self.seed()
        self.rx.filter_edit.setText("MSG_B")  # only 0x120 is MSG_B
        self.assertEqual(self.view_ids(), ["0x120"])

    def test_id_mask_filter(self):
        self.seed()
        self.rx.filter_edit.setText("120/7FF")  # exact match on 0x120 only
        self.assertEqual(self.view_ids(), ["0x120"])
        self.rx.filter_edit.setText("100/700")  # the 0x1__ class
        self.assertEqual(set(self.view_ids()), {"0x100", "0x120", "0x18DAF110"})

    def test_filter_does_not_touch_capture(self):
        self.seed()
        self.rx.filter_edit.setText("nothing-matches")
        self.assertEqual(self.view_ids(), [])
        self.assertEqual(self.rx.model.rowCount(), 4)  # all rows still captured


class DecodedViewTests(unittest.TestCase):
    def setUp(self):
        self.rx = ReceivedFramesWindow(make_dbc())

    def tearDown(self):
        h.dispose(self.rx)

    def select_first(self):
        self.rx.table.selectRow(0)

    def decoded_rows(self):
        d = self.rx.decoded
        return [
            tuple(
                d.item(r, c).text() if d.item(r, c) else None
                for c in range(d.columnCount())
            )
            for r in range(d.rowCount())
        ]

    def test_selecting_a_row_decodes_its_signals(self):
        self.rx.push_frame(0x100, bytes([10, 2]) + b"\x00" * 6, 8, False)
        self.rx.drain()
        self.select_first()
        rows = self.decoded_rows()
        self.assertEqual(rows[0], ("SIG_X", "20", "rpm"))  # 10 * factor 2
        self.assertEqual(rows[1], ("SIG_MODE", "AUTO", ""))  # enum raw 2

    def test_panel_updates_live_on_new_frames(self):
        self.rx.push_frame(0x100, bytes([5, 1]) + b"\x00" * 6, 8, False)
        self.rx.drain()
        self.select_first()
        self.assertEqual(self.decoded_rows()[0][1], "10")
        self.rx.push_frame(0x100, bytes([50, 1]) + b"\x00" * 6, 8, False)
        self.rx.drain()  # same ID selected -> panel refreshes
        self.assertEqual(self.decoded_rows()[0][1], "100")

    def test_no_dbc_no_rows(self):
        rx = ReceivedFramesWindow()
        self.addCleanup(lambda: h.dispose(rx))
        rx.push_frame(0x100, bytes(8), 8, False)
        rx.drain()
        rx.table.selectRow(0)
        self.assertEqual(rx.decoded.rowCount(), 0)

    def test_clear_empties_the_panel(self):
        self.rx.push_frame(0x100, bytes([1, 1]) + b"\x00" * 6, 8, False)
        self.rx.drain()
        self.select_first()
        self.assertGreater(self.rx.decoded.rowCount(), 0)
        self.rx.clear_rx_table()
        self.assertEqual(self.rx.decoded.rowCount(), 0)


class XMetroDbcRefreshTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_load_dbc_reaches_an_open_xmetro(self):
        """7.8: a DBC loaded after XMetro is open updates its gauges."""
        self.mw._apply_dbc(make_dbc("first.dbc"))
        self.mw.open_xmetro_window()
        win = self.mw.xmetro_windows[-1]
        win.add_gauge()
        gauge = win.gauges[-1]
        names_before = {
            gauge.cb_messages.itemText(i) for i in range(gauge.cb_messages.count())
        }
        self.assertTrue(any("MSG_A" in n for n in names_before))

        # Load a different DBC
        other = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 512 OTHER_MSG: 8 ECU
 SG_ OTHER_SIG : 0|8@1+ (1,0) [0|255] "" ECU
"""
        p = os.path.join(h.WORKDIR, "other.dbc")
        with open(p, "w", encoding="utf-8") as f:
            f.write(other)
        self.mw._apply_dbc(dbc_loader.load_dbc(p))

        names_after = {
            gauge.cb_messages.itemText(i) for i in range(gauge.cb_messages.count())
        }
        self.assertTrue(any("OTHER_MSG" in n for n in names_after))
        self.assertFalse(any("MSG_A" in n for n in names_after))

    def test_set_dbc_none_clears_gauges(self):
        self.mw._apply_dbc(make_dbc("x.dbc"))
        self.mw.open_xmetro_window()
        win = self.mw.xmetro_windows[-1]
        win.add_gauge()
        self.mw._apply_dbc(None)
        self.assertEqual(win.gauges[-1].cb_messages.count(), 0)


if __name__ == "__main__":
    unittest.main()

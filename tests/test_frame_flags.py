"""Phase 1 / sub-task 1 — TODO 1.6, 1.7, 2.1/2.2 (form), 2.3, 2.4, 2.5, 2.9, 2.14, 6.9.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import can  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

# 0x123 standard, 0x123 extended (bit 31 = extended in DBC), 0x18FF0001 extended FD
DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 291 STD_123: 8 ECU
 SG_ SIG_A : 0|8@1+ (1,0) [0|255] "" ECU
BO_ 2147483939 EXT_123: 4 ECU
 SG_ SIG_B : 0|8@1+ (1,0) [0|255] "" ECU
BO_ 2566848513 EXT_FD: 16 ECU
 SG_ SIG_C : 0|8@1+ (1,0) [0|255] "" ECU
BA_DEF_ BO_ "VFrameFormat" ENUM "StandardCAN","ExtendedCAN","reserved","J1939PG","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","StandardCAN_FD","ExtendedCAN_FD";
BA_ "VFrameFormat" BO_ 2566848513 15;
"""


def row(fid, **kw):
    r = {
        "enabled": True,
        "id": f"0x{fid:03X}",
        "fd": "n",
        "name": f"M{fid:X}",
        "period": 100,
        "payload": "00 00 00 00 00 00 00 00",
        "dlc": 8,
        "script_path": None,
    }
    r.update(kw)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        with open("flags.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.mw = gui.MainWindow()

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def load(self, signals, **cfg):
        with open("ws_flags.json", "w", encoding="utf-8") as f:
            json.dump({"dbc_file": None, "sliders": [], "signals": signals, **cfg}, f)
        self.mw.CONFIG_FILE = "ws_flags.json"
        self.mw.load_config(auto=True)

    def rows(self):
        return [
            (
                it.text(gui.TX_COL_2_id),
                bool(it.data(gui.TX_COL_DATA, gui.TX_COL_DATA_ROLE_is_ext)),
                bool(it.data(gui.TX_COL_DATA, gui.TX_COL_DATA_ROLE_is_fd)),
                it.data(gui.TX_COL_DATA, gui.TX_COL_DATA_ROLE_dlc),
            )
            for it in self.mw._tx_items()
        ]

    def run_tx(self, ticks=1, is_fd=False):
        self.mw.can_if = FakeIf()
        self.mw.can_if.is_fd = is_fd
        self.mw.start_stop_transmission()
        for _ in range(ticks):
            for t in list(self.mw.timers):
                t.timeout.emit()
        return self.mw.can_if.flags


class ExtendedIdTests(Base):
    def test_json_ext_row_is_sent_extended(self):
        """1.6: a 29-bit row reaches send_frame with is_ext=True."""
        self.load([row(0x123), row(0x123, id="0x00000123", ext="Y", dlc=4)])
        self.assertEqual(
            self.rows(), [("0x123", False, False, 8), ("0x00000123", True, False, 4)]
        )
        flags = self.run_tx()
        self.assertCountEqual(
            flags, [(0x123, False, False, 8), (0x123, True, False, 4)]
        )

    def test_legacy_json_high_id_becomes_extended(self):
        """1.6: files without "ext" could only hold IDs > 0x7FF as extended."""
        self.load([row(0x18FF0001)])
        self.assertEqual(self.rows(), [("0x18FF0001", True, False, 8)])

    def test_workspace_round_trip_keeps_flags(self):
        """1.6 + 2.4: Save writes ext/fd from the roles, Load restores them."""
        self.load(
            [
                row(0x123, id="0x00000123", ext="Y"),
                row(0x200, fd="Y", dlc=12, payload=" ".join(["11"] * 12)),
            ]
        )
        self.mw._save_config_to_file("ws_saved.json")
        with open("ws_saved.json", encoding="utf-8") as f:
            saved = {
                s["id"]: (s["ext"], s["fd"], s["dlc"]) for s in json.load(f)["signals"]
            }
        self.assertEqual(saved, {"0x00000123": ("Y", "n", 8), "0x200": ("n", "Y", 12)})

    def test_caninterface_builds_extended_message(self):
        """1.6: send_frame no longer hard-codes is_extended_id=False."""
        sent = []
        iface = ci.CANInterface.__new__(ci.CANInterface)
        iface.bus = type("Bus", (), {"send": lambda self, m: sent.append(m)})()
        iface.send_frame(0x18FF0001, b"\x01\x02", 2, is_ext=True)
        iface.send_frame(0x123, b"\x01", 1)
        self.assertTrue(sent[0].is_extended_id)
        self.assertEqual(sent[0].arbitration_id, 0x18FF0001)
        self.assertFalse(sent[1].is_extended_id)

    def test_rx_passes_the_ext_flag(self):
        """1.7: the RX thread forwards is_extended_id to the callback."""
        frames = [can.Message(arbitration_id=0x123, data=b"\x01", is_extended_id=True)]
        iface = ci.CANInterface.__new__(ci.CANInterface)
        iface.error_frames = 0
        iface.running = True
        got = []

        class Bus:
            def recv(self, timeout):
                if frames:
                    return frames.pop(0)
                iface.running = False

        iface.bus = Bus()
        iface.receive_callback = lambda *a: got.append(a)
        iface._receive_loop()
        self.assertEqual(got[0][0], 0x123)
        self.assertIs(got[0][5], True)

    def test_rx_keeps_std_and_ext_apart(self):
        """1.7: std 0x123 and ext 0x123 are two RX rows with their own data."""
        rx = self.mw.rx_window
        for _ in range(3):
            rx.push_frame(0x123, b"\x11" * 8, 8, False, None, False)
        rx.push_frame(0x123, b"\x22" * 4, 4, False, None, True)
        rx.drain()
        rows = {r[0]: (r[3], r[4]) for r in h.rx_view_rows(rx)}
        self.assertEqual(
            rows,
            {"0x123": (" ".join(["11"] * 8), "3"), "0x00000123": ("22 22 22 22", "1")},
        )

    def test_rx_dbc_name_matches_the_id_format(self):
        """1.7: the DBC name of the ext message never lands on the std frame."""
        self.mw.rx_window.set_dbc(gui.load_dbc("flags.dbc"))
        self.assertEqual(self.mw.rx_window._dbc_name(0x123, False), "STD_123")
        self.assertEqual(self.mw.rx_window._dbc_name(0x123, True), "EXT_123")


class FdFlagTests(Base):
    def test_dbc_rows_take_fd_and_ext_from_the_dbc(self):
        """2.4: FD/ext come from the DBC message, not from the connection mode."""
        self.mw.dbc = gui.load_dbc("flags.dbc")
        self.mw.populate_signal_tree()
        self.assertEqual(
            self.rows(),
            [
                ("0x123", False, False, 8),
                ("0x00000123", True, False, 4),
                ("0x18FF0001", True, True, 16),
            ],
        )

    def test_json_fd_row_sends_fd(self):
        """2.4: an FD row from JSON is sent as FD (the role was missing before)."""
        self.load([row(0x200, fd="Y", dlc=12, payload=" ".join(["11"] * 12))])
        self.assertEqual(self.run_tx(is_fd=True), [(0x200, False, True, 12)])

    def test_fd_rows_skipped_on_classic_bus(self):
        """2.4: on a classic channel FD rows are skipped with one warning, not an error per tick."""
        self.load([row(0x100), row(0x200, fd="Y", dlc=12)])
        self.assertEqual(self.run_tx(ticks=3), [(0x100, False, False, 8)] * 3)
        warnings = [d for d in h.DIALOGS if d[0] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("0x200", warnings[0][2])

    def test_stored_dlc_clamped_to_frame_type(self):
        """2.4: classic rows carry at most 8 bytes, FD rows a valid FD length."""
        self.load([row(0x100, dlc=12), row(0x200, fd="Y", dlc=10)])
        self.assertEqual([r[3] for r in self.rows()], [8, 12])

    def test_payload_header(self):
        """2.9: no "(0 - 7)" on a table that carries 64-byte frames."""
        self.assertEqual(
            self.mw.signal_tree.headerItem().text(gui.TX_COL_6_payload), "Payload"
        )


class AddIdFormTests(Base):
    def dialog(self, existing=()):
        return gui.AddIdDialog(None, existing)

    def test_defaults(self):
        """2.2: the form proposes 100 ms and 8 bytes."""
        dlg = self.dialog()
        dlg.ed_id.setText("123")
        values, error = dlg.parse()
        self.assertIsNone(error)
        self.assertEqual(values["period"], 100)
        self.assertEqual(values["dlc"], 8)
        self.assertEqual((values["is_fd"], values["is_ext"]), (False, False))

    def test_id_range_depends_on_format(self):
        """2.3: 0x800 is not a standard ID, it is a valid extended one."""
        dlg = self.dialog()
        dlg.ed_id.setText("800")
        self.assertIsNotNone(dlg.parse()[1])
        dlg.cb_ext.setChecked(True)
        self.assertIsNone(dlg.parse()[1])
        dlg.ed_id.setText("20000000")
        self.assertIsNotNone(dlg.parse()[1])
        dlg.ed_id.setText("zz")
        self.assertIsNotNone(dlg.parse()[1])

    def test_duplicates_rejected_per_format(self):
        """2.3: std 0x123 exists -> std 0x123 refused, ext 0x123 accepted."""
        dlg = self.dialog({(0x123, False)})
        dlg.ed_id.setText("0x123")
        dlg.accept()
        self.assertIsNone(dlg.result_values)
        self.assertIn("already", dlg.lbl_error.text())
        dlg.cb_ext.setChecked(True)
        dlg.accept()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

    def test_fd_offers_only_fd_lengths(self):
        """2.3: DLC choices follow the frame type."""
        dlg = self.dialog()
        self.assertEqual(dlg.cb_dlc.count(), 8)
        dlg.cb_fd.setChecked(True)
        self.assertEqual(
            [dlg.cb_dlc.itemData(i) for i in range(dlg.cb_dlc.count())],
            list(gui.CAN_FD_LENGTHS),
        )

    def test_add_manual_id_adds_the_row(self):
        """2.1 + 2.3: Add ID goes through the form and adds one complete row."""

        def fake_exec(dlg):
            dlg.ed_id.setText("18FF0001")
            dlg.cb_ext.setChecked(True)
            dlg.cb_fd.setChecked(True)
            dlg.cb_dlc.setCurrentIndex(dlg.cb_dlc.findData(16))
            dlg.ed_name.setText("MY_ID")
            dlg.accept()
            return dlg.result()

        orig = gui.AddIdDialog.exec
        gui.AddIdDialog.exec = fake_exec
        try:
            self.mw.add_manual_id()
        finally:
            gui.AddIdDialog.exec = orig
        self.assertEqual(self.rows(), [("0x18FF0001", True, True, 16)])
        item = self.mw._tx_items()[0]
        self.assertEqual(item.text(gui.TX_COL_4_name), "MY_ID")
        self.assertEqual(item.text(gui.TX_COL_6_payload), " ".join(["00"] * 16))
        self.assertEqual(
            self.mw.signal_tree.itemWidget(item, gui.TX_COL_5_period).value(), 100
        )
        self.assertTrue(self.mw.btn_delete_all_ids.isEnabled())


class SortTests(Base):
    def test_period_sort_during_tx_keeps_every_id(self):
        """2.5: sorting by Period mid-TX no longer orphans a timer."""
        self.load(
            [row(0x100, period=300), row(0x200, period=100), row(0x300, period=200)]
        )
        self.run_tx()
        self.mw.can_if.flags.clear()
        self.mw.signal_tree.sortItems(gui.TX_COL_5_period, Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [it.text(gui.TX_COL_2_id) for it in self.mw._tx_items()],
            ["0x200", "0x300", "0x100"],
        )
        for t in list(self.mw.timers):
            t.timeout.emit()
        self.assertCountEqual(
            [f[0] for f in self.mw.can_if.flags], [0x100, 0x200, 0x300]
        )

    def test_id_sort_is_numeric_std_first(self):
        """2.5: IDs sort by value, standard before extended, not by text."""
        self.load(
            [
                row(0x18FF0001),
                row(0x7FF),
                row(0x123, id="0x00000123", ext="Y"),
                row(0x80),
            ]
        )
        self.mw.signal_tree.sortItems(gui.TX_COL_2_id, Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [it.text(gui.TX_COL_2_id) for it in self.mw._tx_items()],
            ["0x080", "0x7FF", "0x00000123", "0x18FF0001"],
        )

    def test_delete_stops_only_its_own_timer(self):
        """1.6: deleting ext 0x123 keeps std 0x123 transmitting."""
        self.load([row(0x123), row(0x123, id="0x00000123", ext="Y")])
        self.run_tx()
        self.mw.delete_signal_row(self.mw._find_tx_item(0x123, True))
        self.mw.can_if.flags.clear()
        for t in list(self.mw.timers):
            t.timeout.emit()
        self.assertEqual(self.mw.can_if.flags, [(0x123, False, False, 8)])


class LoadDbcTests(Base):
    def test_load_dbc_twice_adds_no_duplicates(self):
        """6.9: Load DBC adds only the missing messages and keeps manual rows."""
        self.load([row(0x555), row(0x123, period=20)])
        self.mw.dbc = gui.load_dbc("flags.dbc")
        self.mw.populate_signal_tree()
        self.mw.populate_signal_tree()
        ids = [r[0] for r in self.rows()]
        self.assertEqual(ids, ["0x123", "0x555", "0x00000123", "0x18FF0001"])
        kept = self.mw._find_tx_item(0x123, False)
        self.assertEqual(
            self.mw.signal_tree.itemWidget(kept, gui.TX_COL_5_period).value(), 20
        )


if __name__ == "__main__":
    unittest.main()

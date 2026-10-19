"""Phase 1 / sub-task 3 — TODO 2.6, 2.7, 2.8 (TX table mutations during TX).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import shutil
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import SIGNAL, Qt  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.utils import resource_path  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|255] "" ECU
"""


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        shutil.copy(
            resource_path("resources/script_templates/TPS_sawtooth.py"), "sawtooth.py"
        )
        self.mw = gui.MainWindow()
        self.items = {
            fid: self.mw._add_tx_row(fid, f"M{fid:X}", period=100)
            for fid in (0x100, 0x200, 0x300)
        }
        self.mw.can_if = FakeIf()

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def timer(self, fid):
        return self.mw._timer_of(self.items[fid])

    def tick(self, n=1):
        for _ in range(n):
            for t in list(self.mw.timers):
                t.timeout.emit()

    def sent(self, fid):
        return [d for f, d in self.mw.can_if.sent if f == fid]

    def set_enabled(self, fid, on):
        h.tx_check(self.mw, self.items[fid], on)


class ToggleTests(Base):
    def test_toggling_one_row_leaves_the_other_timers_alone(self):
        """2.6: unchecking/re-checking 0x300 must not recreate 0x100/0x200's timers."""
        self.mw.start_stop_transmission()
        t100, t200, t300 = self.timer(0x100), self.timer(0x200), self.timer(0x300)
        self.set_enabled(0x300, False)
        self.assertIsNone(self.timer(0x300))
        self.assertIs(self.timer(0x100), t100)
        self.assertIs(self.timer(0x200), t200)
        self.set_enabled(0x300, True)
        self.assertIsNot(self.timer(0x300), t300)
        self.assertIs(self.timer(0x100), t100)
        self.assertTrue(t100.isActive() and t200.isActive())

    def test_disable_all_is_one_sync_not_a_restart_per_row(self):
        """2.6: Disable All stops every timer without restarting TX per row."""
        self.mw.start_stop_transmission()
        restarts = []
        orig = self.mw.start_tx
        self.mw.start_tx = lambda: restarts.append(1) or orig()
        try:
            self.mw.disable_all_ids_tx()
            self.assertEqual(self.mw.timers, [])
            self.assertTrue(self.mw.tx_running)
            self.mw.disable_all_ids_tx()  # Enable All
            self.assertEqual(len(self.mw.timers), 3)
        finally:
            self.mw.start_tx = orig
        self.assertEqual(restarts, [])

    def test_add_id_during_tx_starts_only_the_new_row(self):
        """2.6: a new manual row starts its own timer, the others keep theirs."""
        self.mw.start_stop_transmission()
        t100 = self.timer(0x100)

        def fake_exec(dlg):
            dlg.ed_id.setText("400")
            dlg.accept()
            return dlg.result()

        orig = gui.AddIdDialog.exec
        gui.AddIdDialog.exec = fake_exec
        try:
            self.mw.add_manual_id()
        finally:
            gui.AddIdDialog.exec = orig
        self.assertIs(self.timer(0x100), t100)
        self.assertEqual(len(self.mw.timers), 4)
        self.tick()
        self.assertEqual(len(self.sent(0x400)), 1)

    def test_script_linked_during_tx_takes_effect(self):
        """2.6: no restart needed any more, so the script must be picked up live."""
        self.mw.start_stop_transmission()
        self.tick()
        self.mw._set_script_link(self.items[0x100], "sawtooth.py")
        self.tick(2)
        self.assertEqual([d[-1] for d in self.sent(0x100)], [0, 1, 2])

    def test_slider_added_and_removed_during_tx(self):
        """2.6: slider overrides are read per tick: add applies, remove stops applying."""
        with open("tbl.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.mw.dbc = gui.load_dbc("tbl.dbc")
        self.mw.start_stop_transmission()
        self.tick()
        w = gui.QWidget()
        w.frame_id, w.is_ext, w.min_val, w.step = 0x100, False, 0, 1
        w.signal = next(s for s in self.mw.dbc.messages[0].signals)
        w.slider = gui.QSlider()
        w.slider.setRange(0, 255)
        w.slider.setValue(42)
        self.mw.slider_widgets.append(w)
        self.tick()
        self.mw.remove_slider_widget(w)
        h.tx_edit(
            self.mw, self.items[0x100], gui.TX_COL_6_payload, "07 00 00 00 00 00 00 00"
        )
        self.tick()
        self.assertEqual([d[0] for d in self.sent(0x100)], [0, 42, 7])


class PeriodTests(Base):
    def test_period_handler_connected_once(self):
        """2.7: Start/Stop TX five times must not stack period handlers."""
        signal = SIGNAL("period_changed(PyObject)")
        before = self.mw.tx_model.receivers(signal)
        for _ in range(5):
            self.mw.start_stop_transmission()
            self.mw.start_stop_transmission()
        self.assertEqual(self.mw.tx_model.receivers(signal), before)
        self.assertEqual(before, 1)

    def test_period_edit_retimes_only_that_row(self):
        """2.7: a period edit during TX changes that timer's interval in place."""
        self.mw.start_stop_transmission()
        t100, t200 = self.timer(0x100), self.timer(0x200)
        h.tx_edit(self.mw, self.items[0x100], gui.TX_COL_5_period, 20)
        self.assertIs(self.timer(0x100), t100)
        self.assertEqual(t100.interval(), 20)
        self.assertEqual(t200.interval(), 100)

    def test_period_is_clamped(self):
        h.tx_edit(self.mw, self.items[0x100], gui.TX_COL_5_period, 0)
        self.assertEqual(self.items[0x100].period, 1)


class PayloadWriteTests(Base):
    def test_tx_writes_do_not_run_the_edit_validation(self):
        """2.8: payloads written by TX never go through the user-edit check."""
        rejected = []
        self.mw.tx_model.payload_rejected.connect(lambda *a: rejected.append(a))
        self.mw._set_script_link(self.items[0x100], "sawtooth.py")
        self.mw.start_stop_transmission()
        self.tick(5)
        self.assertEqual(rejected, [])
        self.assertEqual(
            h.tx_cell(self.mw, self.items[0x100], gui.TX_COL_6_payload)[-2:], "05"
        )

    def test_tx_writes_repaint_at_the_refresh_not_per_frame(self):
        """2.12: 5 ticks x 3 rows -> no repaint until flush(), then one signal."""
        self.mw._set_script_link(self.items[0x100], "sawtooth.py")
        self.mw.start_stop_transmission()
        self.mw.tx_model.flush()
        changed = []
        self.mw.tx_model.dataChanged.connect(lambda *a: changed.append(a))
        self.tick(5)
        self.assertEqual(changed, [])
        self.mw.tx_model.flush()
        self.assertEqual(len(changed), 1)

    def test_user_edit_is_still_validated(self):
        """2.8: a bad manual payload is refused; the row keeps its own."""
        good = "01 02 03 04 05 06 07 08"
        self.assertTrue(
            h.tx_edit(self.mw, self.items[0x200], gui.TX_COL_6_payload, good)
        )
        self.assertFalse(
            h.tx_edit(self.mw, self.items[0x200], gui.TX_COL_6_payload, "zz")
        )
        self.assertEqual(
            h.tx_cell(self.mw, self.items[0x200], gui.TX_COL_6_payload), good
        )
        self.assertEqual(h.DIALOGS[-1][0], "warning")


class ViewTests(Base):
    def test_rows_hold_no_widgets(self):
        """2.13: buttons and spin boxes are painted/edited by delegates."""
        proxy = self.mw.tx_view.model()
        for r in range(proxy.rowCount()):
            for c in range(proxy.columnCount()):
                self.assertIsNone(self.mw.tx_view.indexWidget(proxy.index(r, c)))

    def test_delete_button_removes_its_row(self):
        """2.13: the painted Delete button acts on the row it is drawn on."""
        self.mw.start_stop_transmission()
        self.mw.tx_buttons.delete_clicked.emit(self.items[0x200])
        self.assertEqual(h.tx_view_ids(self.mw), ["0x100", "0x300"])
        self.assertIsNone(self.mw._timer_of(self.items[0x200]))

    def test_click_on_the_painted_buttons(self):
        """2.13: a click in the script cell links; in the delete cell deletes."""
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        self.mw.resize(1200, 600)
        self.mw.show()
        picked = []
        self.mw.modify_payload_script = lambda e: picked.append(e)
        self.mw.tx_buttons.link_clicked.disconnect()
        self.mw.tx_buttons.link_clicked.connect(self.mw.modify_payload_script)
        view = self.mw.tx_view
        rect = view.visualRect(h.tx_index(self.mw, self.items[0x300], 7))
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(rect.left() + 10, rect.center().y()),
        )
        self.assertEqual(picked, [self.items[0x300]])
        rect = view.visualRect(h.tx_index(self.mw, self.items[0x100], 0))
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            rect.center(),
        )
        self.assertEqual(h.tx_view_ids(self.mw), ["0x200", "0x300"])


if __name__ == "__main__":
    unittest.main()

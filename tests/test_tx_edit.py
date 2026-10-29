"""TODO 14.1 / 14.3 - TX row right-click menu and Edit Properties.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import shutil
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.tx_model as tx_model  # noqa: E402
import src.tx_panel as tx_panel  # noqa: E402
from src.utils import resource_path  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

PAYLOAD = "01 02 03 04 05 06 07 08"


def fill(dlg, id=None, ext=None, fd=None, rtr=None, dlc=None, period=None, name=None):
    """Change some fields of the form, in the order a user would."""
    if id is not None:
        dlg.ed_id.setText(id)
    if ext is not None:
        dlg.cb_ext.setChecked(ext)
    if fd is not None:
        dlg.cb_fd.setChecked(fd)
    if rtr is not None:
        dlg.cb_rtr.setChecked(rtr)
    if dlc is not None:
        dlg.cb_dlc.setCurrentIndex(dlg.cb_dlc.findData(dlc))
    if period is not None:
        dlg.sp_period.setValue(period)
    if name is not None:
        dlg.ed_name.setText(name)


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self._orig_exec = tx_panel.AddIdDialog.exec
        self.mw = gui.MainWindow()
        self.a = self.mw._add_tx_row(0x100, "ID_100", period=100, payload=PAYLOAD)
        self.b = self.mw._add_tx_row(0x200, "MSG_B", period=50)
        self.mw.can_if = FakeIf()
        self.mw._dirty = False

    def tearDown(self):
        tx_panel.AddIdDialog.exec = self._orig_exec
        self.mw.stop_tx()
        self.mw.can_if = None
        self.mw._dirty = False  # don't trip the close confirm
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def edit(self, entry, ok=True, **fields):
        """Edit Properties of `entry`: change `fields` in the form, then OK.

        Returns the entry now in that row (a new one when the frame changed).
        """
        row = self.mw.tx_model.row_of(entry)
        self.forms = []

        def fake_exec(dlg):
            self.forms.append((dlg.windowTitle(), dlg.parse()[0]))
            fill(dlg, **fields)
            dlg.accept() if ok else dlg.reject()
            return dlg.result()

        tx_panel.AddIdDialog.exec = fake_exec
        self.mw.edit_tx_row(entry)
        return self.mw.tx_model.entries()[row]

    def sent(self, fid):
        return [d for f, d in self.mw.can_if.sent if f == fid]


class FormTests(Base):
    def test_form_is_filled_in_with_the_row(self):
        """14.3: every field shows the row's configuration."""
        e = self.mw._add_tx_row(
            0x18FF0001, "BIG", period=20, dlc=16, is_fd=True, is_ext=True
        )
        dlg = tx_panel.AddIdDialog(None, {x.key for x in self.mw._tx_entries()}, e)
        self.assertEqual(dlg.windowTitle(), "Edit Properties - 0x18FF0001 BIG")
        self.assertEqual(dlg.ed_id.text(), "0x18FF0001")
        self.assertTrue(dlg.cb_ext.isChecked())
        self.assertTrue(dlg.cb_fd.isChecked())
        self.assertFalse(dlg.cb_rtr.isChecked())
        self.assertEqual(dlg.cb_dlc.currentData(), 16)
        self.assertEqual(dlg.sp_period.value(), 20)
        self.assertEqual(dlg.ed_name.text(), "BIG")
        # Its own ID is not "already in the TX table"
        values, error = dlg.parse()
        self.assertIsNone(error)
        self.assertEqual(
            values,
            {
                "frame_id": 0x18FF0001,
                "name": "BIG",
                "period": 20,
                "dlc": 16,
                "is_fd": True,
                "is_ext": True,
                "is_rtr": False,
            },
        )
        dlg.deleteLater()

    def test_rtr_row_is_filled_in(self):
        e = self.mw._add_tx_row(0x300, "REQ", dlc=3, is_rtr=True)
        dlg = tx_panel.AddIdDialog(None, (), e)
        self.assertTrue(dlg.cb_rtr.isChecked())
        self.assertEqual(dlg.cb_dlc.currentData(), 3)
        dlg.deleteLater()

    def test_another_rows_id_is_refused(self):
        """14.3: moving a row onto another row's ID keeps the form open."""
        dlg = tx_panel.AddIdDialog(None, {x.key for x in self.mw._tx_entries()}, self.a)
        dlg.ed_id.setText("200")
        dlg.accept()
        self.assertIsNone(dlg.result_values)
        self.assertIn("already", dlg.lbl_error.text())
        dlg.cb_ext.setChecked(True)  # ext 0x200 is another frame: free
        dlg.accept()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        dlg.deleteLater()

    def test_add_id_form_is_unchanged(self):
        """Without an entry it is still the empty Add Manual ID form."""
        dlg = tx_panel.AddIdDialog(None, ())
        self.assertEqual(dlg.windowTitle(), "Add Manual ID")
        self.assertEqual(dlg.ed_id.text(), "")
        dlg.ed_id.setText("7")
        self.assertEqual(dlg.parse()[0]["name"], "ID_7")
        dlg.deleteLater()


class SameFrameTests(Base):
    def test_unchanged_form_changes_nothing(self):
        self.assertIs(self.edit(self.a), self.a)
        self.assertEqual(self.forms[0][0], "Edit Properties - 0x100 ID_100")
        self.assertFalse(self.mw._dirty)

    def test_cancel_changes_nothing(self):
        self.assertIs(self.edit(self.a, ok=False, name="X", id="300"), self.a)
        self.assertEqual(self.a.name, "ID_100")
        self.assertFalse(self.mw._dirty)

    def test_name_and_period_edited_in_place_keep_the_job(self):
        """14.3: same frame -> same entry, same TX job (phase kept), retimed."""
        self.mw.start_stop_transmission()
        job = self.mw.tx_scheduler.job(self.a)
        self.assertIs(self.edit(self.a, name="RENAMED", period=20), self.a)
        self.assertIs(self.mw.tx_scheduler.job(self.a), job)
        self.assertEqual(job.period_ns, 20_000_000)
        self.assertEqual(h.tx_cell(self.mw, self.a, tx_model.TX_COL_4_name), "RENAMED")
        self.assertEqual(h.tx_cell(self.mw, self.a, tx_model.TX_COL_5_period), "20")
        self.assertTrue(self.mw._dirty)

    def test_script_keeps_running_through_a_rename(self):
        """3.2: the row's script instance is not reset by a rename."""
        shutil.copy(
            resource_path("resources/script_templates/TPS_sawtooth.py"), "saw.py"
        )
        self.mw._set_script_link(self.a, "saw.py")
        self.mw.start_stop_transmission()
        h.fire_tx(self.mw, 2)
        self.edit(self.a, name="RENAMED")
        h.fire_tx(self.mw, 2)
        self.assertEqual([d[-1] for d in self.sent(0x100)], [1, 2, 3, 4])


class NewFrameTests(Base):
    def test_new_id_takes_the_same_row(self):
        """14.3: no delete + re-add: same row, payload, enable, script link."""
        self.mw._set_script_link(self.a, "C:/scripts/x.py")
        self.mw.tx_model.set_error(self.a, "old error")
        new = self.edit(self.a, id="123")
        self.assertIsNot(new, self.a)
        self.assertEqual(self.mw.tx_model.row_of(new), 0)
        self.assertIsNone(self.mw._find_entry(0x100, False))
        self.assertIs(self.mw._find_entry(0x123, False), new)
        self.assertEqual(h.tx_cell(self.mw, new, tx_model.TX_COL_6_payload), PAYLOAD)
        self.assertEqual(new.script_path, "C:/scripts/x.py")
        self.assertTrue(new.enabled)
        self.assertIsNone(new.error)
        self.assertEqual(new.name, "ID_123")  # the automatic name follows the ID
        self.assertEqual(h.tx_view_ids(self.mw), ["0x123", "0x200"])
        self.assertTrue(self.mw._dirty)

    def test_given_name_is_kept_on_a_new_id(self):
        self.assertEqual(self.edit(self.b, id="201").name, "MSG_B")

    def test_new_id_during_tx(self):
        """14.3: the old ID stops, the new one starts, other rows keep their job."""
        self.mw.start_stop_transmission()
        job_b = self.mw.tx_scheduler.job(self.b)
        h.fire_tx(self.mw)
        new = self.edit(self.a, id="18FF0001", ext=True)
        self.assertIs(self.mw.tx_scheduler.job(self.b), job_b)
        self.assertIsNone(self.mw.tx_scheduler.job(self.a))
        self.assertIsNotNone(self.mw.tx_scheduler.job(new))
        h.fire_tx(self.mw)
        self.assertEqual(len(self.sent(0x100)), 1)
        self.assertEqual(self.sent(0x18FF0001), [bytes.fromhex(PAYLOAD)])
        self.assertIn((0x18FF0001, True, False, 8), self.mw.can_if.flags)

    def test_disabled_row_stays_disabled(self):
        h.tx_check(self.mw, self.a, False)
        self.mw.start_stop_transmission()
        new = self.edit(self.a, id="123")
        self.assertFalse(new.enabled)
        self.assertIsNone(self.mw.tx_scheduler.job(new))

    def test_dlc_change_keeps_the_leading_bytes(self):
        """14.3: shorter -> truncated, longer -> zero-padded."""
        short = self.edit(self.a, dlc=4)
        self.assertEqual(short.payload, bytes([1, 2, 3, 4]))
        longer = self.edit(short, dlc=6)
        self.assertEqual(longer.payload, bytes([1, 2, 3, 4, 0, 0]))

    def test_rtr_edit(self):
        new = self.edit(self.a, rtr=True, dlc=2)
        self.assertTrue(new.is_rtr)
        self.assertEqual(
            h.tx_cell(self.mw, new, tx_model.TX_COL_6_payload), "(RTR, DLC 2)"
        )

    def test_fd_row_on_a_classic_bus_warns_and_is_not_sent(self):
        self.mw.start_stop_transmission()
        new = self.edit(self.a, fd=True, dlc=16)
        self.assertEqual(len(new.payload), 16)
        self.assertEqual(new.payload[:8], bytes.fromhex(PAYLOAD))
        self.assertIsNone(self.mw.tx_scheduler.job(new))
        self.assertIsNone(self.mw.tx_scheduler.job(self.a))
        self.assertEqual([d[1] for d in h.DIALOGS], ["CAN FD"])
        self.assertIn("0x100 ID_100", h.DIALOGS[0][2])

    def test_new_id_gets_its_own_script_instance(self):
        """3.1: one instance per ID - a new ID starts its script fresh."""
        shutil.copy(
            resource_path("resources/script_templates/TPS_sawtooth.py"), "saw.py"
        )
        self.mw._set_script_link(self.a, "saw.py")
        self.mw.start_stop_transmission()
        h.fire_tx(self.mw, 3)
        self.edit(self.a, id="123")
        h.fire_tx(self.mw, 2)
        self.assertEqual([d[-1] for d in self.sent(0x100)], [1, 2, 3])
        self.assertEqual([d[-1] for d in self.sent(0x123)], [1, 2])


class MenuTests(Base):
    # The menus are children of the TX view: they go with the window
    def menu(self, entry):
        menu = self.mw._tx_row_menu(entry)
        return {a.text(): a for a in menu.actions() if not a.isSeparator()}

    def test_menu_entries(self):
        self.assertEqual(
            [a.text() for a in self.mw._tx_row_menu(self.a).actions()],
            [
                "Edit Properties...",
                "",
                "Disable",
                "Send Now",
                "",
                "Link Script...",
                "Unlink Script",
                "",
                "Delete",
            ],
        )
        self.assertFalse(self.menu(self.a)["Unlink Script"].isEnabled())
        self.mw._set_script_link(self.a, "C:/scripts/x.py")
        self.assertTrue(self.menu(self.a)["Unlink Script"].isEnabled())

    def test_edit_properties_action_opens_the_filled_form(self):
        def fake_exec(dlg):
            self.assertEqual(dlg.ed_id.text(), "0x200")
            dlg.ed_name.setText("FROM_MENU")
            dlg.accept()
            return dlg.result()

        tx_panel.AddIdDialog.exec = fake_exec
        self.menu(self.b)["Edit Properties..."].trigger()
        self.assertEqual(self.b.name, "FROM_MENU")

    def test_disable_enable(self):
        """Same path as the En box: the row's job stops and starts again."""
        self.mw.start_stop_transmission()
        self.menu(self.a)["Disable"].trigger()
        self.assertFalse(self.a.enabled)
        self.assertIsNone(self.mw.tx_scheduler.job(self.a))
        self.assertTrue(self.mw._dirty)
        self.menu(self.a)["Enable"].trigger()
        self.assertTrue(self.a.enabled)
        self.assertIsNotNone(self.mw.tx_scheduler.job(self.a))

    def test_send_now_sends_the_clicked_row(self):
        self.mw.sp_burst.setValue(3)
        self.menu(self.b)["Send Now"].trigger()
        self.assertEqual(len(self.sent(0x200)), 3)
        self.assertEqual(self.sent(0x100), [])

    def test_unlink_and_delete(self):
        self.mw._set_script_link(self.a, "C:/scripts/x.py")
        self.menu(self.a)["Unlink Script"].trigger()
        self.assertIsNone(self.a.script_path)
        self.menu(self.a)["Delete"].trigger()
        self.assertEqual(h.tx_view_ids(self.mw), ["0x200"])

    def test_right_click_selects_the_row_and_opens_its_menu(self):
        """14.1: the menu is the clicked row's, and that row becomes the selection."""
        opened = []

        class Menu:
            def exec(self, pos):
                opened.append(self.entry)

            def deleteLater(self):
                pass

        def row_menu(entry):
            menu = Menu()
            menu.entry = entry
            return menu

        self.mw._tx_row_menu = row_menu
        self.mw.tx_view.resize(800, 300)
        rect = self.mw.tx_view.visualRect(
            h.tx_index(self.mw, self.b, tx_model.TX_COL_4_name)
        )
        self.mw._tx_context_menu(rect.center())
        self.mw._tx_context_menu(QPoint(rect.center().x(), 280))  # below the rows
        self.assertEqual(opened, [self.b])
        self.assertIs(self.mw._selected_tx_entry(), self.b)


if __name__ == "__main__":
    unittest.main()

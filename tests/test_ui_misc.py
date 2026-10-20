"""Phase 3 / sub-task 9 — TODO 4.10 (enum combo), 6.8 (recent / unsaved / shortcuts),
10.7 (About).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402
import src.gui as gui  # noqa: E402
import src.workspace as workspace  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|255] "rpm" ECU
 SG_ SIG_MODE : 8|8@1+ (1,0) [0|3] "" ECU
VAL_ 256 SIG_MODE 0 "OFF" 1 "ON" 2 "AUTO" ;
"""


class FakeSettings:
    """In-memory stand-in for QSettings, so tests never touch the registry."""

    _store = {}

    def __init__(self, *a):
        pass

    def value(self, key, default=None):
        return FakeSettings._store.get(key, default)

    def setValue(self, key, val):
        FakeSettings._store[key] = val


class Base(unittest.TestCase):
    def setUp(self):
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self._orig_settings = workspace.QSettings
        workspace.QSettings = FakeSettings
        FakeSettings._store = {}
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig_scan
        workspace.QSettings = self._orig_settings
        self.mw._dirty = False  # don't trip the close confirm
        h.dispose(self.mw)

    def dbc_path(self, name="m.dbc"):
        p = os.path.join(h.WORKDIR, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(DBC)
        return p


class EnumComboTests(Base):
    def test_enum_signal_builds_a_combo_not_a_slider(self):
        self.mw.dbc = dbc_loader.load_dbc(self.dbc_path())
        msg = self.mw.dbc.messages[0]
        sig = next(s for s in msg.signals if s.name == "SIG_MODE")
        w = self.mw._add_slider_widget(msg, sig)
        self.assertTrue(hasattr(w, "combo"))
        self.assertEqual(w.combo.count(), 3)  # OFF/ON/AUTO
        w.combo.setCurrentIndex(w.combo.findText("2: AUTO"))
        self.assertEqual(w.value(), 2.0)  # physical value of raw 2

    def test_enum_override_feeds_the_tx_snapshot(self):
        self.mw.dbc = dbc_loader.load_dbc(self.dbc_path())
        self.mw._add_tx_row(0x100, "A", dlc=8)
        msg = self.mw.dbc.messages[0]
        sig = next(s for s in msg.signals if s.name == "SIG_MODE")
        w = self.mw._add_slider_widget(msg, sig)
        w.combo.setCurrentIndex(w.combo.findText("1: ON"))
        overrides = self.mw._slider_overrides[(0x100, False)]
        self.assertEqual([(s.name, v) for s, v in overrides], [("SIG_MODE", 1.0)])

    def test_enum_restore_picks_the_saved_value(self):
        self.mw.dbc = dbc_loader.load_dbc(self.dbc_path())
        msg = self.mw.dbc.messages[0]
        sig = next(s for s in msg.signals if s.name == "SIG_MODE")
        w = self.mw._add_slider_widget(msg, sig, value=2)
        self.assertEqual(w.value(), 2.0)


class DirtyTests(Base):
    def test_clean_at_start(self):
        self.assertFalse(self.mw._dirty)
        self.assertNotIn("*", self.mw.windowTitle())

    def test_add_row_marks_dirty(self):
        self.mw._add_tx_row(0x100, "A")
        self.assertTrue(self.mw._dirty)
        self.assertIn("*", self.mw.windowTitle())

    def test_save_clears_dirty(self):
        self.mw._add_tx_row(0x100, "A")
        self.mw._save_config_to_file(os.path.join(h.WORKDIR, "ws.json"))
        self.assertFalse(self.mw._dirty)
        self.assertNotIn("*", self.mw.windowTitle())

    def test_load_is_not_marked_dirty(self):
        self.mw._add_tx_row(0x100, "A")
        path = os.path.join(h.WORKDIR, "ws2.json")
        self.mw._save_config_to_file(path)
        self.mw._add_tx_row(0x200, "B")  # dirty again
        self.mw.load_config(path=path)
        self.assertFalse(self.mw._dirty)  # a freshly loaded workspace is clean

    def test_tx_repaint_does_not_mark_dirty(self):
        e = self.mw._add_tx_row(0x100, "A", dlc=2, payload="00 00")
        self.mw._save_config_to_file(os.path.join(h.WORKDIR, "ws3.json"))
        self.assertFalse(self.mw._dirty)
        # A programmatic payload update (as the TX thread does) must not dirty
        self.mw.tx_model.set_payload(e, b"\x01\x02")
        self.mw.tx_model.flush()
        self.assertFalse(self.mw._dirty)


class ConfirmDiscardTests(Base):
    def test_cancel_blocks_load(self):
        self.mw._add_tx_row(0x100, "A")  # dirty
        path = os.path.join(h.WORKDIR, "other.json")
        self.mw._save_config_to_file(path)  # path exists; clears dirty
        self.mw._add_tx_row(0x200, "B")  # dirty again
        orig = QMessageBox.question
        try:
            QMessageBox.question = staticmethod(
                lambda *a, **k: QMessageBox.StandardButton.Cancel
            )
            self.mw.load_config(path=path)
        finally:
            QMessageBox.question = orig
        # Cancelled: the second row is still there, nothing loaded over it
        self.assertIn(0x200, [e.frame_id for e in self.mw._tx_entries()])

    def test_close_respects_cancel(self):
        self.mw._add_tx_row(0x100, "A")
        orig = QMessageBox.question
        try:
            QMessageBox.question = staticmethod(
                lambda *a, **k: QMessageBox.StandardButton.Cancel
            )
            from PySide6.QtGui import QCloseEvent

            ev = QCloseEvent()
            self.mw.closeEvent(ev)
            self.assertFalse(ev.isAccepted())
        finally:
            QMessageBox.question = orig


class RecentFilesTests(Base):
    def test_save_and_load_populate_recent(self):
        p1 = os.path.join(h.WORKDIR, "r1.json")
        self.mw._save_config_to_file(p1)
        self.assertIn(os.path.abspath(p1), self.mw._recent_files())
        self.assertTrue(self.mw.menu_recent.isEnabled())
        self.assertIn(
            os.path.abspath(p1),
            [a.text() for a in self.mw.menu_recent.actions()],
        )

    def test_recent_is_deduplicated_and_capped(self):
        for i in range(workspace.RECENT_MAX + 3):
            self.mw._add_recent(os.path.join(h.WORKDIR, f"f{i}.json"))
        self.assertEqual(len(self.mw._recent_files()), workspace.RECENT_MAX)
        self.mw._add_recent(os.path.join(h.WORKDIR, "f0.json"))  # re-add -> front
        self.assertEqual(
            self.mw._recent_files()[0],
            os.path.abspath(os.path.join(h.WORKDIR, "f0.json")),
        )


class ShortcutAboutTests(Base):
    def test_shortcuts_bound(self):
        from PySide6.QtGui import QAction

        shortcuts = {
            a.shortcut().toString()
            for a in self.mw.findChildren(QAction)
            if not a.shortcut().isEmpty()
        }
        self.assertIn(QKeySequence(QKeySequence.StandardKey.Save).toString(), shortcuts)
        self.assertIn(QKeySequence(QKeySequence.StandardKey.Open).toString(), shortcuts)

    def test_about_shows_version(self):
        from src.exceptions_logger import __version__

        shown = {}
        orig = QMessageBox.about
        try:
            QMessageBox.about = staticmethod(
                lambda parent, title, text: shown.update(title=title, text=text)
            )
            self.mw.show_about()
        finally:
            QMessageBox.about = orig
        self.assertIn(__version__, shown["text"])
        self.assertIn("CANino", shown["title"])


if __name__ == "__main__":
    unittest.main()

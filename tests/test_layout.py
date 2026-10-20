"""1.7.1 — TODO 9.9: main-window layout (menus, dock, status bar, file names
on the Load DBC and Link Log buttons).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtWidgets import QDockWidget, QFileDialog, QLabel  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from test_signal_plot import make_dbc  # noqa: E402


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def menu_titles(self):
        return [a.text() for a in self.mw.menuBar().actions()]

    def test_menus(self):
        self.assertEqual(
            self.menu_titles(), ["&File", "&Scripts", "&Tools", "&View", "&Help"]
        )
        tools = self.mw.menuBar().actions()[2].menu()
        self.assertEqual(
            [a.text() for a in tools.actions() if not a.isSeparator()],
            ["XMetro", "Signal Plot", "VAGILETTA"],
        )

    def test_sliders_dock_toggles_from_view_menu(self):
        dock = self.mw.findChild(QDockWidget, "slider_dock")
        self.assertIs(dock, self.mw.slider_dock)
        self.assertIn(dock.toggleViewAction(), self.mw.view_menu.actions())

    def test_status_bar_holds_bus_labels(self):
        status = self.mw.statusBar()
        self.assertIs(self.mw.lbl_bus_status.parent(), status)
        self.assertIs(self.mw.lbl_busload.parent(), status)
        logos = [w for w in status.findChildren(QLabel) if w.pixmap() is not None]
        self.assertGreaterEqual(len([p for p in logos if not p.pixmap().isNull()]), 2)

    def test_load_dbc_button_shows_the_file(self):
        self.assertEqual(self.mw.btn_load_dbc.text(), "Load DBC")
        self.mw._apply_dbc(make_dbc("layout.dbc"))
        self.assertEqual(self.mw.btn_load_dbc.text(), "layout.dbc")
        self.assertIn("layout.dbc", self.mw.btn_load_dbc.toolTip())
        self.mw._apply_dbc(None)  # cleared workspace
        self.assertEqual(self.mw.btn_load_dbc.text(), "Load DBC")

    def test_link_log_button_shows_the_file(self):
        rx = self.mw.rx_window
        path = os.path.join(h.WORKDIR, "capture.trc")
        orig = QFileDialog.getSaveFileName
        try:
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
            rx.link_csv_file()
        finally:
            QFileDialog.getSaveFileName = orig
        self.assertEqual(rx.btn_link_csv.text(), "capture.trc")
        self.assertIn(path, rx.btn_link_csv.toolTip())

    def test_decoded_panel_toggle(self):
        action = next(
            a for a in self.mw.view_menu.actions() if a.text().startswith("Decoded")
        )
        action.setChecked(False)
        self.assertTrue(self.mw.rx_window.decoded.isHidden())
        action.setChecked(True)
        self.assertFalse(self.mw.rx_window.decoded.isHidden())


if __name__ == "__main__":
    unittest.main()

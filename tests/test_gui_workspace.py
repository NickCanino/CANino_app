"""Phase 0 / sub-task 2 — TODO 9.1, 9.2, 6.1, 6.2, 6.3, 4.1, 4.2, 4.3.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
)  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.utils import resource_path  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|100] "" ECU
 SG_ SIG_Y : 8|8@1+ (1,0) [0|255] "" ECU
"""

ROW = {
    "enabled": True,
    "id": "0x100",
    "fd": "n",
    "name": "MSG_A",
    "period": 100,
    "payload": "00 00 00 00 00 00 00 00",
    "dlc": 8,
    "script_path": None,
}


def slider_cfg(name, value):
    return {
        "msg_name": name,
        "signal_name": name,
        "frame_id": 256,
        "min_val": 0,
        "max_val": 255,
        "step": 1,
        "unit": "",
        "value_index": value,
    }


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        with open("probe.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def load(self, cfg):
        with open("ws.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.mw.CONFIG_FILE = "ws.json"
        self.mw.load_config(auto=True)

    def test_rx_gets_the_workspace_dbc(self):
        """6.1: RX names come from the DBC linked in the workspace."""
        self.load({"dbc_file": "probe.dbc", "signals": [ROW], "sliders": []})
        self.assertIsNotNone(self.mw.rx_window.dbc)

    def test_row_buttons_enabled_without_sliders(self):
        """6.2: Disable/Delete All follow the table even when the file has no sliders."""
        self.load({"dbc_file": None, "signals": [ROW], "sliders": []})
        self.assertTrue(self.mw.btn_disable_all_ids.isEnabled())
        self.assertTrue(self.mw.btn_delete_all_ids.isEnabled())

    def test_sliders_without_dbc_are_skipped(self):
        """6.3: no AttributeError/partial load; a warning instead."""
        self.load(
            {
                "dbc_file": "missing.dbc",
                "signals": [ROW],
                "sliders": [slider_cfg("SIG_X", 1)],
            }
        )
        kinds = [d[0] for d in h.DIALOGS]
        self.assertNotIn("critical", kinds)
        self.assertIn("warning", kinds)
        self.assertEqual(self.mw.signal_tree.topLevelItemCount(), 1)
        self.assertEqual(self.mw.slider_widgets, [])

    def test_sliders_live_inside_the_scroll_area(self):
        """4.1: the slider layout belongs to the scroll area's widget."""
        scroll = self.mw.findChildren(QScrollArea)[0]
        self.assertIs(self.mw.slider_container.parentWidget(), scroll.widget())

    def test_trash_removes_its_own_slider_and_label_shows_value(self):
        """4.2 + 4.3 on sliders restored from a workspace."""
        self.load(
            {
                "dbc_file": "probe.dbc",
                "signals": [ROW],
                "sliders": [slider_cfg("SIG_X", 10), slider_cfg("SIG_Y", 20)],
            }
        )
        first, second = self.mw.slider_widgets
        labels = [
            lbl.text()
            for lbl in first.findChildren(QLabel)
            if lbl.text().startswith("Val")
        ]
        self.assertEqual(labels, ["Val: 10 "])
        first.findChildren(QPushButton)[0].click()
        self.assertEqual([w.signal.name for w in self.mw.slider_widgets], ["SIG_Y"])


class ResourcePathTests(unittest.TestCase):
    def test_resources_resolve_from_source(self):
        """9.1 + 9.2: icons, banner, arduino-cli and VERSION are found from source."""
        for rel in (
            "resources/figures/app_logo.ico",
            "resources/figures/dii_logo.png",
            "tools/arduino-cli.exe",
            "VERSION",
        ):
            with self.subTest(rel=rel):
                self.assertTrue(os.path.exists(resource_path(rel)), resource_path(rel))


if __name__ == "__main__":
    unittest.main()

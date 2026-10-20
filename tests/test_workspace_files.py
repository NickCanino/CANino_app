"""Phase 1 / sub-task 6 — TODO 6.4 (Load replaces), 6.5 (portable paths), 6.6 (Save).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import os
import tempfile
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtWidgets import QFileDialog  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.tx_panel as tx_panel  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|255] "" ECU
"""
SCRIPT = "def get_payload(dlc, id):\n    return bytes([7] * dlc)\n"


def row(fid, script=None, **kw):
    r = {
        "enabled": True,
        "id": f"0x{fid:03X}",
        "fd": "n",
        "name": f"M{fid:X}",
        "period": 100,
        "payload": "00 00 00 00 00 00 00 00",
        "dlc": 8,
        "script_path": script,
    }
    r.update(kw)
    return r


def slider(value):
    return {
        "msg_name": "MSG_A",
        "signal_name": "SIG_X",
        "frame_id": 256,
        "value": value,
    }


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        # A self-contained project folder: workspace + DBC + script side by side
        self.proj = tempfile.mkdtemp(prefix="canino_ws_")
        os.makedirs(os.path.join(self.proj, "dbc"))
        os.makedirs(os.path.join(self.proj, "scripts"))
        with open(os.path.join(self.proj, "dbc", "a.dbc"), "w") as f:
            f.write(DBC)
        with open(os.path.join(self.proj, "scripts", "seven.py"), "w") as f:
            f.write(SCRIPT)
        self.mw = gui.MainWindow()

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def write(self, name, cfg, folder=None):
        path = os.path.join(folder or self.proj, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def load(self, path):
        self.mw.CONFIG_FILE = path
        self.mw.load_config(auto=True)

    def ids(self):
        return h.tx_view_ids(self.mw)


class LoadReplacesTests(Base):
    def test_second_load_replaces_rows_sliders_script_and_dbc(self):
        """6.4: nothing of workspace A survives loading workspace B."""
        a = self.write(
            "a.json",
            {
                "dbc_file": "dbc/a.dbc",
                "global_script": "scripts/seven.py",
                "signals": [row(0x100), row(0x111)],
                "sliders": [slider(5)],
            },
        )
        b = self.write(
            "b.json", {"dbc_file": None, "signals": [row(0x200)], "sliders": []}
        )
        self.load(a)
        self.assertEqual(len(self.mw.slider_widgets), 1)
        self.assertIsNotNone(self.mw.global_script_path)
        self.load(b)
        self.assertEqual(self.ids(), ["0x200"])
        self.assertEqual(self.mw.slider_widgets, [])
        self.assertEqual(self.mw.added_sliders, set())
        self.assertIsNone(self.mw.global_script_path)
        self.assertFalse(self.mw.btn_remove_global_script.isEnabled())
        self.assertIsNone(self.mw.dbc)
        self.assertIsNone(self.mw.rx_window.dbc)

    def test_load_during_tx_stops_it_and_flushes(self):
        """6.4: Load while transmitting = the user's Stop TX first."""
        self.mw._add_tx_row(0x123, "OLD")
        self.mw.can_if = FakeIf()
        self.mw.start_stop_transmission()
        self.load(self.write("c.json", {"signals": [row(0x300)]}))
        self.assertFalse(self.mw.tx_running)
        self.assertEqual(self.mw.tx_scheduler.entries(), [])
        self.assertEqual(self.mw.can_if.flushes, 1)
        self.assertEqual(self.ids(), ["0x300"])

    def test_table_stays_editable_after_load(self):
        """6.4: Add ID works on a loaded workspace."""
        self.load(self.write("d.json", {"signals": [row(0x100)]}))

        def fake_exec(dlg):
            dlg.ed_id.setText("101")
            dlg.accept()
            return dlg.result()

        orig = tx_panel.AddIdDialog.exec
        tx_panel.AddIdDialog.exec = fake_exec
        try:
            self.mw.add_manual_id()
        finally:
            tx_panel.AddIdDialog.exec = orig
        self.assertEqual(self.ids(), ["0x100", "0x101"])

    def test_broken_file_keeps_the_current_workspace(self):
        """6.4: a file that does not parse must not wipe what is loaded."""
        self.load(self.write("e.json", {"signals": [row(0x100)]}))
        bad = os.path.join(self.proj, "broken.json")
        with open(bad, "w") as f:
            f.write("{ not json")
        self.load(bad)
        self.assertEqual(self.ids(), ["0x100"])
        self.assertEqual(h.DIALOGS[-1][0], "critical")


class PathTests(Base):
    def test_paths_resolve_next_to_the_json_from_any_cwd(self):
        """6.5: a workspace folder moved anywhere still loads from any CWD."""
        ws = self.write(
            "w.json",
            {
                "dbc_file": "dbc/a.dbc",
                "global_script": None,
                "signals": [row(0x100, "scripts/seven.py")],
                "sliders": [slider(9)],
            },
        )
        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            self.load(ws)
        finally:
            os.chdir(cwd)
        self.assertIsNotNone(self.mw.dbc)
        self.assertEqual(len(self.mw.slider_widgets), 1)
        path = self.mw._tx_entries()[0].script_path
        self.assertTrue(os.path.isabs(path) and os.path.exists(path), path)
        self.mw.can_if = FakeIf()
        self.mw.start_stop_transmission()
        h.fire_tx(self.mw)
        # script 7s, then the slider writes SIG_X = 9 into byte 0
        self.assertEqual(self.mw.can_if.sent, [(0x100, bytes([9] + [7] * 7))])

    def test_save_stores_paths_relative_to_the_json(self):
        """6.5: DBC, global and per-ID scripts saved relative to the file, with '/'."""
        self.load(
            self.write(
                "w.json",
                {
                    "dbc_file": "dbc/a.dbc",
                    "global_script": "scripts/seven.py",
                    "signals": [row(0x100, "scripts/seven.py")],
                },
            )
        )
        out = os.path.join(self.proj, "sub")
        os.makedirs(out)
        self.mw._save_config_to_file(os.path.join(out, "saved.json"))
        with open(os.path.join(out, "saved.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["dbc_file"], "../dbc/a.dbc")
        self.assertEqual(cfg["global_script"], "../scripts/seven.py")
        self.assertEqual(cfg["signals"][0]["script_path"], "../scripts/seven.py")

    def test_other_drive_is_stored_absolute(self):
        """6.5: relpath() raises across drives — store the absolute path instead."""
        orig = gui.os.path.relpath

        def relpath(path, start=None):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")

        gui.os.path.relpath = relpath
        try:
            self.assertEqual(
                gui.MainWindow._to_workspace_path("x/y.py", self.proj),
                os.path.abspath("x/y.py"),
            )
        finally:
            gui.os.path.relpath = orig

    def test_legacy_cwd_relative_paths_still_load(self):
        """6.5: pre-1.5 files hold CWD-relative paths: found through the CWD fallback."""
        elsewhere = tempfile.mkdtemp()
        ws = self.write(
            "legacy.json",
            {"dbc_file": "dbc/a.dbc", "signals": [row(0x100, "scripts/seven.py")]},
            folder=elsewhere,
        )
        cwd = os.getcwd()
        os.chdir(self.proj)  # the CWD the file was written from
        try:
            self.load(ws)
        finally:
            os.chdir(cwd)
        self.assertIsNotNone(self.mw.dbc)
        path = self.mw._tx_entries()[0].script_path
        self.assertTrue(os.path.exists(path))

    def test_linked_script_is_stored_absolute(self):
        """6.5: linking no longer calls relpath(CWD), which raised across drives."""
        item = self.mw._add_tx_row(0x100, "M")
        target = os.path.join(self.proj, "scripts", "seven.py")
        orig = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (target, ""))
        try:
            self.mw.modify_payload_script(item)
            self.mw.select_global_payload_script()
        finally:
            QFileDialog.getOpenFileName = orig
        self.assertEqual(item.script_path, target)
        self.assertEqual(self.mw.global_script_path, target)


class SaveTests(Base):
    def test_save_without_a_workspace_asks_for_a_file(self):
        """6.6: Save never writes the CWD-relative default file on its own."""
        asked = []
        target = os.path.join(self.proj, "new.json")
        orig = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: asked.append(1) or (target, "")
        )
        try:
            self.mw._add_tx_row(0x100, "M")
            self.mw.save_config()
        finally:
            QFileDialog.getSaveFileName = orig
        self.assertEqual(asked, [1])
        self.assertTrue(os.path.exists(target))
        self.assertFalse(os.path.exists(self.mw.CONFIG_FILE))
        self.assertEqual(self.mw.workspace_path, target)
        self.assertIn("new.json", self.mw.windowTitle())

    def test_save_writes_back_to_the_loaded_file(self):
        """6.6: after Load, Save overwrites that file, without a dialog."""
        ws = self.write("w.json", {"signals": [row(0x100)]})
        self.load(ws)
        self.mw._add_tx_row(0x200, "NEW")
        orig = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: self.fail("dialog shown")
        )
        try:
            self.mw.save_config()
        finally:
            QFileDialog.getSaveFileName = orig
        with open(ws) as f:
            self.assertEqual(
                [s["id"] for s in json.load(f)["signals"]], ["0x100", "0x200"]
            )

    def test_cancelled_save_as_keeps_no_path(self):
        orig = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
        try:
            self.mw.save_config()
        finally:
            QFileDialog.getSaveFileName = orig
        self.assertIsNone(self.mw.workspace_path)


if __name__ == "__main__":
    unittest.main()

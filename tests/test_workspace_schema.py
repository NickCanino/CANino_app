"""Phase 2 / sub-task 6 — TODO 6.7: versioned workspace schema + migration.

The version-1 fixtures copy the layouts of real files written by CANino
1.0.2, 1.2.x, 1.3.5 and 1.5. Run from the repo root:
    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import tempfile
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtWidgets import QFileDialog  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
from src.utils import resource_path  # noqa: E402
from src.workspace import (  # noqa: E402
    WORKSPACE_VERSION,
    WorkspaceError,
    migrate,
)

# CANino 1.0.2: no "fd", no "ext", Windows paths, sliders by index
V1_0_2 = {
    "dbc_file": "resources\\dbc_files\\a.dbc",
    "signals": [
        {
            "enabled": True,
            "id": "0x123",
            "name": "A",
            "period": 10,
            "payload": "00 00 00 00 00 00 00 00",
            "dlc": 8,
            "script_path": "resources\\script_templates\\template_payload_script_sawtooth.py",
        },
        {
            "enabled": False,
            "id": "0x18FF0001",
            "name": "B",
            "period": 100,
            "payload": "",
            "dlc": 8,
            "script_path": None,
        },
    ],
    "sliders": [
        {
            "msg_name": "SIG_X",  # before 1.5 this held the signal name
            "signal_name": "SIG_X",
            "frame_id": 256,
            "min_val": 0,
            "max_val": 255,
            "step": 1,
            "unit": "",
            "value_index": 42,
        }
    ],
}
# CANino 1.2.x: "fd": null
V1_2 = {
    "dbc_file": None,
    "global_script": "..\\resources\\script_templates\\GLO_TPS_sawtooth.py",
    "signals": [{"enabled": True, "id": "0x100", "fd": None, "dlc": 8}],
    "sliders": [],
}
# CANino 1.5: "ext"/"fd" as "Y"/"n", "/" paths, slider values
V1_5 = {
    "dbc_file": "dbc/a.dbc",
    "global_script": None,
    "signals": [
        {"enabled": True, "id": "0x00000123", "ext": "Y", "fd": "n", "dlc": 4},
        {"enabled": True, "id": "0x200", "ext": "n", "fd": "Y", "dlc": 12},
    ],
    "sliders": [
        {
            "msg_name": "MSG_A",
            "signal_name": "SIG_X",
            "frame_id": 256,
            "is_ext": False,
            "value": 7.5,
            "value_index": 99,  # ignored: "value" wins
        }
    ],
}


class MigrateTests(unittest.TestCase):
    def test_v1_0_2(self):
        out, notes = migrate(V1_0_2)
        self.assertEqual((out["format"], out["version"]), ("canino-workspace", 2))
        self.assertEqual(out["dbc_file"], "resources/dbc_files/a.dbc")
        a, b = out["signals"]
        self.assertEqual((a["id"], a["ext"], a["fd"]), ("0x123", False, False))
        self.assertEqual((b["id"], b["ext"], b["enabled"]), ("0x18FF0001", True, False))
        self.assertEqual(
            a["script_path"],
            "resources/script_templates/template_payload_script_sawtooth.py",
        )
        self.assertEqual(out["sliders"][0]["value"], 42)
        text = " ".join(notes)
        for expected in (
            "version 1",
            "2 row(s) had no ID format",
            "path(s)",
            "slider value",
        ):
            self.assertIn(expected, text)

    def test_v1_2_null_fd(self):
        out, notes = migrate(V1_2)
        self.assertIs(out["signals"][0]["fd"], False)
        self.assertEqual(
            out["global_script"], "../resources/script_templates/GLO_TPS_sawtooth.py"
        )
        self.assertIn("CAN FD flag", " ".join(notes))

    def test_v1_5_flags_and_values(self):
        out, notes = migrate(V1_5)
        flags = [(s["id"], s["ext"], s["fd"], s["dlc"]) for s in out["signals"]]
        self.assertEqual(
            flags, [("0x00000123", True, False, 4), ("0x200", False, True, 12)]
        )
        self.assertEqual(out["sliders"][0]["value"], 7.5)
        self.assertEqual(out["sliders"][0]["is_ext"], False)
        # Only the version change is worth saying: flags were all present
        self.assertEqual(len(notes), 1)

    def test_current_version_unchanged(self):
        out, _ = migrate(V1_5)
        again, notes = migrate(out)
        self.assertEqual(again, out)
        self.assertEqual(notes, [])

    def test_bad_rows_are_skipped_and_reported(self):
        cfg = {
            "version": 2,
            "signals": [
                {"id": "0x100", "ext": False},
                {"id": "0x100", "ext": False},  # duplicate
                {"id": "0x100", "ext": True},  # same number, other format: fine
                {"id": "zz"},
                {"id": "0x800", "ext": False},  # not a standard ID
                "garbage",
            ],
        }
        out, notes = migrate(cfg)
        self.assertEqual(
            [(s["id"], s["ext"]) for s in out["signals"]],
            [("0x100", False), ("0x00000100", True)],
        )
        (note,) = notes
        for expected in ("row 2", "row 4", "row 5", "row 6"):
            self.assertIn(expected, note)

    def test_refused(self):
        for cfg, why in (
            ([], "no JSON object"),
            ({"format": "something-else"}, "format"),
            ({"version": WORKSPACE_VERSION + 1}, "newer CANino"),
            ({"version": "2"}, "unknown workspace version"),
            ({"signals": {}}, "must be lists"),
        ):
            with self.subTest(why=why):
                with self.assertRaises(WorkspaceError) as ctx:
                    migrate(cfg)
                self.assertIn(why, str(ctx.exception))


class LoadSaveTests(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def write(self, cfg, name="ws.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def load(self, path, auto=True):
        """auto: the start-up load; else File -> Load with `path` picked."""
        if auto:
            self.mw.CONFIG_FILE = path
            self.mw.load_config(auto=True)
            return
        orig = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
        try:
            self.mw.load_config()
        finally:
            QFileDialog.getOpenFileName = orig

    def test_saved_file_is_versioned_and_round_trips(self):
        self.mw._add_tx_row(0x123, "A", is_ext=True, dlc=4, period=20)
        self.mw._add_tx_row(0x200, "B", is_fd=True, dlc=12, enabled=False)
        path = os.path.join(self.dir, "out.json")
        self.mw._save_config_to_file(path)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["format"], saved["version"]), ("canino-workspace", 2))
        self.assertEqual(saved["signals"][0]["ext"], True)
        self.load(path)
        rows = [
            (e.id_text, e.is_ext, e.is_fd, e.dlc, e.period, e.enabled)
            for e in self.mw._tx_entries()
        ]
        self.assertEqual(
            rows,
            [
                ("0x00000123", True, False, 4, 20, True),
                ("0x200", False, True, 12, 100, False),
            ],
        )

    def test_newer_file_keeps_the_current_workspace(self):
        self.mw._add_tx_row(0x111, "KEEP")
        self.load(self.write({"version": 99, "signals": []}), auto=False)
        self.assertEqual([e.id_text for e in self.mw._tx_entries()], ["0x111"])
        self.assertEqual(h.DIALOGS[-1][0], "critical")
        self.assertIn("newer CANino", h.DIALOGS[-1][2])

    def test_manual_load_of_an_old_file_says_what_changed(self):
        self.load(self.write(V1_2), auto=False)
        kind, _, text = h.DIALOGS[-1]
        self.assertEqual(kind, "information")
        self.assertIn("Converted from workspace version 1", text)

    def test_start_up_load_warns_only_about_lost_rows(self):
        self.load(self.write(V1_2))
        self.assertEqual(h.DIALOGS, [])
        self.load(self.write({"signals": [{"id": "zz"}, {"id": "0x100"}]}))
        self.assertEqual(h.DIALOGS[-1][0], "warning")
        self.assertIn("row 1", h.DIALOGS[-1][2])
        self.assertEqual([e.id_text for e in self.mw._tx_entries()], ["0x100"])

    def test_renamed_template_is_found_by_its_new_name(self):
        """6.7: a 1.0 workspace links template_payload_script_sawtooth.py."""
        scripts = os.path.join(self.dir, "scripts")
        os.makedirs(scripts)
        shutil.copy(
            resource_path("resources/script_templates/TPS_sawtooth.py"),
            os.path.join(scripts, "TPS_sawtooth.py"),
        )
        cfg = {
            "signals": [
                {
                    "id": "0x100",
                    "script_path": "scripts\\template_payload_script_sawtooth.py",
                }
            ]
        }
        self.load(self.write(cfg))
        (entry,) = self.mw._tx_entries()
        self.assertEqual(entry.script_path, os.path.join(scripts, "TPS_sawtooth.py"))

    def test_renamed_template_through_the_cwd_fallback(self):
        """6.7: pre-1.5 paths are CWD-relative; the rename applies there too."""
        os.makedirs(os.path.join(self.dir, "res"))
        shutil.copy(
            resource_path("resources/script_templates/TPS_blink.py"),
            os.path.join(self.dir, "res", "TPS_blink.py"),
        )
        elsewhere = tempfile.mkdtemp()
        cfg = {
            "signals": [
                {"id": "0x100", "script_path": "res\\template_payload_script_blink.py"}
            ]
        }
        path = self.write(cfg)
        moved = os.path.join(elsewhere, "ws.json")
        shutil.move(path, moved)
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            self.load(moved)
        finally:
            os.chdir(cwd)
        (entry,) = self.mw._tx_entries()
        self.assertEqual(
            entry.script_path, os.path.join(self.dir, "res", "TPS_blink.py")
        )


if __name__ == "__main__":
    unittest.main()

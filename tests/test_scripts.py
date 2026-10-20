"""Phase 1 / sub-task 4 — TODO 3.3, 3.4, 3.5, 3.7, 3.8, 3.12 + replay CSV parsing.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import glob
import logging
import os
import shutil
import tempfile
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import Qt  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.tx_model as tx_model  # noqa: E402
import src.tx_panel as tx_panel  # noqa: E402
from src.utils import resource_path  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

TEMPLATES = resource_path("resources/script_templates")
LENGTHS = list(range(1, 9)) + [12, 16, 20, 24, 32, 48, 64]
MARKED = (
    "TPS_random.py",
    "GLO_TPS_random.py",
    "TPS_read_from_file.py",
    "GLO_TPS_read_from_file.py",
)
REPLAY = ("TPS_read_from_file.py", "GLO_TPS_read_from_file.py")


def template_names():
    return sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(TEMPLATES, "*.py"))
        if " " not in os.path.basename(p)  # the untracked local copy (3.9)
    )


def write_replay(directory, fid, rows):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"payload_sequence_ID_{fid:03X}.csv"), "w") as f:
        f.write("Index,B7,B6,B5,B4,B3,B2,B1,B0\n")
        for i, row in enumerate(rows, 1):
            f.write(f"{i}," + ",".join(row) + "\n")


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="canino_tpl_")
        # Templates in <dir>/script_templates, replay files in <dir>/tmp, as in resources/
        self.tpl = os.path.join(self.dir, "script_templates")
        shutil.copytree(TEMPLATES, self.tpl)
        write_replay(
            os.path.join(self.dir, "tmp"), 0x123, [["0"] * 7 + ["5"], ["0"] * 7 + ["6"]]
        )

    def load(self, name, tag=""):
        return tx_panel.load_payload_function(
            os.path.join(self.tpl, name), f"tpl_{name[:-3]}{tag}"
        )

    def test_every_template_returns_dlc_bytes(self):
        """3.5: no hard-coded 8-byte buffers — exact length for classic and FD DLCs."""
        for name in template_names():
            fn = self.load(name)
            for dlc in LENGTHS:
                with self.subTest(template=name, dlc=dlc):
                    out = fn(dlc, 0x123)
                    self.assertIsInstance(out, bytes)
                    self.assertEqual(len(out), dlc)

    def test_marker_kept_and_dlc_1_handled(self):
        """3.12 + 3.6: byte 1 = 0xA7 from DLC 2 up; DLC 1 is sent, without marker."""
        for name in MARKED:
            fn = self.load(name)
            with self.subTest(template=name):
                self.assertEqual(len(fn(1, 0x123)), 1)
                for dlc in (2, 8, 64):
                    self.assertEqual(fn(dlc, 0x123)[1], 0xA7)

    def test_headers_state_the_real_signature(self):
        """3.8: no more 'get_payload() -> bytes' in the template headers."""
        for name in template_names():
            with self.subTest(template=name):
                with open(os.path.join(self.tpl, name), encoding="utf-8") as f:
                    text = f.read()
                self.assertNotIn("get_payload() -> bytes", text)
                self.assertIn("get_payload(dlc: int, id: int) -> bytes | None", text)

    def test_replay_csv_dir_follows_the_script_not_the_cwd(self):
        """3.7: replay files found next to the templates whatever the CWD."""
        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            for name in REPLAY:
                with self.subTest(template=name):
                    fn = self.load(name, "_cwd")
                    self.assertEqual(fn(8, 0x123)[0], 5)
                    self.assertEqual(fn(8, 0x123)[0], 6)
                    self.assertEqual(fn(8, 0x123)[0], 5)  # cycles
        finally:
            os.chdir(cwd)

    def test_replay_without_file_returns_none_and_reads_once(self):
        """3.7: an ID without a replay file -> None (manual payload), file looked up once."""
        for name in REPLAY:
            fn = self.load(name, "_none")
            mod = fn.__globals__
            calls = []
            orig = mod["_load_payloads_for_id"]
            mod["_load_payloads_for_id"] = lambda arbid: calls.append(arbid) or orig(
                arbid
            )
            with self.subTest(template=name):
                for _ in range(50):
                    self.assertIsNone(fn(8, 0x555))
                self.assertEqual(calls, [0x555])

    def test_replay_bytes_are_decimal(self):
        """Replay CSVs hold decimal bytes: 10 was sent as 0x10 (16), 99 as 0x99 (153)."""
        write_replay(
            os.path.join(self.dir, "tmp"),
            0x200,
            [["255", "128", "99", "16", "10", "0x1F", "1", "9"]],
        )
        for name in REPLAY:
            fn = self.load(name, "_dec")
            with self.subTest(template=name):
                out = fn(8, 0x200)
                # B0 is the last column; byte 1 is the attack marker
                self.assertEqual(out[0], 9)
                self.assertEqual(list(out[2:]), [0x1F, 10, 16, 99, 128, 255])

    def test_marker_can_be_switched_off(self):
        """ATTACK_MARKER = None: replay is byte-exact, random keeps byte 1 random."""
        write_replay(
            os.path.join(self.dir, "tmp"),
            0x300,
            [["8", "7", "6", "5", "4", "3", "2", "1"]],
        )
        for name in MARKED:
            fn = self.load(name, "_off")
            fn.__globals__["ATTACK_MARKER"] = None
            with self.subTest(template=name):
                if name in REPLAY:
                    self.assertEqual(fn(8, 0x300), bytes([1, 2, 3, 4, 5, 6, 7, 8]))
                else:
                    self.assertNotEqual({fn(8, 0x300)[1] for _ in range(200)}, {0xA7})


FG = Qt.ItemDataRole.ForegroundRole


class GuiScriptTests(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.item = self.mw._add_tx_row(
            0x100, "M100", payload="11 22 33 44 55 66 77 88"
        )
        self.mw.can_if = FakeIf()
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = lambda r: self.records.append(r)
        logging.getLogger().addHandler(self.handler)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        h.dispose(self.mw)

    def script(self, name, body):
        with open(name, "w", encoding="utf-8") as f:
            f.write(body)
        self.mw._set_script_link(self.item, name)

    def tick(self, n=1):
        h.fire_tx(self.mw, n)

    def sent(self):
        return self.mw.can_if.sent

    def tip(self):
        return h.tx_cell(
            self.mw, self.item, tx_model.TX_COL_6_payload, Qt.ItemDataRole.ToolTipRole
        )

    def errors_logged(self):
        return [
            r
            for r in self.records
            if r.levelno >= logging.ERROR and "not sent" in r.getMessage()
        ]

    def test_missing_script_is_not_replaced_by_the_manual_payload(self):
        """3.4: missing file -> warning at Start TX, frame not sent, row in error."""
        self.mw._set_script_link(self.item, "gone.py")
        self.mw.start_stop_transmission()
        self.tick(5)
        self.assertEqual(self.sent(), [])
        self.assertEqual(h.DIALOGS[-1][0], "warning")
        self.assertIn("gone.py", h.DIALOGS[-1][2])
        self.assertIn("not found", self.tip())
        self.assertEqual(len(self.errors_logged()), 1)

    def test_missing_global_script_is_reported(self):
        self.mw.global_script_path = "gone_global.py"
        self.mw.start_stop_transmission()
        self.tick()
        self.assertEqual(self.sent(), [])
        self.assertIn("Global script", h.DIALOGS[-1][2])

    def test_failing_script_logged_once_and_shown_then_cleared(self):
        """3.3: one log record per distinct error, red row while failing, cleared on success."""
        self.script(
            "flaky.py",
            "n = 0\n"
            "def get_payload(dlc, id):\n"
            "    global n\n"
            "    n += 1\n"
            "    if n <= 10:\n"
            "        raise RuntimeError('boom')\n"
            "    return bytes(dlc)\n",
        )
        self.mw.start_stop_transmission()
        self.tick(10)
        self.assertEqual(self.sent(), [])
        self.assertEqual(len(self.errors_logged()), 1)
        self.assertIsNotNone(self.errors_logged()[0].exc_info)  # traceback kept once
        self.assertIn("boom", self.tip())
        self.assertEqual(
            h.tx_cell(self.mw, self.item, tx_model.TX_COL_6_payload, FG).name().upper(),
            tx_model.ROW_ERROR_COLOR,
        )
        self.tick()
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.tip(), "")
        self.assertIsNone(h.tx_cell(self.mw, self.item, tx_model.TX_COL_6_payload, FG))

    def test_none_means_manual_payload(self):
        """3.7 / script API: None -> the row's manual payload goes out."""
        self.script("none.py", "def get_payload(dlc, id):\n    return None\n")
        self.mw.start_stop_transmission()
        self.tick()
        self.assertEqual(self.sent(), [(0x100, bytes.fromhex("1122334455667788"))])

    def test_wrong_length_is_an_error_bytearray_is_fine(self):
        self.script("short.py", "def get_payload(dlc, id):\n    return b'\\x01'\n")
        self.mw.start_stop_transmission()
        self.tick()
        self.assertEqual(self.sent(), [])
        self.assertIn("returned 1 bytes, the DLC is 8", self.tip())
        self.mw.stop_tx()
        self.script(
            "ba.py", "def get_payload(dlc, id):\n    return bytearray(range(dlc))\n"
        )
        self.mw.start_stop_transmission()
        self.tick()
        self.assertEqual(self.sent(), [(0x100, bytes(range(8)))])

    def test_start_tx_clears_the_logged_errors(self):
        """3.3: a new run logs its errors again (once)."""
        self.script("bad.py", "def get_payload(dlc, id):\n    raise KeyError('k')\n")
        self.mw.start_stop_transmission()
        self.tick(3)
        self.mw.start_stop_transmission()
        self.mw.start_stop_transmission()
        self.tick(3)
        self.assertEqual(len(self.errors_logged()), 2)


if __name__ == "__main__":
    unittest.main()

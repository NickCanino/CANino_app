"""Phase 1 / sub-task 8 — TODO 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9 (VAGILETTA).

No Arduino and no arduino-cli needed: run_cli / Popen are faked.
Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import QCoreApplication, QThread  # noqa: E402

import src.vagiletta_programmer_class as vag  # noqa: E402

# `board list --format json` from arduino-cli 1.3.0 on the bench PC: two COM ports
# with no recognised board (no Arduino attached)
REAL_NO_BOARD = json.dumps(
    {
        "detected_ports": [
            {"port": {"address": "COM15", "label": "COM15", "protocol": "serial"}},
            {"port": {"address": "COM14", "label": "COM14", "protocol": "serial"}},
        ]
    }
)
WITH_UNO = json.dumps(
    {
        "detected_ports": [
            {
                "matching_boards": [{"name": "Arduino Uno", "fqbn": "arduino:avr:uno"}],
                "port": {"address": "COM3", "protocol": "serial"},
            },
            {
                "matching_boards": [
                    {"name": "Arduino Mega", "fqbn": "arduino:avr:mega"}
                ],
                "port": {"address": "COM4", "protocol": "serial"},
            },
            {"port": {"address": "COM5", "protocol": "serial"}},
            {"port": {"address": "192.168.1.7", "protocol": "network"}},
        ]
    }
)


def completed(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


def pump(cond, limit=5.0):
    t = time.time() + limit
    while time.time() < t and not cond():
        QCoreApplication.processEvents()
        time.sleep(0.005)


class ParseTests(unittest.TestCase):
    def test_only_uno_ports_by_default(self):
        """8.4: the bench's two non-Arduino COM ports are no longer offered."""
        self.assertEqual(vag.parse_board_list(REAL_NO_BOARD), [])
        self.assertEqual(
            vag.parse_board_list(WITH_UNO), [("COM3", "COM3 - Arduino Uno")]
        )

    def test_unidentified_serial_ports_on_request(self):
        """8.4: clones without a board match can be shown; other boards and network ports never."""
        self.assertEqual(
            [p for p, _ in vag.parse_board_list(WITH_UNO, show_unidentified=True)],
            ["COM3", "COM5"],
        )

    def test_pre_1_0_list_schema(self):
        old = json.dumps(
            [
                {
                    "port": {"address": "COM7", "protocol": "serial"},
                    "matching_boards": [{"fqbn": "arduino:avr:uno"}],
                }
            ]
        )
        self.assertEqual([p for p, _ in vag.parse_board_list(old)], ["COM7"])

    def test_core_installed(self):
        """8.6: arduino:avr counts only with an installed version."""
        installed = {"platforms": [{"id": "arduino:avr", "installed_version": "1.8.8"}]}
        indexed_only = {"platforms": [{"id": "arduino:avr", "latest_version": "1.8.8"}]}
        self.assertTrue(vag.core_installed(json.dumps(installed)))
        self.assertFalse(vag.core_installed(json.dumps(indexed_only)))
        self.assertFalse(vag.core_installed(json.dumps({"platforms": []})))
        self.assertFalse(vag.core_installed("{}"))


class FakePopen:
    """Records arduino-cli calls; `block` makes communicate() wait until kill()."""

    calls = []
    outputs = {}
    block = False

    def __init__(self, args, **kwargs):
        FakePopen.calls.append((args[1:], kwargs.get("creationflags")))
        self.args = args
        self.returncode = None
        self._killed = threading.Event()

    def communicate(self):
        if FakePopen.block and self.args[1] == "compile":
            self._killed.wait(5)
            self.returncode = 1
            return "killed", None
        out, code = FakePopen.outputs.get(self.args[1], ("", 0))
        self.returncode = code
        return out, None

    def poll(self):
        return self.returncode

    def kill(self):
        self._killed.set()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._orig_popen = vag.subprocess.Popen
        vag.subprocess.Popen = FakePopen
        FakePopen.calls, FakePopen.block = [], False
        FakePopen.outputs = {
            "core": (
                '{"platforms": [{"id": "arduino:avr", "installed_version": "1.8.8"}]}',
                0,
            )
        }
        self._orig_env = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()

    def tearDown(self):
        vag.subprocess.Popen = self._orig_popen
        if self._orig_env is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._orig_env

    def run_worker(self, worker):
        result = []
        worker.finished.connect(lambda ok, msg: result.append((ok, msg)))
        worker.run()
        return result[0]

    def commands(self):
        return [" ".join(a[:2]) for a, _ in FakePopen.calls]

    def test_installed_core_goes_straight_to_compile(self):
        ok, _ = self.run_worker(vag.FlashWorker("COM3", {"speed": 1, "mode": "x"}))
        self.assertTrue(ok)
        self.assertEqual(self.commands(), ["core list", "compile --fqbn", "upload -p"])

    def test_missing_core_is_installed_first(self):
        """8.6: a fresh PC has no arduino:avr — install it before compiling."""
        FakePopen.outputs["core"] = ('{"platforms": []}', 0)
        ok, _ = self.run_worker(vag.FlashWorker("COM3", {"speed": 1, "mode": "x"}))
        self.assertTrue(ok)
        self.assertEqual(
            self.commands(),
            [
                "core list",
                "core update-index",
                "core install",
                "compile --fqbn",
                "upload -p",
            ],
        )
        self.assertIn(
            ["core", "install", "arduino:avr"], [list(a) for a, _ in FakePopen.calls]
        )

    def test_cancel_kills_the_running_step(self):
        """8.5: Cancel stops arduino-cli; nothing is uploaded."""
        FakePopen.block = True
        worker = vag.FlashWorker("COM3", {"speed": 2, "mode": "x"})
        result = []
        worker.finished.connect(lambda ok, msg: result.append((ok, msg)))
        t = threading.Thread(target=worker.run)
        t.start()
        deadline = time.time() + 5
        while time.time() < deadline and "compile --fqbn" not in self.commands():
            time.sleep(0.01)
        worker.cancel()
        t.join(5)
        # finished was emitted from the plain thread: queued to this one
        pump(lambda: bool(result))
        self.assertEqual(result, [(False, "Flash cancelled.")])
        self.assertNotIn("upload -p", self.commands())

    def test_no_console_window(self):
        """8.7: every arduino-cli call runs with CREATE_NO_WINDOW."""
        self.run_worker(vag.FlashWorker("COM3", {"speed": 3, "mode": "x"}))
        self.assertEqual({flags for _, flags in FakePopen.calls}, {vag.NO_WINDOW})
        self.assertEqual(vag.NO_WINDOW, getattr(subprocess, "CREATE_NO_WINDOW", 0))
        seen = {}
        orig = vag.subprocess.run
        vag.subprocess.run = lambda *a, **k: seen.update(k) or completed("{}")
        try:
            vag.run_cli(["board", "list"])
        finally:
            vag.subprocess.run = orig
        self.assertEqual(seen.get("creationflags"), vag.NO_WINDOW)

    def test_build_dir_outside_the_cwd(self):
        """8.8: sketches go to %LOCALAPPDATA%\\CANinoApp, not ./arduino_build in OneDrive."""
        proj = vag.prepare_project({"speed": 4, "mode": "x"})
        self.assertTrue(str(proj).startswith(os.environ["LOCALAPPDATA"]))
        self.assertFalse(os.path.exists("arduino_build"))
        self.assertEqual(len(list(proj.glob("*.ino"))), 1)


class DialogTests(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self.cli_calls = []

        def slow_cli(args, timeout=60):
            self.cli_calls.append(list(args))
            time.sleep(0.5)  # the real `board list` takes ~1.4 s
            return completed(WITH_UNO)

        self._orig = vag.run_cli
        vag.run_cli = slow_cli

    def tearDown(self):
        vag.run_cli = self._orig

    def test_opening_does_not_wait_for_the_scan(self):
        """8.3: the constructor returns before `board list` finishes."""
        t = time.perf_counter()
        dlg = vag.VagilettaWindow()
        self.assertLess(time.perf_counter() - t, 0.4)
        self.assertIn("Scanning", dlg.lbl_status.text())
        pump(lambda: dlg.scan_thread is None)
        self.assertEqual(dlg.ports, [("COM3", "COM3 - Arduino Uno")])
        dlg.done(0)

    def test_combo_change_does_not_call_arduino_cli(self):
        """8.3: picking a port re-filters the cached scan; the port leaves the other nodes."""
        dlg = vag.VagilettaWindow()
        pump(lambda: dlg.scan_thread is None)
        calls = len(self.cli_calls)
        dlg.combos[0].setCurrentIndex(dlg.combos[0].findData("COM3"))
        self.assertEqual(len(self.cli_calls), calls)
        self.assertEqual(dlg.combos[1].findData("COM3"), -1)
        dlg.done(0)

    def test_second_flash_refused_while_one_runs(self):
        """8.5: a running flash's QThread is never overwritten."""
        dlg = vag.VagilettaWindow()
        pump(lambda: dlg.scan_thread is None)
        busy = QThread(dlg)
        dlg.flash_thread = busy
        dlg.combos[0].setCurrentIndex(dlg.combos[0].findData("COM3"))
        dlg._handle_flash(dlg.combos[0], {"speed": 1, "mode": "x"})
        self.assertIs(dlg.flash_thread, busy)
        self.assertEqual(h.DIALOGS[-1][0], "warning")
        dlg.flash_thread = None
        dlg.done(0)

    def test_english_tooltips_and_no_shadowed_thread(self):
        """8.7 + 8.9: tooltips everywhere, English strings, QObject.thread() intact."""
        dlg = vag.VagilettaWindow()
        pump(lambda: dlg.scan_thread is None)
        self.assertTrue(dlg.refresh_btn.toolTip())
        self.assertTrue(all(b.toolTip() for b in dlg.flash_buttons))
        self.assertTrue(all(c.toolTip() for c in dlg.combos))
        self.assertIsInstance(dlg.thread(), QThread)
        with open(vag.__file__, encoding="utf-8") as f:
            src = f.read()
        for italian in (
            "Errore",
            "Seleziona",
            "Annulla",
            "completato",
            "fallit",
            "Successo",
        ):
            self.assertNotIn(italian, src)
        dlg.done(0)


if __name__ == "__main__":
    unittest.main()

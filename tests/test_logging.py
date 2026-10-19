"""Phase 1 / sub-task 9a — TODO 9.3, 9.4, 9.5 (logging).

Import-time behaviour runs in a fresh interpreter: the logger is set up on import.
Run from the repo root:  python -m unittest discover -s tests -v
"""

import glob
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.exceptions_logger as el  # noqa: E402
import src.gui as gui  # noqa: E402

REPO = h.REPO


def run_python(code, env_extra, cwd):
    env = dict(os.environ, PYTHONPATH=REPO, CANINO_LOG_CONSOLE="0", **env_extra)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class LogFileTests(unittest.TestCase):
    def setUp(self):
        self.logs = tempfile.mkdtemp(prefix="canino_logs_")
        self.cwd = tempfile.mkdtemp(prefix="canino_cwd_")

    def files(self):
        return glob.glob(os.path.join(self.logs, "canino_app_*.log*"))

    def test_clean_session_leaves_no_file_and_no_cwd_log_dir(self):
        """9.3: importing the app no longer creates log/ in the CWD nor an empty file."""
        res = run_python("import src.gui", {"CANINO_LOG_DIR": self.logs}, self.cwd)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.files(), [])
        self.assertFalse(os.path.exists(os.path.join(self.cwd, "log")))

    def test_first_error_creates_the_file(self):
        code = (
            "from src.exceptions_logger import log_exception\n"
            "try:\n    1 / 0\nexcept Exception as e:\n    log_exception(e)\n"
        )
        res = run_python(code, {"CANINO_LOG_DIR": self.logs}, self.cwd)
        self.assertEqual(res.returncode, 0, res.stderr)
        (path,) = self.files()
        with open(path, encoding="utf-8") as f:
            text = f.read()
        # 9.4: the record names the caller (the -c string is module "<string>", line 5)
        self.assertRegex(
            text, r"\[ERROR\] canino <string>:5: ZeroDivisionError: division by zero"
        )
        self.assertIn("Traceback", text)

    def test_old_logs_are_pruned(self):
        """9.3: only the newest LOG_KEEP files survive a start-up."""
        for i in range(el.LOG_KEEP + 10):
            path = os.path.join(self.logs, f"canino_app_v1.0_{i:03}.log")
            with open(path, "w") as f:
                f.write("x")
            os.utime(path, (time.time() - 1000 + i, time.time() - 1000 + i))
        res = run_python(
            "import src.exceptions_logger", {"CANINO_LOG_DIR": self.logs}, self.cwd
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        names = sorted(os.path.basename(p) for p in self.files())
        self.assertEqual(len(names), el.LOG_KEEP)
        self.assertEqual(names[0], "canino_app_v1.0_010.log")

    def test_default_dir_is_per_user(self):
        """9.3: without the override, logs go to %LOCALAPPDATA%\\CANinoApp\\log."""
        saved = {k: os.environ.get(k) for k in ("CANINO_LOG_DIR", "LOCALAPPDATA")}
        try:
            os.environ.pop("CANINO_LOG_DIR", None)
            os.environ["LOCALAPPDATA"] = self.cwd
            self.assertEqual(
                el.default_log_dir(), os.path.join(self.cwd, "CANinoApp", "log")
            )
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class RecordTests(unittest.TestCase):
    def test_record_points_at_the_caller(self):
        """9.4: module/lineno are the caller's, not exceptions_logger's."""
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logging.getLogger().addHandler(handler)
        try:
            try:
                raise KeyError("k")
            except KeyError as e:
                line = sys._getframe().f_lineno + 1
                el.log_exception(e)
        finally:
            logging.getLogger().removeHandler(handler)
        (rec,) = [r for r in records if r.name == "canino"]
        self.assertEqual((rec.module, rec.lineno), ("test_logging", line))
        self.assertIsNotNone(rec.exc_info)

    def test_no_print_left_in_the_sources(self):
        """9.5: print() is invisible in the windowed exe — everything goes to the logger."""
        for path in glob.glob(os.path.join(REPO, "src", "*.py")):
            if path.endswith("PCANBasic.py"):  # vendor file, untouched
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    code = line.split("#", 1)[0]
                    if re.search(r"(?<![\w.])print\(", code):
                        self.fail(f"{os.path.basename(path)}:{n}: {line.strip()}")
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("sys._getframe", f.read(), path)


class MenuTests(unittest.TestCase):
    def test_help_menu_opens_the_log_folder(self):
        """9.3: the logs moved, so the app says where they are."""
        orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        opened = []
        orig_open = gui.QDesktopServices.openUrl
        gui.QDesktopServices.openUrl = staticmethod(
            lambda url: opened.append(url.toLocalFile())
        )
        try:
            mw = gui.MainWindow()
            mw.action_open_logs.trigger()
            mw.close()
        finally:
            gui.QDesktopServices.openUrl = orig_open
            ci.CANInterface.get_available_channels = orig_scan
        self.assertEqual(
            [os.path.normpath(p) for p in opened], [os.path.normpath(el.log_dir)]
        )


if __name__ == "__main__":
    unittest.main()

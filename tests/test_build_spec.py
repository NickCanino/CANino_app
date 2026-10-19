"""Phase 1 / sub-task 9b — TODO 10.3, 10.4, 10.6 (packaging).

The PyInstaller spec is executed with stub Analysis/PYZ/EXE and a fake git,
so no build runs. Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import subprocess
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

REPO = h.REPO
SPEC = os.path.join(REPO, "CANinoApp_exe_setup.spec")


class Analysis:
    """What the spec reads from PyInstaller's Analysis: TOC lists of (dest, src, type)."""

    def __init__(self, binaries=(), datas=()):
        self.pure = []
        self.scripts = []
        self.binaries = list(binaries)
        self.datas = list(datas)


class Recorder:
    def __init__(self, analysis=None):
        self.calls = {}
        self.analysis = analysis or Analysis()

    def __getattr__(self, name):
        def stub(*args, **kwargs):
            self.calls[name] = (args, kwargs)
            return self.analysis if name == "Analysis" else object()

        return stub


def run_spec(git_outputs, analysis=None, onedir=False):
    """Execute the spec; git_outputs maps a git subcommand to its stdout (or an exception)."""
    rec = Recorder(analysis)
    os.environ["CANINO_ONEDIR"] = "1" if onedir else "0"

    def fake_check_output(cmd, *a, **k):
        out = git_outputs[cmd[1]]
        if isinstance(out, Exception):
            raise out
        return out.encode()

    orig = subprocess.check_output
    cwd = os.getcwd()
    subprocess.check_output = fake_check_output
    os.chdir(REPO)
    try:
        ns = {
            "Analysis": rec.Analysis,
            "PYZ": rec.PYZ,
            "EXE": rec.EXE,
            "COLLECT": rec.COLLECT,
            "__name__": "spec",
        }
        with open(SPEC, encoding="utf-8") as f:
            exec(compile(f.read(), SPEC, "exec"), ns)
    finally:
        subprocess.check_output = orig
        os.chdir(cwd)
        os.environ.pop("CANINO_ONEDIR", None)
    return rec.calls


TEMPLATES = "resources/script_templates/TPS_sawtooth.py\nresources/script_templates/GLO_TPS_random.py"


class SpecTests(unittest.TestCase):
    def test_clean_tree_name_and_bundle(self):
        """10.3: no src/*.py data copies; tracked templates shipped."""
        calls = run_spec({"rev-parse": "abc1234", "status": "", "ls-files": TEMPLATES})
        with open(os.path.join(REPO, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
        self.assertEqual(calls["EXE"][1]["name"], f"CANinoApp_v{version}_habc1234")
        datas = calls["Analysis"][1]["datas"]
        self.assertFalse([d for d in datas if d[0].startswith("src/")], datas)
        self.assertIn(
            (
                "resources/script_templates/TPS_sawtooth.py",
                "resources/script_templates",
            ),
            datas,
        )
        for src, _ in datas:
            self.assertTrue(os.path.exists(os.path.join(REPO, src)), src)

    def test_dirty_tree_is_marked(self):
        """10.6: tracked changes -> the exe name says so."""
        calls = run_spec(
            {"rev-parse": "abc1234", "status": " M src/gui.py", "ls-files": TEMPLATES}
        )
        self.assertTrue(calls["EXE"][1]["name"].endswith("_habc1234-dirty"))

    def test_untracked_template_never_shipped(self):
        """10.3: without git, the fallback glob still skips the local 'TPS_sawtooth - 130.py'."""
        calls = run_spec(
            {
                "rev-parse": OSError("no git"),
                "status": "",
                "ls-files": OSError("no git"),
            }
        )
        self.assertTrue(calls["EXE"][1]["name"].endswith("_hnogit"))
        shipped = [
            d[0] for d in calls["Analysis"][1]["datas"] if "script_templates" in d[0]
        ]
        self.assertTrue(shipped)
        self.assertFalse([s for s in shipped if " " in s], shipped)


class QtTrimTests(unittest.TestCase):
    GIT = {"rev-parse": "abc1234", "status": "", "ls-files": TEMPLATES}

    def test_unused_qt_parts_are_dropped(self):
        """10.11: OpenGL/QML/PDF/network Qt parts out, what CANino uses stays."""
        keep = [
            "PySide6/Qt6Core.dll",
            "PySide6/Qt6Gui.dll",
            "PySide6/Qt6Widgets.dll",
            "PySide6/Qt6Svg.dll",
            "PySide6/plugins/platforms/qwindows.dll",
            "PySide6/plugins/imageformats/qico.dll",
            "PySide6/plugins/styles/qmodernwindowsstyle.dll",
            "libcrypto-3.dll",  # Python's hashlib (VAGILETTA's sketch hash)
        ]
        drop = [
            "PySide6/opengl32sw.dll",
            "PySide6/Qt6Quick.dll",
            "PySide6/Qt6Qml.dll",
            "PySide6/Qt6QmlModels.dll",
            "PySide6/Qt6Pdf.dll",
            "PySide6/Qt6Network.dll",
            "PySide6/QtNetwork.pyd",
            "PySide6/Qt6OpenGL.dll",
            "PySide6/Qt6VirtualKeyboard.dll",
            "libssl-3-x64.dll",
            "PySide6/plugins/tls/qopensslbackend.dll",
            "PySide6/plugins/imageformats/qpdf.dll",
            "PySide6/plugins/platforms/qdirect2d.dll",
        ]
        a = Analysis(
            binaries=[(p.replace("/", "\\"), "src", "BINARY") for p in keep + drop],
            datas=[("PySide6/translations/qtbase_de.qm", "src", "DATA")],
        )
        run_spec(self.GIT, a)
        self.assertEqual([b[0].replace("\\", "/") for b in a.binaries], keep)
        self.assertEqual(a.datas, [])

    def test_onefile_by_default_onedir_on_request(self):
        """10.8: CANINO_ONEDIR=1 builds a folder (COLLECT), else one exe."""
        calls = run_spec(self.GIT)
        self.assertNotIn("COLLECT", calls)
        self.assertFalse(calls["EXE"][1]["exclude_binaries"])
        calls = run_spec(self.GIT, onedir=True)
        self.assertTrue(calls["EXE"][1]["exclude_binaries"])
        self.assertEqual(calls["COLLECT"][1]["name"], calls["EXE"][1]["name"])


class RequirementsTests(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(REPO, name), encoding="utf-8") as f:
            return [
                line.strip() for line in f if line.strip() and not line.startswith("#")
            ]

    def test_runtime_pinned_and_without_build_tools(self):
        """10.4: exact pins; PyInstaller is a dev dependency."""
        runtime = self.read("requirements.txt")
        self.assertTrue(all("==" in r for r in runtime), runtime)
        self.assertEqual(
            sorted(r.split("==")[0].lower() for r in runtime),
            ["cantools", "pyside6", "python-can"],
        )
        dev = self.read("requirements-dev.txt")
        self.assertIn("-r requirements.txt", dev)
        self.assertTrue(any(r.lower().startswith("pyinstaller==") for r in dev))


if __name__ == "__main__":
    unittest.main()

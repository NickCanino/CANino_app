# -----------------------------------------------------------------------------
#  Project: CANinoApp — shared test harness (offscreen Qt, no hardware)
# -----------------------------------------------------------------------------
"""Import this before anything from `src`.

- Qt runs offscreen and QMessageBox statics are recorded instead of blocking.
- The CWD moves to a temp dir: importing src.* creates log/ in the CWD and
  MainWindow auto-loads a CWD-relative default workspace.
- FakePCAN stands in for the PCAN-Basic DLL used by python-can.
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
WORKDIR = tempfile.mkdtemp(prefix="canino_tests_")
os.environ["CANINO_LOG_DIR"] = os.path.join(WORKDIR, "log")
os.environ["CANINO_LOG_CONSOLE"] = "0"
os.chdir(WORKDIR)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])

DIALOGS = []


def _record(kind):
    def f(parent, title, text, *args, **kwargs):
        DIALOGS.append((kind, title, text))
        return QMessageBox.StandardButton.Yes

    return staticmethod(f)


for _kind in ("information", "warning", "critical", "question"):
    setattr(QMessageBox, _kind, _record(_kind))


class FakePCAN:
    """Records the init calls python-can makes; `init_result` forces a failure."""

    calls = []
    init_result = None  # None -> PCAN_ERROR_OK
    status_result = 0  # what GetStatus() reports

    def __init__(self):
        pass

    def _result(self):
        from can.interfaces.pcan.basic import PCAN_ERROR_OK

        return PCAN_ERROR_OK if FakePCAN.init_result is None else FakePCAN.init_result

    def Initialize(self, channel, btr0btr1, hwtype, ioport, interrupt):
        FakePCAN.calls.append(("Initialize", btr0btr1.value))
        return self._result()

    def InitializeFD(self, channel, bitrate_fd):
        FakePCAN.calls.append(("InitializeFD", bitrate_fd.decode()))
        return self._result()

    def SetValue(self, channel, parameter, value, *args):
        from can.interfaces.pcan.basic import PCAN_ERROR_OK

        FakePCAN.calls.append(
            (
                "SetValue",
                getattr(parameter, "value", parameter),
                getattr(value, "value", value),
            )
        )
        return PCAN_ERROR_OK

    def GetStatus(self, channel):
        return FakePCAN.status_result

    def GetValue(self, channel, parameter):
        from can.interfaces.pcan.basic import PCAN_ERROR_OK

        return PCAN_ERROR_OK, b"4.10.1.968"

    def GetErrorText(self, *args):
        from can.interfaces.pcan.basic import PCAN_ERROR_OK

        return PCAN_ERROR_OK, b"fake PCAN error"

    def Read(self, channel):
        from can.interfaces.pcan.basic import PCAN_ERROR_QRCVEMPTY

        return PCAN_ERROR_QRCVEMPTY, None, None

    def Uninitialize(self, channel):
        from can.interfaces.pcan.basic import PCAN_ERROR_OK

        return PCAN_ERROR_OK


def init_calls():
    """FakePCAN calls without the SetValue ones (mode, events, ...)."""
    return [c for c in FakePCAN.calls if c[0] != "SetValue"]


def install_fake_pcan():
    import can.interfaces.pcan.pcan as pcanmod

    pcanmod.PCANBasic = FakePCAN
    pcanmod.HAS_EVENTS = False
    FakePCAN.calls.clear()
    FakePCAN.init_result = None
    FakePCAN.status_result = 0

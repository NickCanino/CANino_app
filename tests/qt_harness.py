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

import src.tx_scheduler as _tx_scheduler  # noqa: E402

# No TX thread: tests fire the scheduled rows themselves (fire_tx), so frame
# counts never depend on the wall clock. Timing tests opt in per instance.
_tx_scheduler.TxScheduler.threaded = False

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


def tx_view_ids(mw):
    """TX ID column in view (sorted) order."""
    proxy = mw.tx_view.model()
    return [proxy.index(r, 2).data() for r in range(proxy.rowCount())]


def tx_index(mw, entry, col):
    """View (proxy) index of an entry's cell: what a click or an edit goes through."""
    row = mw.tx_model.row_of(entry)
    return mw.tx_view.model().mapFromSource(mw.tx_model.index(row, col))


def tx_cell(mw, entry, col, role=None):
    from PySide6.QtCore import Qt

    return tx_index(mw, entry, col).data(
        Qt.ItemDataRole.DisplayRole if role is None else role
    )


def tx_edit(mw, entry, col, value):
    """A user edit (Period / Payload), as the view's delegate commits it."""
    from PySide6.QtCore import Qt

    return mw.tx_view.model().setData(
        tx_index(mw, entry, col), value, Qt.ItemDataRole.EditRole
    )


def tx_check(mw, entry, checked):
    """The user ticks / unticks a row's En box."""
    from PySide6.QtCore import Qt

    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    return mw.tx_view.model().setData(
        tx_index(mw, entry, 1), state.value, Qt.ItemDataRole.CheckStateRole
    )


def fire_tx(mw, times=1):
    """One tick of every scheduled TX row (no TX thread in tests), then the
    GUI refresh that repaints the rows and feeds XMetro."""
    for _ in range(times):
        mw.tx_scheduler.fire_all()
    mw._tx_refresh()


def rx_view_rows(rx):
    """The RX table as the user sees it: one list of cell texts per row, in view order."""
    proxy = rx.table.model()
    return [
        [proxy.index(r, c).data() for c in range(proxy.columnCount())]
        for r in range(proxy.rowCount())
    ]

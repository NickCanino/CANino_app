# -----------------------------------------------------------------------------
#  Project: CANinoApp
#  Author: Nicasio Canino <nicasio.canino@phd.unipi.it>
#  Organization: Department of Information Engineering (DII), University of Pisa
#  Collaborators: Sergio Saponara <sergio.saponara@unipi.it>, Daniele Rossi <daniele.rossi1@unipi.it>
#  Copyright 2025 Nicasio Canino
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -----------------------------------------------------------------------------

# TODO: assicurarsi che se si fa "load config" e poi "load DBC", la tabella venga aggiornata correttamente (no ID doppioni, mantenuti ID non inclusi nel DBC)

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QGroupBox,
    QTreeWidget,
    QTreeWidgetItem,
    QSpinBox,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QSplitter,
    QStyle,
    QMenuBar,
    QMenu,
    QSlider,
    QScrollArea,
    QStyledItemDelegate,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QCheckBox,
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QFont
from PySide6.QtCore import Qt, QTimer, QObject, Signal
import shiboken6
import importlib.util
import json
import os
import sys
import time
import re
import can

from src.dbc_loader import load_dbc
from src.can_interface import CANInterface
from src.exceptions_logger import log_exception, __version__
from src.xmetro_class import XMetroWindow
from src.vagiletta_programmer_class import VagilettaWindow
from src.received_frames_class import ReceivedFramesWindow
from src.utils import resource_path, format_can_id
from src.PCANBasic import (
    PCAN_BAUD_1M,
    PCAN_BAUD_800K,
    PCAN_BAUD_500K,
    PCAN_BAUD_250K,
    PCAN_BAUD_125K,
    PCAN_BAUD_100K,
    PCAN_BAUD_95K,
    PCAN_BAUD_83K,
    PCAN_BAUD_50K,
    PCAN_BAUD_47K,
    PCAN_BAUD_33K,
    PCAN_BAUD_20K,
    PCAN_BAUD_10K,
    PCAN_BAUD_5K,
)


PCAN_BAUD_FD_2M = can.BitTimingFd(
    f_clock=80000000,
    nom_brp=10,
    nom_tseg1=12,
    nom_tseg2=3,
    nom_sjw=1,
    data_brp=4,
    data_tseg1=7,
    data_tseg2=2,
    data_sjw=1,
)


def pcan_timing(pcan_baud) -> can.BitTiming:
    """Exact classic-CAN timing from a PCAN BTR0BTR1 constant (8 MHz clock).

    Passing `bitrate=` instead is not enough: python-can's PCAN map has no
    entry for 95.238/83.333/47.619/33.333 kbit/s and falls back to 500k.
    """
    v = pcan_baud.value
    return can.BitTiming.from_registers(f_clock=8_000_000, btr0=v >> 8, btr1=v & 0xFF)


def load_payload_function(path: str, module_name: str):
    """Load a payload script as its own module and return its get_payload().

    Every call yields an independent module, so module-level state (counters,
    caches) is never shared between two loads of the same file.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load payload script {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    get_payload_fn = getattr(module, "get_payload", None)
    if not callable(get_payload_fn):
        raise RuntimeError(f"{path} does not contain a function get_payload()")
    return get_payload_fn


BUSLOAD_refresh_rate_ms = 1000
BUS_STATUS_POLL_MS = 250
# Error-warning / error-passive this long while transmitting = frames are not
# being acknowledged: stop TX instead of filling the 32.8k-frame driver queue
TX_ERROR_GRACE_S = 2.0
BUS_STATUS_COLORS = {
    "ok": "#4CAF50",
    "info": "#2196F3",
    "warn": "#FF9800",
    "severe": "#E53935",
}

# Tx column definition
TX_COL_0_del = 0
TX_COL_1_enable = 1
TX_COL_2_id = 2
TX_COL_3_fd = 3
TX_COL_4_name = 4
TX_COL_5_period = 5
TX_COL_6_payload = 6
TX_COL_7_script = 7

TX_COL_DATA = TX_COL_2_id
TX_COL_DATA_ROLE_script = Qt.ItemDataRole.UserRole
TX_COL_DATA_ROLE_dlc = Qt.ItemDataRole.UserRole + 1
TX_COL_DATA_ROLE_is_fd = Qt.ItemDataRole.UserRole + 2
TX_COL_DATA_ROLE_is_ext = Qt.ItemDataRole.UserRole + 3

TX_COL_SCRIPTDATA = TX_COL_7_script
TX_COL_SCRIPTDATA_path = Qt.ItemDataRole.UserRole

CAN_MAX_STD_ID = 0x7FF
CAN_MAX_EXT_ID = 0x1FFFFFFF
# Payload lengths a CAN FD frame can carry (DLC codes 0-15)
CAN_FD_LENGTHS = (1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


def valid_dlc(dlc, is_fd: bool) -> int:
    """Clamp a stored DLC to a length the frame type can carry."""
    try:
        dlc = int(dlc)
    except (TypeError, ValueError):
        return 8
    if not is_fd:
        return min(max(dlc, 1), 8)
    return next((n for n in CAN_FD_LENGTHS if n >= dlc), 64)


def json_flag(value) -> bool:
    """Workspace flags are saved as "Y"/"n"; older files may hold null or bools."""
    if isinstance(value, str):
        return value.strip().upper() in ("Y", "YES", "TRUE", "1")
    return bool(value)


class TxItem(QTreeWidgetItem):
    """TX row that sorts IDs and periods by value, not by cell text.

    Sorting moves the items with their widgets, so timers that hold an item
    stay valid; the old Period sort rebuilt every row and orphaned them
    (TODO 2.5).
    """

    def sort_key(self, column):
        tree = self.treeWidget()
        if column == TX_COL_2_id:
            ext = bool(self.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_ext))
            try:
                return (ext, int(self.text(TX_COL_2_id), 16))
            except ValueError:
                return (ext, -1)
        if column == TX_COL_5_period and tree is not None:
            spin = tree.itemWidget(self, TX_COL_5_period)
            return spin.value() if spin is not None else 0
        return self.text(column).lower()

    def __lt__(self, other):
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else TX_COL_2_id
        if isinstance(other, TxItem):
            return self.sort_key(column) < other.sort_key(column)
        return super().__lt__(other)


class AddIdDialog(QDialog):
    """One form for a manual TX row, validated before it closes (TODO 2.3)."""

    def __init__(self, parent=None, existing_keys=()):
        super().__init__(parent)
        self.setWindowTitle("Add Manual ID")
        self.existing_keys = set(existing_keys)
        self.result_values = None

        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("hex, e.g. 123 or 18FF0001")
        self.cb_ext = QCheckBox("29-bit extended ID")
        self.cb_fd = QCheckBox("CAN FD frame")
        self.cb_dlc = QComboBox()
        self.sp_period = QSpinBox()
        self.sp_period.setRange(1, 10000)
        self.sp_period.setValue(100)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("optional")
        self.lbl_error = QLabel()
        self.lbl_error.setStyleSheet("color: #E53935;")

        form = QFormLayout(self)
        form.addRow("ID:", self.ed_id)
        form.addRow("", self.cb_ext)
        form.addRow("", self.cb_fd)
        form.addRow("DLC (bytes):", self.cb_dlc)
        form.addRow("Period (ms):", self.sp_period)
        form.addRow("Name:", self.ed_name)
        form.addRow(self.lbl_error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.cb_fd.toggled.connect(self._fill_dlc)
        self._fill_dlc(False)

    def _fill_dlc(self, is_fd):
        current = self.cb_dlc.currentData() or 8
        self.cb_dlc.clear()
        for n in CAN_FD_LENGTHS if is_fd else range(1, 9):
            self.cb_dlc.addItem(str(n), n)
        self.cb_dlc.setCurrentIndex(
            max(0, self.cb_dlc.findData(valid_dlc(current, is_fd)))
        )

    def parse(self):
        """(values, None) when the form is valid, else (None, error text)."""
        text = self.ed_id.text().strip()
        if text.lower().startswith("0x"):
            text = text[2:]
        try:
            frame_id = int(text, 16)
        except ValueError:
            return None, "The ID must be a hexadecimal number."
        is_ext = self.cb_ext.isChecked()
        limit = CAN_MAX_EXT_ID if is_ext else CAN_MAX_STD_ID
        if not 0 <= frame_id <= limit:
            kind = "extended" if is_ext else "standard"
            return None, f"A {kind} ID must be in 0x0 - 0x{limit:X}."
        if (frame_id, is_ext) in self.existing_keys:
            return (
                None,
                f"{format_can_id(frame_id, is_ext)} is already in the TX table.",
            )
        name = self.ed_name.text().strip() or f"ID_{frame_id:X}"
        return {
            "frame_id": frame_id,
            "name": name,
            "period": self.sp_period.value(),
            "dlc": self.cb_dlc.currentData(),
            "is_fd": self.cb_fd.isChecked(),
            "is_ext": is_ext,
        }, None

    def accept(self):
        values, error = self.parse()
        if error:
            self.lbl_error.setText(error)
            return
        self.result_values = values
        super().accept()


class PayloadEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        # Only allow editing for payload column (column 6)
        if index.column() == 6:
            return super().createEditor(parent, option, index)
        return None

    def initStyleOption(self, option, index):
        # Monospace style for some columns
        super().initStyleOption(option, index)
        if (
            index.column() == TX_COL_2_id
            or index.column() == TX_COL_4_name
            or index.column() == TX_COL_6_payload
        ):
            font = QFont("Courier New", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            option.font = font


class RxBridge(QObject):
    """Carries received frames from the RX thread to the GUI thread (queued)."""

    frame_received = Signal(int, object)


class SliderMeta:
    def __init__(
        self,
        msg_name: str,
        signal_name: str,
        frame_id: int,
        min_val: float,
        max_val: float,
        step: float,
        unit: str,
        value_index: int,
    ):
        self.msg_name = msg_name
        self.signal_name = signal_name
        self.frame_id = frame_id
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.unit = unit
        self.value_index = value_index  # posizione dello slider


class MainWindow(QMainWindow):
    CONFIG_FILE = "resources/workspace_config_files/default_config_file.json"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CANino App - v{__version__}")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setGeometry(100, 100, 1100, 700)

        # Class Attributes
        self.dbc = None
        self.can_if = None
        self.timers = []
        self.tx_skipped_fd = []
        self.tx_running = False
        self.global_script_path = None
        self.global_script_cache = {}
        # (frame_id, script_path) -> get_payload of that ID's own script instance;
        # emptied at Start TX only, so internal TX restarts keep script state
        self.script_instances = {}
        self.project_root = os.getcwd()

        self.busload_tx_arbitration_bits = 0
        self.busload_tx_data_bits = 0

        # --- MENU ---
        menubar = QMenuBar(self)
        menubar.setStyleSheet(
            """
            
            QMenuBar::item {
                background: #1E1E1E;
                color: white;
            }
            QMenuBar::item:selected {
                background: #553200;
            }
            QMenu {
                background-color: #444444;
                color: white;
            }
            QMenu::item:selected {
                background: #666666;
            }
        """
        )
        file_menu = QMenu("&File", self)
        action_save = QAction("Save", self)
        action_save_as = QAction("Save As...", self)
        action_load = QAction("Load", self)
        # Connect actions to methods
        action_save.triggered.connect(self.save_config)
        action_save_as.triggered.connect(self.save_config_as)
        action_load.triggered.connect(self.load_config)
        # Set icons for actions
        action_save.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        action_save_as.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        action_load.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        # Add actions to the file menu
        file_menu.addAction(action_save)
        file_menu.addAction(action_save_as)
        file_menu.addAction(action_load)
        menubar.addMenu(file_menu)

        # --- AGGIUNGI L'AZIONE "VAGILETTA" ALLA MENUBAR ---
        action_vagiletta = QAction("VAGILETTA", self)
        action_vagiletta.triggered.connect(self.open_vagiletta_window)
        menubar.addAction(action_vagiletta)

        # --- AGGIUNGI L'AZIONE "XMETRO" ALLA MENUBAR ---
        action_xmetro = QAction("XMetro", self)
        # action_xmetro.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
        action_xmetro.triggered.connect(self.open_xmetro_window)
        menubar.addAction(action_xmetro)

        self.setMenuBar(menubar)

        # --- CONTROLLI IN ALTO ---
        top_controls = QWidget()
        top_layout = QHBoxLayout()
        top_controls.setLayout(top_layout)
        top_controls.setFixedHeight(50)  # Imposta l'altezza fissa del box superiore

        # --- PULSANTI E COMBOBOX IN ALTO ---
        self.btn_load_dbc = QPushButton("  Load DBC")
        self.btn_load_dbc.setToolTip(
            "Load a DBC file to be used for TX list, RX decoding, Sliders, and XMetro Gauges."
        )
        self.btn_load_dbc.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.btn_load_dbc.setFixedSize(120, 30)
        self.btn_load_dbc.clicked.connect(self.load_dbc_file)
        top_layout.addWidget(self.btn_load_dbc)

        ## ComboBox per selezionare il canale CAN
        self.lbl_bus_tx = QLabel("Channel:")
        self.lbl_bus_tx.setToolTip(
            "Select the USB-to-CAN bus channel to be used for TX and RX."
        )
        self.lbl_bus_tx.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_bus_tx, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.cb_bus_tx = QComboBox()
        self.cb_bus_tx.setFixedSize(200, 30)
        top_layout.addWidget(self.cb_bus_tx)

        self.btn_refresh_bus = QPushButton()
        self.btn_refresh_bus.setToolTip(
            "Refresh the list of available USB-to-CAN bus channels."
        )
        self.btn_refresh_bus.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.btn_refresh_bus.setFixedSize(30, 30)
        self.btn_refresh_bus.clicked.connect(self.refresh_bus_list)
        top_layout.addWidget(self.btn_refresh_bus)

        # Timer per aggiornare il busload
        self.timer_busload = QTimer(self)
        self.timer_busload.timeout.connect(self.timer_busload_elapsed)
        self.timer_busload.start(BUSLOAD_refresh_rate_ms)

        self.lbl_busload = QLabel("BusLoad:")
        self.lbl_busload.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_busload, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Controller state, polled while connected (TODO 1.5)
        self.lbl_bus_status = QLabel("Bus: -")
        self.lbl_bus_status.setToolTip("CAN controller state of the connected channel.")
        top_layout.addWidget(
            self.lbl_bus_status, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        self.timer_bus_status = QTimer(self)
        self.timer_bus_status.timeout.connect(self.poll_bus_status)
        self._bus_bad_since = None

        self.lbl_baudrate = QLabel("Baudrate:")
        self.lbl_baudrate.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_baudrate, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.cb_baudrate = QComboBox()
        # (label, python-can timing, data bitrate, arbitration bitrate if CAN FD)
        self.baudrate_values = [
            ("2 MBit/s (CANFD)", PCAN_BAUD_FD_2M, 2000000, 500000),
            ("1 MBit/s", pcan_timing(PCAN_BAUD_1M), 1000000, 0),
            ("800 kBit/s", pcan_timing(PCAN_BAUD_800K), 800000, 0),
            ("500 kBit/s", pcan_timing(PCAN_BAUD_500K), 500000, 0),
            ("250 kBit/s", pcan_timing(PCAN_BAUD_250K), 250000, 0),
            ("125 kBit/s", pcan_timing(PCAN_BAUD_125K), 125000, 0),
            ("100 kBit/s", pcan_timing(PCAN_BAUD_100K), 100000, 0),
            ("95.238 kBit/s", pcan_timing(PCAN_BAUD_95K), 95238, 0),
            ("83.333 kBit/s", pcan_timing(PCAN_BAUD_83K), 83333, 0),
            ("50 kBit/s", pcan_timing(PCAN_BAUD_50K), 50000, 0),
            ("47.619 kBit/s", pcan_timing(PCAN_BAUD_47K), 47619, 0),
            ("33.333 kBit/s", pcan_timing(PCAN_BAUD_33K), 33333, 0),
            ("20 kBit/s", pcan_timing(PCAN_BAUD_20K), 20000, 0),
            ("10 kBit/s", pcan_timing(PCAN_BAUD_10K), 10000, 0),
            ("5 kBit/s", pcan_timing(PCAN_BAUD_5K), 5000, 0),
        ]
        # The timing is looked up by index: a BitTiming is a Mapping and must
        # not go through QVariant conversion as combo item data
        for label, _timing, _data_val, _arb_val in self.baudrate_values:
            self.cb_baudrate.addItem(label)
        self.cb_baudrate.setCurrentIndex(3)  # Default to 500 kBit/s
        self.cb_baudrate.setFixedSize(150, 30)
        top_layout.addWidget(self.cb_baudrate)

        self.cb_listen_only = QCheckBox("Listen only")
        self.cb_listen_only.setToolTip(
            "Connect without ever driving the bus: no ACK, no error flags, no TX.\n"
            "Use it to sniff a vehicle or an unknown network."
        )
        top_layout.addWidget(self.cb_listen_only)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setToolTip(
            "Connect to the selected USB-to-CAN bus channel, with the selected Baudrate."
        )
        self.btn_connect.setCheckable(True)
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.btn_connect.setFixedSize(100, 30)
        self.btn_connect.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
        )
        top_layout.addWidget(self.btn_connect)

        # Button to ADD IDs in TX
        self.btn_add_id = QPushButton("Add ID")
        self.btn_add_id.setToolTip("Add a new CAN ID manually to the TX list.")
        self.btn_add_id.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.btn_add_id.setFixedSize(100, 30)
        self.btn_add_id.clicked.connect(self.add_manual_id)

        # Button to start TX
        self.btn_start_tx = QPushButton("Start TX")
        self.btn_start_tx.setToolTip(
            "Start the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        )
        self.btn_start_tx.setFixedSize(100, 30)
        self.btn_start_tx.clicked.connect(self.start_stop_transmission)
        self.btn_start_tx.setEnabled(False)  # Disabilita il pulsante all'inizio

        # Button to disable all ID in TX
        self.btn_disable_all_ids = QPushButton("Disable All")
        self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
        self.btn_disable_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        )
        self.btn_disable_all_ids.setFixedSize(100, 30)
        self.btn_disable_all_ids.clicked.connect(self.disable_all_ids_tx)
        self.btn_disable_all_ids.setEnabled(False)  # Disabilita il pulsante all'inizio

        # Button to delete all IDs in TX
        self.btn_delete_all_ids = QPushButton("Delete All")
        self.btn_delete_all_ids.setToolTip("Delete all CAN IDs from the TX list.")
        self.btn_delete_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.btn_delete_all_ids.setFixedSize(100, 30)
        self.btn_delete_all_ids.clicked.connect(self.delete_all_ids_tx)
        self.btn_delete_all_ids.setEnabled(False)  # Disabilitato all'inizio

        # # Button to open the XMetro window
        # self.btn_add_xmetro = QPushButton("Add XMetro")
        # self.btn_add_xmetro.setIcon(
        #     self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        # )
        # self.btn_add_xmetro.setFixedSize(140, 30)
        # self.btn_add_xmetro.clicked.connect(self.open_xmetro_window)
        # self.xmetro_windows = []

        # Button to link a global Payload Script
        self.btn_link_global_script = QPushButton("Link Global Script")
        self.btn_link_global_script.setToolTip(
            "Link a global Payload Script to be used for ALL transmitted CAN frames."
        )
        self.btn_link_global_script.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.btn_link_global_script.setFixedSize(200, 30)
        # self.btn_link_global_script.setStyleSheet("overflow: hidden; text-overflow: ellipsis;")
        # self.btn_link_global_script.setToolTip(self.btn_link_global_script.text())
        self.btn_link_global_script.clicked.connect(self.select_global_payload_script)

        # Button to REMOVE a global Payload Script
        self.btn_remove_global_script = QPushButton()
        self.btn_remove_global_script.setToolTip(
            "Remove the linked Global Payload Script."
        )
        self.btn_remove_global_script.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self.btn_remove_global_script.setFixedSize(30, 30)
        self.btn_remove_global_script.setEnabled(False)  # Disabilitato di default
        self.btn_remove_global_script.clicked.connect(self.remove_global_payload_script)

        # Layout orizzontale per i due pulsanti
        tx_buttons_layout = QHBoxLayout()
        tx_buttons_layout.addWidget(self.btn_add_id)
        tx_buttons_layout.addWidget(self.btn_delete_all_ids)
        tx_buttons_layout.addStretch(0)
        tx_buttons_layout.addWidget(self.btn_disable_all_ids)
        tx_buttons_layout.addWidget(self.btn_start_tx)
        # tx_buttons_layout.addWidget(self.btn_add_xmetro)
        tx_buttons_layout.addStretch(0)
        tx_buttons_layout.addWidget(self.btn_link_global_script)
        tx_buttons_layout.addWidget(self.btn_remove_global_script)

        # --- ALBERO DEI SEGNALI ---
        self.signal_tree = QTreeWidget()
        self.signal_tree.setHeaderLabels(
            [
                "",
                "En",
                "ID",
                "FD",
                "Name",
                "Period (ms)",
                "Payload",
                "Script for Specific ID",
            ]
        )
        self.signal_tree.setColumnWidth(TX_COL_0_del, 40)  # old: 50
        self.signal_tree.setColumnWidth(TX_COL_1_enable, 30)  # old: 50
        self.signal_tree.setColumnWidth(TX_COL_2_id, 50)
        self.signal_tree.setColumnWidth(TX_COL_3_fd, 30)
        self.signal_tree.setColumnWidth(TX_COL_4_name, 100)
        self.signal_tree.setColumnWidth(TX_COL_5_period, 80)
        self.signal_tree.setColumnWidth(TX_COL_6_payload, 200)  # old: 190
        self.signal_tree.setColumnWidth(TX_COL_7_script, 70)
        self.signal_tree.itemChanged.connect(self.on_signal_tree_item_changed)

        self.signal_tree.setSortingEnabled(True)
        self.signal_tree.setItemDelegate(PayloadEditDelegate(self.signal_tree))
        self.signal_tree.header().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

        # Groupbox per i controlli di trasmissione
        tx_group = QGroupBox()
        tx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #4CAF50; border-radius: 5px; }"
        )
        # Crea il layout verticale per il gruppo di trasmissione
        tx_layout = QVBoxLayout()
        tx_group.setLayout(tx_layout)
        tx_title = QLabel("Transmitted CAN Frames (TX)")
        tx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tx_title.setStyleSheet("font-weight: bold;")
        tx_layout.addWidget(tx_title)
        tx_layout.addLayout(tx_buttons_layout)
        tx_layout.addWidget(self.signal_tree)

        # Aggiungi il layout dei controlli di ricezione al layout principale
        self.rx_window = ReceivedFramesWindow(self.dbc)
        # RX thread -> GUI thread hand-over for the XMetro gauges
        self.xmetro_windows = []
        self.rx_bridge = RxBridge(self)
        self.rx_bridge.frame_received.connect(self._feed_gauges)
        rx_group = QGroupBox()
        rx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #2196F3; border-radius: 5px; }"
        )
        # Crea il layout verticale per il gruppo di ricezione
        rx_layout = QVBoxLayout()
        rx_group.setLayout(rx_layout)
        rx_title = QLabel("Received CAN Frames (RX)")
        rx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rx_title.setStyleSheet("font-weight: bold;")
        rx_layout.addWidget(rx_title)
        rx_layout.addWidget(self.rx_window)

        # --- GRUPPO DEGLI SLIDER ---
        slider_group = QGroupBox()
        slider_group.setStyleSheet(
            "QGroupBox { border: 2px solid #FF9800; border-radius: 5px; }"
        )
        slider_group.setMinimumWidth(300)

        slider_layout = QVBoxLayout()
        slider_group.setLayout(slider_layout)

        slider_title = QLabel("Sliders for TX")
        slider_title.setAlignment(Qt.AlignmentFlag.AlignTop)
        slider_title.setStyleSheet("font-weight: bold;")
        slider_layout.addWidget(slider_title)

        self.btn_add_slider = QPushButton("Add Slider")
        self.btn_add_slider.setToolTip(
            "Add a new slider for the selected CAN signal, from the linked DBC file."
        )
        self.btn_add_slider.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.btn_add_slider.setFixedSize(150, 30)
        slider_layout.addWidget(self.btn_add_slider)

        # Area scrollabile
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        slider_scroll_widget = QWidget()
        self.slider_container = QVBoxLayout()
        slider_scroll_widget.setLayout(self.slider_container)
        scroll_area.setWidget(slider_scroll_widget)
        slider_layout.addWidget(scroll_area)
        self.slider_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.added_sliders = set()
        self.slider_widgets = []

        def add_slider():
            if not hasattr(self, "dbc") or self.dbc is None:
                QMessageBox.warning(self, "DBC", "Load a DBC file first!")
                return

            # Only consider checked TX items
            checked_ids = set()
            for i in range(self.signal_tree.topLevelItemCount()):
                item = self.signal_tree.topLevelItem(i)
                if item.checkState(TX_COL_1_enable) == Qt.CheckState.Checked:
                    try:
                        frame_id = int(item.text(TX_COL_2_id), 16)
                        checked_ids.add(frame_id)
                    except Exception:
                        continue

            if not checked_ids:
                QMessageBox.warning(self, "Slider", "No TX messages enabled.")
                return

            # Filter DBC messages to only those with checked IDs
            filtered_msgs = [
                msg for msg in self.dbc.messages if msg.frame_id in checked_ids
            ]
            if not filtered_msgs:
                QMessageBox.warning(
                    self, "Slider", "No checked DBC messages found in TX table."
                )
                return

            msg_names = [msg.name for msg in filtered_msgs]
            msg_idx, ok = QInputDialog.getItem(
                self, "Select Message", "Message:", msg_names, 0, False
            )
            if not ok:
                return

            msg = next(m for m in self.dbc.messages if m.name == msg_idx)
            sig_names = [sig.name for sig in msg.signals]
            sig_idx, ok = QInputDialog.getItem(
                self, "Select Signal", "Signal:", sig_names, 0, False
            )
            if not ok:
                return

            sig = next(s for s in msg.signals if s.name == sig_idx)
            key = (msg.name, sig.name)
            if key in self.added_sliders:
                QMessageBox.warning(
                    self,
                    "Slider already exists",
                    f"Slider already exists for {msg.name} (0x{msg.frame_id:03X}) → {sig.name} [{sig.length+sig.start_bit-1}:{sig.start_bit}]",
                )
                return

            self.added_sliders.add(key)

            # Calcolo min/max SEMPRE da bit_length, offset, scale, signed/unsigned, endianess
            factor = getattr(sig, "factor", getattr(sig, "scale", 1.0)) or 1.0
            offset = getattr(sig, "offset", 0.0)
            bit_length = getattr(sig, "length", 8)
            is_signed = getattr(sig, "is_signed", False)
            # endianess non influisce su min/max, ma la includo per completezza
            if is_signed:
                raw_min = -(2 ** (bit_length - 1))
                raw_max = 2 ** (bit_length - 1) - 1
            else:
                raw_min = 0
                raw_max = 2**bit_length - 1

            min_val = raw_min * factor + offset
            max_val = raw_max * factor + offset
            step = factor

            # Crea il widget per lo slider
            slider_widget = QGroupBox()
            slider_widget.setFixedHeight(100)  # Altezza fissa
            slider_widget.setStyleSheet(
                "QGroupBox { margin-top: 10px; border: 1px solid gray; border-radius: 5px; }"
            )
            slider_layout_inner = QVBoxLayout()
            slider_widget.setLayout(slider_layout_inner)

            # Aggiungi il widget dello slider alla lista
            if not hasattr(
                self, "slider_widgets"
            ):  # Ensure slider_widgets is initialized
                self.slider_widgets = []

            slider_widget.key = key  # Store the key for later reference
            self.slider_widgets.append(slider_widget)  # Store the widget for later use

            label = QLabel(
                f"{msg.name} (0x{msg.frame_id:03X}) → {sig.name} [{sig.length+sig.start_bit-1}:{sig.start_bit}]"
            )
            slider_layout_inner.addWidget(label)

            # Crea e setta lo slider
            num_steps = int(round((max_val - min_val) / step))

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(num_steps)
            slider.setSingleStep(1)
            slider.setValue(0)
            slider_layout_inner.addWidget(slider)

            # Salva metadata
            slider_widget.frame_id = msg.frame_id
            slider_widget.is_ext = msg.is_extended_frame
            slider_widget.signal = sig
            slider_widget.slider = slider
            slider_widget.min_val = min_val
            slider_widget.max_val = max_val
            slider_widget.step = step
            slider_widget.unit = sig.unit if sig.unit else ""

            info_layout = QHBoxLayout()
            lbl_min = QLabel(f"Min: {min_val}")
            lbl_max = QLabel(f"Max: {max_val}")
            lbl_value = QLabel(f"Val: {min_val} [{sig.unit}]")
            btn_remove = QPushButton()
            btn_remove.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            )
            btn_remove.setFixedWidth(30)

            def update_value_label(step_index):
                real_value = min_val + step_index * step
                formatted = f"{real_value:.2f}" if step < 1.0 else f"{int(real_value)}"
                lbl_value.setText(f"Val: {formatted} {sig.unit if sig.unit else ''}")

            def remove_slider():
                for i in reversed(range(self.slider_container.count())):
                    widget = self.slider_container.itemAt(i).widget()
                    if widget == slider_widget:
                        # Rimuovi il widget visivamente
                        widget.setParent(None)

                        # Rimuovi la chiave dallo set di slider aggiunti
                        self.added_sliders.discard(key)

                        # Rimuovi il widget dalla lista slider_widgets
                        if hasattr(self, "slider_widgets"):
                            self.slider_widgets = [
                                w
                                for w in self.slider_widgets
                                if not (
                                    w.frame_id == msg.frame_id
                                    and w.signal.name == sig.name
                                )
                            ]

                        # Riavvia la trasmissione per aggiornare il comportamento
                        if self.tx_running:
                            self.stop_tx()
                            self.start_tx()
                        break

            slider.valueChanged.connect(update_value_label)
            btn_remove.clicked.connect(remove_slider)

            info_layout.addWidget(lbl_min)
            info_layout.addStretch()
            info_layout.addWidget(lbl_value)
            info_layout.addStretch()
            info_layout.addWidget(lbl_max)
            info_layout.addWidget(btn_remove)
            slider_layout_inner.addLayout(info_layout)

            self.slider_container.addWidget(slider_widget)

        self.refresh_bus_list()

        self.btn_add_slider.clicked.connect(add_slider)

        # --- SPLITTER PRINCIPALE ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        # Box sinistra: splitter verticale con TX e RX
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tx_group)
        left_splitter.addWidget(rx_group)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(slider_group)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 2)

        # --- BARRA IN FONDO CON IMMAGINE ---
        footer_widget = QWidget()
        footer_widget.setFixedHeight(40)  # Altezza fissa, puoi cambiare il valore

        footer_bar = QHBoxLayout(footer_widget)
        footer_bar.setContentsMargins(0, 0, 0, 0)
        footer_bar.setSpacing(0)

        footer_label_banner = QLabel()
        footer_label_banner.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom
        )

        footer_label_dii = QLabel()
        footer_label_dii.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom
        )

        # Scala la figura in base all'altezza fissa
        footer_height = footer_widget.height()

        pixmap_banner_app = QPixmap(
            resource_path("resources/figures/CANinoApp_banner_background.png")
        )
        scaled_pixmap_banner_app = pixmap_banner_app.scaledToHeight(
            footer_height, Qt.TransformationMode.SmoothTransformation
        )
        footer_label_banner.setPixmap(scaled_pixmap_banner_app)

        pixmap_dii = QPixmap(resource_path("resources/figures/dii_logo.png"))
        scaled_pixmap_dii = pixmap_dii.scaledToHeight(
            footer_height, Qt.TransformationMode.SmoothTransformation
        )
        footer_label_dii.setPixmap(scaled_pixmap_dii)

        footer_bar.addWidget(footer_label_banner)
        footer_bar.addWidget(footer_label_dii)

        # Layout principale
        main_layout = QVBoxLayout()
        main_layout.addWidget(top_controls)
        main_layout.addWidget(main_splitter)
        main_layout.addWidget(footer_widget)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.refresh_bus_list()
        # Carica la configurazione all'avvio, se esiste
        self.load_config(auto=True)

    def disable_all_ids_tx(self):
        if (
            self.btn_disable_all_ids.text() == "Enable All"
        ):  # Attualmente disabilitati, quindi abilita tutti
            for i in range(self.signal_tree.topLevelItemCount()):
                item = self.signal_tree.topLevelItem(i)
                item.setCheckState(TX_COL_1_enable, Qt.CheckState.Checked)

            self.btn_disable_all_ids.setText("Disable All")
            self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
            self.btn_disable_all_ids.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
            )
        else:  # Attualmente abilitati, quindi disabilita tutti
            for i in range(self.signal_tree.topLevelItemCount()):
                item = self.signal_tree.topLevelItem(i)
                item.setCheckState(TX_COL_1_enable, Qt.CheckState.Unchecked)

            self.btn_disable_all_ids.setText("Enable All")
            self.btn_disable_all_ids.setToolTip("Enable all CAN IDs in the TX list.")
            self.btn_disable_all_ids.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
            )

    def delete_all_ids_tx(self):
        """
        Elimina tutti gli ID dalla tabella TX dopo conferma.
        """
        if self.signal_tree.topLevelItemCount() == 0:
            return  # Tabella già vuota

        # Chiedi conferma
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete all IDs from the TX list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Ferma la trasmissione se è attiva
            if self.tx_running:
                self.stop_tx()
            else:
                # Assicurati che i timer siano puliti anche se non in "running"
                for t in self.timers:
                    t.stop()
                self.timers.clear()

            # Pulisci la tabella
            self.signal_tree.clear()

            # Disabilita i pulsanti che dipendono dalla lista
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def clear_busload_stats(self):
        self.busload_tx_arbitration_bits = 0
        self.busload_tx_data_bits = 0

    def get_busload_tx_arbitration_bits(self):
        return self.busload_tx_arbitration_bits

    def get_busload_tx_data_bits(self):
        return self.busload_tx_data_bits

    def save_config(self):
        self._save_config_to_file(self.CONFIG_FILE)

    def save_config_as(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save configuration as", "", "File JSON (*.json)"
        )
        if filename:
            self._save_config_to_file(filename)
            self.CONFIG_FILE = filename  # Aggiorna il file di default

    def _save_config_to_file(self, filename):
        if hasattr(self, "dbc") and self.dbc is not None:  # Verifica se dbc è caricato
            dbc_path = os.path.relpath(
                self.dbc.dbc_filename, start=self.project_root
            )  # percorso relativo del file DBC
        else:
            dbc_path = None

        config = {
            "dbc_file": dbc_path,
            "signals": [],
            "sliders": [],
            "global_script": (
                self.global_script_path if self.global_script_path else None
            ),
        }

        for widget in getattr(self, "slider_widgets", []):
            meta = SliderMeta(
                msg_name=widget.signal.name,
                signal_name=widget.signal.name,
                frame_id=widget.frame_id,
                min_val=widget.min_val,
                max_val=widget.max_val,
                step=widget.step,
                unit=widget.unit,
                value_index=widget.slider.value(),
            )
            config["sliders"].append(meta.__dict__)

        for i in range(self.signal_tree.topLevelItemCount()):
            item = self.signal_tree.topLevelItem(i)
            signal = {
                "enabled": item.checkState(TX_COL_1_enable) == Qt.CheckState.Checked,
                "id": item.text(TX_COL_2_id),
                "ext": "Y" if item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_ext) else "n",
                "fd": "Y" if item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd) else "n",
                "name": item.text(TX_COL_4_name),
                "period": (
                    self.signal_tree.itemWidget(item, TX_COL_5_period).value()
                    if self.signal_tree.itemWidget(item, TX_COL_5_period)
                    else 100
                ),
                "payload": item.text(TX_COL_6_payload),
                "dlc": item.data(TX_COL_DATA, TX_COL_DATA_ROLE_dlc) or 8,
                "script_path": item.data(
                    TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path
                ),  # salva anche lo script per l'ID
            }
            config["signals"].append(signal)
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(
                self,
                "Configuration saved",
                f"Configuration successfully saved to:\n{filename}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving configuration: {e}")
            log_exception(__file__, sys._getframe().f_lineno, e)

    def load_config(self, auto=False):
        if auto:  # Carica automaticamente il file di configurazione predefinito
            filename = self.CONFIG_FILE
            if not os.path.exists(filename):
                return
        else:  # Carica tramite dialogo
            filename, _ = QFileDialog.getOpenFileName(
                self, "Load configuration", "", "File JSON (*.json)"
            )
            if not filename:
                return

        try:  # Prova a caricare il file di configurazione
            self.CONFIG_FILE = filename  # Aggoiorna il percorso di default

            with open(filename, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Loads DBC if existing
            dbc_file = config.get("dbc_file")
            if dbc_file is not None:
                print(f"[DEBUG] Loading DBC from: {dbc_file}")
                absolute_path = os.path.abspath(
                    os.path.join(self.project_root, dbc_file)
                )
                if os.path.exists(absolute_path):
                    self.dbc = load_dbc(absolute_path)
                    self.rx_window.set_dbc(self.dbc)  # RX names (TODO 6.1)
                else:
                    QMessageBox.warning(
                        self,
                        "DBC",
                        f"Cannot find DBC file:\n{absolute_path}",
                    )

            # Restores global script
            global_script = config.get("global_script")
            if global_script:
                self.global_script_path = global_script
                self.global_script_cache.clear()
                self.btn_link_global_script.setStyleSheet(
                    "background-color: #4CAF50; color: white;"
                )
                self.btn_link_global_script.setToolTip(
                    f"Global Script: {global_script}"
                )
                self.btn_link_global_script.setText(os.path.basename(global_script))
                self.btn_remove_global_script.setEnabled(True)
            else:
                self.global_script_path = None
                self.global_script_cache.clear()
                self.btn_link_global_script.setStyleSheet("")
                self.btn_link_global_script.setToolTip("No Global Script Linked")
                self.btn_link_global_script.setText("Link Global Script")
                self.btn_link_global_script.setToolTip(
                    "Link a global Payload Script to be used for all transmitted CAN frames."
                )
                self.btn_remove_global_script.setEnabled(False)

            # Load signals only if present in the configuration
            for sig in config.get("signals") or []:
                try:
                    frame_id = int(sig.get("id", "0"), 16)
                except (TypeError, ValueError):
                    continue
                # Files written before 1.5 carry no "ext": they could not send
                # IDs above 0x7FF, so the number decides (TODO 1.6)
                is_ext = json_flag(sig.get("ext")) or frame_id > CAN_MAX_STD_ID
                if frame_id > CAN_MAX_EXT_ID:
                    continue

                # Row already in the table (e.g. from the DBC): link the script only
                existing = self._find_tx_item(frame_id, is_ext)
                if existing is not None:
                    if sig.get("script_path"):
                        self._set_script_link(existing, sig["script_path"])
                    continue

                self._add_tx_row(
                    frame_id,
                    sig.get("name", ""),
                    period=sig.get("period", 100),
                    dlc=sig.get("dlc", 8),
                    is_fd=json_flag(sig.get("fd")),
                    is_ext=is_ext,
                    payload=sig.get("payload", ""),
                    script_path=sig.get("script_path"),
                    enabled=bool(sig.get("enabled")),
                )
            self.signal_tree.sortItems(TX_COL_2_id, Qt.SortOrder.AscendingOrder)

            # Load sliders
            sliders_cfg = config.get("sliders") or []
            if sliders_cfg and self.dbc is None:
                QMessageBox.warning(
                    self,
                    "Sliders",
                    f"{len(sliders_cfg)} slider(s) skipped: they need the workspace DBC, which is not loaded.",
                )
                sliders_cfg = []
            if sliders_cfg:
                print("[DEBUG] Loading sliders from configuration...")
                for meta in sliders_cfg:
                    msg = next(
                        (
                            m
                            for m in self.dbc.messages
                            if m.frame_id == meta["frame_id"]
                        ),
                        None,
                    )
                    if not msg:
                        continue
                    sig = next(
                        (s for s in msg.signals if s.name == meta["signal_name"]), None
                    )
                    if not sig:
                        continue

                    # Ricostruisci lo slider manualmente
                    key = (msg.name, sig.name)
                    if key in self.added_sliders:
                        continue
                    self.added_sliders.add(key)

                    # Calcolo min/max SEMPRE da bit_length, offset, scale, signed/unsigned, endianess
                    factor = getattr(sig, "factor", getattr(sig, "scale", 1.0)) or 1.0
                    offset = getattr(sig, "offset", 0.0)
                    bit_length = getattr(sig, "length", 8)
                    is_signed = getattr(sig, "is_signed", False)
                    if is_signed:
                        raw_min = -(2 ** (bit_length - 1))
                        raw_max = 2 ** (bit_length - 1) - 1
                    else:
                        raw_min = 0
                        raw_max = 2**bit_length - 1
                    min_val = raw_min * factor + offset
                    max_val = raw_max * factor + offset
                    step = factor
                    value_index = meta["value_index"]
                    unit = sig.unit if hasattr(sig, "unit") and sig.unit else ""

                    # costruttore slider come da add_slider()
                    slider_widget = QGroupBox()
                    slider_widget.setFixedHeight(100)
                    slider_layout_inner = QVBoxLayout()
                    slider_widget.setLayout(slider_layout_inner)

                    label = QLabel(
                        f"{msg.name} (0x{msg.frame_id:03X}) → {sig.name} [{sig.length+sig.start_bit-1}:{sig.start_bit}]"
                    )
                    slider_layout_inner.addWidget(label)

                    slider = QSlider(Qt.Orientation.Horizontal)
                    num_steps = int(round((max_val - min_val) / step))
                    slider.setMinimum(0)
                    slider.setMaximum(num_steps)
                    slider.setSingleStep(1)
                    slider.setValue(value_index)
                    slider_layout_inner.addWidget(slider)

                    # Salva metadata
                    slider_widget.frame_id = msg.frame_id
                    slider_widget.is_ext = msg.is_extended_frame
                    slider_widget.signal = sig
                    slider_widget.slider = slider
                    slider_widget.min_val = min_val
                    slider_widget.max_val = max_val
                    slider_widget.step = step
                    slider_widget.unit = unit

                    info_layout = QHBoxLayout()
                    lbl_min = QLabel(f"Min: {min_val}")
                    lbl_max = QLabel(f"Max: {max_val}")
                    lbl_value = QLabel(f"Val: {min_val} [{unit}]")
                    btn_remove = QPushButton()
                    btn_remove.setIcon(
                        self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                    )
                    btn_remove.setFixedWidth(30)

                    def update_value_label(
                        step_index,
                        min_val=min_val,
                        step=step,
                        lbl_value=lbl_value,
                        unit=unit,
                    ):
                        real_value = min_val + step_index * step
                        formatted = (
                            f"{real_value:.2f}" if step < 1.0 else f"{int(real_value)}"
                        )
                        lbl_value.setText(f"Val: {formatted} {unit}")

                    slider.valueChanged.connect(update_value_label)
                    update_value_label(slider.value())  # show the restored value
                    # Bind this slider's widget now: a closure would see the last
                    # loop iteration's variables (TODO 4.2)
                    btn_remove.clicked.connect(
                        lambda _=False, w=slider_widget: self.remove_slider_widget(w)
                    )

                    info_layout.addWidget(lbl_min)
                    info_layout.addStretch()
                    info_layout.addWidget(lbl_value)
                    info_layout.addStretch()
                    info_layout.addWidget(lbl_max)
                    info_layout.addWidget(btn_remove)
                    slider_layout_inner.addLayout(info_layout)

                    if not hasattr(self, "slider_widgets"):
                        self.slider_widgets = []

                    self.slider_container.addWidget(slider_widget)
                    slider_widget.key = key  # Unico identificatore per lo slider
                    self.slider_widgets.append(slider_widget)

            # Row-dependent buttons follow the table, sliders or not (TODO 6.2)
            has_rows = self.signal_tree.topLevelItemCount() > 0
            self.btn_disable_all_ids.setEnabled(has_rows)
            self.btn_delete_all_ids.setEnabled(has_rows)

            if not auto:
                QMessageBox.information(
                    self, "Configuration", "Configuration loaded successfully."
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {e}")
            log_exception(__file__, sys._getframe().f_lineno, e)

    def open_vagiletta_window(self):
        dlg = VagilettaWindow(self)
        dlg.exec()

    def remove_slider_widget(self, widget):
        # Remove the widget from the slider_container and update the slider list
        widget.setParent(None)
        if hasattr(widget, "key"):
            self.added_sliders.discard(widget.key)

        self.slider_widgets = [w for w in self.slider_widgets if w != widget]
        if self.tx_running:
            self.stop_tx()
            self.start_tx()

    def refresh_bus_list(self):
        self.cb_bus_tx.clear()
        for display, handle in CANInterface.get_available_channels():
            self.cb_bus_tx.addItem(display, handle)
        if self.cb_bus_tx.count() == 0 and CANInterface.scan_error:
            self.cb_bus_tx.addItem(CANInterface.scan_error, None)

    def toggle_connection(self):
        if self.btn_connect.isChecked():  # Connect button is checked
            channel = self.cb_bus_tx.currentData()  # Get the selected channel
            if channel is None:
                QMessageBox.warning(
                    self,
                    "Warning",
                    CANInterface.scan_error or "No CAN channel selected",
                )
                self.btn_connect.setChecked(False)
                return

            # --- Check if the selected channel is still available ---
            available_channels = [
                handle for _, handle in CANInterface.get_available_channels()
            ]
            if channel not in available_channels:
                QMessageBox.critical(
                    self,
                    "Error",
                    "The selected CAN channel is no longer available (it may be in use or disconnected). Refresh the channel list and try again.",
                )
                self.btn_connect.setChecked(False)
                self.btn_start_tx.setEnabled(False)
                return

            bitrate_lbl, timing, _, _ = self.baudrate_values[
                self.cb_baudrate.currentIndex()
            ]
            if isinstance(timing, can.BitTimingFd) and not CANInterface.is_fd_capable(
                channel
            ):
                QMessageBox.warning(
                    self,
                    "CAN FD",
                    "The selected channel does not support CAN FD. Choose a classic CAN baudrate.",
                )
                self.btn_connect.setChecked(False)
                return

            try:  # Try to connect to the CAN interface
                listen_only = self.cb_listen_only.isChecked()
                self.can_if = CANInterface(
                    channel, timing=timing, listen_only=listen_only
                )
                self.can_if.set_receive_callback(self.process_received_frame)
                mode = "listen only (no TX)" if listen_only else "normal"
                QMessageBox.information(
                    self,
                    "Info",
                    f"Connected to: \n    > {self.cb_bus_tx.currentText()}\n    > Baudrate: {bitrate_lbl}\n    > Mode: {mode}",
                )

                self.btn_connect.setText("Disconnect")
                self.btn_connect.setToolTip(
                    "Disconnect from the selected USB-to-CAN bus channel."
                )
                self.btn_connect.setIcon(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserStop)
                )

                self.cb_baudrate.setEnabled(False)
                self.cb_bus_tx.setEnabled(False)
                self.btn_refresh_bus.setEnabled(False)
                self.btn_add_id.setEnabled(True)
                self.cb_listen_only.setEnabled(False)
                self.btn_start_tx.setEnabled(not listen_only)
                self._bus_bad_since = None
                self.timer_bus_status.start(BUS_STATUS_POLL_MS)
                self.poll_bus_status()

            except Exception as e:
                self.can_if = None
                QMessageBox.critical(self, "Error", f"Error opening CAN: {e}")
                log_exception(__file__, sys._getframe().f_lineno, e)
                self.btn_connect.setChecked(False)
                self.btn_start_tx.setEnabled(False)  # <--- Disable if error

        else:  # Disconnect
            self.timer_bus_status.stop()
            if self.can_if:
                self.can_if.close()
                self.can_if = None
            self.lbl_bus_status.setText("Bus: -")
            self.lbl_bus_status.setStyleSheet("")
            self.cb_listen_only.setEnabled(True)
            self.btn_connect.setText("Connect")
            self.btn_connect.setToolTip(
                "Connect to the selected USB-to-CAN bus channel, with the selected Baudrate."
            )
            self.btn_connect.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
            )

            self.cb_baudrate.setEnabled(True)
            self.cb_bus_tx.setEnabled(True)
            self.btn_refresh_bus.setEnabled(True)
            self.btn_add_id.setEnabled(True)
            self.btn_start_tx.setEnabled(False)  # <--- Disabilita dopo disconnessione
            if self.tx_running:
                self.stop_tx()  # <--- Ferma la trasmissione se attiva

    def load_dbc_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open DBC file", "", "DBC Files (*.dbc)"
        )
        if filename:
            self.dbc = load_dbc(filename)
            self.populate_signal_tree()
            self.rx_window.set_dbc(self.dbc)
            self.btn_disable_all_ids.setEnabled(True)
            self.btn_delete_all_ids.setEnabled(True)

    def populate_signal_tree(self):
        """Add the DBC messages that are not in the TX table yet (TODO 6.9)."""
        if not self.dbc:
            return
        for msg in self.dbc.messages:
            if self._find_tx_item(msg.frame_id, msg.is_extended_frame) is not None:
                continue
            self._add_tx_row(
                msg.frame_id,
                msg.name,
                period=msg.cycle_time or 100,
                dlc=msg.payload_length,
                is_fd=msg.is_fd,
                is_ext=msg.is_extended_frame,
            )
        self.signal_tree.sortItems(TX_COL_2_id, Qt.SortOrder.AscendingOrder)

    def _add_tx_row(
        self,
        frame_id,
        name,
        period=100,
        dlc=8,
        is_fd=False,
        is_ext=False,
        payload="",
        script_path=None,
        enabled=True,
    ):
        """The one TX row builder, for DBC, workspace and manual rows (TODO 2.14).

        Frame flags live in item roles (dlc, is_fd, is_ext): the TX callback
        reads them from there, the cell texts are display only (TODO 2.4).
        """
        is_fd = bool(is_fd)
        is_ext = bool(is_ext) or frame_id > CAN_MAX_STD_ID
        dlc = valid_dlc(dlc, is_fd)
        parts = (payload or "").strip().split()
        if len(parts) != dlc or not all(
            re.fullmatch(r"[0-9a-fA-F]{2}", p) for p in parts
        ):
            parts = ["00"] * dlc

        # No itemChanged while the row is half built: the payload check would
        # run before the DLC role is set
        blocked = self.signal_tree.blockSignals(True)
        try:
            item = TxItem(self.signal_tree)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_dlc, dlc)
            item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd, is_fd)
            item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_is_ext, is_ext)
            item.setCheckState(
                TX_COL_1_enable,
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked,
            )
            item.setText(TX_COL_2_id, format_can_id(frame_id, is_ext))
            item.setToolTip(
                TX_COL_2_id, "29-bit extended ID" if is_ext else "11-bit standard ID"
            )
            item.setText(TX_COL_3_fd, "Y" if is_fd else "n")
            item.setText(TX_COL_4_name, name)
            item.setText(TX_COL_6_payload, " ".join(p.upper() for p in parts))

            period_spin = QSpinBox()
            period_spin.setRange(1, 10000)
            try:
                period_spin.setValue(int(period))
            except (TypeError, ValueError):
                period_spin.setValue(100)
            self.signal_tree.setItemWidget(item, TX_COL_5_period, period_spin)

            btn_delete_id = QPushButton()
            btn_delete_id.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            )
            btn_delete_id.setToolTip("Delete")
            btn_delete_id.clicked.connect(
                lambda _=False, it=item: self.delete_signal_row(it)
            )
            self.signal_tree.setItemWidget(item, TX_COL_0_del, btn_delete_id)

            self._setup_script_buttons_for_item(item)
            if script_path:
                self._set_script_link(item, script_path)
        finally:
            self.signal_tree.blockSignals(blocked)
        return item

    @staticmethod
    def _row_key(item):
        """(ID, is_ext) of a TX row: std 0x123 and ext 0x123 are distinct frames."""
        try:
            frame_id = int(item.text(TX_COL_2_id), 16)
        except ValueError:
            frame_id = -1
        return frame_id, bool(item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_ext))

    def _tx_items(self):
        return [
            self.signal_tree.topLevelItem(i)
            for i in range(self.signal_tree.topLevelItemCount())
        ]

    def _find_tx_item(self, frame_id, is_ext):
        key = (frame_id, bool(is_ext))
        return next((it for it in self._tx_items() if self._row_key(it) == key), None)

    def add_manual_id(self):
        dlg = AddIdDialog(self, {self._row_key(it) for it in self._tx_items()})
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_values is None:
            return
        self._add_tx_row(**dlg.result_values)
        self.signal_tree.sortItems(TX_COL_2_id, Qt.SortOrder.AscendingOrder)

        # Se la trasmissione è attiva, riavvia per includere il nuovo ID
        if self.tx_running:
            self.stop_tx()
            self.start_tx()
        self.btn_disable_all_ids.setEnabled(True)
        self.btn_delete_all_ids.setEnabled(True)

    def delete_signal_row(self, item):
        idx = self.signal_tree.indexOfTopLevelItem(item)
        if idx != -1:
            # Stop this row's timer only: another row may share the ID number
            for t in [t for t in self.timers if getattr(t, "tx_item", None) is item]:
                t.stop()
                self.timers.remove(t)
            self.signal_tree.takeTopLevelItem(idx)

        if self.signal_tree.topLevelItemCount() == 0:
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def on_signal_tree_item_changed(self, item, column):
        if column == TX_COL_1_enable:  # Checkbox abilitazione
            if self.tx_running:
                self.stop_tx()
                self.start_tx()

            try:  # Get the frame ID from the item text
                frame_id = int(item.text(TX_COL_2_id), 16)
            except Exception:
                frame_id = None
            if frame_id is not None and hasattr(self, "slider_widgets"):
                for slider_widget in self.slider_widgets:
                    if getattr(slider_widget, "frame_id", None) == frame_id:
                        slider_widget.slider.setEnabled(
                            item.checkState(TX_COL_1_enable) == Qt.CheckState.Checked
                        )

        elif column == TX_COL_6_payload:  # Payload
            text = item.text(TX_COL_6_payload).strip()
            parti = text.split()
            dlc = item.data(TX_COL_DATA, TX_COL_DATA_ROLE_dlc) or None

            hex_pair_re = re.compile(r"^[0-9a-fA-F]{2}$")
            if len(parti) != dlc or any(not hex_pair_re.match(p) for p in parti):
                QMessageBox.warning(
                    self,
                    "Error Payload",
                    f"Payload must contain exactly {dlc} bytes in hexadecimal (00-FF), e.g. {' '.join(['00'] * dlc)}",
                )
                item.setText(TX_COL_6_payload, " ".join(["00"] * dlc))

    def select_global_payload_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Global Python script", "", "Python Files (*.py)"
        )
        rel_file_path = (
            os.path.relpath(file_path, start=self.project_root) if file_path else None
        )

        if rel_file_path:
            self.global_script_path = rel_file_path
            self.global_script_cache.clear()
            self.btn_link_global_script.setStyleSheet(
                "background-color: #4CAF50; color: white;"
            )
            self.btn_link_global_script.setToolTip(f"Global Script: {rel_file_path}")
            self.btn_link_global_script.setText(os.path.basename(rel_file_path))
            self.btn_remove_global_script.setEnabled(True)

            QMessageBox.information(
                self,
                "Global Script selected",
                f"Global script set for all IDs:\n{rel_file_path}\n\n"
                "This will be used for all TX payloads unless a specific script is set for an ID.",
            )

    def remove_global_payload_script(self):
        """
        Rimuove il link allo script di payload globale, ripristinando
        lo stato di default dei pulsanti.
        """
        self.global_script_path = None
        self.global_script_cache.clear()

        # Ripristina il pulsante "Link Global Script"
        self.btn_link_global_script.setStyleSheet("")
        self.btn_link_global_script.setToolTip(
            "Link a global Payload Script to be used for all transmitted CAN frames."
        )
        self.btn_link_global_script.setText("Link Global Script")

        # Disabilita il pulsante "Remove"
        self.btn_remove_global_script.setEnabled(False)

    def remove_local_payload_script(self, item):
        """Rimuove il link allo script di payload per un ID specifico."""
        self._set_script_link(item, None)

    def _set_script_link(self, item, script_path):
        """Store a row's script path and show it on the row's script buttons."""
        item.setData(TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path, script_path)
        script_widget = self.signal_tree.itemWidget(item, TX_COL_7_script)
        if not script_widget:
            return
        btn_link_local = script_widget.findChild(QPushButton, "btn_link_local")
        btn_unlink_local = script_widget.findChild(QPushButton, "btn_unlink_local")
        if btn_link_local:
            if script_path:
                btn_link_local.setStyleSheet("background-color: #4CAF50; color: white;")
                btn_link_local.setToolTip(f"Script: {script_path}")
                btn_link_local.setText(os.path.basename(script_path))
            else:
                btn_link_local.setStyleSheet("")
                btn_link_local.setToolTip(
                    "Link a Payload Script to be used for THIS trasmitted CAN frame."
                )
                btn_link_local.setText("Link Script")
        if btn_unlink_local:
            btn_unlink_local.setEnabled(bool(script_path))

    def _setup_script_buttons_for_item(self, item):
        """
        Crea il widget composito con i pulsanti Link/Unlink
        per la colonna script della tabella TX.
        """
        # Contenitore principale
        script_widget = QWidget()
        script_layout = QHBoxLayout()
        script_layout.setContentsMargins(2, 0, 2, 0)  # Spaziatura ridotta
        script_layout.setSpacing(5)

        # Pulsante Link
        btn_link_local = QPushButton("Link Script")
        btn_link_local.setObjectName("btn_link_local")  # Per trovarlo dopo
        btn_link_local.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        btn_link_local.setToolTip(
            "Link a Payload Script to be used for THIS trasmitted CAN frame."
        )
        btn_link_local.clicked.connect(
            lambda _, it=item: self.modify_payload_script(it)
        )

        # Pulsante Unlink
        btn_unlink_local = QPushButton()
        btn_unlink_local.setObjectName("btn_unlink_local")  # Per trovarlo dopo
        btn_unlink_local.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        btn_unlink_local.setToolTip("Remove the linked Payload Script.")
        btn_unlink_local.setFixedSize(30, 25)  # Rendilo piccolo
        btn_unlink_local.setEnabled(False)  # Disabilitato di default
        btn_unlink_local.clicked.connect(
            lambda _, it=item: self.remove_local_payload_script(it)
        )

        script_layout.addWidget(btn_link_local)
        script_layout.addWidget(btn_unlink_local)
        script_widget.setLayout(script_layout)

        self.signal_tree.setItemWidget(item, TX_COL_7_script, script_widget)

    def modify_payload_script(self, item):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Python script", "", "Python Files (*.py)"
        )
        rel_file_path = (
            os.path.relpath(file_path, start=self.project_root) if file_path else None
        )

        if rel_file_path:
            self._set_script_link(item, rel_file_path)
            QMessageBox.information(
                self,
                "Script selected",
                f"Script associated with ID {item.text(TX_COL_2_id)}:\n{rel_file_path}\n\n"
                "This will be used for TX payload and overwrites the eventual global script for this ID.",
            )

    # Update the payload of a single signal in the CAN message
    def insert_value_in_payload(
        self, frame_id: int, signal_name: str, value: int, current_payload: bytes
    ) -> bytes:
        """
        Uses cantools to update a single signal in the existing payload.
        """
        if not self.dbc or not hasattr(self.dbc, "db"):
            raise RuntimeError("DBC not loaded correctly.")

        message = self.dbc.db.get_message_by_frame_id(frame_id)
        if not message:
            raise ValueError(f"Message with ID {frame_id} not found in DBC.")

        try:
            decoded = message.decode(current_payload)
        except Exception:
            decoded = {sig.name: 0 for sig in message.signals}

        decoded[signal_name] = value
        return bytes(message.encode(decoded))

    def start_stop_transmission(self) -> None:
        if not self.tx_running:
            if not self.can_if:
                QMessageBox.warning(
                    self,
                    "Attention",
                    "You must connect to the CAN bus before starting transmission",
                )
                return
            if getattr(self.can_if, "listen_only", False):
                QMessageBox.warning(
                    self, "Listen only", "The channel is connected in listen-only mode."
                )
                return
            self._bus_bad_since = None
            # Every run starts every script from its initial state
            self.script_instances.clear()
            self.global_script_cache.clear()
            self.start_tx()
            if self.tx_skipped_fd:
                QMessageBox.warning(
                    self,
                    "CAN FD",
                    "The bus is connected as classic CAN: these CAN FD rows are not "
                    "transmitted:\n" + "\n".join(self.tx_skipped_fd),
                )
        else:
            self.stop_tx()
            # Frames the bus could not take yet would otherwise go out later,
            # e.g. when a node appears (TODO 1.14). Only on the user's Stop TX:
            # internal stop/start restarts must not drop in-flight frames.
            if self.can_if is not None and not self.can_if.flush_tx():
                QMessageBox.critical(
                    self, "Error", "Could not reopen the CAN channel after Stop TX."
                )
                self.btn_connect.setChecked(False)
                self.toggle_connection()

    def poll_bus_status(self):
        """Show the controller state; stop TX when frames cannot get out (TODO 1.5).

        Bus-off and a full TX queue stop TX at once. Error-warning/passive
        stop it after TX_ERROR_GRACE_S: a noisy bus may pass through them,
        a node alone or at the wrong bitrate stays there (bench, 2026-10-16).
        The stop is the user's Stop TX, so the stale backlog is dropped too.
        """
        if self.can_if is None:
            return
        st = self.can_if.bus_status()
        mode = " (listen only)" if getattr(self.can_if, "listen_only", False) else ""
        self.lbl_bus_status.setText(f"Bus: {st.text}{mode}")
        self.lbl_bus_status.setStyleSheet(
            f"color: {BUS_STATUS_COLORS.get(st.level, '')}; font-weight: bold;"
        )
        self.lbl_bus_status.setToolTip(
            f"PCAN status 0x{st.code:X}; error frames received: "
            f"{getattr(self.can_if, 'error_frames', 0)}"
            if st.code >= 0
            else "CAN controller state of the connected channel."
        )

        if not self.tx_running or st.level in ("ok", "info"):
            self._bus_bad_since = None
            return
        now = time.monotonic()
        if self._bus_bad_since is None:
            self._bus_bad_since = now
        if st.level != "severe" and now - self._bus_bad_since < TX_ERROR_GRACE_S:
            return
        self._bus_bad_since = None
        self.start_stop_transmission()  # = the user's Stop TX, flushes the queue
        QMessageBox.warning(
            self,
            "TX stopped",
            f"Transmission stopped: the bus reports '{st.text}'.\n\n"
            "Frames are not being acknowledged. Check the baudrate, the "
            "termination and that at least one other node is active.",
        )

    def start_tx(self):
        """Starts the periodic transmission of enabled CAN messages in ascending order of ID."""
        self.timers.clear()
        # (frame_id, is_ext): {'nominal': period, 'offset': 0, 'samples': [], 'last_time': None}
        self.tx_periods = {}
        # A classic-CAN channel rejects every FD frame: skip those rows, once
        bus_is_fd = bool(getattr(self.can_if, "is_fd", False))
        self.tx_skipped_fd = []
        items_to_send = []
        for item in self._tx_items():  # Itera su tutti gli ID
            if item.checkState(TX_COL_1_enable) != Qt.CheckState.Checked:
                continue
            key = self._row_key(item)
            if key[0] < 0:
                continue
            if item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd) and not bus_is_fd:
                self.tx_skipped_fd.append(
                    f"{item.text(TX_COL_2_id)} {item.text(TX_COL_4_name)}"
                )
                continue
            items_to_send.append((key, item))
        items_to_send.sort(key=lambda x: (x[0][1], x[0][0]))

        # Prepara gli slider per i frame
        slider_overrides = {}
        if hasattr(
            self, "slider_widgets"
        ):  # Controlla se gli slider sono stati aggiunti
            for w in self.slider_widgets:
                skey = (w.frame_id, bool(getattr(w, "is_ext", False)))
                slider_overrides.setdefault(skey, []).append((w.signal, w.slider))

        # Inizializza i timer ed il dizionario per la cache degli script
        for tx_key, item in items_to_send:
            frame_id, is_ext = tx_key
            period_spin = self.signal_tree.itemWidget(item, TX_COL_5_period)
            period = period_spin.value() if period_spin else 1000
            self.tx_periods[tx_key] = {
                "nominal": period,
                "offset": 0,
                "samples": [],
                "last_time": None,
            }
            # Connect live update for period spinbox
            if period_spin is not None:

                def make_period_handler(tkey=tx_key, tree_item=item):
                    def handler(new_period):
                        if self.tx_running:
                            # Update timer and tx_periods
                            for t in self.timers:
                                if getattr(t, "tx_item", None) is tree_item:
                                    t.stop()
                                    t.start(new_period)
                                    self.tx_periods[tkey]["nominal"] = new_period
                                    break

                    return handler

                period_spin.valueChanged.connect(make_period_handler())

            script_path = item.data(TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path)
            # The frame flags of a row never change after it is created
            is_fd = bool(item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd))
            dlc = valid_dlc(item.data(TX_COL_DATA, TX_COL_DATA_ROLE_dlc), is_fd)

            def make_callback(
                frame_id=frame_id,
                is_ext=is_ext,
                is_fd=is_fd,
                dlc=dlc,
                item=item,
                script_path=script_path,
            ):
                tx_key = (frame_id, is_ext)

                def callback():
                    now_time = time.time() * 1000  # ms
                    txp = self.tx_periods[tx_key]

                    # FIXME: riabilitare controllo adattivo del periodo correggendo il conflitto con metodo timer_busload_elapsed()
                    # Monitor period
                    # if txp["last_time"] is not None:
                    #    real_period = now_time - txp["last_time"]
                    #    txp["samples"].append(real_period)
                    #    # if len(txp["samples"]) > 10:
                    #    #     txp["samples"].pop(0)

                    #    # Calculate mean and check hysteresis
                    #    if len(txp["samples"]) == 10:
                    #        # Calcola la media attuale dei periodi e poi ripulisce la lista
                    #        real_mean_period = sum(txp["samples"]) / 10
                    #        txp["samples"].pop(0)

                    #        ref_period = txp["nominal"]
                    #        p_factor = 0.0  # Fattore di proporzione
                    #        i_factor = 0.002  # Fattore di integrazione

                    #        error_period = float(ref_period) - real_mean_period

                    #        # --- INTEGRALE: accumula l'errore nel tempo ---
                    #        if "integral" not in txp:
                    #            txp["integral"] = 0.0
                    #        txp["integral"] += error_period

                    #        # --- PI controller ---
                    #        new_period = (
                    #            int(
                    #                error_period * p_factor + txp["integral"] * i_factor
                    #            )
                    #            + ref_period
                    #        )

                    #        # Aggiorna il periodo del timer se necessario
                    #        if new_period != ref_period + txp["offset"]:
                    #            txp["offset"] = new_period - ref_period
                    #            print(
                    #                f"[DEBUG] Update of period for ID 0x{frame_id:03X}: (Ierr: {txp['integral']:02f} ms, corr: {new_period - ref_period:02f} ms) ref:{ref_period} -> new:{new_period} ms"
                    #            )

                    #            for t in self.timers:
                    #                if (
                    #                    hasattr(t, "frame_id")
                    #                    and t.frame_id == frame_id
                    #                ):
                    #                    t.stop()
                    #                    t.start(max(5, new_period))
                    #                    break

                    txp["last_time"] = (
                        now_time  # Aggiorna l'ultimo tempo di trasmissione
                    )

                    # Se il payload è stato specificato come script, lo esegue
                    try:
                        # 1. Per-ID script has priority
                        if script_path and os.path.exists(script_path):
                            # One instance per ID, even when IDs share the file
                            key = (frame_id, is_ext, script_path)
                            get_payload_fn = self.script_instances.get(key)
                            if get_payload_fn is None:
                                get_payload_fn = load_payload_function(
                                    script_path,
                                    f"canino_tx_script_{frame_id:X}{'x' if is_ext else ''}",
                                )
                                self.script_instances[key] = get_payload_fn

                            payload = get_payload_fn(dlc, frame_id)
                            if not isinstance(payload, bytes) or len(payload) != dlc:
                                raise ValueError(
                                    f"get_payload(dlc) must return exactly {dlc} bytes"
                                )

                        # 2. Otherwise, use global script if set
                        elif self.global_script_path and os.path.exists(
                            self.global_script_path
                        ):
                            if self.global_script_path not in self.global_script_cache:
                                get_payload_fn = load_payload_function(
                                    self.global_script_path, "canino_global_script"
                                )
                                self.global_script_cache[self.global_script_path] = (
                                    get_payload_fn
                                )
                            else:
                                get_payload_fn = self.global_script_cache[
                                    self.global_script_path
                                ]

                            payload = get_payload_fn(dlc, frame_id)
                            if not isinstance(payload, bytes) or len(payload) != dlc:
                                raise ValueError(
                                    f"get_payload(dlc) must return exactly {dlc} bytes"
                                )

                        # 3. Otherwise, use manual payload
                        else:
                            payload_text = item.text(TX_COL_6_payload).strip()

                            if payload_text:
                                payload_parts = payload_text.split()
                                payload = bytes(int(b, 16) for b in payload_parts[:dlc])
                            else:
                                payload = bytes([0x00] * dlc)

                            # Se lo script restituisce un payload, usa solo i primi DLC byte
                            if isinstance(payload, bytes):
                                payload = payload[:dlc] + bytes(
                                    [0x00] * max(0, dlc - len(payload))
                                )

                        # Apply slider overrides
                        payload_list = list(payload)
                        if tx_key in slider_overrides:
                            for sig, slider in slider_overrides[tx_key]:
                                val_index = slider.value()
                                real_value = (
                                    slider.parent().min_val
                                    + val_index * slider.parent().step
                                )
                                result = self.insert_value_in_payload(
                                    frame_id, sig.name, real_value, bytes(payload_list)
                                )
                                if isinstance(result, int):
                                    result = bytes([result])
                                payload_list = list(result)

                        # Apply padding
                        final_payload = bytes(payload_list)
                        if len(final_payload) != dlc:
                            final_payload = final_payload[:dlc] + bytes(
                                [0x00] * max(0, dlc - len(final_payload))
                            )
                        # print(f"[DEBUG] final_payload type: {type(final_payload)}, value: {final_payload}")

                        # Invia il frame e aggiorna il payload nella finestra TX
                        self.send_can_message(
                            frame_id, final_payload, dlc, is_fd, is_ext
                        )
                        item.setText(
                            TX_COL_6_payload,
                            " ".join(f"{b:02X}" for b in final_payload),
                        )

                        # Update live gauges (XMetro)
                        # for gauge in getattr(self, "xmetro_windows", []):
                        #     if gauge.cb_messages.currentData() == frame_id:
                        #         if not isinstance(
                        #             final_payload, bytes
                        #         ):  # Converti in bytes se necessario
                        #             try:
                        #                 final_payload = bytes(final_payload)
                        #             except Exception:
                        #                 print(
                        #                     f"[XMetro] Payload not convertible: {type(final_payload)}, value {final_payload}"
                        #                 )
                        #                 continue
                        #         # Update the gauge with the final payload
                        #         gauge.update_gauge(final_payload)
                        #         # print(f"[XMetro] Payload passed to gauge: {type(final_payload)}, value {final_payload}")

                    except Exception as e:
                        print(f"[Error TX ID {frame_id:03X}]: {e}")
                        log_exception(__file__, sys._getframe().f_lineno, e)

                return callback

            timer = QTimer(self)
            # CoarseTimer (Qt's default) rounds intervals above 20 ms up to the
            # 15.625 ms Windows tick: 50 ms ran at 62.5 ms on the bus (TODO 2.10)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.tx_item = item  # Custom attribute for lookup
            timer.timeout.connect(make_callback())
            timer.start(period)
            self.timers.append(timer)

        self.tx_running = True
        self.btn_start_tx.setText("Stop TX")
        self.btn_start_tx.setToolTip(
            "Stop the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogNoButton)
        )

    def stop_tx(self):
        for t in self.timers:
            t.stop()
        self.timers.clear()
        self.tx_running = False
        self.btn_start_tx.setText("Start TX")
        self.btn_start_tx.setToolTip(
            "Start the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        )

    def make_timer_callback(self, frame_id, data, dlc, is_fd, item=None):
        def callback():
            self.send_can_message(frame_id, data, dlc, is_fd)
            if item:
                item.setText(TX_COL_6_payload, " ".join(f"{b:02X}" for b in data))

        return callback

    def send_can_message(self, frame_id, data, dlc=None, is_fd=False, is_ext=False):
        if not self.can_if:
            return
        try:
            # determine DLC
            if dlc is None:
                dlc = len(data) if data else 0
            dlc = max(0, min(int(dlc), 64))

            # Compact bit counting:
            # arbitration = SOF(1) + ID(11|29) + RTR/IDE/RES(≈3) + DLC(4)
            # data_phase = data(8*dlc) + CRC(+delim)
            # NOTE: ACK/EOF/IFS are transmitted at nominal bitrate in CAN-FD -> count them in arbitration_bits for is_fd
            arbitration_bits = 1 + (29 if is_ext else 11) + 3 + 4
            if not is_fd:
                crc_total = 15 + 1
                data_phase_bits = (
                    8 * dlc + crc_total + 2 + 7 + 3
                )  # ACK+EOF+IFS at same bitrate
            else:
                crc_total = (17 + 1) if dlc <= 16 else (21 + 1)
                data_phase_bits = 8 * dlc + crc_total  # only data+CRC at data-rate
                arbitration_bits += (
                    2 + 7 + 3
                )  # ACK + EOF + IFS are at nominal (arbitration) bitrate

            # update counters (arbitration at nominal rate, data phase at data rate for FD)
            self.busload_tx_arbitration_bits += arbitration_bits
            self.busload_tx_data_bits += data_phase_bits

            # send
            self.can_if.send_frame(frame_id, data, dlc, is_fd, is_ext=is_ext)
        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def process_received_frame(
        self, frame_id, data, dlc=None, is_fd=False, timestamp=None, is_ext=False
    ):
        """Runs in the RX thread: no Qt widget may be touched from here."""
        try:
            # aggiorna il buffer/tabella RX
            self.rx_window.update_frame(frame_id, data, dlc, is_fd, timestamp, is_ext)

            # Gauges live in the GUI thread: hand the frame over via a queued
            # signal, only while an XMetro window is open (TODO 7.1)
            if self.xmetro_windows:
                self.rx_bridge.frame_received.emit(frame_id, bytes(data))

        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def _feed_gauges(self, frame_id, data):
        """GUI thread: update every XMetro gauge showing `frame_id`."""
        alive = [w for w in self.xmetro_windows if shiboken6.isValid(w)]
        self.xmetro_windows[:] = alive
        for window in alive:
            for gauge in window.gauges:
                if gauge.cb_messages.currentData() == frame_id:
                    gauge.update_gauge(data)

    def closeEvent(self, event):
        """Release TX, the PCAN channel, the CSV and the XMetro windows (TODO 1.9)."""
        if self.tx_running:
            self.stop_tx()
        if self.can_if is not None:
            self.can_if.close()  # joins the RX thread, then shuts the bus down
            self.can_if = None
        if self.rx_window.csv_file:
            self.rx_window.stop_log()
        for window in self.xmetro_windows:
            if shiboken6.isValid(window):
                window.close()
        self.xmetro_windows.clear()
        super().closeEvent(event)

    def open_xmetro_window(self):
        print("Opening XMetro window...")

        if not hasattr(self, "dbc") or self.dbc is None:
            print("No DBC file loaded")
            QMessageBox.warning(self, "DBC", "Load a DBC file first!")
            return

        if not self.dbc.db.messages:
            print("No messages in DBC")
            QMessageBox.warning(self, "XMetro", "No messages in DBC file.")
            return

        try:
            xmetro = XMetroWindow(self.dbc)
            self.xmetro_windows.append(xmetro)

            xmetro.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            xmetro.show()
            print("XMetro window created and shown")

        except Exception as e:
            print(f"Error creating XMetro window: {str(e)}")
            log_exception(__file__, sys._getframe().f_lineno, e)

    def timer_busload_elapsed(self):
        # Sums of TX bits in arbitration phase and data phase (for CAN-FD)
        tot_arbitration_bits = (
            self.rx_window.get_busload_rx_arbitration_bits()
            + self.get_busload_tx_arbitration_bits()
        )
        tot_data_bits = (
            self.rx_window.get_busload_rx_data_bits() + self.get_busload_tx_data_bits()
        )

        # Stats reset
        self.rx_window.clear_busload_stats()
        self.clear_busload_stats()

        # Extraction of values from selected baudrate
        label, pcan_val, real_data_val, real_arb_val = self.baudrate_values[
            self.cb_baudrate.currentIndex()
        ]

        # Total time occupied in the bus
        if real_arb_val > 0:
            # CAN-FD: arbitration phase (500 kbit/s) + data phase (2 Mbit/s)
            arbitration_baudrate = real_arb_val
            data_baudrate = real_data_val

            tot_arbitration_time_s = float(tot_arbitration_bits) / arbitration_baudrate
            tot_data_time_s = float(tot_data_bits) / data_baudrate
        else:
            # classic CAN: fixed bitrate for arbitration and data phases
            arbitration_baudrate = real_data_val  # unique bitrate
            tot_arbitration_time_s = (
                float(tot_arbitration_bits + tot_data_bits) / arbitration_baudrate
            )
            tot_data_time_s = 0.0  # no distiction

        # print(
        #     f"arbitration_baudrate={arbitration_baudrate} data_baudrate={real_data_val} "
        #     f"tot_arbitration_time_s={tot_arbitration_time_s:6.4f} tot_data_time_s={tot_data_time_s:6.4f} "
        #     f"tot_arbitration_bits={tot_arbitration_bits:6.4f} tot_data_bits={tot_data_bits:6.4f} "
        #     f"real_arb_val={real_arb_val} real_data_val={real_data_val}"
        # )

        # Busload as percentage
        busload = ((tot_arbitration_time_s + tot_data_time_s) * 100) / (
            float(BUSLOAD_refresh_rate_ms) / 1000
        )

        self.lbl_busload.setText(f"BusLoad: {busload:3.1f}%")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

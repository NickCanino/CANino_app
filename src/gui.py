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
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QTableView,
    QAbstractItemView,
    QHeaderView,
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QDesktopServices
from PySide6.QtCore import Qt, QTimer, QUrl, QSortFilterProxyModel
import shiboken6
import importlib.util
import json
import logging
import os
import sys
import time
import can

from src.dbc_loader import (
    load_dbc,
    encode_signal,
    decode_signal,
    signal_range,
    dbc_bit_label,
)
from src.can_interface import CANInterface
from src.exceptions_logger import log_exception, __version__, log_dir as LOG_DIR
from src.xmetro_class import XMetroWindow
from src.vagiletta_programmer_class import VagilettaWindow
from src.received_frames_class import ReceivedFramesWindow
from src.utils import resource_path, format_can_id
from src.tx_model import (  # noqa: F401  (TX_COL_*, CAN_* are part of gui's API)
    TxEntry,
    TxTableModel,
    TxButtonDelegate,
    PeriodDelegate,
    SORT_ROLE as TX_SORT_ROLE,
    TX_COL_0_del,
    TX_COL_1_enable,
    TX_COL_2_id,
    TX_COL_3_fd,
    TX_COL_4_name,
    TX_COL_5_period,
    TX_COL_6_payload,
    TX_COL_7_script,
    CAN_MAX_STD_ID,
    CAN_MAX_EXT_ID,
    CAN_FD_LENGTHS,
    ROW_ERROR_COLOR,
    valid_dlc,
)
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
# Slider positions; QSlider ranges are int32, 32/64-bit raw ranges are not
SLIDER_MAX_STEPS = 10000
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

# The TX engine repaints the rows it changed this often (TODO 2.12)
TX_REFRESH_MS = 100


def json_flag(value) -> bool:
    """Workspace flags are saved as "Y"/"n"; older files may hold null or bools."""
    if isinstance(value, str):
        return value.strip().upper() in ("Y", "YES", "TRUE", "1")
    return bool(value)


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
        # (frame_id, is_ext, error) already logged in this run: once each (TODO 3.3)
        self._tx_errors_logged = set()
        self.tx_running = False
        self.global_script_path = None
        self.global_script_cache = {}
        # (frame_id, script_path) -> get_payload of that ID's own script instance;
        # emptied at Start TX only, so internal TX restarts keep script state
        self.script_instances = {}
        self.workspace_path = None  # file of the last Load / Save (TODO 6.6)

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

        help_menu = QMenu("&Help", self)
        action_logs = QAction("Open log folder", self)
        action_logs.setToolTip(LOG_DIR)
        action_logs.triggered.connect(self.open_log_folder)
        help_menu.addAction(action_logs)
        self.action_open_logs = action_logs

        # --- "VAGILETTA" action in the menu bar ---
        action_vagiletta = QAction("VAGILETTA", self)
        action_vagiletta.triggered.connect(self.open_vagiletta_window)
        menubar.addAction(action_vagiletta)

        # --- "XMetro" action in the menu bar ---
        action_xmetro = QAction("XMetro", self)
        # action_xmetro.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
        action_xmetro.triggered.connect(self.open_xmetro_window)
        menubar.addAction(action_xmetro)

        menubar.addMenu(help_menu)
        self.setMenuBar(menubar)

        # --- TOP CONTROLS ---
        top_controls = QWidget()
        top_layout = QHBoxLayout()
        top_controls.setLayout(top_layout)
        top_controls.setFixedHeight(50)  # Fixed height of the top bar

        # --- TOP BUTTONS AND COMBO BOXES ---
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

        # Combo box to select the CAN channel
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

        # Timer that refreshes the busload
        self.timer_busload = QTimer(self)
        self.timer_busload.timeout.connect(self.timer_busload_elapsed)
        self.timer_busload.start(BUSLOAD_refresh_rate_ms)

        self._busload_since = time.monotonic()
        self.lbl_busload = QLabel("BusLoad: -")
        self.lbl_busload.setToolTip(
            "Share of the last second the bus was busy: every frame seen on the "
            "wire (received, and transmitted from the adapter's echo), stuff "
            "bits, ACK, EOF and intermission included. Error frames are not counted."
        )
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
        self.btn_start_tx.setEnabled(False)  # Disabled until connected

        # Button to disable all ID in TX
        self.btn_disable_all_ids = QPushButton("Disable All")
        self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
        self.btn_disable_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        )
        self.btn_disable_all_ids.setFixedSize(100, 30)
        self.btn_disable_all_ids.clicked.connect(self.disable_all_ids_tx)
        self.btn_disable_all_ids.setEnabled(False)  # Disabled until there are rows

        # Button to delete all IDs in TX
        self.btn_delete_all_ids = QPushButton("Delete All")
        self.btn_delete_all_ids.setToolTip("Delete all CAN IDs from the TX list.")
        self.btn_delete_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.btn_delete_all_ids.setFixedSize(100, 30)
        self.btn_delete_all_ids.clicked.connect(self.delete_all_ids_tx)
        self.btn_delete_all_ids.setEnabled(False)  # Disabled until there are rows

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
        self.btn_remove_global_script.setEnabled(False)  # Nothing linked yet
        self.btn_remove_global_script.clicked.connect(self.remove_global_payload_script)

        # Horizontal layout for the TX buttons
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

        # --- TX TABLE: TxEntry rows -> model -> sorting proxy -> view (TODO 2.13) ---
        self.tx_model = TxTableModel(self)
        self.tx_model.enabled_changed.connect(self._on_enabled_changed)
        self.tx_model.period_changed.connect(self._on_period_changed)
        self.tx_model.payload_rejected.connect(self._on_payload_rejected)
        self.tx_proxy = QSortFilterProxyModel(self)
        self.tx_proxy.setSourceModel(self.tx_model)
        self.tx_proxy.setSortRole(TX_SORT_ROLE)
        self.tx_proxy.setDynamicSortFilter(True)
        self.tx_view = QTableView()
        self.tx_view.setModel(self.tx_proxy)
        self.tx_view.verticalHeader().hide()
        self.tx_view.setWordWrap(False)
        self.tx_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tx_view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tx_buttons = TxButtonDelegate(self.tx_view)
        self.tx_buttons.delete_clicked.connect(self.delete_signal_row)
        self.tx_buttons.link_clicked.connect(self.modify_payload_script)
        self.tx_buttons.unlink_clicked.connect(self.remove_local_payload_script)
        self.tx_view.setItemDelegateForColumn(TX_COL_0_del, self.tx_buttons)
        self.tx_view.setItemDelegateForColumn(TX_COL_7_script, self.tx_buttons)
        self.tx_view.setItemDelegateForColumn(
            TX_COL_5_period, PeriodDelegate(self.tx_view)
        )
        for col, width in (
            (TX_COL_0_del, 40),
            (TX_COL_1_enable, 30),
            (TX_COL_2_id, 90),
            (TX_COL_3_fd, 30),
            (TX_COL_4_name, 100),
            (TX_COL_5_period, 80),
            (TX_COL_6_payload, 200),
            (TX_COL_7_script, 150),
        ):
            self.tx_view.setColumnWidth(col, width)
        self.tx_view.horizontalHeader().setSectionResizeMode(
            TX_COL_7_script, QHeaderView.ResizeMode.Stretch
        )
        self.tx_view.setSortingEnabled(True)
        self.tx_view.sortByColumn(TX_COL_2_id, Qt.SortOrder.AscendingOrder)
        # Payloads and errors written by the TX engine reach the screen at ~10 Hz
        self.tx_refresh_timer = QTimer(self)
        self.tx_refresh_timer.timeout.connect(self.tx_model.flush)
        self.tx_refresh_timer.start(TX_REFRESH_MS)

        # Group box for the transmission controls
        tx_group = QGroupBox()
        tx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #4CAF50; border-radius: 5px; }"
        )
        # Vertical layout of the TX group
        tx_layout = QVBoxLayout()
        tx_group.setLayout(tx_layout)
        tx_title = QLabel("Transmitted CAN Frames (TX)")
        tx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tx_title.setStyleSheet("font-weight: bold;")
        tx_layout.addWidget(tx_title)
        tx_layout.addLayout(tx_buttons_layout)
        tx_layout.addWidget(self.tx_view)

        # RX controls
        self.rx_window = ReceivedFramesWindow(self.dbc)
        # The RX window drains the RX queue in the GUI thread and hands the
        # latest payload of each frame to the XMetro gauges
        self.xmetro_windows = []
        self.rx_window.frames_received.connect(self._feed_latest)
        rx_group = QGroupBox()
        rx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #2196F3; border-radius: 5px; }"
        )
        # Vertical layout of the RX group
        rx_layout = QVBoxLayout()
        rx_group.setLayout(rx_layout)
        rx_title = QLabel("Received CAN Frames (RX)")
        rx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rx_title.setStyleSheet("font-weight: bold;")
        rx_layout.addWidget(rx_title)
        rx_layout.addWidget(self.rx_window)

        # --- SLIDER GROUP ---
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

        # Scroll area
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

        self.refresh_bus_list()

        self.btn_add_slider.clicked.connect(self.add_slider)

        # --- MAIN SPLITTER ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        # Left side: vertical splitter with TX and RX
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tx_group)
        left_splitter.addWidget(rx_group)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(slider_group)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 2)

        # --- FOOTER WITH LOGOS ---
        footer_widget = QWidget()
        footer_widget.setFixedHeight(40)  # Fixed height

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

        # Scale the images to the footer height
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

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(top_controls)
        main_layout.addWidget(main_splitter)
        main_layout.addWidget(footer_widget)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.refresh_bus_list()
        # Load the default workspace at start-up, if it exists
        self.load_config(auto=True)

    def disable_all_ids_tx(self):
        if (
            self.btn_disable_all_ids.text() == "Enable All"
        ):  # Currently disabled: enable all
            self._set_all_enabled(True)

            self.btn_disable_all_ids.setText("Disable All")
            self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
            self.btn_disable_all_ids.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
            )
        else:  # Currently enabled: disable all
            self._set_all_enabled(False)

            self.btn_disable_all_ids.setText("Enable All")
            self.btn_disable_all_ids.setToolTip("Enable all CAN IDs in the TX list.")
            self.btn_disable_all_ids.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
            )

    def delete_all_ids_tx(self):
        """
        Delete every ID from the TX table, after confirmation.
        """
        if self.tx_model.rowCount() == 0:
            return  # Table already empty

        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete all IDs from the TX list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Stop the transmission if it is running
            if self.tx_running:
                self.stop_tx()
            else:
                # Make sure no timer is left, even when not running
                for t in self.timers:
                    t.stop()
                self.timers.clear()

            # Clear the table
            self.tx_model.clear()

            # Disable the buttons that need rows
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def save_config(self):
        """Save to the workspace file last loaded or saved; Save As if there is none (TODO 6.6)."""
        if self.workspace_path:
            self._save_config_to_file(self.workspace_path)
        else:
            self.save_config_as()

    def save_config_as(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save configuration as",
            self.workspace_path or "",
            "File JSON (*.json)",
        )
        if filename:
            self._save_config_to_file(filename)

    @staticmethod
    def _to_workspace_path(path, base_dir):
        """Path as stored in a workspace: relative to the JSON file (TODO 6.5).

        On another drive there is no relative path: stored absolute.
        """
        if not path:
            return None
        absolute = os.path.abspath(path)
        try:
            return os.path.relpath(absolute, base_dir).replace(os.sep, "/")
        except ValueError:
            return absolute

    @staticmethod
    def _from_workspace_path(path, base_dir):
        """Absolute path of a stored one: next to the JSON file first, then the CWD.

        Files written before 1.5 hold paths relative to the CWD CANino was
        started in; a path found nowhere resolves next to the JSON file and is
        reported where it is used.
        """
        if not path:
            return None
        if os.path.isabs(path):
            return os.path.normpath(path)
        for base in (base_dir, os.getcwd()):
            candidate = os.path.abspath(os.path.join(base, path))
            if os.path.exists(candidate):
                return candidate
        return os.path.abspath(os.path.join(base_dir, path))

    def _set_workspace_path(self, path):
        self.workspace_path = os.path.abspath(path) if path else None
        name = f" - {os.path.basename(path)}" if path else ""
        self.setWindowTitle(f"CANino App - v{__version__}{name}")

    def _save_config_to_file(self, filename):
        base = os.path.dirname(os.path.abspath(filename))
        config = {
            "dbc_file": self._to_workspace_path(
                self.dbc.dbc_filename if self.dbc is not None else None, base
            ),
            "signals": [],
            "sliders": [],
            "global_script": self._to_workspace_path(self.global_script_path, base),
        }

        for widget in self.slider_widgets:
            config["sliders"].append(
                {
                    "msg_name": widget.msg_name,
                    "signal_name": widget.signal.name,
                    "frame_id": widget.frame_id,
                    "is_ext": widget.is_ext,
                    "min_val": widget.min_val,
                    "max_val": widget.max_val,
                    "step": widget.step,
                    "unit": widget.unit,
                    "value_index": widget.slider.value(),
                    "value": widget.value(),
                }
            )

        for entry in self._tx_entries():
            config["signals"].append(
                {
                    "enabled": entry.enabled,
                    "id": entry.id_text,
                    "ext": "Y" if entry.is_ext else "n",
                    "fd": "Y" if entry.is_fd else "n",
                    "name": entry.name,
                    "period": entry.period,
                    "payload": " ".join(f"{b:02X}" for b in entry.payload),
                    "dlc": entry.dlc,
                    "script_path": self._to_workspace_path(entry.script_path, base),
                }
            )
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving configuration: {e}")
            log_exception(e)
            return False
        self._set_workspace_path(filename)
        QMessageBox.information(
            self,
            "Configuration saved",
            f"Configuration successfully saved to:\n{filename}",
        )
        return True

    def _clear_workspace(self):
        """Empty TX table, sliders, global script and DBC: Load replaces (TODO 6.4)."""
        if self.tx_running:
            self.start_stop_transmission()  # = the user's Stop TX, drops the backlog
        self.tx_model.clear()
        for widget in list(self.slider_widgets):
            self.remove_slider_widget(widget)
        self.added_sliders.clear()
        self._set_global_script(None)
        self.script_instances.clear()
        self.dbc = None
        self.rx_window.set_dbc(None)
        self.btn_disable_all_ids.setText("Disable All")
        self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
        self.btn_disable_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        )

    def load_config(self, auto=False):
        """Replace the workspace with a JSON file (TODO 6.4); the table stays editable."""
        if auto:  # Load the default workspace file
            filename = self.CONFIG_FILE
            if not os.path.exists(filename):
                return
        else:  # Ask for the file
            filename, _ = QFileDialog.getOpenFileName(
                self, "Load configuration", "", "File JSON (*.json)"
            )
            if not filename:
                return

        # Parse first: a broken file must not wipe the current workspace
        try:
            with open(filename, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("not a CANino workspace (no JSON object)")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {e}")
            log_exception(e)
            return

        try:
            was_running = self.tx_running
            self._clear_workspace()
            self._set_workspace_path(filename)
            base = os.path.dirname(os.path.abspath(filename))

            # Loads DBC if existing
            dbc_path = self._from_workspace_path(config.get("dbc_file"), base)
            if dbc_path is not None:
                if os.path.exists(dbc_path):
                    self.dbc = load_dbc(dbc_path)
                    self.rx_window.set_dbc(self.dbc)  # RX names (TODO 6.1)
                else:
                    QMessageBox.warning(
                        self, "DBC", f"Cannot find DBC file:\n{dbc_path}"
                    )

            # Restores global script (a missing file is reported at Start TX)
            self._set_global_script(
                self._from_workspace_path(config.get("global_script"), base)
            )

            for sig in config.get("signals") or []:
                try:
                    frame_id = int(sig.get("id", "0"), 16)
                except (TypeError, ValueError):
                    continue
                # Files written before 1.5 carry no "ext": they could not send
                # IDs above 0x7FF, so the number decides (TODO 1.6)
                is_ext = json_flag(sig.get("ext")) or frame_id > CAN_MAX_STD_ID
                if frame_id > CAN_MAX_EXT_ID or self._find_entry(frame_id, is_ext):
                    continue  # invalid, or a duplicate row in the file
                self._add_tx_row(
                    frame_id,
                    sig.get("name", ""),
                    period=sig.get("period", 100),
                    dlc=sig.get("dlc", 8),
                    is_fd=json_flag(sig.get("fd")),
                    is_ext=is_ext,
                    payload=sig.get("payload", ""),
                    script_path=self._from_workspace_path(sig.get("script_path"), base),
                    enabled=bool(sig.get("enabled")),
                )

            # Load sliders
            sliders_cfg = config.get("sliders") or []
            if sliders_cfg and self.dbc is None:
                QMessageBox.warning(
                    self,
                    "Sliders",
                    f"{len(sliders_cfg)} slider(s) skipped: they need the workspace DBC, which is not loaded.",
                )
                sliders_cfg = []
            for meta in sliders_cfg:
                msg = self._find_slider_message(meta)
                sig = next(
                    (
                        s
                        for s in getattr(msg, "signals", [])
                        if s.name == meta.get("signal_name")
                    ),
                    None,
                )
                if sig is None:
                    continue
                value = meta.get("value")
                if value is None:  # files before 1.5: index into the old range
                    value = meta.get("min_val", 0) + meta.get(
                        "value_index", 0
                    ) * meta.get("step", 1)
                self._add_slider_widget(msg, sig, value)

            # Row-dependent buttons follow the table, sliders or not (TODO 6.2)
            has_rows = self.tx_model.rowCount() > 0
            self.btn_disable_all_ids.setEnabled(has_rows)
            self.btn_delete_all_ids.setEnabled(has_rows)

            if not auto:
                stopped = "\n\nTransmission was stopped." if was_running else ""
                QMessageBox.information(
                    self,
                    "Configuration",
                    f"Configuration loaded successfully.{stopped}",
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {e}")
            log_exception(e)

    def open_log_folder(self):
        """Logs live in the user's app data now, not next to the exe (TODO 9.3)."""
        os.makedirs(LOG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_DIR))

    def open_vagiletta_window(self):
        dlg = VagilettaWindow(self)
        dlg.exec()

    def remove_slider_widget(self, widget):
        # Remove the widget from the slider_container and update the slider list
        widget.setParent(None)
        if hasattr(widget, "key"):
            self.added_sliders.discard(widget.key)

        self.slider_widgets = [w for w in self.slider_widgets if w != widget]

    def _find_slider_message(self, meta):
        """DBC message of a saved slider: by name (1.5+), else by frame number."""
        by_name = {m.name: m for m in self.dbc.messages}
        if meta.get("msg_name") in by_name:
            return by_name[meta["msg_name"]]
        # Before 1.5 "msg_name" held the signal name (TODO 4.8)
        candidates = [
            m for m in self.dbc.messages if m.frame_id == meta.get("frame_id")
        ]
        if "is_ext" in meta:
            candidates = [
                m for m in candidates if m.is_extended_frame == bool(meta["is_ext"])
            ]
        return min(candidates, key=lambda m: m.is_extended_frame, default=None)

    def add_slider(self):
        if self.dbc is None:
            QMessageBox.warning(self, "DBC", "Load a DBC file first!")
            return

        # Only consider checked TX rows
        checked = {e.key for e in self._tx_entries() if e.enabled}
        if not checked:
            QMessageBox.warning(self, "Slider", "No TX messages enabled.")
            return
        msgs = [
            m
            for m in self.dbc.messages
            if (m.frame_id, m.is_extended_frame) in checked and m.signals
        ]
        if not msgs:
            QMessageBox.warning(
                self, "Slider", "No checked DBC messages found in TX table."
            )
            return

        labels = [
            f"{m.name} ({format_can_id(m.frame_id, m.is_extended_frame)})" for m in msgs
        ]
        label, ok = QInputDialog.getItem(
            self, "Select Message", "Message:", labels, 0, False
        )
        if not ok:
            return
        msg = msgs[labels.index(label)]
        sig_names = [sig.name for sig in msg.signals]
        sig_name, ok = QInputDialog.getItem(
            self, "Select Signal", "Signal:", sig_names, 0, False
        )
        if not ok:
            return
        sig = msg.signals[sig_names.index(sig_name)]
        if (msg.name, sig.name) in self.added_sliders:
            QMessageBox.warning(
                self,
                "Slider already exists",
                f"Slider already exists for {msg.name} → {sig.name}",
            )
            return

        # Start from the value the row is sending now: no jump on the bus
        entry = self._find_entry(msg.frame_id, msg.is_extended_frame)
        value = None
        if entry is not None:
            try:
                value = decode_signal(entry.payload, sig)
            except ValueError:
                value = None
        self._add_slider_widget(msg, sig, value)

    def _add_slider_widget(self, msg, sig, value=None):
        """The one slider builder, for Add Slider and workspace load (TODO 4.9).

        Range = DBC [min|max] when set, else every raw value (TODO 4.7); at most
        SLIDER_MAX_STEPS positions, so 32/64-bit signals fit QSlider's int32
        (TODO 4.4). `value` (physical) is clamped into the range.
        """
        key = (msg.name, sig.name)
        if key in self.added_sliders:
            return None
        self.added_sliders.add(key)

        min_val, max_val = signal_range(sig)
        factor = abs(sig.factor or 1.0)
        span = max_val - min_val
        if sig.is_float:
            steps = SLIDER_MAX_STEPS
        else:
            steps = int(min(SLIDER_MAX_STEPS, max(0, round(span / factor))))
        step = span / steps if steps else 0.0
        integral = (
            not sig.is_float
            and float(step).is_integer()
            and float(min_val).is_integer()
        )
        unit = sig.unit or ""

        slider_widget = QGroupBox()
        slider_widget.setFixedHeight(100)
        slider_widget.setStyleSheet(
            "QGroupBox { margin-top: 10px; border: 1px solid gray; border-radius: 5px; }"
        )
        inner = QVBoxLayout()
        slider_widget.setLayout(inner)
        inner.addWidget(
            QLabel(
                f"{msg.name} ({format_can_id(msg.frame_id, msg.is_extended_frame)})"
                f" → {sig.name} [{dbc_bit_label(sig)}]"
            )
        )

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, steps)
        slider.setSingleStep(1)
        inner.addWidget(slider)

        def fmt(v):
            return f"{int(round(v))}" if integral else f"{v:.3f}"

        info_layout = QHBoxLayout()
        lbl_value = QLabel()
        btn_remove = QPushButton()
        btn_remove.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_remove.setFixedWidth(30)
        info_layout.addWidget(QLabel(f"Min: {fmt(min_val)}"))
        info_layout.addStretch()
        info_layout.addWidget(lbl_value)
        info_layout.addStretch()
        info_layout.addWidget(QLabel(f"Max: {fmt(max_val)}"))
        info_layout.addWidget(btn_remove)
        inner.addLayout(info_layout)

        slider_widget.key = key
        slider_widget.msg_name = msg.name
        slider_widget.frame_id = msg.frame_id
        slider_widget.is_ext = msg.is_extended_frame
        slider_widget.signal = sig
        slider_widget.slider = slider
        slider_widget.min_val = min_val
        slider_widget.max_val = max_val
        slider_widget.step = step
        slider_widget.unit = unit
        slider_widget.value = lambda: min_val + slider.value() * step

        # Connected before setValue, so the label shows the restored value (TODO 4.3)
        slider.valueChanged.connect(
            lambda i: lbl_value.setText(f"Val: {fmt(min_val + i * step)} {unit}")
        )
        if value is None or not steps:
            index = 0
        else:
            index = round((min(max(value, min_val), max_val) - min_val) / step)
        slider.setValue(index)
        lbl_value.setText(f"Val: {fmt(slider_widget.value())} {unit}")
        btn_remove.clicked.connect(
            lambda _=False, w=slider_widget: self.remove_slider_widget(w)
        )

        entry = self._find_entry(msg.frame_id, msg.is_extended_frame)
        if entry is not None:
            slider.setEnabled(entry.enabled)
        self.slider_container.addWidget(slider_widget)
        self.slider_widgets.append(slider_widget)
        return slider_widget

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
                self.can_if.set_receive_callback(self.rx_window.push_frame)
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
                log_exception(e)
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
            self.btn_start_tx.setEnabled(False)  # No TX without a channel
            if self.tx_running:
                self.stop_tx()  # Stop the transmission if it is running

    def load_dbc_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open DBC file", "", "DBC Files (*.dbc)"
        )
        if filename:
            self.dbc = load_dbc(filename)
            self.populate_signal_tree()
            self._sync_tx_timers()
            self.rx_window.set_dbc(self.dbc)
            self.btn_disable_all_ids.setEnabled(True)
            self.btn_delete_all_ids.setEnabled(True)

    def populate_signal_tree(self):
        """Add the DBC messages that are not in the TX table yet (TODO 6.9)."""
        if not self.dbc:
            return
        for msg in self.dbc.messages:
            if self._find_entry(msg.frame_id, msg.is_extended_frame) is not None:
                continue
            self._add_tx_row(
                msg.frame_id,
                msg.name,
                period=msg.cycle_time or 100,
                dlc=msg.payload_length,
                is_fd=msg.is_fd,
                is_ext=msg.is_extended_frame,
            )

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

        The TxEntry normalises the frame flags, DLC, period and payload
        (an invalid payload becomes all zeros) and is the row's only state.
        """
        return self.tx_model.add(
            TxEntry(
                frame_id,
                name,
                is_ext=is_ext,
                is_fd=is_fd,
                dlc=dlc,
                period=period,
                payload=(payload or "").strip(),
                enabled=enabled,
                script_path=script_path or None,
            )
        )

    def _tx_entries(self):
        return self.tx_model.entries()

    def _find_entry(self, frame_id, is_ext):
        return self.tx_model.find(frame_id, is_ext)

    def add_manual_id(self):
        dlg = AddIdDialog(self, {e.key for e in self._tx_entries()})
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_values is None:
            return
        self._add_tx_row(**dlg.result_values)

        skipped = self._sync_tx_timers()  # starts the new row if TX is running
        if skipped:
            QMessageBox.warning(
                self,
                "CAN FD",
                "The bus is connected as classic CAN: this row is not transmitted:\n"
                + "\n".join(skipped),
            )
        self.btn_disable_all_ids.setEnabled(True)
        self.btn_delete_all_ids.setEnabled(True)

    def delete_signal_row(self, entry):
        # Stop this row's timer only: another row may share the ID number
        timer = self._timer_of(entry)
        if timer is not None:
            timer.stop()
            self.timers.remove(timer)
        self.tx_model.remove(entry)

        if self.tx_model.rowCount() == 0:
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def _update_slider_enabled(self, entry):
        """Sliders of a disabled row are greyed out."""
        for w in self.slider_widgets:
            if (w.frame_id, bool(getattr(w, "is_ext", False))) == entry.key:
                w.slider.setEnabled(entry.enabled)

    def _set_all_enabled(self, enabled):
        """Enable/Disable All: one timer sync, not one TX restart per row."""
        self.tx_model.set_all_enabled(enabled)
        self._sync_tx_timers()
        for entry in self._tx_entries():
            self._update_slider_enabled(entry)

    def _on_enabled_changed(self, entry):
        """The user ticked/unticked En: start/stop this row only (TODO 2.6)."""
        self._sync_tx_timers()
        self._update_slider_enabled(entry)

    def _on_payload_rejected(self, entry, text):
        """A typed payload that does not parse is refused; the row keeps its own."""
        QMessageBox.warning(
            self,
            "Error Payload",
            f"Payload must contain exactly {entry.dlc} bytes in hexadecimal (00-FF), "
            f"e.g. {' '.join(['00'] * entry.dlc)}",
        )

    def select_global_payload_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Global Python script", "", "Python Files (*.py)"
        )
        if file_path:
            # Absolute in memory; relative to the JSON file only when saved (TODO 6.5)
            self._set_global_script(os.path.abspath(file_path))
            QMessageBox.information(
                self,
                "Global Script selected",
                f"Global script set for all IDs:\n{self.global_script_path}\n\n"
                "This will be used for all TX payloads unless a specific script is set for an ID.",
            )

    def remove_global_payload_script(self):
        """Unlink the global payload script."""
        self._set_global_script(None)

    def _set_global_script(self, path):
        """Link (path) or unlink (None) the global script and update its buttons."""
        self.global_script_path = path or None
        self.global_script_cache.clear()
        if self.global_script_path:
            self.btn_link_global_script.setStyleSheet(
                "background-color: #4CAF50; color: white;"
            )
            self.btn_link_global_script.setToolTip(f"Global Script: {path}")
            self.btn_link_global_script.setText(os.path.basename(path))
        else:
            self.btn_link_global_script.setStyleSheet("")
            self.btn_link_global_script.setToolTip(
                "Link a global Payload Script to be used for all transmitted CAN frames."
            )
            self.btn_link_global_script.setText("Link Global Script")
        self.btn_remove_global_script.setEnabled(bool(self.global_script_path))

    def remove_local_payload_script(self, entry):
        """Unlink the payload script of one row."""
        self._set_script_link(entry, None)

    def _set_script_link(self, entry, script_path):
        """Link (path) or unlink (None) a row's script."""
        self.tx_model.set_script(entry, script_path)

    def modify_payload_script(self, entry):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Python script", "", "Python Files (*.py)"
        )
        if file_path:
            # Absolute in memory: relpath() raised across drives (TODO 6.5)
            script_path = os.path.abspath(file_path)
            self._set_script_link(entry, script_path)
            QMessageBox.information(
                self,
                "Script selected",
                f"Script associated with ID {entry.id_text}:\n{script_path}\n\n"
                "This will be used for TX payload and overwrites the eventual global script for this ID.",
            )

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
            self._tx_errors_logged.clear()
            for entry in self._tx_entries():
                self.tx_model.set_error(entry, None)
            self.start_tx()
            problems = []
            if self.tx_skipped_fd:
                problems.append(
                    "The bus is connected as classic CAN: these CAN FD rows are "
                    "not transmitted:\n" + "\n".join(self.tx_skipped_fd)
                )
            missing = self._missing_scripts()
            if missing:
                problems.append(
                    "Script files not found - these frames are not sent until the "
                    "script is linked again:\n" + "\n".join(missing)
                )
            if problems:
                QMessageBox.warning(self, "Start TX", "\n\n".join(problems))
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
        """Start one timer per enabled row; returns the skipped FD rows."""
        for t in self.timers:
            t.stop()
        self.timers.clear()
        self.tx_running = True
        self.tx_skipped_fd = self._sync_tx_timers()
        self.btn_start_tx.setText("Stop TX")
        self.btn_start_tx.setToolTip(
            "Stop the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogNoButton)
        )
        return self.tx_skipped_fd

    def _timer_of(self, entry):
        return next((t for t in self.timers if t.tx_entry is entry), None)

    def _sync_tx_timers(self):
        """Make the running timers match the table (TODO 2.6).

        Only rows whose state changed are touched: every other row keeps its
        timer phase and its script instance. Returns the enabled CAN FD rows
        skipped because the channel is classic CAN.
        """
        if not self.tx_running:
            return []
        entries = {id(e): e for e in self._tx_entries()}
        for t in list(self.timers):
            if id(t.tx_entry) not in entries or not t.tx_entry.enabled:
                t.stop()
                self.timers.remove(t)

        # A classic-CAN channel rejects every FD frame: skip those rows
        bus_is_fd = bool(getattr(self.can_if, "is_fd", False))
        running = {id(t.tx_entry) for t in self.timers}
        skipped = []
        # Ascending ID order, so equal periods fire lowest ID first
        for entry in sorted(entries.values(), key=lambda e: (e.is_ext, e.frame_id)):
            if id(entry) in running or not entry.enabled:
                continue
            if entry.is_fd and not bus_is_fd:
                skipped.append(f"{entry.id_text} {entry.name}")
                continue
            self._start_row_timer(entry)
        return skipped

    def _start_row_timer(self, entry):
        timer = QTimer(self)
        # CoarseTimer (Qt's default) rounds intervals above 20 ms up to the
        # 15.625 ms Windows tick: 50 ms ran at 62.5 ms on the bus (TODO 2.10)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.tx_entry = entry  # Custom attribute for lookup
        timer.timeout.connect(lambda e=entry: self._send_row(e))
        timer.start(entry.period)
        self.timers.append(timer)

    def _on_period_changed(self, entry):
        """Period edit: retime this row only (TODO 2.7)."""
        timer = self._timer_of(entry)
        if timer is not None:
            timer.setInterval(entry.period)

    def _script_payload(self, entry):
        """Payload from the row's script or the global one; None = manual payload.

        A linked script that is missing or fails raises: the frame is not sent
        rather than silently sent with the manual payload (TODO 3.4).
        """
        frame_id, is_ext, dlc = entry.frame_id, entry.is_ext, entry.dlc
        script_path = entry.script_path
        if script_path:  # 1. Per-ID script has priority
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"script not found: {script_path}")
            # One instance per ID, even when IDs share the file
            key = (frame_id, is_ext, script_path)
            get_payload_fn = self.script_instances.get(key)
            if get_payload_fn is None:
                get_payload_fn = load_payload_function(
                    script_path,
                    f"canino_tx_script_{frame_id:X}{'x' if is_ext else ''}",
                )
                self.script_instances[key] = get_payload_fn
        elif self.global_script_path:  # 2. Otherwise, the global script
            if not os.path.exists(self.global_script_path):
                raise FileNotFoundError(
                    f"global script not found: {self.global_script_path}"
                )
            get_payload_fn = self.global_script_cache.get(self.global_script_path)
            if get_payload_fn is None:
                get_payload_fn = load_payload_function(
                    self.global_script_path, "canino_global_script"
                )
                self.global_script_cache[self.global_script_path] = get_payload_fn
        else:
            return None

        payload = get_payload_fn(dlc, frame_id)
        if payload is None:  # the script leaves this frame to the manual payload
            return None
        if not isinstance(payload, (bytes, bytearray)) or len(payload) != dlc:
            got = (
                f"{len(payload)} bytes"
                if isinstance(payload, (bytes, bytearray))
                else type(payload).__name__
            )
            raise ValueError(f"get_payload() returned {got}, the DLC is {dlc}")
        return bytes(payload)

    def _send_row(self, entry):
        """One TX tick of a row: script > global script > manual payload, then sliders.

        Script link and sliders are read at every tick, so linking a script or
        adding/removing a slider takes effect without restarting TX. The frame
        flags of an entry never change after it is created.
        """
        frame_id, is_ext, dlc = entry.frame_id, entry.is_ext, entry.dlc
        try:
            payload = self._script_payload(entry)
            if payload is None:  # 3. Manual payload
                payload = entry.payload

            # Apply slider overrides
            for w in self.slider_widgets:
                if (
                    w.frame_id == frame_id
                    and bool(getattr(w, "is_ext", False)) == is_ext
                ):
                    value = w.min_val + w.slider.value() * w.step
                    payload = encode_signal(payload, w.signal, value)

            # Apply padding
            final_payload = bytes(payload[:dlc]) + bytes(max(0, dlc - len(payload)))
        except Exception as e:
            self._row_failed(entry, e)
            return

        # Send the frame; the row shows it at the next refresh (TODO 2.12)
        self.send_can_message(frame_id, final_payload, dlc, entry.is_fd, is_ext)
        if self.xmetro_windows:  # gauges follow transmitted frames too (TODO 7.2)
            self._feed_gauges(frame_id, is_ext, final_payload)
        self.tx_model.set_error(entry, None)
        self.tx_model.set_payload(entry, final_payload)

    def _row_failed(self, entry, e):
        """Frame not sent: show it on the row, log each distinct error once (TODO 3.3)."""
        message = f"{type(e).__name__}: {e}"
        self.tx_model.set_error(entry, message)
        key = (entry.frame_id, entry.is_ext, message)
        if key not in self._tx_errors_logged:
            self._tx_errors_logged.add(key)
            logging.error("TX %s not sent: %s", entry.id_text, message, exc_info=e)

    def _missing_scripts(self):
        """Enabled rows (and the global script) whose script file is not there."""
        missing = [
            f"{e.id_text} {e.name}: {e.script_path}"
            for e in self._tx_entries()
            if e.enabled and e.script_path and not os.path.exists(e.script_path)
        ]
        if self.global_script_path and not os.path.exists(self.global_script_path):
            missing.append(f"Global script: {self.global_script_path}")
        return missing

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

    def send_can_message(self, frame_id, data, dlc=None, is_fd=False, is_ext=False):
        if not self.can_if:
            return
        try:
            if dlc is None:
                dlc = len(data) if data else 0
            dlc = max(0, min(int(dlc), 64))
            # Not counted for the busload here: the adapter's echo is (TODO 9.8)
            self.can_if.send_frame(frame_id, data, dlc, is_fd, is_ext=is_ext)
        except Exception as e:
            log_exception(e)

    def _feed_latest(self, latest):
        """GUI thread, after each RX drain: the newest payload of each frame (TODO 7.1)."""
        if self.xmetro_windows:
            for (frame_id, is_ext), data in latest.items():
                self._feed_gauges(frame_id, is_ext, data)

    def _feed_gauges(self, frame_id, is_ext, data):
        """GUI thread: update every XMetro gauge showing this frame."""
        for window in self.xmetro_windows:
            if shiboken6.isValid(window):
                window.feed(frame_id, is_ext, data)

    def _forget_xmetro(self, window_id):
        """A closed XMetro window leaves the list, so RX stops feeding it (TODO 7.5)."""
        self.xmetro_windows[:] = [w for w in self.xmetro_windows if id(w) != window_id]

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
        if self.dbc is None:
            QMessageBox.warning(self, "DBC", "Load a DBC file first!")
            return
        if not any(m.signals for m in self.dbc.messages):
            QMessageBox.warning(self, "XMetro", "No messages with signals in DBC file.")
            return

        try:
            xmetro = XMetroWindow(self.dbc)
            xmetro.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            xmetro.destroyed.connect(
                lambda _=None, wid=id(xmetro): self._forget_xmetro(wid)
            )
            self.xmetro_windows.append(xmetro)
            xmetro.show()
        except Exception as e:
            QMessageBox.critical(self, "XMetro", f"Cannot open XMetro: {e}")
            log_exception(e)

    def timer_busload_elapsed(self):
        """Busload over the time since the last update, at the channel's own rates.

        The rates come from the open channel, not from the combo box, which
        can be changed after connecting (TODO 9.8).
        """
        nominal_bits, data_bits = self.rx_window.take_busload_bits()
        now = time.monotonic()
        elapsed, self._busload_since = now - self._busload_since, now
        timing = getattr(self.can_if, "timing", None)
        if timing is None or elapsed <= 0:
            self.lbl_busload.setText("BusLoad: -")
            return
        if isinstance(timing, can.BitTimingFd):
            busy_s = nominal_bits / timing.nom_bitrate + data_bits / timing.data_bitrate
        else:
            busy_s = (nominal_bits + data_bits) / timing.bitrate
        self.lbl_busload.setText(f"BusLoad: {100 * busy_s / elapsed:3.1f}%")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

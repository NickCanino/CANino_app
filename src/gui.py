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

# TODO: aggiungere un modo per scollegare lo script linkato, che sia global o per singolo ID

from PyQt6.QtWidgets import (
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
)
from PyQt6.QtGui import QAction, QIcon, QPixmap, QFont
from PyQt6.QtCore import Qt, QTimer
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
from src.utils import resource_path
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

BUSLOAD_refresh_rate_ms = 1000

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

TX_COL_PERIODDATA = TX_COL_5_period
TX_COL_PERIODDATA_period = Qt.ItemDataRole.DisplayRole

TX_COL_SCRIPTDATA = TX_COL_7_script
TX_COL_SCRIPTDATA_path = Qt.ItemDataRole.UserRole


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
        self.tx_running = False
        self.global_script_path = None
        self.global_script_cache = {}
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

        self.lbl_baudrate = QLabel("Baudrate:")
        self.lbl_baudrate.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_baudrate, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.cb_baudrate = QComboBox()
        self.baudrate_values = [
            ("2 MBit/s (CANFD)", PCAN_BAUD_FD_2M, 2000000, 500000),
            ("1 MBit/s", str(PCAN_BAUD_1M.value), 1000000, 0),
            ("800 kBit/s", str(PCAN_BAUD_800K.value), 800000, 0),
            ("500 kBit/s", str(PCAN_BAUD_500K.value), 500000, 0),
            ("250 kBit/s", str(PCAN_BAUD_250K.value), 250000, 0),
            ("125 kBit/s", str(PCAN_BAUD_125K.value), 125000, 0),
            ("100 kBit/s", str(PCAN_BAUD_100K.value), 100000, 0),
            ("95.238 kBit/s", str(PCAN_BAUD_95K.value), 95238, 0),
            ("83.333 kBit/s", str(PCAN_BAUD_83K.value), 83333, 0),
            ("50 kBit/s", str(PCAN_BAUD_50K.value), 50000, 0),
            ("47.619 kBit/s", str(PCAN_BAUD_47K.value), 47619, 0),
            ("33.333 kBit/s", str(PCAN_BAUD_33K.value), 33333, 0),
            ("20 kBit/s", str(PCAN_BAUD_20K.value), 20000, 0),
            ("10 kBit/s", str(PCAN_BAUD_10K.value), 10000, 0),
            ("5 kBit/s", str(PCAN_BAUD_5K.value), 5000, 0),
        ]
        for label, pcan_val, real_data_val, real_arb_val in self.baudrate_values:
            self.cb_baudrate.addItem(label, pcan_val)
        self.cb_baudrate.setCurrentIndex(0)  # Default to 2 MBit/s (CANFD)
        self.cb_baudrate.setFixedSize(150, 30)
        top_layout.addWidget(self.cb_baudrate)

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
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.btn_start_tx.setFixedSize(100, 30)
        self.btn_start_tx.clicked.connect(self.start_stop_transmission)
        self.btn_start_tx.setEnabled(False)  # Disabilita il pulsante all'inizio

        # Button to disable all ID in TX
        self.btn_disable_all_ids = QPushButton("Disable All")
        self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
        self.btn_disable_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.btn_disable_all_ids.setFixedSize(100, 30)
        self.btn_disable_all_ids.clicked.connect(self.disable_all_ids_tx)
        self.btn_disable_all_ids.setEnabled(False)  # Disabilita il pulsante all'inizio

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
            "Link a global Payload Script to be used for all transmitted CAN frames."
        )
        self.btn_link_global_script.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.btn_link_global_script.setFixedSize(220, 30)
        # self.btn_link_global_script.setStyleSheet("overflow: hidden; text-overflow: ellipsis;")
        # self.btn_link_global_script.setToolTip(self.btn_link_global_script.text())
        self.btn_link_global_script.clicked.connect(self.select_global_payload_script)

        # Layout orizzontale per i due pulsanti
        tx_buttons_layout = QHBoxLayout()
        tx_buttons_layout.addWidget(self.btn_add_id)
        tx_buttons_layout.addWidget(self.btn_start_tx)
        tx_buttons_layout.addWidget(self.btn_disable_all_ids)
        # tx_buttons_layout.addWidget(self.btn_add_xmetro)
        tx_buttons_layout.addStretch(0)
        tx_buttons_layout.addWidget(self.btn_link_global_script)

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
                "Payload (0 - 7)",
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
        self.signal_tree.header().sectionClicked.connect(self.handle_signal_tree_sort)
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

        # Contenitore per gli slider dinamici
        self.slider_container = QVBoxLayout()
        slider_layout.addLayout(self.slider_container)

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
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
            )
        else:  # Attualmente abilitati, quindi disabilita tutti
            for i in range(self.signal_tree.topLevelItemCount()):
                item = self.signal_tree.topLevelItem(i)
                item.setCheckState(TX_COL_1_enable, Qt.CheckState.Unchecked)

            self.btn_disable_all_ids.setText("Enable All")
            self.btn_disable_all_ids.setToolTip("Enable all CAN IDs in the TX list.")
            self.btn_disable_all_ids.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            )

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
                "fd": item.text(TX_COL_3_fd),
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
                    # self.populate_signal_tree()
                    # self.rx_window.set_dbc(self.dbc)
                    # self.btn_disable_all_ids.setEnabled(True)
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
            else:
                self.global_script_path = None
                self.global_script_cache.clear()
                self.btn_link_global_script.setStyleSheet("")
                self.btn_link_global_script.setToolTip("No Global Script Linked")
                self.btn_link_global_script.setText("Link Global Script")
                self.btn_link_global_script.setToolTip(
                    "Link a global Payload Script to be used for all transmitted CAN frames."
                )

            # Load signals only if present in the configuration
            if "signals" in config:
                print("[DEBUG] Loading signals from configuration...")
                loaded_ids = set()  # Keep track of already loaded IDs
                for i in range(self.signal_tree.topLevelItemCount()):
                    item = self.signal_tree.topLevelItem(i)
                    try:
                        existing_id = int(item.text(TX_COL_2_id), 16)
                        loaded_ids.add(existing_id)
                    except Exception:
                        pass

                for sig in config["signals"]:
                    try:
                        frame_id = int(sig.get("id", "0"), 16)
                    except ValueError:
                        continue

                    # Se è già stato caricato dal DBC (populate_signal_tree), collega solo lo script
                    if frame_id in loaded_ids:
                        item = next(
                            (
                                self.signal_tree.topLevelItem(i)
                                for i in range(self.signal_tree.topLevelItemCount())
                                if int(
                                    self.signal_tree.topLevelItem(i).text(TX_COL_2_id),
                                    16,
                                )
                                == frame_id
                            ),
                            None,
                        )  # trova l'item corrispondente all'ID

                        if item and sig.get(
                            "script_path"
                        ):  # se l'item esiste e ha uno script
                            script_path = sig["script_path"]
                            item.setData(
                                TX_COL_7_script, TX_COL_DATA_ROLE_script, script_path
                            )
                            script_btn = self.signal_tree.itemWidget(
                                item, TX_COL_7_script
                            )
                            if script_btn and isinstance(script_btn, QPushButton):
                                script_btn.setChecked(True)
                                script_btn.setStyleSheet(
                                    "background-color: #4CAF50; color: white;"
                                )
                                script_btn.setToolTip(
                                    f"Script: {os.path.relpath(script_path, start=self.project_root)}"
                                )
                                script_btn.setText(os.path.basename(script_path))
                        # continue  # salta l'aggiunta dell'intero messaggio: già caricato

                    else:  # Messaggio non caricato: aggiungilo manualmente
                        msg_item = QTreeWidgetItem(self.signal_tree)
                        msg_item.setFlags(
                            msg_item.flags()
                            | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsEditable
                        )
                        msg_item.setCheckState(
                            1,
                            (
                                Qt.CheckState.Checked
                                if sig.get("enabled")
                                else Qt.CheckState.Unchecked
                            ),
                        )
                        msg_item.setText(TX_COL_2_id, sig.get("id", ""))
                        msg_item.setText(TX_COL_3_fd, sig.get("fd", "n"))
                        msg_item.setText(TX_COL_4_name, sig.get("name", ""))

                        period_spin = QSpinBox()
                        period_spin.setRange(1, 10000)
                        period_spin.setValue(sig.get("period", 100))
                        self.signal_tree.setItemWidget(
                            msg_item, TX_COL_5_period, period_spin
                        )
                        msg_item.setText(TX_COL_5_period, str(period_spin.value()))
                        msg_item.setData(
                            TX_COL_PERIODDATA,
                            TX_COL_PERIODDATA_period,
                            period_spin.value(),
                        )

                        # Payload e DLC
                        raw_payload = sig.get("payload", "")
                        dlc = sig.get("dlc", 8)
                        payload_parts = raw_payload.strip().split()
                        if len(payload_parts) != dlc or any(
                            len(p) != 2 for p in payload_parts
                        ):
                            raw_payload = " ".join(["00"] * dlc)
                        msg_item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_dlc, dlc)
                        msg_item.setText(TX_COL_6_payload, raw_payload)

                        # Pulsanti standard
                        btn_delete_id = QPushButton()
                        btn_delete_id.setIcon(
                            self.style().standardIcon(
                                QStyle.StandardPixmap.SP_TrashIcon
                            )
                        )
                        btn_delete_id.setToolTip("Delete")
                        btn_delete_id.clicked.connect(
                            lambda _, item=msg_item: self.delete_signal_row(item)
                        )
                        self.signal_tree.setItemWidget(
                            msg_item, TX_COL_0_del, btn_delete_id
                        )

                        script_btn = QPushButton("Link Script")
                        script_btn.setCheckable(True)
                        script_btn.setIcon(
                            self.style().standardIcon(
                                QStyle.StandardPixmap.SP_FileDialogDetailedView
                            )
                        )
                        # script_btn.setToolTip("Script Payload")
                        script_btn.clicked.connect(
                            lambda _, item=msg_item: self.modify_payload_script(item)
                        )
                        self.signal_tree.setItemWidget(
                            msg_item, TX_COL_7_script, script_btn
                        )

                        if sig.get("script_path"):
                            script_path = sig["script_path"]
                            msg_item.setData(
                                TX_COL_7_script, TX_COL_DATA_ROLE_script, script_path
                            )
                            script_btn.setChecked(True)
                            script_btn.setStyleSheet(
                                "background-color: #4CAF50; color: white;"
                            )
                            script_btn.setToolTip(
                                f"Script: {os.path.relpath(script_path, start=self.project_root)}"
                            )
                            script_btn.setText(os.path.basename(script_path))

            # Load sliders
            if "sliders" in config and len(config["sliders"]) > 0:
                print("[DEBUG] Loading sliders from configuration...")
                for meta in config["sliders"]:
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

                    def remove_slider():
                        for i in reversed(range(self.slider_container.count())):
                            widget = self.slider_container.itemAt(i).widget()
                            if widget == slider_widget:
                                widget.setParent(None)
                                self.added_sliders.discard(key)
                                if hasattr(self, "slider_widgets"):
                                    self.slider_widgets = [
                                        w
                                        for w in self.slider_widgets
                                        if not (
                                            w.frame_id == msg.frame_id
                                            and w.signal.name == sig.name
                                        )
                                    ]
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

                    if not hasattr(self, "slider_widgets"):
                        self.slider_widgets = []

                    self.slider_container.addWidget(slider_widget)
                    slider_widget.key = key  # Unico identificatore per lo slider
                    self.slider_widgets.append(slider_widget)

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

    def toggle_connection(self):
        if self.btn_connect.isChecked():  # Connect button is checked
            channel = self.cb_bus_tx.currentData()  # Get the selected channel
            if channel is None:
                QMessageBox.warning(self, "Warning", "No CAN channel selected")
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

            try:  # Try to connect to the CAN interface
                bitrate_lbl = self.cb_baudrate.currentText()
                print(f"[DEBUG] selected timing: {bitrate_lbl}")
                self.can_if = CANInterface(
                    channel, timing=bitrate_lbl, is_fd=("f_clock=" in bitrate_lbl)
                )
                self.can_if.set_receive_callback(self.process_received_frame)
                QMessageBox.information(
                    self,
                    "Info",
                    f"Connected to: \n    > {self.cb_bus_tx.currentText()}\n    > Baudrate: {bitrate_lbl}",
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
                self.btn_start_tx.setEnabled(True)  # <--- Enable after connection

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error opening CAN: {e}")
                log_exception(__file__, sys._getframe().f_lineno, e)
                self.btn_connect.setChecked(False)
                self.btn_start_tx.setEnabled(False)  # <--- Disable if error

        else:  # Disconnect
            if self.can_if:
                self.can_if.close()
                self.can_if = None
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

    def populate_signal_tree(
        self,
    ):  # Popola l'albero dei segnali con i messaggi del DBC
        self.signal_tree.clear()
        if not self.dbc:
            return
        is_fd = self.can_if.is_fd if self.can_if is not None else False
        for msg in self.dbc.messages:
            msg_item = QTreeWidgetItem(self.signal_tree)
            msg_item.setFlags(
                msg_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            msg_item.setCheckState(TX_COL_1_enable, Qt.CheckState.Checked)
            msg_item.setText(TX_COL_2_id, f"0x{msg.frame_id:03X}")
            msg_item.setText(TX_COL_3_fd, "Y" if is_fd else "n")
            msg_item.setText(TX_COL_4_name, msg.name)

            period_spin = QSpinBox()
            period_spin.setRange(1, 10000)
            period_spin.setValue(msg.cycle_time if msg.cycle_time else 100)

            self.signal_tree.setItemWidget(msg_item, TX_COL_5_period, period_spin)
            msg_item.setText(TX_COL_5_period, str(period_spin.value()))
            msg_item.setData(
                TX_COL_5_period, Qt.ItemDataRole.DisplayRole, period_spin.value()
            )
            msg_item.setData(
                TX_COL_DATA, TX_COL_DATA_ROLE_dlc, msg.payload_length
            )  # Store DLC in user data
            msg_item.setText(
                TX_COL_6_payload, " ".join(["00"] * msg.payload_length)
            )  # Set default payload

            # Add delete button as first column
            btn_delete_id = QPushButton()
            btn_delete_id.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            )
            btn_delete_id.setToolTip("Delete")
            btn_delete_id.clicked.connect(
                lambda _, item=msg_item: self.delete_signal_row(item)
            )
            self.signal_tree.setItemWidget(msg_item, TX_COL_0_del, btn_delete_id)

            # Add custom payload button in 5th column
            script_btn = QPushButton("Link Script")
            script_btn.setCheckable(True)
            script_btn.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                )
            )
            script_btn.setToolTip("No Script Linked")
            script_btn.clicked.connect(
                lambda _, item=msg_item: self.modify_payload_script(item)
            )
            self.signal_tree.setItemWidget(msg_item, TX_COL_7_script, script_btn)

            self.signal_tree.sortItems(
                TX_COL_2_id, Qt.SortOrder.AscendingOrder
            )  # Ascending sort by ID (column 2)

    def add_manual_id(self):
        id_text, ok = QInputDialog.getText(
            self, "Add Manual ID", "Enter hex. ID (e.g. 100):"
        )
        if not ok or not id_text:
            return

        try:
            frame_id = int(id_text, 16)
        except ValueError:
            QMessageBox.warning(self, "Error", "Invalid ID")
            return

        name, ok = QInputDialog.getText(self, "Add Manual ID", "Enter name:")
        if not ok or not name:
            return

        period, ok = QInputDialog.getInt(
            self, "Add Manual ID", "Enter period (ms):", min=1, max=10000
        )
        if not ok:
            return

        is_fd, ok = QInputDialog.getInt(
            self, "Add Manual ID", "Select if FD (0-1):", min=0, max=1
        )

        if is_fd == 1:
            dlc, ok = QInputDialog.getInt(
                self, "Add Manual ID", "Enter DLC (1-64):", min=1, max=64
            )
        elif is_fd == 0:
            dlc, ok = QInputDialog.getInt(
                self, "Add Manual ID", "Enter DLC (1-8):", min=1, max=8
            )
        if not ok:
            return

        msg_item = QTreeWidgetItem(self.signal_tree)
        msg_item.setFlags(
            msg_item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEditable
        )
        msg_item.setCheckState(TX_COL_1_enable, Qt.CheckState.Checked)
        msg_item.setText(TX_COL_2_id, f"0x{frame_id:03X}")
        msg_item.setText(TX_COL_3_fd, "Y" if is_fd else "n")
        msg_item.setText(TX_COL_4_name, name)

        # Salva DLC e is_fd come dato dell'item
        msg_item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_dlc, dlc)
        msg_item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd, is_fd)

        period_spin = QSpinBox()
        period_spin.setRange(1, 10000)
        period_spin.setValue(period)
        self.signal_tree.setItemWidget(msg_item, TX_COL_5_period, period_spin)
        msg_item.setText(TX_COL_5_period, str(period_spin.value()))
        msg_item.setData(
            TX_COL_PERIODDATA, Qt.ItemDataRole.DisplayRole, period_spin.value()
        )

        msg_item.setText(TX_COL_6_payload, " ".join(["00"] * dlc))

        # Pulsanti standard
        btn_delete_id = QPushButton()
        btn_delete_id.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_delete_id.setToolTip("Delete")
        btn_delete_id.clicked.connect(
            lambda _, item=msg_item: self.delete_signal_row(item)
        )
        self.signal_tree.setItemWidget(msg_item, TX_COL_0_del, btn_delete_id)

        # Pulsante per linkare lo script del payload
        script_btn = QPushButton("Link Script")
        script_btn.setCheckable(True)
        script_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        script_btn.setToolTip("No Script Linked")
        script_btn.clicked.connect(
            lambda _, item=msg_item: self.modify_payload_script(item)
        )
        self.signal_tree.setItemWidget(msg_item, TX_COL_7_script, script_btn)

        # Ascending sort by ID (column 2)
        self.signal_tree.sortItems(TX_COL_2_id, Qt.SortOrder.AscendingOrder)

        # Se la trasmissione è attiva, riavvia per includere il nuovo ID
        if self.tx_running:
            self.stop_tx()
            self.start_tx()

        self.btn_disable_all_ids.setEnabled(True)

    def delete_signal_row(self, item):
        idx = self.signal_tree.indexOfTopLevelItem(item)
        if idx != -1:
            # Se la trasmissione è attiva, ferma e rimuovi il timer relativo all'ID
            if self.tx_running:
                try:
                    frame_id = int(item.text(TX_COL_2_id), 16)
                    timers_to_remove = []
                    for t in self.timers:
                        if hasattr(t, "frame_id") and t.frame_id == frame_id:
                            t.stop()
                            timers_to_remove.append(t)
                    for t in timers_to_remove:
                        self.timers.remove(t)
                    if hasattr(self, "tx_periods") and frame_id in self.tx_periods:
                        del self.tx_periods[frame_id]
                except Exception:
                    pass
            self.signal_tree.takeTopLevelItem(idx)

        if self.signal_tree.topLevelItemCount() == 0:
            self.btn_disable_all_ids.setEnabled(False)

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

        elif column == TX_COL_5_period:  # Periodo (ms) column changed
            # Update the timer for this item if TX is running
            if self.tx_running:
                frame_id = None
                try:
                    frame_id = int(item.text(TX_COL_2_id), 16)
                except Exception:
                    return
                # Find and update the timer for this frame_id
                for t in getattr(self, "timers", []):
                    if hasattr(t, "frame_id") and t.frame_id == frame_id:
                        period_spin = self.signal_tree.itemWidget(item, TX_COL_5_period)
                        new_period = period_spin.value() if period_spin else 1000
                        item.setText(TX_COL_5_period, str(new_period))

                        t.stop()
                        t.start(new_period)
                        if hasattr(self, "tx_periods") and frame_id in self.tx_periods:
                            self.tx_periods[frame_id]["nominal"] = new_period
                        break

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
            QMessageBox.information(
                self,
                "Global Script selected",
                f"Global script set for all IDs:\n{rel_file_path}\n\n"
                "This will be used for all TX payloads unless a specific script is set for an ID.",
            )

    def modify_payload_script(self, item):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Python script", "", "Python Files (*.py)"
        )
        rel_file_path = (
            os.path.relpath(file_path, start=self.project_root) if file_path else None
        )

        if rel_file_path:
            item.setData(TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path, rel_file_path)
            widget = self.signal_tree.itemWidget(item, TX_COL_7_script)
            if widget and isinstance(widget, QPushButton):
                widget.setChecked(True)
                widget.setStyleSheet("background-color: #4CAF50; color: white;")
                widget.setToolTip(f"Script: {rel_file_path}")
                widget.setText(os.path.basename(rel_file_path))

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
            self.start_tx()
        else:
            self.stop_tx()

    def start_tx(self):
        """Starts the periodic transmission of enabled CAN messages in ascending order of ID."""
        self.timers.clear()
        self.tx_periods = (
            {}
        )  # frame_id: {'nominal': period, 'offset': 0, 'samples': [], 'last_time': None}
        items_to_send = []
        for i in range(self.signal_tree.topLevelItemCount()):  # Itera su tutti gli ID
            item = self.signal_tree.topLevelItem(i)
            if item.checkState(TX_COL_1_enable) == Qt.CheckState.Checked:
                try:
                    frame_id = int(item.text(TX_COL_2_id), 16)
                    items_to_send.append((frame_id, item))
                except Exception:
                    continue
        items_to_send.sort(key=lambda x: x[0])

        # Prepara gli slider per i frame
        slider_overrides = {}
        if hasattr(
            self, "slider_widgets"
        ):  # Controlla se gli slider sono stati aggiunti
            for w in self.slider_widgets:
                fid = w.frame_id
                sig = w.signal
                if fid not in slider_overrides:
                    slider_overrides[fid] = []
                slider_overrides[fid].append((sig, w.slider))

        # Inizializza i timer ed il dizionario per la cache degli script
        for frame_id, item in items_to_send:
            period_spin = self.signal_tree.itemWidget(item, TX_COL_5_period)
            period = period_spin.value() if period_spin else 1000
            self.tx_periods[frame_id] = {
                "nominal": period,
                "offset": 0,
                "samples": [],
                "last_time": None,
            }
            # Connect live update for period spinbox
            if period_spin is not None:

                def make_period_handler(fid=frame_id, spin=period_spin, tree_item=item):
                    def handler(new_period):
                        if self.tx_running:
                            # Update timer and tx_periods
                            for t in self.timers:
                                if hasattr(t, "frame_id") and t.frame_id == fid:
                                    t.stop()
                                    t.start(new_period)
                                    self.tx_periods[fid]["nominal"] = new_period
                                    break

                    return handler

                period_spin.valueChanged.connect(make_period_handler())

            script_path = item.data(TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path)
            script_cache = {}

            def make_callback(frame_id=frame_id, item=item, script_path=script_path):
                def callback():
                    now_time = time.time() * 1000  # ms
                    txp = self.tx_periods[frame_id]

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

                    dlc = (
                        item.data(TX_COL_DATA, TX_COL_DATA_ROLE_dlc) or 8
                    )  # se il payload viene da testo manuale
                    if not isinstance(dlc, int) or not (1 <= dlc <= 64):
                        dlc = 8

                    is_fd = (
                        item.data(TX_COL_DATA, TX_COL_DATA_ROLE_is_fd) or 0
                    )  # 0 se CAN, 1 se CAN-FD
                    if not isinstance(is_fd, int) or not (0 <= is_fd <= 1):
                        is_fd = 0

                    # Se il payload è stato specificato come script, lo esegue
                    try:
                        # 1. Per-ID script has priority
                        if script_path and os.path.exists(script_path):
                            if script_path not in script_cache:
                                script_globals = {}
                                with open(script_path, "r", encoding="utf-8") as f:
                                    exec(f.read(), script_globals)
                                get_payload_fn = script_globals.get("get_payload")
                                if not callable(get_payload_fn):
                                    raise RuntimeError(
                                        "Selected script file does not contain a function get_payload()"
                                    )
                                script_cache[script_path] = get_payload_fn
                            else:
                                get_payload_fn = script_cache[script_path]

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
                                script_globals = {}
                                with open(
                                    self.global_script_path, "r", encoding="utf-8"
                                ) as f:
                                    exec(f.read(), script_globals)
                                get_payload_fn = script_globals.get("get_payload")
                                if not callable(get_payload_fn):
                                    raise RuntimeError(
                                        "Global script file does not contain a function get_payload()"
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
                        if frame_id in slider_overrides:
                            for sig, slider in slider_overrides[frame_id]:
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
                        self.send_can_message(frame_id, final_payload, dlc, is_fd)
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
            timer.frame_id = frame_id  # Custom attribute for lookup
            timer.timeout.connect(
                make_callback(frame_id=frame_id, item=item, script_path=script_path)
            )
            timer.start(period)
            self.timers.append(timer)

        self.tx_running = True
        self.btn_start_tx.setText("Stop TX")
        self.btn_start_tx.setToolTip(
            "Stop the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
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
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )

    def make_timer_callback(self, frame_id, data, dlc, is_fd, item=None):
        def callback():
            self.send_can_message(frame_id, data, dlc, is_fd)
            if item:
                item.setText(TX_COL_6_payload, " ".join(f"{b:02X}" for b in data))

        return callback

    def send_can_message(self, frame_id, data, dlc=None, is_fd=False):
        if not self.can_if:
            return
        try:
            # determine DLC
            if dlc is None:
                dlc = len(data) if data else 0
            dlc = max(0, min(int(dlc), 64))

            # extended ID heuristic
            is_ext = isinstance(frame_id, int) and frame_id > 0x7FF

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
            self.can_if.send_frame(frame_id, data, dlc, is_fd)
        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def process_received_frame(self, frame_id, data, dlc=None, is_fd=False):
        try:
            # aggiorna il buffer/tabella RX
            self.rx_window.update_frame(frame_id, data, dlc, is_fd)

            # Aggiorna i gauge che mostrano questo frame ID
            for gauge in getattr(self, "gauges", []):
                if gauge.cb_messages.currentData() == frame_id:
                    if not isinstance(data, bytes):
                        data = bytes(data)
                    gauge.update_gauge(data)

        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

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
            # Mantieni una lista di finestre XMetro
            if not hasattr(self, "xmetro_windows"):
                self.xmetro_windows = []

            xmetro = XMetroWindow(self.dbc)
            self.xmetro_windows.append(xmetro)

            xmetro.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            xmetro.show()
            print("XMetro window created and shown")

        except Exception as e:
            print(f"Error creating XMetro window: {str(e)}")
            log_exception(__file__, sys._getframe().f_lineno, e)

    def handle_signal_tree_sort(self, column):
        if column == TX_COL_4_name:
            self.signal_tree.setSortingEnabled(False)
            items = []
            for i in range(self.signal_tree.topLevelItemCount()):
                item = self.signal_tree.topLevelItem(i)
                period_spin = self.signal_tree.itemWidget(item, TX_COL_4_name)
                if period_spin is not None:
                    period_value = int(period_spin.value())
                else:
                    try:
                        period_value = int(item.text(TX_COL_4_name))
                    except Exception:
                        period_value = 100
                item_data = {
                    "check_state": item.checkState(TX_COL_1_enable),
                    "id": item.text(TX_COL_2_id),
                    "fd": item.text(TX_COL_3_fd),
                    "name": item.text(TX_COL_4_name),
                    "dlc": item.data(TX_COL_DATA, TX_COL_DATA_ROLE_dlc),
                    "payload": item.text(TX_COL_6_payload),
                    "script_path": item.data(TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path),
                    "period": period_value,
                }
                items.append((period_value, item_data))

            if not hasattr(self, "_period_sort_asc") or self._period_sort_asc is False:
                items.sort(key=lambda x: x[0])
                self._period_sort_asc = True
            else:
                items.sort(key=lambda x: x[0], reverse=True)
                self._period_sort_asc = False

            self.signal_tree.clear()
            for _, item_data in items:
                check_state = item_data["check_state"]
                id_text = item_data["id"]
                name_text = item_data["name"]
                dlc = item_data["dlc"] if item_data["dlc"] is not None else 8
                is_fd = item_data["is_fd"]
                payload = item_data["payload"]
                script_path = item_data["script_path"]
                period_val = item_data["period"] if "period" in item_data else 100

                msg_item = QTreeWidgetItem(self.signal_tree)
                msg_item.setFlags(
                    msg_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEditable
                )
                msg_item.setCheckState(TX_COL_1_enable, check_state)
                msg_item.setText(TX_COL_2_id, id_text)
                msg_item.setText(TX_COL_3_fd, is_fd)
                msg_item.setText(TX_COL_4_name, name_text)
                msg_item.setData(TX_COL_DATA, TX_COL_DATA_ROLE_dlc, dlc)
                msg_item.setText(TX_COL_6_payload, payload)
                if script_path:
                    msg_item.setData(
                        TX_COL_SCRIPTDATA, TX_COL_SCRIPTDATA_path, script_path
                    )

                period_spin = QSpinBox()
                period_spin.setRange(1, 10000)
                period_spin.setValue(period_val)
                self.signal_tree.setItemWidget(msg_item, TX_COL_5_period, period_spin)
                # Imposta solo il valore numerico come DisplayRole, non il testo
                msg_item.setData(
                    TX_COL_PERIODDATA, TX_COL_PERIODDATA_period, period_spin.value()
                )

                def on_period_changed(new_value, item=msg_item):
                    item.setData(TX_COL_PERIODDATA, TX_COL_PERIODDATA_period, new_value)

                period_spin.valueChanged.connect(on_period_changed)

                btn_delete_id = QPushButton()
                btn_delete_id.setIcon(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                )
                btn_delete_id.setToolTip("Delete")
                btn_delete_id.clicked.connect(
                    lambda _, item=msg_item: self.delete_signal_row(item)
                )
                self.signal_tree.setItemWidget(msg_item, TX_COL_0_del, btn_delete_id)

                # TODO: verificare differenza tra qui ed i metodi add_manual_id() e populate_signal_tree()
                script_btn = QPushButton("Link Script")
                script_btn.setCheckable(True)
                script_btn.setIcon(
                    self.style().standardIcon(
                        QStyle.StandardPixmap.SP_FileDialogDetailedView
                    )
                )
                script_btn.setToolTip("No Script Linked")
                script_btn.clicked.connect(
                    lambda _, item=msg_item: self.modify_payload_script(item)
                )
                self.signal_tree.setItemWidget(msg_item, TX_COL_7_script, script_btn)
                if script_path:
                    script_btn.setChecked(True)
                    script_btn.setStyleSheet("background-color: #4CAF50; color: white;")
                    script_btn.setToolTip(f"Script: {script_path}")
                    script_btn.setText(os.path.basename(script_path))

            self.signal_tree.setSortingEnabled(True)

        else:
            if hasattr(self, "_period_sort_asc"):
                del self._period_sort_asc

            self.signal_tree.setSortingEnabled(True)
            self.signal_tree.sortItems(
                column, self.signal_tree.header().sortIndicatorOrder()
            )

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

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
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QGroupBox,
    QMessageBox,
    QSplitter,
    QStyle,
    QMenuBar,
    QMenu,
    QCheckBox,
    QDockWidget,
    QStatusBar,
    QToolBar,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QDesktopServices
from PySide6.QtCore import Qt, QTimer, QUrl
import shiboken6
import os
import time
import can

from src.can_interface import CANInterface
from src.exceptions_logger import log_exception, __version__, log_dir as LOG_DIR
from src.xmetro_class import XMetroWindow
from src.signal_plot_class import SignalPlotWindow
from src.vagiletta_programmer_class import VagilettaWindow
from src.received_frames_class import ReceivedFramesWindow
from src.trace_replay import MAX_GAP_S
from src.utils import resource_path
from src.tx_panel import TxPanelMixin
from src.slider_panel import SliderPanelMixin
from src.workspace import WorkspaceMixin
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


BUSLOAD_refresh_rate_ms = 1000
BUS_STATUS_POLL_MS = 250
BUSLOAD_TOOLTIP = (
    "Share of the last second the bus was busy: every frame seen on the "
    "wire (received, and transmitted from the adapter's echo), stuff "
    "bits, ACK, EOF and intermission included. Error frames are not counted."
)
# Error-warning / error-passive this long while transmitting = frames are not
# being acknowledged: stop TX instead of filling the 32.8k-frame driver queue
TX_ERROR_GRACE_S = 2.0
# Height of the logos at the right of the status bar
STATUS_LOGO_PX = 22
BUS_STATUS_COLORS = {
    "ok": "#4CAF50",
    "info": "#2196F3",
    "warn": "#FF9800",
    "severe": "#E53935",
}


class MainWindow(TxPanelMixin, SliderPanelMixin, WorkspaceMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CANino App - v{__version__}")
        self.setWindowIcon(QIcon(resource_path("resources/figures/app_logo.ico")))
        self.setGeometry(100, 100, 1450, 850)

        # Class Attributes
        self.dbc = None
        self.can_if = None
        self.workspace_path = None  # file of the last Load / Save (TODO 6.6)
        self._dirty = False  # unsaved changes since the last Load/Save (TODO 6.8)
        self._loading = False  # True while load_config rebuilds the workspace

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
        action_save.setShortcut(QKeySequence.StandardKey.Save)  # Ctrl+S (TODO 6.8)
        action_load.setShortcut(QKeySequence.StandardKey.Open)  # Ctrl+O
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
        file_menu.addSeparator()
        action_load_dbc = QAction("Load DBC...", self)
        action_load_dbc.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        action_load_dbc.triggered.connect(self.load_dbc_file)
        file_menu.addAction(action_load_dbc)
        self.menu_recent = QMenu("Recent workspaces", self)
        file_menu.insertMenu(action_load_dbc, self.menu_recent)
        self._rebuild_recent_menu()
        menubar.addMenu(file_menu)

        scripts_menu = QMenu("&Scripts", self)
        action_new_script = QAction("New script from template...", self)
        action_new_script.setToolTip(
            "Copy a bundled payload-script template to a file you can edit and link."
        )
        action_new_script.triggered.connect(self.new_script_from_template)
        action_new_script.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        scripts_menu.addAction(action_new_script)
        menubar.addMenu(scripts_menu)

        help_menu = QMenu("&Help", self)
        action_logs = QAction("Open log folder", self)
        action_logs.setToolTip(LOG_DIR)
        action_logs.triggered.connect(self.open_log_folder)
        help_menu.addAction(action_logs)
        action_about = QAction("About CANino App", self)
        action_about.triggered.connect(self.show_about)
        help_menu.addAction(action_about)
        self.action_open_logs = action_logs

        # Tools: the separate windows
        tools_menu = QMenu("&Tools", self)
        action_xmetro = QAction("XMetro", self)
        action_xmetro.triggered.connect(self.open_xmetro_window)
        tools_menu.addAction(action_xmetro)
        action_plot = QAction("Signal Plot", self)
        action_plot.triggered.connect(self.open_signal_plot_window)
        tools_menu.addAction(action_plot)
        tools_menu.addSeparator()
        # Replay preference, read when a replay starts (QSettings)
        action_gaps = QAction(
            f"Replay: Compress Idle Gaps > {MAX_GAP_S:g} s", self, checkable=True
        )
        action_gaps.setChecked(self.replay_compress_gaps())
        action_gaps.toggled.connect(self.set_replay_compress_gaps)
        tools_menu.addAction(action_gaps)
        self.action_replay_gaps = action_gaps
        tools_menu.addSeparator()
        action_vagiletta = QAction("VAGILETTA", self)
        action_vagiletta.triggered.connect(self.open_vagiletta_window)
        tools_menu.addAction(action_vagiletta)
        menubar.addMenu(tools_menu)

        # View: show/hide panels; filled once the panels exist
        self.view_menu = QMenu("&View", self)
        menubar.addMenu(self.view_menu)

        menubar.addMenu(help_menu)
        self.setMenuBar(menubar)

        # --- TOP CONTROLS ---
        top_controls = QWidget()
        top_layout = QHBoxLayout()
        top_controls.setLayout(top_layout)
        top_controls.setFixedHeight(44)  # Fixed height of the top bar
        top_layout.setContentsMargins(6, 4, 6, 4)

        # --- TOP BUTTONS AND COMBO BOXES ---
        # Combo box to select the CAN channel
        self.lbl_interface = QLabel("Interface:")
        self.lbl_interface.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(
            self.lbl_interface, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        self.cb_interface = QComboBox()
        self.cb_interface.addItem("PCAN-USB", "pcan")
        self.cb_interface.addItem("Virtual (no hardware)", "virtual")
        self.cb_interface.setFixedSize(170, 30)
        self.cb_interface.setToolTip(
            "PCAN-USB: a PEAK adapter. Virtual: an in-process loopback bus for "
            "demos and tests, no hardware (only this app is on it)."
        )
        self.cb_interface.currentIndexChanged.connect(self.refresh_bus_list)
        top_layout.addWidget(self.cb_interface)

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
        self.lbl_busload.setToolTip(BUSLOAD_TOOLTIP)
        self.lbl_busload.setMinimumWidth(220)

        # Controller state, polled while connected (TODO 1.5)
        self.lbl_bus_status = QLabel("Bus: -")
        self.lbl_bus_status.setToolTip("CAN controller state of the connected channel.")
        self.lbl_bus_status.setMinimumWidth(160)
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
        top_layout.addStretch(1)

        top_bar = QToolBar("Connection", self)
        top_bar.setMovable(False)
        top_bar.setFloatable(False)
        top_bar.toggleViewAction().setVisible(False)  # always shown
        top_bar.addWidget(top_controls)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, top_bar)

        tx_group = self._build_tx_panel()

        # RX controls
        self.rx_window = ReceivedFramesWindow(self.dbc)
        # The RX window drains the RX queue in the GUI thread and hands the
        # latest payload of each frame to the XMetro gauges, every sample of
        # the plotted frames to the Signal Plots (TODO 7.10)
        self.xmetro_windows = []
        self.signal_plot_windows = []
        self.rx_window.frames_received.connect(self._feed_latest)
        self.rx_window.samples_received.connect(self._feed_plots)
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
        rx_layout.addWidget(self.rx_window, 1)

        slider_group = self._build_slider_panel()

        # --- CENTRAL AREA: TX over RX ---
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tx_group)
        left_splitter.addWidget(rx_group)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(6, 0, 0, 0)
        main_layout.addWidget(left_splitter)
        self.setCentralWidget(container)

        # --- SIDE PANELS: docks on the left/right edge only, shown, hidden or
        # floated from the View menu; on the same side Sliders stay on top ---
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)  # no tabs
        self._ordering_docks = False
        self.slider_dock = self._side_dock(
            "DBC Signal Sliders (TX)", "slider_dock", slider_group
        )
        self.decoded_dock = self._side_dock(
            "DBC Decoded Signals (RX)", "decoded_dock", self._decoded_group()
        )
        self.resizeDocks([self.slider_dock], [320], Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self.slider_dock, self.decoded_dock], [500, 250], Qt.Orientation.Vertical
        )
        for dock, text in (
            (self.slider_dock, "DBC Signal Sliders panel (TX)"),
            (self.decoded_dock, "DBC Decoded Signals panel (RX)"),
        ):
            action = dock.toggleViewAction()
            action.setText(text)
            self.view_menu.addAction(action)
            dock.dockLocationChanged.connect(self._schedule_dock_order)
            dock.topLevelChanged.connect(self._schedule_dock_order)
            dock.visibilityChanged.connect(self._schedule_dock_order)

        # --- STATUS BAR: bus state, busload, linked DBC, logos ---
        status = QStatusBar(self)
        status.addWidget(self.lbl_bus_status)
        status.addWidget(self.lbl_busload)
        self.lbl_dbc = QLabel()
        status.addWidget(self.lbl_dbc)
        self._show_dbc_name(None)
        for figure in ("CANinoApp_banner_background.png", "dii_logo.png"):
            logo = QLabel()
            logo.setPixmap(
                QPixmap(resource_path(f"resources/figures/{figure}")).scaledToHeight(
                    STATUS_LOGO_PX, Qt.TransformationMode.SmoothTransformation
                )
            )
            logo.setContentsMargins(8, 0, 8, 0)
            status.addPermanentWidget(logo)
        self.setStatusBar(status)

        self.refresh_bus_list()
        # Load the default workspace at start-up, if it exists
        self.load_config(auto=True)

    def open_log_folder(self):
        """Logs live in the user's app data now, not next to the exe (TODO 9.3)."""
        os.makedirs(LOG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_DIR))

    def show_about(self):
        """Version, libraries and license (TODO 10.7)."""
        import platform

        import cantools

        from PySide6 import __version__ as pyside_version

        def img(name, height):
            path = resource_path(f"resources/figures/{name}").replace(os.sep, "/")
            return f'<img src="{path}" height="{height}">'

        QMessageBox.about(
            self,
            "About CANino App",
            f"{img('CANinoApp_banner_background.png', 48)}<br>"
            f"<b>CANino App</b> v{__version__}<br><br>"
            "Transmit, receive and inspect CAN / CAN FD traffic through a "
            "PEAK PCAN-USB adapter.<br><br>"
            "Nicasio Canino - Department of Information Engineering (DII), "
            "University of Pisa<br>"
            "Apache License 2.0<br>"
            '<a href="https://github.com/NickCanino/CANino_app">'
            "github.com/NickCanino/CANino_app</a><br><br>"
            f"Python {platform.python_version()} &middot; PySide6 {pyside_version} "
            f"&middot; python-can {can.__version__} &middot; cantools "
            f"{cantools.__version__}<br><br>"
            f"{img('dii_logo.png', 40)}",
        )

    def open_vagiletta_window(self):
        dlg = VagilettaWindow(self)
        dlg.exec()

    def refresh_bus_list(self):
        self.cb_bus_tx.clear()
        if self.cb_interface.currentData() == "virtual":
            # No hardware to enumerate: one in-process loopback channel
            self.cb_bus_tx.addItem("virtual0", "virtual0")
            return
        for display, handle in CANInterface.get_available_channels():
            self.cb_bus_tx.addItem(display, handle)
        if self.cb_bus_tx.count() == 0 and CANInterface.scan_error:
            self.cb_bus_tx.addItem(CANInterface.scan_error, None)

    def toggle_connection(self):
        if self.btn_connect.isChecked():  # Connect button is checked
            interface = self.cb_interface.currentData()
            channel = self.cb_bus_tx.currentData()  # Get the selected channel
            if channel is None:
                QMessageBox.warning(
                    self,
                    "Warning",
                    CANInterface.scan_error or "No CAN channel selected",
                )
                self.btn_connect.setChecked(False)
                return

            # Hardware-only checks: the virtual loopback has no HW to scan
            if interface == "pcan":
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
            if (
                interface == "pcan"
                and isinstance(timing, can.BitTimingFd)
                and not CANInterface.is_fd_capable(channel)
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
                    channel, timing=timing, listen_only=listen_only, interface=interface
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
                self.cb_interface.setEnabled(False)
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
            self.stop_replay()  # a running replay sends to this channel
            if self.tx_running:  # the TX thread must be gone before the bus
                self.stop_tx()
            if self.can_if:
                self.can_if.close()
                self.can_if = None
            self.lbl_bus_status.setText("Bus: -")
            self.lbl_bus_status.setStyleSheet("")
            self.lbl_busload.setText("BusLoad: -")
            self.lbl_busload.setToolTip(BUSLOAD_TOOLTIP)
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
            self.cb_interface.setEnabled(True)
            self.btn_refresh_bus.setEnabled(True)
            self.btn_add_id.setEnabled(True)
            self.btn_start_tx.setEnabled(False)  # No TX without a channel
            if self.tx_running:
                self.stop_tx()  # Stop the transmission if it is running

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

    def _feed_plots(self, samples):
        """GUI thread: every RX or TX sample of the plotted frames (TODO 7.10)."""
        for window in self.signal_plot_windows:
            if shiboken6.isValid(window):
                window.feed_samples(samples)

    def _update_plot_keys(self):
        """The frames any open Signal Plot shows: only these are collected, in
        full, by the RX drain and the TX thread (TODO 7.10)."""
        keys = frozenset(
            key
            for window in self.signal_plot_windows
            if shiboken6.isValid(window)
            for key in window.keys()
        )
        self.rx_window.sample_keys = keys
        self._plot_tx_keys = keys

    def _apply_dbc(self, dbc):
        """Set the DBC everywhere it is used: RX names + decoded panel, and any
        open XMetro window (TODO 7.8). Callers stop setting self.dbc themselves."""
        self.dbc = dbc
        self._show_dbc_name(dbc)
        self.rx_window.set_dbc(dbc)
        for window in self.xmetro_windows + self.signal_plot_windows:
            if shiboken6.isValid(window):
                window.set_dbc(dbc)

    def _decoded_group(self):
        """The RX decoded-signal table in a bordered box, like the Sliders one:
        purple, apart from TX green, RX blue and Sliders orange."""
        group = QGroupBox()
        group.setStyleSheet(
            "QGroupBox { border: 2px solid #9C27B0; border-radius: 5px; }"
        )
        layout = QVBoxLayout(group)
        layout.addWidget(self.rx_window.decoded)
        return group

    def _side_dock(self, title, name, widget):
        """A dock for `widget` on the right edge, movable to the left one only."""
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        return dock

    def _schedule_dock_order(self, *_):
        """After a dock moves, shows or docks back: fix the order once the
        layout has settled (geometries are stale inside the signal)."""
        QTimer.singleShot(0, self, self._order_side_docks)  # dropped if self dies

    def _order_side_docks(self):
        """Sliders above Decoded when both are docked on the same side."""
        top, bottom = self.slider_dock, self.decoded_dock
        if self._ordering_docks:
            return
        if any(d.isFloating() or d.isHidden() for d in (top, bottom)):
            return
        if self.dockWidgetArea(top) != self.dockWidgetArea(bottom):
            return
        if top.geometry().bottom() < bottom.geometry().top():
            return  # already stacked in the right order
        self._ordering_docks = True
        try:
            self.splitDockWidget(top, bottom, Qt.Orientation.Vertical)
        finally:
            self._ordering_docks = False

    def _show_dbc_name(self, dbc):
        """Status bar: the linked DBC's file name, the full path in the tooltip."""
        path = getattr(dbc, "dbc_filename", None) if dbc is not None else None
        if path:
            self.lbl_dbc.setText(f"DBC: {os.path.basename(path)}")
            self.lbl_dbc.setToolTip(path)
        else:
            self.lbl_dbc.setText("DBC: -")
            self.lbl_dbc.setToolTip("No DBC linked: File → Load DBC...")

    def _forget_xmetro(self, window_id):
        """A closed XMetro window leaves the list, so RX stops feeding it (TODO 7.5)."""
        self.xmetro_windows[:] = [w for w in self.xmetro_windows if id(w) != window_id]

    def _forget_plot(self, window_id):
        """A closed Signal Plot window leaves the list (as for XMetro, TODO 7.5)."""
        self.signal_plot_windows[:] = [
            w for w in self.signal_plot_windows if id(w) != window_id
        ]
        self._update_plot_keys()

    def closeEvent(self, event):
        """Release TX, the PCAN channel, the log file and XMetro windows (TODO 1.9)."""
        if not self._confirm_discard():  # offer to save unsaved changes (TODO 6.8)
            event.ignore()
            return
        self.stop_replay()
        if self.tx_running:
            self.stop_tx()
        if self.can_if is not None:
            self.can_if.close()  # joins the RX thread, then shuts the bus down
            self.can_if = None
        if self.rx_window.log_open:
            self.rx_window.stop_log()
        for window in self.xmetro_windows + self.signal_plot_windows:
            if shiboken6.isValid(window):
                window.close()
        self.xmetro_windows.clear()
        self.signal_plot_windows.clear()
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

    def open_signal_plot_window(self):
        if self.dbc is None:
            QMessageBox.warning(self, "DBC", "Load a DBC file first!")
            return
        if not any(m.signals for m in self.dbc.messages):
            QMessageBox.warning(
                self, "Signal Plot", "No messages with signals in DBC file."
            )
            return
        try:
            plot = SignalPlotWindow(self.dbc)
            plot.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            plot.destroyed.connect(lambda _=None, wid=id(plot): self._forget_plot(wid))
            plot.keys_changed.connect(self._update_plot_keys)
            self.signal_plot_windows.append(plot)
            plot.show()
        except Exception as e:
            QMessageBox.critical(self, "Signal Plot", f"Cannot open Signal Plot: {e}")
            log_exception(e)

    def timer_busload_elapsed(self):
        """Busload over the time since the last update, at the channel's own rates.

        The rates come from the open channel, not from the combo box, which
        can be changed after connecting (TODO 9.8).
        """
        nominal_bits, data_bits = self.rx_window.take_busload_bits()
        rx, tx = self.rx_window.take_frame_counts()
        now = time.monotonic()
        elapsed, self._busload_since = now - self._busload_since, now
        timing = getattr(self.can_if, "timing", None)
        if timing is None or elapsed <= 0:
            self.lbl_busload.setText("BusLoad: -")
            self.lbl_busload.setToolTip(BUSLOAD_TOOLTIP)
            return
        if isinstance(timing, can.BitTimingFd):
            busy_s = nominal_bits / timing.nom_bitrate + data_bits / timing.data_bitrate
        else:
            busy_s = (nominal_bits + data_bits) / timing.bitrate
        fps = round((rx + tx) / elapsed)
        self.lbl_busload.setText(
            f"BusLoad: {100 * busy_s / elapsed:3.1f}% [{fps} fr/s]"
        )
        self.lbl_busload.setToolTip(
            f"{BUSLOAD_TOOLTIP}\nFrames on the wire since the last update: "
            f"{rx} received, {tx} transmitted (own echoes), over {elapsed:.1f} s."
        )

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

"""TX side of the main window: the TX table and its buttons, the payload
scripts and the glue to the TX thread (TODO 9.7).

TxPanelMixin is mixed into MainWindow; it has no __init__ of its own:
MainWindow calls _build_tx_panel() while it lays the window out.
"""

from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QGroupBox,
    QSpinBox,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QStyle,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QTableView,
    QAbstractItemView,
    QHeaderView,
)
from PySide6.QtCore import Qt, QTimer, QSortFilterProxyModel
import importlib.util
import glob
import logging
import os
import shutil

from src.dbc_loader import (
    load_dbc,
    encode_signal,
)
from src.exceptions_logger import log_exception
from src.utils import format_can_id, resource_path
from src.tx_scheduler import TxScheduler
from src.tx_model import (
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
    valid_dlc,
)


# The TX engine repaints the rows it changed this often (TODO 2.12)
TX_REFRESH_MS = 100


def templates_dir() -> str:
    """The bundled payload-script templates (shipped in the exe, TODO 3.11)."""
    return resource_path("resources/script_templates")


def list_templates() -> list[tuple[str, str]]:
    """[(name, absolute path)] of the bundled templates, sorted by name."""
    found = glob.glob(os.path.join(templates_dir(), "*.py"))
    return sorted((os.path.basename(p), p) for p in found)


def copy_template(src: str, dest: str) -> str:
    """Copy a template to `dest` (adding .py if missing); returns the path."""
    if not dest.lower().endswith(".py"):
        dest += ".py"
    shutil.copyfile(src, dest)
    return dest


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


class TxPanelMixin:
    def _build_tx_panel(self):
        """TX state, buttons and table; returns the TX group box."""
        # One TX thread with absolute deadlines (TODO 2.11); it calls _send_row
        self.tx_scheduler = TxScheduler(self._send_row)
        self.tx_skipped_fd = []
        # (frame_id, is_ext, error) already logged in this run: once each (TODO 3.3)
        self._tx_errors_logged = set()
        self.tx_running = False
        self.global_script_path = None
        self.global_script_cache = {}
        # (frame_id, script_path) -> get_payload of that ID's own script instance;
        # emptied at Start TX only, so internal TX restarts keep script state
        self.script_instances = {}
        # script path -> mtime at load: a changed file is hot-reloaded (TODO 3.10)
        self._script_mtimes = {}

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

        # Button to link a global Payload Script
        self.btn_link_global_script = QPushButton("Link Global Script")
        self.btn_link_global_script.setToolTip(
            "Link a global Payload Script to be used for ALL transmitted CAN frames."
        )
        self.btn_link_global_script.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.btn_link_global_script.setFixedSize(200, 30)
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
        self.tx_refresh_timer.timeout.connect(self._tx_refresh)
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
        return tx_group

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

            # Clear the table
            self.tx_model.clear()

            # Disable the buttons that need rows
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def load_dbc_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open DBC file", "", "DBC Files (*.dbc)"
        )
        if filename:
            self.dbc = load_dbc(filename)
            self.populate_signal_tree()
            self._sync_tx()
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

        skipped = self._sync_tx()  # starts the new row if TX is running
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
        # Stop this row only: another row may share the ID number
        self.tx_scheduler.remove(entry)
        self.tx_model.remove(entry)

        if self.tx_model.rowCount() == 0:
            self.btn_disable_all_ids.setEnabled(False)
            self.btn_delete_all_ids.setEnabled(False)

    def _set_all_enabled(self, enabled):
        """Enable/Disable All: one timer sync, not one TX restart per row."""
        self.tx_model.set_all_enabled(enabled)
        self._sync_tx()
        for entry in self._tx_entries():
            self._update_slider_enabled(entry)

    def _on_enabled_changed(self, entry):
        """The user ticked/unticked En: start/stop this row only (TODO 2.6)."""
        self._sync_tx()
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

    def new_script_from_template(self):
        """Copy a bundled template to a file the user picks (TODO 3.11).

        The new file is linked to a TX row afterwards with the row's Link
        button, like any other script.
        """
        templates = list_templates()
        if not templates:
            QMessageBox.warning(
                self, "Templates", "No payload-script templates are bundled."
            )
            return
        by_name = dict(templates)
        name, ok = QInputDialog.getItem(
            self,
            "New script from template",
            "Template (per-ID TPS_*, global GLO_TPS_*):",
            list(by_name),
            0,
            False,
        )
        if not ok or not name:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save script as", name, "Python scripts (*.py)"
        )
        if not dest:
            return
        try:
            path = copy_template(by_name[name], dest)
        except OSError as e:
            QMessageBox.critical(
                self, "New script", f"Could not create the script:\n{e}"
            )
            return
        QMessageBox.information(
            self,
            "New script",
            f"Template '{name}' copied to:\n{path}\n\n"
            "Link it to a TX row with the Link button in the "
            "'Script for Specific ID' column, or as the global script.",
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
            self._script_mtimes.clear()
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

    def start_tx(self):
        """Start the TX thread with one job per enabled row; returns the skipped FD rows."""
        self.tx_scheduler.stop()
        self.tx_running = True
        self.tx_scheduler.start()
        self.tx_skipped_fd = self._sync_tx()
        self.btn_start_tx.setText("Stop TX")
        self.btn_start_tx.setToolTip(
            "Stop the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogNoButton)
        )
        return self.tx_skipped_fd

    def _sync_tx(self):
        """Make the scheduled rows match the table (TODO 2.6).

        Only rows whose state changed are touched: every other row keeps its
        phase and its script instance. Returns the enabled CAN FD rows
        skipped because the channel is classic CAN.
        """
        if not self.tx_running:
            return []
        entries = {id(e): e for e in self._tx_entries()}
        for entry in self.tx_scheduler.entries():
            if id(entry) not in entries or not entry.enabled:
                self.tx_scheduler.remove(entry)

        # A classic-CAN channel rejects every FD frame: skip those rows
        bus_is_fd = bool(getattr(self.can_if, "is_fd", False))
        skipped = []
        # Ascending ID order, so equal periods fire lowest ID first
        for entry in sorted(entries.values(), key=lambda e: (e.is_ext, e.frame_id)):
            if not entry.enabled or self.tx_scheduler.job(entry) is not None:
                continue
            if entry.is_fd and not bus_is_fd:
                skipped.append(f"{entry.id_text} {entry.name}")
                continue
            self.tx_scheduler.add(entry)
        return skipped

    def _on_period_changed(self, entry):
        """Period edit: retime this row only (TODO 2.7)."""
        self.tx_scheduler.retime(entry)

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
                self._remember_script_mtime(script_path)
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
                self._remember_script_mtime(self.global_script_path)
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
        """TX thread: one frame of a row — script > global script > manual payload,
        then the sliders' snapshot. No Qt object is touched here.

        Script link and sliders are read at every tick, so linking a script or
        adding/removing a slider takes effect without restarting TX. The frame
        flags of an entry never change after it is created.
        """
        frame_id, is_ext, dlc = entry.frame_id, entry.is_ext, entry.dlc
        try:
            payload = self._script_payload(entry)
            if payload is None:  # 3. Manual payload
                payload = entry.payload
            for signal, value in self._slider_overrides.get(entry.key, ()):
                payload = encode_signal(payload, signal, value)
            final_payload = bytes(payload[:dlc]) + bytes(max(0, dlc - len(payload)))
        except Exception as e:
            self._row_failed(entry, e)
            return

        # The row shows it (and XMetro gets it) at the next refresh (TODO 2.12)
        self.send_can_message(frame_id, final_payload, dlc, entry.is_fd, is_ext)
        self.tx_model.set_error(entry, None)
        self.tx_model.set_payload(entry, final_payload)

    def _remember_script_mtime(self, path):
        try:
            self._script_mtimes[path] = os.path.getmtime(path)
        except OSError:
            self._script_mtimes.pop(path, None)

    def _check_script_reloads(self):
        """Drop the cached instance of any linked script whose file changed, so
        the next tick reloads it: editing a script takes effect without a
        restart (TODO 3.10). Run in the GUI thread, not the TX hot path, so no
        per-frame stat(); the reload itself then happens once, on next access."""
        for path, old in list(self._script_mtimes.items()):
            try:
                now = os.path.getmtime(path)
            except OSError:
                continue  # missing file is handled as a send error per tick
            if now == old:
                continue
            self._script_mtimes[path] = now
            is_global = path == self.global_script_path
            self.global_script_cache.pop(path, None)
            for key in [k for k in self.script_instances if k[2] == path]:
                del self.script_instances[key]
            # Rows driven by this file: a per-ID link to it, or any row when it
            # is the global script. Re-arm their error logging so a fix that
            # still fails with the same message is reported once more.
            affected = {
                e.key
                for e in self._tx_entries()
                if e.script_path == path or (is_global and not e.script_path)
            }
            self._tx_errors_logged = {
                e for e in self._tx_errors_logged if (e[0], e[1]) not in affected
            }

    def _tx_refresh(self):
        """GUI thread, ~10 Hz: repaint the rows sent since the last refresh and
        feed their payloads to the XMetro gauges (TODO 7.2)."""
        if self._script_mtimes:
            self._check_script_reloads()
        sent = self.tx_model.flush()
        if self.xmetro_windows:
            for entry in sent:
                if entry.error is None:
                    self._feed_gauges(entry.frame_id, entry.is_ext, entry.payload)

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
        self.tx_scheduler.stop()  # returns once no frame is being produced
        self.tx_running = False
        self._tx_refresh()
        self.btn_start_tx.setText("Start TX")
        self.btn_start_tx.setToolTip(
            "Start the transmission of enabled CAN frames from the TX table."
        )
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        )

    def send_can_message(self, frame_id, data, dlc=None, is_fd=False, is_ext=False):
        can_if = self.can_if  # TX thread: read once
        if not can_if:
            return
        try:
            if dlc is None:
                dlc = len(data) if data else 0
            dlc = max(0, min(int(dlc), 64))
            # Not counted for the busload here: the adapter's echo is (TODO 9.8)
            can_if.send_frame(frame_id, data, dlc, is_fd, is_ext=is_ext)
        except Exception as e:
            log_exception(e)

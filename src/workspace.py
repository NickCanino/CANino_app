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

"""Workspace files: load and save the TX table, sliders, scripts and DBC (TODO 9.7)."""

from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QStyle,
)
import json
import os

from src.dbc_loader import (
    load_dbc,
)
from src.exceptions_logger import log_exception, __version__
from src.tx_model import (
    CAN_MAX_STD_ID,
    CAN_MAX_EXT_ID,
)


def json_flag(value) -> bool:
    """Workspace flags are saved as "Y"/"n"; older files may hold null or bools."""
    if isinstance(value, str):
        return value.strip().upper() in ("Y", "YES", "TRUE", "1")
    return bool(value)


class WorkspaceMixin:
    CONFIG_FILE = "resources/workspace_config_files/default_config_file.json"

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

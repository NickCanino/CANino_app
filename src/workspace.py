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

"""Workspace files: load and save the TX table, sliders, scripts and DBC.

Every file CANino writes carries "format" and "version" (TODO 6.7). A file
without them is version 1: anything written up to 1.5. migrate() turns any
known version into the current one, reports what it changed, and refuses
files written by a newer CANino; loading never works on unmigrated data.

Version 2 (1.6): flags are JSON booleans, paths use "/", sliders store their
physical value only. Version 1 files may hold "Y"/"n"/null flags, no "ext"
(IDs above 0x7FF were extended), no "fd", backslashes in paths, and sliders
with only an index into a recomputed range (value_index).

Version 3 (1.7): each signal gains "rtr" (remote frame). Missing in v1/v2 files
means a normal data frame.
"""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QStyle,
)
from PySide6.QtCore import QSettings
import json
import os

from src.dbc_loader import load_dbc
from src.exceptions_logger import log_exception, __version__
from src.tx_model import CAN_MAX_STD_ID, CAN_MAX_EXT_ID

RECENT_MAX = 8
WORKSPACE_FORMAT = "canino-workspace"
WORKSPACE_VERSION = 3
# Templates renamed in c971828 (2025-08-01): a workspace that links the old
# name finds the new file in the same folder
TEMPLATE_RENAMES = {
    "template_payload_script_blink.py": "TPS_blink.py",
    "template_payload_script_sawtooth.py": "TPS_sawtooth.py",
}


class WorkspaceError(ValueError):
    """The file is not a workspace this CANino can read."""


def json_flag(value) -> bool:
    """Version 1 flags: "Y"/"n", null, or (rarely) booleans."""
    if isinstance(value, str):
        return value.strip().upper() in ("Y", "YES", "TRUE", "1")
    return bool(value)


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def migrate(config):
    """Any known workspace layout -> the current version; returns (config, notes).

    `notes` lists, in plain words, what was converted or dropped. Raises
    WorkspaceError for non-workspaces and files from a newer CANino.
    """
    if not isinstance(config, dict):
        raise WorkspaceError("not a CANino workspace (no JSON object)")
    fmt = config.get("format", WORKSPACE_FORMAT)
    if fmt != WORKSPACE_FORMAT:
        raise WorkspaceError(f"not a CANino workspace (format {fmt!r})")
    version = config.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise WorkspaceError(f"unknown workspace version {version!r}")
    if version > WORKSPACE_VERSION:
        raise WorkspaceError(
            f"written by a newer CANino (workspace version {version}; this "
            f"version reads up to {WORKSPACE_VERSION}) - update CANino"
        )
    signals = config.get("signals")
    sliders = config.get("sliders")
    signals = [] if signals is None else signals
    sliders = [] if sliders is None else sliders
    if not isinstance(signals, list) or not isinstance(sliders, list):
        raise WorkspaceError("'signals' and 'sliders' must be lists")

    notes = []
    counts = {"ext": 0, "fd": 0, "paths": 0, "slider_values": 0}

    def path(p):
        if not p:
            return None
        if not isinstance(p, str):
            raise WorkspaceError(f"path {p!r} is not a string")
        if "\\" in p:
            counts["paths"] += 1
            p = p.replace("\\", "/")
        return p

    out = {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "dbc_file": path(config.get("dbc_file")),
        "global_script": path(config.get("global_script")),
        "signals": [],
        "sliders": [],
    }

    seen = set()
    skipped = []
    for n, sig in enumerate(signals, 1):
        if not isinstance(sig, dict):
            skipped.append(f"row {n}: not an object")
            continue
        raw_id = sig.get("id")
        try:
            frame_id = raw_id if isinstance(raw_id, int) else int(str(raw_id), 16)
        except ValueError:
            skipped.append(f"row {n}: ID {raw_id!r} is not hexadecimal")
            continue
        if "ext" in sig and sig["ext"] is not None:
            is_ext = json_flag(sig["ext"])
        else:  # before 1.5 IDs above 0x7FF could only be extended (TODO 1.6)
            is_ext = frame_id > CAN_MAX_STD_ID
            counts["ext"] += version == 1
        if not 0 <= frame_id <= (CAN_MAX_EXT_ID if is_ext else CAN_MAX_STD_ID):
            skipped.append(f"row {n}: ID 0x{frame_id:X} out of range")
            continue
        if (frame_id, is_ext) in seen:
            skipped.append(f"row {n}: ID 0x{frame_id:X} appears twice")
            continue
        seen.add((frame_id, is_ext))
        if sig.get("fd") is None:  # missing, or null (1.2.x)
            counts["fd"] += version == 1
        out["signals"].append(
            {
                "enabled": json_flag(sig.get("enabled")),
                "id": f"0x{frame_id:08X}" if is_ext else f"0x{frame_id:03X}",
                "ext": is_ext,
                "fd": json_flag(sig.get("fd")),
                "name": str(sig.get("name") or ""),
                "period": _int(sig.get("period"), 100),
                "payload": str(sig.get("payload") or ""),
                "dlc": _int(sig.get("dlc"), 8),
                "script_path": path(sig.get("script_path")),
                # v3 (1.7): remote frame. Missing in v1/v2 -> a normal data frame.
                "rtr": json_flag(sig.get("rtr")) and not json_flag(sig.get("fd")),
            }
        )

    for n, meta in enumerate(sliders, 1):
        if not isinstance(meta, dict) or not meta.get("signal_name"):
            skipped.append(f"slider {n}: no signal name")
            continue
        value = meta.get("value")
        if value is None:  # before 1.5: an index into the old range
            value = meta.get("min_val", 0) + meta.get("value_index", 0) * meta.get(
                "step", 1
            )
            counts["slider_values"] += 1
        slider = {
            # Before 1.5 "msg_name" held the signal name (TODO 4.8); the
            # loader falls back to the frame ID when no message matches
            "msg_name": meta.get("msg_name"),
            "signal_name": meta["signal_name"],
            "frame_id": meta.get("frame_id"),
            "value": value,
        }
        if meta.get("is_ext") is not None:
            slider["is_ext"] = bool(meta["is_ext"])
        out["sliders"].append(slider)

    if version < WORKSPACE_VERSION:
        notes.append(
            f"Converted from workspace version {version} to {WORKSPACE_VERSION}; "
            "Save writes the new format."
        )
    if counts["ext"]:
        notes.append(
            f"{counts['ext']} row(s) had no ID format: IDs above 0x7FF taken as "
            "extended, the others as standard."
        )
    if counts["fd"]:
        notes.append(f"{counts['fd']} row(s) had no CAN FD flag: taken as classic CAN.")
    if counts["paths"]:
        notes.append(f"{counts['paths']} path(s) converted from '\\' to '/'.")
    if counts["slider_values"]:
        notes.append(
            f"{counts['slider_values']} slider value(s) recomputed from the saved position."
        )
    if skipped:
        notes.append("Skipped: " + "; ".join(skipped) + ".")
    return out, notes


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
        self._update_title()

    def _update_title(self):
        path = self.workspace_path
        name = f" - {os.path.basename(path)}" if path else ""
        star = " *" if getattr(self, "_dirty", False) else ""
        self.setWindowTitle(f"CANino App - v{__version__}{name}{star}")

    def _mark_dirty(self, *_):
        """A user change since the last Load/Save (TODO 6.8). Ignored while a
        workspace is being loaded (those changes are the file, not the user's)."""
        if getattr(self, "_loading", False) or self._dirty:
            return
        self._dirty = True
        self._update_title()

    def _mark_clean(self):
        self._dirty = False
        self._update_title()

    def _confirm_discard(self) -> bool:
        """Ask before dropping unsaved changes; True to proceed, False to cancel."""
        if not self._dirty:
            return True
        choice = QMessageBox.question(
            self,
            "Unsaved changes",
            "The workspace has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.save_config()
            return not self._dirty  # a cancelled Save As leaves it dirty
        return True  # Discard

    # --- recent workspaces (TODO 6.8) ---

    @staticmethod
    def _recent_files():
        value = QSettings("CANinoApp", "CANinoApp").value("recent_files", [])
        if isinstance(value, str):  # a single entry comes back as a bare string
            value = [value]
        return [p for p in (value or []) if p]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        files = [p for p in self._recent_files() if p != path]
        files.insert(0, path)
        QSettings("CANinoApp", "CANinoApp").setValue("recent_files", files[:RECENT_MAX])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        menu = getattr(self, "menu_recent", None)
        if menu is None:
            return
        menu.clear()
        files = self._recent_files()
        menu.setEnabled(bool(files))
        for path in files:
            action = QAction(path, self)
            action.triggered.connect(lambda _=False, p=path: self.load_config(path=p))
            menu.addAction(action)

    def _save_config_to_file(self, filename):
        base = os.path.dirname(os.path.abspath(filename))
        config = {
            "format": WORKSPACE_FORMAT,
            "version": WORKSPACE_VERSION,
            "app_version": __version__,  # informative only
            "dbc_file": self._to_workspace_path(
                self.dbc.dbc_filename if self.dbc is not None else None, base
            ),
            "global_script": self._to_workspace_path(self.global_script_path, base),
            "signals": [
                {
                    "enabled": entry.enabled,
                    "id": entry.id_text,
                    "ext": entry.is_ext,
                    "fd": entry.is_fd,
                    "name": entry.name,
                    "period": entry.period,
                    "payload": " ".join(f"{b:02X}" for b in entry.payload),
                    "dlc": entry.dlc,
                    "script_path": self._to_workspace_path(entry.script_path, base),
                    "rtr": entry.is_rtr,
                }
                for entry in self._tx_entries()
            ],
            "sliders": [
                {
                    "msg_name": widget.msg_name,
                    "signal_name": widget.signal.name,
                    "frame_id": widget.frame_id,
                    "is_ext": widget.is_ext,
                    "value": widget.value(),
                    "unit": widget.unit,  # informative only
                }
                for widget in self.slider_widgets
            ],
        }
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving configuration: {e}")
            log_exception(e)
            return False
        self._set_workspace_path(filename)
        self._mark_clean()
        self._add_recent(filename)
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
        self._apply_dbc(None)
        self.btn_disable_all_ids.setText("Mute All")
        self.btn_disable_all_ids.setToolTip("Disable all CAN IDs in the TX list.")
        self.btn_disable_all_ids.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        )

    def _script_from_workspace(self, path, base_dir):
        """Script path of a workspace; a renamed template is found by its new name,
        through the same lookup (next to the JSON file, then the CWD)."""
        resolved = self._from_workspace_path(path, base_dir)
        if resolved and not os.path.exists(resolved):
            new_name = TEMPLATE_RENAMES.get(os.path.basename(path))
            if new_name:
                renamed = self._from_workspace_path(
                    os.path.join(os.path.dirname(path), new_name), base_dir
                )
                if os.path.exists(renamed):
                    return renamed
        return resolved

    def load_config(self, auto=False, path=None):
        """Replace the workspace with a JSON file (TODO 6.4); the table stays editable.

        `path` loads a specific file (a Recent entry); `auto` loads the default
        file at start-up without prompting.
        """
        if auto:  # Load the default workspace file
            filename = self.CONFIG_FILE
            if not os.path.exists(filename):
                return
        else:
            if path:  # a Recent-workspaces entry
                filename = path
            else:  # Ask for the file
                filename, _ = QFileDialog.getOpenFileName(
                    self, "Load configuration", "", "File JSON (*.json)"
                )
                if not filename:
                    return
            if not self._confirm_discard():  # offer to keep unsaved changes
                return

        # Parse and migrate first: a broken or too new file must not wipe the
        # current workspace (TODO 6.7)
        try:
            with open(filename, "r", encoding="utf-8") as f:
                config, notes = migrate(json.load(f))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {e}")
            log_exception(e)
            return

        try:
            was_running = self.tx_running
            self._loading = True  # user changes during the rebuild are the file's
            self._clear_workspace()
            self._set_workspace_path(filename)
            base = os.path.dirname(os.path.abspath(filename))

            # Loads DBC if existing
            dbc_path = self._from_workspace_path(config["dbc_file"], base)
            if dbc_path is not None:
                if os.path.exists(dbc_path):
                    self._apply_dbc(
                        load_dbc(dbc_path)
                    )  # RX names (TODO 6.1), XMetro (7.8)
                else:
                    QMessageBox.warning(
                        self, "DBC", f"Cannot find DBC file:\n{dbc_path}"
                    )

            # Restores global script (a missing file is reported at Start TX)
            self._set_global_script(
                self._script_from_workspace(config["global_script"], base)
            )

            for sig in config["signals"]:
                self._add_tx_row(
                    int(sig["id"], 16),
                    sig["name"],
                    period=sig["period"],
                    dlc=sig["dlc"],
                    is_fd=sig["fd"],
                    is_ext=sig["ext"],
                    payload=sig["payload"],
                    script_path=self._script_from_workspace(sig["script_path"], base),
                    enabled=sig["enabled"],
                    is_rtr=sig["rtr"],
                )

            # Load sliders
            sliders_cfg = config["sliders"]
            if sliders_cfg and self.dbc is None:
                QMessageBox.warning(
                    self,
                    "Sliders",
                    f"{len(sliders_cfg)} slider(s) skipped: they need the workspace DBC, which is not loaded.",
                )
                sliders_cfg = []
            missing = []
            for meta in sliders_cfg:
                msg = self._find_slider_message(meta)
                sig = next(
                    (
                        s
                        for s in getattr(msg, "signals", [])
                        if s.name == meta["signal_name"]
                    ),
                    None,
                )
                if sig is None:
                    missing.append(meta["signal_name"])
                    continue
                self._add_slider_widget(msg, sig, meta["value"])
            if missing:
                notes.append(
                    "Slider(s) for signals not in the DBC skipped: "
                    + ", ".join(missing)
                    + "."
                )

            # Row-dependent buttons follow the table, sliders or not (TODO 6.2)
            has_rows = self.tx_model.rowCount() > 0
            self.btn_disable_all_ids.setEnabled(has_rows)
            self.btn_delete_all_ids.setEnabled(has_rows)

            dropped = [n for n in notes if "kipped" in n]
            if not auto:
                stopped = "\n\nTransmission was stopped." if was_running else ""
                details = "".join(f"\n\n{n}" for n in notes)
                QMessageBox.information(
                    self,
                    "Configuration",
                    f"Configuration loaded successfully.{stopped}{details}",
                )
            elif dropped:  # at start-up only what was lost is worth a dialog
                QMessageBox.warning(self, "Configuration", "\n\n".join(dropped))
            if not auto:
                self._add_recent(filename)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {e}")
            log_exception(e)
        finally:
            self._loading = False
            self._mark_clean()  # a freshly loaded workspace matches its file

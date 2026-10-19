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
    QDialog,
    QGridLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QGroupBox,
    QProgressDialog,
)
from PySide6.QtGui import QPixmap, QImage, QIcon
from PySide6.QtCore import Qt, QThread, Signal, QObject
import hashlib
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from src.exceptions_logger import log_exception
from src.utils import resource_path


# Absolute and normalised: CreateProcess rejects "tools/arduino-cli.exe"
ARDUINO_CLI = os.path.normpath(resource_path("tools/arduino-cli.exe"))
INO_IMG_PATH = resource_path("resources/figures/arduino_uno.png")
APP_LOGO_PATH = resource_path("resources/figures/app_logo.ico")
FQBN = "arduino:avr:uno"
CORE = "arduino:avr"
# The windowed exe opened a console window for every arduino-cli call (TODO 8.7)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NUM_NODES = 8

NUM_TO_LETTER = ["A", "B", "C", "D", "E", "F", "G", "H"]


def build_dir() -> Path:
    """Sketch cache in the user's local app data, not in the CWD (TODO 8.8).

    ./arduino_build sat inside the OneDrive repo, whose sync locked it
    (PermissionError in the field logs).
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "CANinoApp" / "arduino_build"


def get_params_hash(params: dict) -> str:
    s = "_".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(s.encode()).hexdigest()


def prepare_project(params: dict) -> Path:
    h = get_params_hash(params)
    target_dir = build_dir() / h
    sketch_file = target_dir / f"{h}.ino"

    if sketch_file.exists():
        return target_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    # Placeholder firmware (TODO 8.2 / 8.10)
    template = """
    int SPEED = {speed};
    const char* MODE = "{mode}";
    void setup() {{
        Serial.begin(9600);
    }}
    void loop() {{
        Serial.print("Speed: ");
        Serial.println(SPEED);
        delay(1000);
    }}
    """

    sketch_file.write_text(template.format(**params))
    return target_dir


def run_cli(args, timeout=60):
    """Run arduino-cli without a console window; returns CompletedProcess."""
    return subprocess.run(
        [ARDUINO_CLI, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=NO_WINDOW,
    )


def parse_board_list(text: str, show_unidentified: bool = False) -> list:
    """[(port, label)] from `board list --format json` (TODO 8.4).

    Only serial ports recognised as an Arduino Uno; serial ports with no
    recognised board (CH340 clones, but also Bluetooth COM ports) only when
    asked. The text output was parsed before - it is localised ("Porta",
    "Sconosciuto") and listed every serial port.
    """
    data = json.loads(text or "{}")
    # arduino-cli >= 1.0: {"detected_ports": [...]}; older versions: a bare list
    entries = data.get("detected_ports") or [] if isinstance(data, dict) else data
    ports = []
    for entry in entries:
        port = entry.get("port") or {}
        address = port.get("address")
        if not address or port.get("protocol") != "serial":
            continue
        boards = entry.get("matching_boards") or entry.get("boards") or []
        uno = next((b for b in boards if b.get("fqbn") == FQBN), None)
        if uno is not None:
            ports.append((address, f"{address} - {uno.get('name') or 'Arduino Uno'}"))
        elif not boards and show_unidentified:
            ports.append((address, f"{address} - unidentified"))
    return ports


def core_installed(text: str) -> bool:
    """True if `core list --format json` lists arduino:avr as installed (TODO 8.6)."""
    data = json.loads(text or "{}")
    platforms = data.get("platforms") or [] if isinstance(data, dict) else data
    return any(
        p.get("id") == CORE and (p.get("installed_version") or p.get("installed"))
        for p in platforms
    )


class PortScanWorker(QObject):
    """`board list` takes ~1.4 s: run it off the GUI thread (TODO 8.3)."""

    done = Signal(str, str)  # raw JSON, error text

    def run(self):
        try:
            res = run_cli(["board", "list", "--format", "json"], timeout=30)
            if res.returncode != 0:
                self.done.emit(
                    "", res.stderr.strip() or "arduino-cli board list failed"
                )
            else:
                self.done.emit(res.stdout, "")
        except Exception as e:
            log_exception(e)
            self.done.emit("", str(e))


class FlashWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, port, params):
        super().__init__()
        self.port = port
        self.params = params
        self._proc = None
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self):
        """Called from the GUI thread: kill the running arduino-cli (TODO 8.5)."""
        with self._lock:
            self.cancelled = True
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()

    def _run(self, args):
        """One arduino-cli step; None if cancelled, else (returncode, output)."""
        with self._lock:
            if self.cancelled:
                return None
            self._proc = subprocess.Popen(
                [ARDUINO_CLI, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=NO_WINDOW,
            )
        out, _ = self._proc.communicate()
        with self._lock:
            code, self._proc = self._proc.returncode, None
            if self.cancelled:
                return None
        return code, out

    def run(self):
        try:
            self.progress.emit(5, "Preparing the sketch...")
            proj = prepare_project(self.params)

            self.progress.emit(10, "Checking the Arduino AVR core...")
            step = self._run(["core", "list", "--format", "json"])
            if step is None:
                return self.finished.emit(False, "Flash cancelled.")
            if step[0] != 0 or not core_installed(step[1]):
                # Fresh PC: compile fails without the core (TODO 8.6)
                self.progress.emit(
                    15, "Installing the Arduino AVR core (needs internet)..."
                )
                for args in (["core", "update-index"], ["core", "install", CORE]):
                    step = self._run(args)
                    if step is None:
                        return self.finished.emit(False, "Flash cancelled.")
                    if step[0] != 0:
                        return self.finished.emit(
                            False, f"Installing {CORE} failed:\n{step[1]}"
                        )

            self.progress.emit(30, "Compiling...")
            step = self._run(["compile", "--fqbn", FQBN, str(proj)])
            if step is None:
                return self.finished.emit(False, "Flash cancelled.")
            if step[0] != 0:
                return self.finished.emit(False, f"Compilation failed:\n{step[1]}")

            self.progress.emit(70, f"Uploading to {self.port}...")
            step = self._run(["upload", "-p", self.port, "--fqbn", FQBN, str(proj)])
            if step is None:
                return self.finished.emit(False, "Flash cancelled.")
            if step[0] != 0:
                return self.finished.emit(False, f"Upload failed:\n{step[1]}")

            self.progress.emit(100, "Done")
            self.finished.emit(True, f"Flashed {self.port}.")

        except Exception as e:
            log_exception(e)
            self.finished.emit(False, str(e))


class VagilettaWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VAGILETTA")
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)
        self.setMinimumSize(900, 400)
        self.setWindowIcon(QIcon(APP_LOGO_PATH))

        self.pixmap_scaled = QPixmap(INO_IMG_PATH).scaled(
            100,
            100,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.pixmap_greyed = self._get_pixmap_greyed(self.pixmap_scaled)

        top = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Scan the serial ports for Arduino Uno boards.")
        self.refresh_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_btn.setFixedSize(80, 30)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.cb_unidentified = QCheckBox("Show unidentified serial ports")
        self.cb_unidentified.setToolTip(
            "Also list serial ports arduino-cli cannot identify, e.g. Uno clones\n"
            "with a CH340 chip - and Bluetooth or other COM ports."
        )
        self.cb_unidentified.toggled.connect(self._apply_scan)
        self.lbl_status = QLabel()
        top.addWidget(self.refresh_btn)
        top.addWidget(self.cb_unidentified)
        top.addWidget(self.lbl_status, 1)
        main_layout.addLayout(top)
        grid = QGridLayout()
        main_layout.addLayout(grid)

        self.combos = []
        self.arduino_imgs = []
        self.flash_buttons = []
        self.ports = []  # [(port, label)] from the last scan
        self._scan_json = ""
        self.progress_dialog = None
        # Not self.thread: that shadowed QObject.thread() (TODO 8.7)
        self.scan_thread = self.scan_worker = None
        self.flash_thread = self.flash_worker = None

        for i in range(2):
            for j in range(4):
                index = i * 4 + j
                group = QGroupBox(f"Node {index + 1}")
                group.setStyleSheet(
                    "QGroupBox { border: 2px solid #2196F3; border-radius: 8px; margin-top: 8px; }"
                )
                vbox = QVBoxLayout(group)

                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setPixmap(self.pixmap_greyed)
                img_label.setToolTip("Grey: no port selected for this node.")
                vbox.addWidget(img_label)
                self.arduino_imgs.append(img_label)

                combo = QComboBox()
                combo.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                combo.setToolTip(
                    f"Serial port of node {index + 1}; a port can serve one node only."
                )
                # Only re-filters the cached scan: no arduino-cli call (TODO 8.3)
                combo.currentIndexChanged.connect(self._update_combos)
                vbox.addWidget(combo)
                self.combos.append(combo)

                flash_btn = QPushButton("Flash")
                flash_btn.setToolTip(
                    f"Compile and upload node {index + 1}'s sketch to its port."
                )
                flash_btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                params = {
                    "speed": 100 + index * 10,
                    "mode": "fast" if index % 2 == 0 else "slow",
                }
                flash_btn.clicked.connect(
                    lambda _=False, c=combo, p=params: self._handle_flash(c, p)
                )
                vbox.addWidget(flash_btn)
                self.flash_buttons.append(flash_btn)

                grid.addWidget(group, i, j)

        self._update_combos()
        self.refresh_ports()

    def _get_pixmap_greyed(self, scaled_pixmap):
        img = scaled_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(img)

    # --- port scan -------------------------------------------------------------
    def refresh_ports(self):
        """Start an asynchronous `board list`; the dialog stays responsive."""
        if self.scan_thread is not None:
            return
        self.refresh_btn.setEnabled(False)
        self.lbl_status.setText("Scanning serial ports...")
        self.scan_thread = QThread(self)
        self.scan_worker = PortScanWorker()
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.done.connect(self._on_scan_done)
        self.scan_worker.done.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self._scan_finished)
        self.scan_thread.start()

    def _scan_finished(self):
        self.scan_thread.deleteLater()
        self.scan_worker.deleteLater()
        self.scan_thread = self.scan_worker = None
        self.refresh_btn.setEnabled(self.flash_thread is None)

    def _on_scan_done(self, raw_json, error):
        if error:
            self._scan_json = ""
            self.lbl_status.setText(f"Port scan failed: {error.splitlines()[0]}")
        else:
            self._scan_json = raw_json
        self._apply_scan(report=not error)

    def _apply_scan(self, *_, report=True):
        try:
            self.ports = parse_board_list(
                self._scan_json, self.cb_unidentified.isChecked()
            )
        except ValueError as e:
            self.ports = []
            self.lbl_status.setText(f"Unreadable arduino-cli output: {e}")
            report = False
        if report:
            self.lbl_status.setText(
                f"{len(self.ports)} port(s) found."
                if self.ports
                else "No Arduino Uno found."
            )
        self._update_combos()

    def _update_combos(self, *_):
        """Each port can be picked by one node only."""
        labels = dict(self.ports)
        chosen = [c.currentData() for c in self.combos]
        for i, combo in enumerate(self.combos):
            current = combo.currentData()
            taken = {p for j, p in enumerate(chosen) if j != i and p}
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-", None)
            for port, label in self.ports:
                if port not in taken:
                    combo.addItem(label, port)
            if current in labels and current not in taken:
                combo.setCurrentIndex(combo.findData(current))
            combo.setEnabled(bool(self.ports) and self.flash_thread is None)
            combo.blockSignals(False)
            selected = combo.currentData() is not None
            self.arduino_imgs[i].setPixmap(
                self.pixmap_scaled if selected else self.pixmap_greyed
            )

    # --- flashing --------------------------------------------------------------
    def _handle_flash(self, combo, params):
        if self.flash_thread is not None:
            QMessageBox.warning(self, "VAGILETTA", "A flash is already running.")
            return
        port = combo.currentData()
        if not port:
            QMessageBox.warning(self, "VAGILETTA", "Select a port first.")
            return

        self.progress_dialog = QProgressDialog(
            "Flashing Arduino...", "Cancel", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("Flashing")
        self.progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)

        # One flash at a time: a second Flash overwrote the running QThread (TODO 8.5)
        self._set_busy(True)
        self.flash_thread = QThread(self)
        self.flash_worker = FlashWorker(port, params)
        self.flash_worker.moveToThread(self.flash_thread)
        self.flash_worker.progress.connect(self._on_flash_progress)
        self.flash_worker.finished.connect(self._on_flash_finished)
        self.flash_worker.finished.connect(self.flash_thread.quit)
        self.flash_thread.started.connect(self.flash_worker.run)
        self.flash_thread.finished.connect(self._flash_thread_finished)
        # Cancel kills arduino-cli; before, it only quit the event loop (TODO 8.5)
        # A lambda runs in the GUI thread at once; a queued call to the worker would
        # wait for its thread, which is blocked inside run()
        self.progress_dialog.canceled.connect(
            lambda: self.flash_worker is not None and self.flash_worker.cancel()
        )
        self.flash_thread.start()
        self.progress_dialog.show()

    def _set_busy(self, busy):
        for btn in self.flash_buttons:
            btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy and self.scan_thread is None)
        for combo in self.combos:
            combo.setEnabled(not busy and bool(self.ports))

    def _on_flash_progress(self, value, text):
        if self.progress_dialog is not None:
            self.progress_dialog.setLabelText(text)
            self.progress_dialog.setValue(value)

    def _on_flash_finished(self, success, message):
        if self.progress_dialog is not None:
            self.progress_dialog.hide()
        cancelled = self.flash_worker is not None and self.flash_worker.cancelled
        if success or cancelled:
            QMessageBox.information(self, "VAGILETTA", message)
        else:
            QMessageBox.critical(self, "VAGILETTA", message)

    def _flash_thread_finished(self):
        self.flash_thread.deleteLater()
        self.flash_worker.deleteLater()
        self.flash_thread = self.flash_worker = None
        self._set_busy(False)

    def done(self, result):
        """Closing while flashing kills arduino-cli and waits for the thread."""
        if self.flash_worker is not None:
            self.flash_worker.cancel()
        for thread in (self.flash_thread, self.scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait(5000)
        super().done(result)

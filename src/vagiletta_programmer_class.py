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

#TODO: add tooltips in VAGILETTA window

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QGroupBox,
    QProgressDialog,
)
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
import subprocess
import hashlib
import sys
from pathlib import Path
from src.exceptions_logger import log_exception
from src.utils import resource_path


ARDUINO_CLI = resource_path("tools/arduino-cli.exe")
BUILD_DIR = Path("./arduino_build")
INO_IMG_PATH = resource_path("resources/figures/arduino_uno.png")
APP_LOGO_PATH = resource_path("resources/figures/app_logo.ico")

NUM_TO_LETTER = ["A", "B", "C", "D", "E", "F", "G", "H"]


def get_params_hash(params: dict) -> str:
    s = "_".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(s.encode()).hexdigest()


def prepare_project(params: dict) -> Path:
    h = get_params_hash(params)
    target_dir = BUILD_DIR / h

    if target_dir.exists():
        return target_dir

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    sketch_dir = target_dir
    sketch_dir.mkdir(parents=True)
    sketch_file = sketch_dir / f"{h}.ino"

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

    code = template.format(**params)
    sketch_file.write_text(code)
    return target_dir


def list_arduino_ports():
    try:
        result = subprocess.run(
            [ARDUINO_CLI, "board", "list"], capture_output=True, text=True
        )
        ports = ["-"]  # di default solo "-"

        lines = result.stdout.splitlines()

        if lines and not lines[0].startswith("No boards found."):
            valid_ports = [
                line.split()[0]
                for line in lines
                if line and not line.startswith("Port")
            ]
            ports.extend(valid_ports)

        return ports
    except Exception as e:
        log_exception(__file__, sys._getframe().f_lineno, e)
        return ["-"]


class FlashWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, port, params):
        super().__init__()
        self.port = port
        self.params = params

    def run(self):
        try:
            self.progress.emit(10)
            proj = prepare_project(self.params)
            fqbn = "arduino:avr:uno"
            self.progress.emit(30)

            res_compile = subprocess.run(
                [ARDUINO_CLI, "compile", "--fqbn", fqbn, str(proj)],
                capture_output=True,
                text=True,
            )
            if res_compile.returncode != 0:
                self.finished.emit(
                    False, f"Compilazione fallita:\n{res_compile.stderr}"
                )
                return

            self.progress.emit(70)
            res_upload = subprocess.run(
                [ARDUINO_CLI, "upload", "-p", self.port, "--fqbn", fqbn, str(proj)],
                capture_output=True,
                text=True,
            )
            if res_upload.returncode != 0:
                self.finished.emit(False, f"Upload fallito:\n{res_upload.stderr}")
                return

            self.progress.emit(100)
            self.finished.emit(True, f"Flash su {self.port} completato!")

        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)
            self.finished.emit(False, str(e))


class VagilettaWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vagiletta")
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

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        refresh_btn.setFixedSize(80, 30)
        refresh_btn.clicked.connect(self.refresh_ports)

        main_layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        grid = QGridLayout()
        main_layout.addLayout(grid)

        self.combos = []
        self.arduino_imgs = []
        self.progress_dialog = None

        for i in range(2):
            for j in range(4):
                index = i * 4 + j
                group = QGroupBox(
                    f"Node {index + 1}"
                )  # group = QGroupBox(f"Node {NUM_TO_LETTER[index]}")
                group.setStyleSheet(
                    "QGroupBox { border: 2px solid #2196F3; border-radius: 8px; margin-top: 8px; }"
                )
                vbox = QVBoxLayout(group)

                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setPixmap(self.pixmap_greyed)
                vbox.addWidget(img_label)
                self.arduino_imgs.append(img_label)

                combo = QComboBox()
                combo.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                combo.currentIndexChanged.connect(self._make_combo_handler(index))
                vbox.addWidget(combo)
                self.combos.append(combo)

                flash_btn = QPushButton("Flash")
                flash_btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                params = {
                    "speed": 100 + index * 10,
                    "mode": "fast" if index % 2 == 0 else "slow",
                }
                flash_btn.clicked.connect(
                    lambda _, c=combo, p=params: self._handle_flash(c, p)
                )
                vbox.addWidget(flash_btn)

                grid.addWidget(group, i, j)

        self.refresh_ports()

    def _get_pixmap_greyed(self, scaled_pixmap):
        img = scaled_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(img)

    def refresh_ports(self):
        self.ports = list_arduino_ports()
        selected = [c.currentText() for c in self.combos if c.currentText() != "-"]

        for i, combo in enumerate(self.combos):
            current = combo.currentText()
            available_ports = [
                p for p in self.ports if p == "-" or p not in selected or p == current
            ]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(available_ports)
            combo.setEnabled(len(self.ports) > 1)

            if current in available_ports:
                combo.setCurrentText(current)

            combo.blockSignals(False)
            if combo.currentText() == "-" or not combo.currentText():
                self.arduino_imgs[i].setPixmap(self.pixmap_greyed)
            else:
                self.arduino_imgs[i].setPixmap(self.pixmap_scaled)

    def _make_combo_handler(self, idx):
        def handler(_):
            self.refresh_ports()

        return handler

    def _handle_flash(self, combo, params):
        port = combo.currentText()
        if not port or port == "-":
            QMessageBox.warning(self, "Errore", "Seleziona una porta!")
            return

        # Progress dialog
        self.progress_dialog = QProgressDialog(
            "Flashing Arduino...", "Annulla", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("Flash in corso")
        self.progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()

        # Threading
        self.thread = QThread()
        self.worker = FlashWorker(port, params)
        self.worker.moveToThread(self.thread)
        self.worker.progress.connect(self.progress_dialog.setValue)
        self.worker.finished.connect(self._on_flash_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.started.connect(self.worker.run)
        self.progress_dialog.canceled.connect(self.thread.quit)
        self.thread.start()

    def _on_flash_finished(self, success, message):
        self.progress_dialog.reset()
        if success:
            QMessageBox.information(self, "Successo", message)
        else:
            QMessageBox.critical(self, "Errore", message)

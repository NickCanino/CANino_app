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

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QMessageBox,
    QWidget,
    QSizePolicy,
    QStyle,
    QGroupBox,
)
from PyQt6.QtGui import QPixmap, QIcon, QImage
from PyQt6.QtCore import Qt
import subprocess
import hashlib
import shutil
import os
from pathlib import Path
from src.exceptions_logger import log_exception

ARDUINO_CLI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../tools/arduino-cli.exe")
)
BUILD_DIR = Path("./arduino_build")  # TODO: verificare che sia il percorso giusto
INO_IMG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../resources/figures/arduino_uno.png")
)


def get_params_hash(params: dict) -> str:
    s = "_".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(s.encode()).hexdigest()


def prepare_project(params: dict) -> Path:
    h = get_params_hash(params)
    target_dir = BUILD_DIR / h

    if target_dir.exists():
        return target_dir

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    sketch_dir = target_dir
    sketch_dir.mkdir(parents=True)
    sketch_file = sketch_dir / "MySketch.ino"

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

        ports = []
        lines = result.stdout.splitlines()

        # Filtra solo le righe che contengono porte valide
        valid_ports = [
            line.split()[0]
            for line in lines
            if line and not line.startswith("Port")
        ]

        # Se ci sono porte, aggiungile dopo '-'
        ports.append("-")
        ports.extend(valid_ports)

        return ports
    
    except Exception as e:
        log_exception(e)
        return []


class VagilettaWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vagiletta")
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)
        self.setMinimumSize(900, 400)

        # Scaled pixmap of Arduino Uno
        self.pixmap_scaled = QPixmap(INO_IMG_PATH).scaled(
            100, 100,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        # Greyed pixmap
        self.pixmap_greyed = self._get_pixmap_greyed(self.pixmap_scaled)

        # --- Pulsante di refresh sopra la matrice ---
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        refresh_btn.setFixedSize(80, 30)
        refresh_btn.clicked.connect(self.refresh_ports)
        main_layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # --- Matrice 2x4 di box ---
        grid = QGridLayout()
        main_layout.addLayout(grid)
        self.boxes = []
        self.combos = []
        self.arduino_imgs = []
        self.img_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__), "../resources/figures/arduino_uno.png"
            )
        )

        for i in range(2):
            for j in range(4):
                group = QGroupBox(f"Slot {i*4+j+1}")
                group.setStyleSheet(
                    "QGroupBox { border: 2px solid #2196F3; border-radius: 8px; margin-top: 8px; }"
                )
                vbox = QVBoxLayout(group)

                # Immagine Arduino
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setPixmap(self.pixmap_greyed)
                vbox.addWidget(img_label)
                self.arduino_imgs.append(img_label)

                # ComboBox porte
                combo = QComboBox()
                combo.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                combo.currentIndexChanged.connect(self._make_combo_handler(i * 4 + j))
                vbox.addWidget(combo)
                self.combos.append(combo)

                # Pulsante flash
                flash_btn = QPushButton("Flash")
                flash_btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                vbox.addWidget(flash_btn)

                params = {
                    "speed": 100 + (i * 4 + j) * 10,
                    "mode": "fast" if (i * 4 + j) % 2 == 0 else "slow",
                }

                def do_flash(combo=combo, params=params):
                    port = combo.currentText()
                    if not port or port == "-":
                        QMessageBox.warning(self, "Errore", "Seleziona una porta!")
                        return
                    
                    proj = prepare_project(params)
                    fqbn = "arduino:avr:uno"
                    try:
                        res_compile = subprocess.run(
                            [ARDUINO_CLI, "compile", "--fqbn", fqbn, str(proj)],
                            capture_output=True,
                            text=True,
                        )
                        if res_compile.returncode != 0:
                            QMessageBox.critical(
                                self,
                                "Errore",
                                f"Compilazione fallita:\n{res_compile.stderr}",
                            )
                            return
                        res_upload = subprocess.run(
                            [
                                ARDUINO_CLI,
                                "upload",
                                "-p",
                                port,
                                "--fqbn",
                                fqbn,
                                str(proj),
                            ],
                            capture_output=True,
                            text=True,
                        )
                        if res_upload.returncode != 0:
                            QMessageBox.critical(
                                self, "Errore", f"Upload fallito:\n{res_upload.stderr}"
                            )
                            return
                        QMessageBox.information(
                            self, "Successo", f"Flash su {port} completato!"
                        )
                    except Exception as e:
                        log_exception(e)
                        QMessageBox.critical(self, "Errore", str(e))

                flash_btn.clicked.connect(do_flash)
                grid.addWidget(group, i, j)
                self.boxes.append((combo, flash_btn, img_label))

        self.refresh_ports()

    def _get_pixmap_greyed(self, scaled_pixmap):
        img = scaled_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(img)

    def refresh_ports(self):
        self.ports = list_arduino_ports()

        # Raccogli le porte già selezionate (tranne '-')
        selected = [c.currentText() for c in self.combos if c.currentText() != "-"]

        for i, combo in enumerate(self.combos):
            current = combo.currentText()

            # Costruisci la lista delle porte disponibili per questa combo
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

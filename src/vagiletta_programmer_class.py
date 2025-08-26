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

import subprocess
import hashlib
import shutil
from pathlib import Path
from PyQt6.QtWidgets import QDialog, QGridLayout, QComboBox, QPushButton, QLabel, QVBoxLayout, QMessageBox, QWidget, QSizePolicy

ARDUINO_CLI = os.path.abspath(os.path.join(os.path.dirname(__file__), "../tools/arduino-cli.exe"))
BUILD_DIR = Path("./arduino_build")

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
        result = subprocess.run([ARDUINO_CLI, "board", "list"], capture_output=True, text=True)
        ports = []
        for line in result.stdout.splitlines():
            if line.startswith("Port"):
                continue
            parts = line.split()
            if parts:
                ports.append(parts[0])
        return ports
    except Exception as e:
        return []

class VagilettaWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vagiletta")
        layout = QGridLayout()
        self.setLayout(layout)
        self.setMinimumSize(900, 400)
        self.boxes = []

        for i in range(2):
            for j in range(4):
                box = QWidget()
                vbox = QVBoxLayout(box)
                label = QLabel(f"Slot {i*4+j+1}")
                vbox.addWidget(label)

                combo = QComboBox()
                combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                combo.addItems(list_arduino_ports())
                vbox.addWidget(combo)

                flash_btn = QPushButton("Flash")
                flash_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                vbox.addWidget(flash_btn)

                # Parametri di esempio, puoi renderli dinamici
                params = {"speed": 100 + (i*4+j)*10, "mode": "fast" if (i*4+j)%2==0 else "slow"}

                def do_flash(combo=combo, params=params):
                    port = combo.currentText()
                    if not port:
                        QMessageBox.warning(self, "Errore", "Seleziona una porta!")
                        return
                    proj = prepare_project(params)
                    fqbn = "arduino:avr:uno"
                    try:
                        # Compile
                        res_compile = subprocess.run([ARDUINO_CLI, "compile", "--fqbn", fqbn, str(proj)], capture_output=True, text=True)
                        if res_compile.returncode != 0:
                            QMessageBox.critical(self, "Errore", f"Compilazione fallita:\n{res_compile.stderr}")
                            return
                        # Upload
                        res_upload = subprocess.run([ARDUINO_CLI, "upload", "-p", port, "--fqbn", fqbn, str(proj)], capture_output=True, text=True)
                        if res_upload.returncode != 0:
                            QMessageBox.critical(self, "Errore", f"Upload fallito:\n{res_upload.stderr}")
                            return
                        QMessageBox.information(self, "Successo", f"Flash su {port} completato!")
                    except Exception as e:
                        QMessageBox.critical(self, "Errore", str(e))

                flash_btn.clicked.connect(do_flash)
                layout.addWidget(box, i, j)
                self.boxes.append((combo, flash_btn))
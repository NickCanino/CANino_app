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
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QStyle,
    QStyledItemDelegate,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QTimer, QDateTime
import time
import csv
import sys
import statistics
from datetime import datetime

from src.exceptions_logger import log_exception

RX_refresh_rate_ms = 500

# Rx column definition (see also setHorizontalHeaderLabels)
RX_COL_0_id = 0
RX_COL_1_name = 1
RX_COL_2_dlc = 2
RX_COL_3_payload = 3
RX_COL_4_count = 4
RX_COL_5_period = 5
RX_COL_6_min = 6
RX_COL_7_max = 7
RX_COL_8_dev_std = 8
RX_COL_9_last_received = 9


class PayloadEditDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        # Monospace style for some columns
        super().initStyleOption(option, index)
        if (
            index.column() == RX_COL_0_id
            or index.column() == RX_COL_1_name
            or index.column() == RX_COL_2_dlc
            or index.column() == RX_COL_3_payload
        ):
            font = QFont("Arial", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            option.font = font


class ReceivedFramesWindow(QWidget):
    def __init__(self, dbc=None):
        super().__init__()
        self.dbc = dbc
        self.csv_path = None
        self.csv_file = None
        self.csv_writer = None
        self.log_active = False
        self.log_paused = False

        self.busload_rx_arbitration_bits = 0  # busload Rx statistics
        self.busload_rx_data_bits = 0  # busload Rx statistics

        layout = QVBoxLayout()

        # --- Barra pulsanti log ---
        log_btn_layout = QHBoxLayout()
        # Pulsante per collegare il file CSV
        self.btn_link_csv = QPushButton("Link CSV")
        self.btn_link_csv.setToolTip("Link a CSV file for logging")
        self.btn_link_csv.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon)
        )
        self.btn_link_csv.setFixedSize(120, 30)
        self.btn_link_csv.setCheckable(True)

        # Pulsante per avviare il log
        self.btn_start_log = QPushButton("Start LOG")
        self.btn_start_log.setToolTip("Start logging to CSV")
        self.btn_start_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.btn_start_log.setFixedSize(100, 30)

        # Pulsante per mettere in pausa il log
        self.btn_pause_log = QPushButton("Pause LOG")
        self.btn_pause_log.setToolTip("Pause logging to CSV")
        self.btn_pause_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self.btn_pause_log.setFixedSize(100, 30)

        # Pulsante per fermare il log
        self.btn_stop_log = QPushButton("Stop LOG")
        self.btn_stop_log.setToolTip("Stop logging to CSV")
        self.btn_stop_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self.btn_stop_log.setFixedSize(100, 30)

        # Pulsante per pulire tabella RX
        self.btn_clear_table = QPushButton("Clear")
        self.btn_clear_table.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self.btn_clear_table.setToolTip("Clear RX table")
        self.btn_clear_table.setFixedSize(80, 30)

        # Styles for buttons
        self.btn_start_log.setStyleSheet(
            """
            QPushButton {
                border: none; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
            QPushButton:disabled {
                background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
            }
        """
        )  # Bordo verde
        self.btn_pause_log.setStyleSheet(
            """
            QPushButton {
                border: none; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
            QPushButton:disabled {
                background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
            }
        """
        )  # Bordo azzurro
        self.btn_stop_log.setStyleSheet(
            """
            QPushButton {
                border: none; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
            QPushButton:disabled {
                background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
            }
        """
        )  # Bordo rosso

        self.btn_start_log.setEnabled(False)
        self.btn_pause_log.setEnabled(False)
        self.btn_stop_log.setEnabled(False)

        log_btn_layout.addWidget(self.btn_clear_table)
        log_btn_layout.addStretch(0)
        log_btn_layout.addWidget(self.btn_link_csv)
        log_btn_layout.addWidget(self.btn_start_log)
        log_btn_layout.addWidget(self.btn_pause_log)
        log_btn_layout.addWidget(self.btn_stop_log)
        layout.addLayout(log_btn_layout)

        # Connect buttons
        self.btn_clear_table.clicked.connect(self.clear_rx_table)
        self.btn_link_csv.clicked.connect(self.link_csv_file)
        self.btn_start_log.clicked.connect(self.start_log)
        self.btn_pause_log.clicked.connect(self.pause_log)
        self.btn_stop_log.clicked.connect(self.stop_log)

        # --- Tabella RX ---
        self.table = QTableWidget(0, 10)  # 10 colonne
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Name",
                "DLC",
                "Payload",
                "Count",
                "Period (ms)",
                "Min (ms)",
                "Max (ms)",
                "Dev. Std (ms)",
                "Last Received",
            ]
        )
        # Imposta larghezza colonne
        self.table.setColumnWidth(RX_COL_0_id, 50)
        self.table.setColumnWidth(RX_COL_1_name, 100)
        self.table.setColumnWidth(RX_COL_2_dlc, 50)
        self.table.setColumnWidth(RX_COL_3_payload, 800)  # old: 140
        self.table.setColumnWidth(RX_COL_4_count, 70)
        self.table.setColumnWidth(RX_COL_5_period, 80)  # old: 100
        self.table.setColumnWidth(RX_COL_6_min, 80)
        self.table.setColumnWidth(RX_COL_7_max, 80)
        self.table.setColumnWidth(RX_COL_8_dev_std, 100)
        self.table.setColumnWidth(RX_COL_9_last_received, 140)

        self.table.setItemDelegate(PayloadEditDelegate(self.table))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Abilita l'ordinamento delle colonne
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(
            lambda _: self.frames.clear()
        )  # Pulisci il mapping quando si riordinano le righe della tabella
        # self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        # Aggiungi un menu contestuale per rimuovere le righe
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.frames = {}
        self._rx_buffer = {}  # <--- buffer temporaneo

        # Timer per aggiornare la tabella ogni secondo
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_table)
        self.refresh_timer.start(RX_refresh_rate_ms)  # ogni 500 ms

    def clear_busload_stats(self):
        self.busload_rx_arbitration_bits = 0
        self.busload_rx_data_bits = 0

    def get_busload_rx_arbitration_bits(self):
        return self.busload_rx_arbitration_bits

    def get_busload_rx_data_bits(self):
        return self.busload_rx_data_bits

    def clear_rx_table(self):
        self.table.setRowCount(0)
        self._rx_buffer.clear()

    def update_frame(
        self, frame_id: int, data: bytes, dlc: int = None, is_fd: bool = False
    ):
        # Aggiorna solo il buffer, non la tabella direttamente

        self.busload_rx_arbitration_bits += (
            79  # 11 can id (suppose base frame format) + 68 arbitration other bits
        )
        self.busload_rx_data_bits += dlc

        now = time.time()
        if frame_id not in self._rx_buffer:  # Nuovo frame
            self._rx_buffer[frame_id] = {
                "count": 1,
                "dlc": dlc if dlc is not None else len(data),
                "data": data,
                "last_time": now,
                "periods": [0],
                "min": None,
                "max": None,
                "avg_period": None,
            }
        else:  # Frame già esistente
            f = self._rx_buffer[frame_id]

            self.log_frame_to_csv(
                frame_id=frame_id,
                data=f["data"],
                dlc=f["dlc"],
                count=f["count"],
                # min=f["min"],
                # max=f["max"],
                avg_period=f["avg_period"],
                periods=f["periods"],
            )

            f["count"] += 1
            period = (now - f["last_time"]) * 1000
            f["last_time"] = now
            f["dlc"] = len(data)
            f["data"] = data
            f["periods"].append(period)

            if f["min"] is None:  # primo aggiornamento
                f["min"] = period
            else:
                f["min"] = period if period < f["min"] else f["min"]

            if f["max"] is None:  # primo aggiornamento
                f["max"] = period
            else:
                f["max"] = period if period > f["max"] else f["max"]

            if f["avg_period"] is None:  # primo aggiornamento
                f["avg_period"] = period
            else:  # aggiorna l'EMA
                f["avg_period"] = 0.1 * period + 0.9 * f["avg_period"]

            if (
                len(f["periods"]) > 20 or f["count"] < 5
            ):  # Limita a 20 periodi per evitare overflow butta i primi 5 per calcolare la deviazione standard
                f["periods"].pop(0)  # rimuovi il più vecchio

    def refresh_table(self):
        for frame_id, f in self._rx_buffer.items():
            id_str = f"0x{frame_id:03X}"
            row = None
            # Cerca la riga con l'ID giusto (colonna 0)
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item and item.text() == id_str:
                    row = r
                    break
            if row is None:
                # crea nuova riga
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, RX_COL_0_id, QTableWidgetItem(id_str))
            # Aggiorna sempre il nome dalla DBC (anche se già presente)
            msg_name = ""
            if self.dbc and hasattr(self.dbc, "db"):
                try:
                    msg = self.dbc.db.get_message_by_frame_id(frame_id)
                    if msg:
                        msg_name = msg.name
                except Exception:
                    pass

            self.table.setItem(row, RX_COL_1_name, QTableWidgetItem(msg_name))
            self.table.setItem(row, RX_COL_2_dlc, QTableWidgetItem(str(f["dlc"])))
            self.table.setItem(
                row,
                RX_COL_3_payload,
                QTableWidgetItem(" ".join(f"{b:02X}" for b in f["data"])),
            )
            self.table.setItem(row, RX_COL_4_count, QTableWidgetItem(str(f["count"])))
            self.table.setItem(
                row,
                RX_COL_5_period,
                QTableWidgetItem(f"{f['avg_period']:.1f}" if f["avg_period"] else "-"),
            )
            self.table.setItem(
                row,
                RX_COL_6_min,
                QTableWidgetItem(f"{f['min']:.1f}" if f["min"] else "-"),
            )
            self.table.setItem(
                row,
                RX_COL_7_max,
                QTableWidgetItem(f"{f['max']:.1f}" if f["max"] else "-"),
            )

            std_dev = statistics.pstdev(f["periods"]) if len(f["periods"]) > 1 else 0.0
            self.table.setItem(
                row,
                RX_COL_8_dev_std,
                QTableWidgetItem(f"{std_dev:.1f}" if std_dev else "-"),
            )

            last_recv = QDateTime.fromSecsSinceEpoch(int(f["last_time"]))
            self.table.setItem(
                row,
                RX_COL_9_last_received,
                QTableWidgetItem(last_recv.toString(Qt.DateFormat.ISODate)),
            )

    def set_dbc(self, dbc):
        self.dbc = dbc
        # Aggiorna i nomi dei messaggi già presenti in tabella
        for frame_id, f in self.frames.items():
            row = f["row"]
            msg_name = ""
            if self.dbc and hasattr(self.dbc, "db"):
                try:
                    msg = self.dbc.db.get_message_by_frame_id(frame_id)
                    if msg:
                        msg_name = msg.name
                except Exception:
                    pass
            self.table.setItem(row, RX_COL_1_name, QTableWidgetItem(msg_name))

    def link_csv_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select CSV file", "", "CSV Files (*.csv)"
        )
        if path:
            self.csv_path = path

            self.btn_start_log.setText("Start LOG")
            self.btn_start_log.setToolTip("Start logging to CSV")

            self.btn_start_log.setEnabled(True)
            self.btn_pause_log.setEnabled(False)
            self.btn_stop_log.setEnabled(False)

            self.btn_start_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: 2px solid #388E3C; border-radius: 6px;
                }
                QPushButton:hover:enabled {
                    background-color: #8C8C8C;
                }
            """
            )  # Bordo verde
            self.btn_pause_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
                }
            """
            )  # Bordo azzurro
            self.btn_stop_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
                }
            """
            )  # Bordo rosso

            self.log_active = False
            self.log_paused = False

    def log_frame_to_csv(self, frame_id, data, dlc, count, avg_period, periods):
        """
        Logs a single CAN frame to CSV, if logging is active and not paused.
        """
        if self.log_active and not self.log_paused and self.csv_writer:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
                id_str = f"0x{frame_id:03X}"
                msg_name = ""
                if self.dbc and hasattr(self.dbc, "db"):
                    try:
                        msg = self.dbc.db.get_message_by_frame_id(frame_id)
                        if msg:
                            msg_name = msg.name
                    except Exception:
                        pass
                payload_str = " ".join(f"{b:02X}" for b in data)
                std_dev = statistics.pstdev(periods) if len(periods) > 1 else 0.0
                self.csv_writer.writerow(
                    [
                        timestamp,
                        id_str,
                        msg_name,
                        dlc,
                        payload_str,
                        count,
                        f"{avg_period:.1f}" if avg_period else "-",
                        f"{std_dev:.1f}" if std_dev else "-",
                    ]
                )
                self.csv_file.flush()
            except Exception as e:
                log_exception(__file__, sys._getframe().f_lineno, e)

    def start_log(self):  # metodo per avviare il log e aprire il file CSV
        if not self.csv_path:
            return
        # Se il log era stoppato, pulisci il file
        if not self.log_active or not self.csv_file:
            self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(
                [
                    "Timestamp",
                    "ID",
                    "Name",
                    "DLC",
                    "Payload",
                    "Count",
                    "Period (ms)",
                    "Std.Dev (ms)",
                ]
            )

        self.log_active = True
        self.log_paused = False

        self.btn_start_log.setText("Start LOG")
        self.btn_start_log.setToolTip("Logging active")

        self.btn_pause_log.setText("Pause LOG")
        self.btn_pause_log.setToolTip("Pause logging to CSV")

        self.btn_stop_log.setText("Stop LOG")
        self.btn_stop_log.setToolTip("Stop logging to CSV")

        self.btn_start_log.setEnabled(False)
        self.btn_start_log.setStyleSheet(
            """
            QPushButton {
                background-color: #488E3C; color: white; border: 2px solid #388E3C; border-radius: 6px;
            }
        """
        )  # Bordo verde

        self.btn_pause_log.setEnabled(True)
        self.btn_pause_log.setStyleSheet(
            """
            QPushButton {
                background-color: #3C3C3C; color: white; border: 2px solid #1565C0; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
        """
        )  # Bordo azzurro

        self.btn_stop_log.setEnabled(True)
        self.btn_stop_log.setStyleSheet(
            """
            QPushButton {
                background-color: #3C3C3C; color: white; border: 2px solid #B71C1C; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
        """
        )  # Bordo rosso

    def pause_log(self):  # metodo per mettere in pausa il log e non chiudere il file
        if self.log_active:
            self.log_paused = True

            self.btn_start_log.setText("Resume LOG")
            self.btn_start_log.setToolTip("Resume logging to CSV")

            self.btn_pause_log.setText("Pause LOG")
            self.btn_pause_log.setToolTip("Logging paused")

            self.btn_stop_log.setText("Stop LOG")
            self.btn_stop_log.setToolTip("Stop logging to CSV")

            self.btn_start_log.setEnabled(True)
            self.btn_start_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: 2px solid #388E3C; border-radius: 6px;
                }
                QPushButton:hover:enabled {
                    background-color: #8C8C8C;
                }
            """
            )  # Bordo verde

            self.btn_pause_log.setEnabled(False)
            self.btn_pause_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #1565C0; color: white; border: 2px solid #1565C0; border-radius: 6px;
                }
            """
            )  # Bordo e interno azzurro

            self.btn_stop_log.setEnabled(True)
            self.btn_stop_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: 2px solid #B71C1C; border-radius: 6px;
                }
                QPushButton:hover:enabled {
                    background-color: #8C8C8C;
                }
            """
            )
            # Non chiudere il file, solo mettere in pausa

    def stop_log(self):  # metodo per fermare il log e chiudere il file
        self.log_active = False
        self.log_paused = False

        self.btn_start_log.setText("Restart LOG")
        self.btn_start_log.setToolTip("Restart logging to CSV")

        self.btn_pause_log.setText("Pause LOG")
        self.btn_pause_log.setToolTip("Pause logging to CSV")

        self.btn_stop_log.setText("Stop LOG")
        self.btn_stop_log.setToolTip("Stopped logging to CSV")

        self.btn_start_log.setEnabled(True)
        self.btn_start_log.setStyleSheet(
            """
            QPushButton {
                background-color: #3C3C3C; color: white; border: 2px solid #388E3C; border-radius: 6px;
            }
            QPushButton:hover:enabled {
                background-color: #8C8C8C;
            }
        """
        )  # Bordo verde

        self.btn_pause_log.setEnabled(False)
        self.btn_pause_log.setStyleSheet(
            """
            QPushButton {
                background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
            }
        """
        )  # Bordo azzurro

        self.btn_stop_log.setEnabled(False)
        self.btn_stop_log.setStyleSheet(
            """
            QPushButton {
                background-color: #B71C1C; color: white; border: 2px solid #B71C1C; border-radius: 6px;
            }
        """
        )  # Bordo e interno rosso

        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

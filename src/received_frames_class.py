from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QStyle,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
import time
import csv
import statistics

from src.exceptions_logger import log_exception


class ReceivedFramesWindow(QWidget):
    def __init__(self, dbc=None):
        super().__init__()
        self.dbc = dbc
        self.csv_path = None
        self.csv_file = None
        self.csv_writer = None
        self.log_active = False
        self.log_paused = False

        layout = QVBoxLayout()

        # --- Barra pulsanti log ---
        log_btn_layout = QHBoxLayout()
        self.btn_link_csv = QPushButton(" Link file CSV")
        self.btn_link_csv.setToolTip("Collega un file CSV per il logging")
        self.btn_link_csv.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon)
        )
        self.btn_link_csv.setFixedSize(120, 30)
        self.btn_link_csv.setCheckable(True)

        self.btn_start_log = QPushButton(" Start LOG")
        self.btn_start_log.setToolTip("Avvia il logging su CSV")
        self.btn_start_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.btn_start_log.setFixedSize(120, 30)
        # self.btn_start_log.setCheckable(True)

        self.btn_pause_log = QPushButton(" Pausa LOG")
        self.btn_pause_log.setToolTip("Pausa il logging su CSV")
        self.btn_pause_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self.btn_pause_log.setFixedSize(120, 30)
        # self.btn_pause_log.setCheckable(True)

        self.btn_stop_log = QPushButton(" Stop LOG")
        self.btn_stop_log.setToolTip("Ferma il logging su CSV")
        self.btn_stop_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self.btn_stop_log.setFixedSize(120, 30)
        # self.btn_stop_log.setCheckable(True)

        self.btn_start_log.setEnabled(False)
        self.btn_pause_log.setEnabled(False)
        self.btn_stop_log.setEnabled(False)

        log_btn_layout.addWidget(self.btn_link_csv)
        log_btn_layout.addWidget(self.btn_start_log)
        log_btn_layout.addWidget(self.btn_pause_log)
        log_btn_layout.addWidget(self.btn_stop_log)
        layout.addLayout(log_btn_layout)

        # Connect buttons
        self.btn_link_csv.clicked.connect(self.link_csv_file)
        self.btn_start_log.clicked.connect(self.start_log)
        self.btn_pause_log.clicked.connect(self.pause_log)
        self.btn_stop_log.clicked.connect(self.stop_log)

        # --- Tabella RX ---
        self.table = QTableWidget(0, 8)  # 8 colonne
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Nome",
                "DLC",
                "Payload (0-7)",
                "Ultimo ricevimento",
                "Conteggio",
                "Periodo (ms)",
                "Dev. Std (ms)",
            ]
        )
        # Imposta larghezza colonne
        self.table.setColumnWidth(0, 50)  # ID
        self.table.setColumnWidth(1, 100)  # Nome
        self.table.setColumnWidth(2, 50)  # DLC
        self.table.setColumnWidth(3, 140)  # Payload
        self.table.setColumnWidth(4, 140)  # Ultimo ricevimento
        self.table.setColumnWidth(5, 70)  # Conteggio
        self.table.setColumnWidth(6, 100)  # Periodo EMA (ms)
        self.table.setColumnWidth(7, 100)  # Dev. Std (ms)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Abilita l'ordinamento delle colonne
        self.table.setSortingEnabled(True)
        # self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        # Aggiungi un menu contestuale per rimuovere le righe
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.frames = {}
        self._rx_buffer = {}  # <--- buffer temporaneo

        # Timer per aggiornare la tabella ogni secondo
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_table)
        self.refresh_timer.start(500)  # ogni 500 ms

    def update_frame(self, frame_id: int, data: bytes, dlc: int = None):
        # Aggiorna solo il buffer, non la tabella direttamente
        now = time.time()
        if frame_id not in self._rx_buffer:  # Nuovo frame
            self._rx_buffer[frame_id] = {
                "count": 1,
                "dlc": dlc if dlc is not None else len(data),
                "data": data,
                "last_time": now,
                "periods": [0],
                "avg_period": None,
            }
        else:  # Frame già esistente
            f = self._rx_buffer[frame_id]
            f["count"] += 1
            period = (now - f["last_time"]) * 1000
            f["last_time"] = now
            f["dlc"] = len(data)
            f["data"] = data
            f["periods"].append(period)

            if f["avg_period"] is None:  # primo aggiornamento
                f["avg_period"] = period
            else:  # aggiorna l'EMA
                f["avg_period"] = 0.1 * period + 0.9 * f["avg_period"]

            if len(f["periods"]) > 100:  # Limita a 100 periodi per evitare overflow
                f["periods"].pop(0)

    def refresh_table(self):
        for frame_id, f in self._rx_buffer.items():
            # Trova la riga con l'ID giusto (colonna 0)
            row = None
            id_str = f"0x{frame_id:03X}"
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item and item.text() == id_str:
                    row = r
                    break
            if row is None:
                # crea nuova riga
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(id_str))
                # Nome messaggio dal DBC
                msg_name = ""
                if self.dbc and hasattr(self.dbc, "db"):
                    try:
                        msg = self.dbc.db.get_message_by_frame_id(frame_id)
                        if msg:
                            msg_name = msg.name
                    except Exception:
                        pass
                self.table.setItem(row, 1, QTableWidgetItem(msg_name))

            # Aggiorna sempre la riga trovata
            std_dev = statistics.stdev(f["periods"]) if len(f["periods"]) > 1 else 0.0
            self.table.setItem(row, 2, QTableWidgetItem(str(f["dlc"])))
            self.table.setItem(
                row, 3, QTableWidgetItem(" ".join(f"{b:02X}" for b in f["data"]))
            )
            last_recv = QDateTime.fromSecsSinceEpoch(int(f["last_time"]))
            self.table.setItem(
                row, 4, QTableWidgetItem(last_recv.toString(Qt.DateFormat.ISODate))
            )
            self.table.setItem(row, 5, QTableWidgetItem(str(f["count"])))
            self.table.setItem(
                row,
                6,
                QTableWidgetItem(f"{f['avg_period']:.1f}" if f["avg_period"] else "-"),
            )
            self.table.setItem(
                row, 7, QTableWidgetItem(f"{std_dev:.1f}" if std_dev else "-")
            )

        # Logging su CSV
        if self.log_active and not self.log_paused and self.csv_writer:
            try:
                timestamp = QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate)
                id_str = f"0x{frame_id:03X}"
                msg_name = ""
                if self.dbc and hasattr(self.dbc, "db"):
                    try:
                        msg = self.dbc.db.get_message_by_frame_id(frame_id)
                        if msg:
                            msg_name = msg.name
                    except Exception:
                        pass
                payload_str = " ".join(f"{b:02X}" for b in f["data"])
                std_dev = (
                    statistics.stdev(f["periods"]) if len(f["periods"]) > 1 else 0.0
                )
                self.csv_writer.writerow(
                    [
                        timestamp,
                        id_str,
                        msg_name,
                        f["dlc"],
                        payload_str,
                        f["count"],
                        f"{f['avg_period']:.1f}" if f["avg_period"] else "-",
                        f"{std_dev:.1f}" if std_dev else "-",
                    ]
                )
                self.csv_file.flush()
            except Exception as e:
                log_exception(e)

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
            self.table.setItem(row, 1, QTableWidgetItem(msg_name))

    def link_csv_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Seleziona file CSV", "", "CSV Files (*.csv)"
        )
        if path:
            self.csv_path = path
            self.btn_start_log.setEnabled(True)
            self.btn_pause_log.setEnabled(False)
            self.btn_stop_log.setEnabled(False)
            self.log_active = False
            self.log_paused = False

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
                    "Nome",
                    "DLC",
                    "Payload",
                    "Conteggio",
                    "Periodo(ms)",
                    "Dev.Std(ms)",
                ]
            )

        self.log_active = True
        self.log_paused = False
        self.btn_start_log.setEnabled(False)

        self.btn_pause_log.setEnabled(True)

        self.btn_stop_log.setEnabled(True)

    def pause_log(self):  # metodo per mettere in pausa il log e non chiudere il file
        if self.log_active:
            self.log_paused = True
            self.btn_start_log.setEnabled(True)

            self.btn_pause_log.setEnabled(False)
            # Non chiudere il file, solo mettere in pausa

    def stop_log(self):  # metodo per fermare il log e chiudere il file
        self.log_active = False
        self.log_paused = False
        self.btn_start_log.setEnabled(True)

        self.btn_pause_log.setEnabled(False)

        self.btn_stop_log.setEnabled(False)

        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

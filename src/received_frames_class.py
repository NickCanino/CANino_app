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
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer, QDateTime
import time
import csv
import statistics
import threading
from datetime import datetime

from src.exceptions_logger import log_exception
from src.utils import format_can_id

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
            # font = QFont("Arial", 10)
            font = QFont("Courier New", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            option.font = font


class ReceivedFramesWindow(QWidget):
    def __init__(self, dbc=None):
        super().__init__()
        self.dbc = dbc
        self._dbc_names = self._names_of(dbc)
        self.csv_path = None
        self.csv_file = None
        self.csv_writer = None
        self.log_active = False
        self.log_paused = False

        self.busload_rx_arbitration_bits = 0  # busload Rx statistics
        self.busload_rx_data_bits = 0  # busload Rx statistics

        layout = QVBoxLayout()

        # --- Log button bar ---
        log_btn_layout = QHBoxLayout()
        # Link the CSV file
        self.btn_link_csv = QPushButton("Link CSV")
        self.btn_link_csv.setToolTip("Link a CSV file for logging")
        self.btn_link_csv.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon)
        )
        self.btn_link_csv.setFixedSize(120, 30)
        self.btn_link_csv.setCheckable(True)

        # Start logging
        self.btn_start_log = QPushButton("Start LOG")
        self.btn_start_log.setToolTip("Start logging to CSV")
        self.btn_start_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.btn_start_log.setFixedSize(100, 30)

        # Pause logging
        self.btn_pause_log = QPushButton("Pause LOG")
        self.btn_pause_log.setToolTip("Pause logging to CSV")
        self.btn_pause_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self.btn_pause_log.setFixedSize(100, 30)

        # Stop logging
        self.btn_stop_log = QPushButton("Stop LOG")
        self.btn_stop_log.setToolTip("Stop logging to CSV")
        self.btn_stop_log.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self.btn_stop_log.setFixedSize(100, 30)

        # Clear the RX table
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
        )  # green border
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
        )  # blue border
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
        )  # red border

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

        # --- RX table ---
        self.table = QTableWidget(0, 10)  # 10 columns
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
        # Column widths
        self.table.setColumnWidth(RX_COL_0_id, 50)
        self.table.setColumnWidth(RX_COL_1_name, 100)
        self.table.setColumnWidth(RX_COL_2_dlc, 50)
        self.table.setColumnWidth(RX_COL_3_payload, 200)  # old: 140
        self.table.setColumnWidth(RX_COL_4_count, 70)
        self.table.setColumnWidth(RX_COL_5_period, 80)  # old: 100
        self.table.setColumnWidth(RX_COL_6_min, 80)
        self.table.setColumnWidth(RX_COL_7_max, 80)
        self.table.setColumnWidth(RX_COL_8_dev_std, 100)
        self.table.setColumnWidth(RX_COL_9_last_received, 140)

        self.table.setItemDelegate(PayloadEditDelegate(self.table))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Sortable columns
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(
            lambda _: self.frames.clear()
        )  # Drop the row mapping when the rows are re-sorted
        # self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        # Table
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.frames = {}
        self._rx_buffer = {}  # (id, is_ext) -> stats, filled by the RX thread
        # The RX thread writes _rx_buffer and the CSV, the GUI thread reads the
        # buffer and opens/closes the CSV: both go through this lock (TODO 5.2/5.5)
        self._lock = threading.Lock()

        # Table refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_table)
        self.refresh_timer.start(RX_refresh_rate_ms)  # every 500 ms

    def clear_busload_stats(self):
        self.busload_rx_arbitration_bits = 0
        self.busload_rx_data_bits = 0

    def get_busload_rx_arbitration_bits(self):
        return self.busload_rx_arbitration_bits

    def get_busload_rx_data_bits(self):
        return self.busload_rx_data_bits

    def clear_rx_table(self):
        self.table.setRowCount(0)
        with self._lock:
            self._rx_buffer.clear()

    def update_frame(
        self,
        frame_id: int,
        data: bytes,
        dlc: int = None,
        is_fd: bool = False,
        timestamp: float = None,
        is_ext: bool = False,
    ):
        """Called from the RX thread; `timestamp` is the PCAN hardware time.

        Frames are keyed by (ID, is_ext): standard 0x123 and extended
        0x00000123 are different frames (TODO 1.7).
        """
        with self._lock:
            self._update_frame_locked(frame_id, data, dlc, is_fd, timestamp, is_ext)

    def _update_frame_locked(self, frame_id, data, dlc, is_fd, timestamp, is_ext):
        # Only the buffer: the table is refreshed from it in the GUI thread

        # DLC from the data when not given
        if dlc is None:
            dlc = len(data) if data else 0
        dlc = max(0, min(int(dlc), 64))

        # Compact bit counting:
        # arbitration = SOF(1) + ID(11|29) + RTR/IDE/RES(≈3) + DLC(4)
        # data_phase = data(8*dlc) + CRC(+delim)
        # NOTE: ACK/EOF/IFS go at the nominal bitrate in CAN FD -> counted in arbitration_bits
        arbitration_bits = 1 + (29 if is_ext else 11) + 3 + 4
        if not is_fd:
            crc_total = 15 + 1
            data_phase_bits = 8 * dlc + crc_total + 2 + 7 + 3
        else:
            crc_total = (17 + 1) if dlc <= 16 else (21 + 1)
            data_phase_bits = 8 * dlc + crc_total
            arbitration_bits += 2 + 7 + 3

        # RX counters (arbitration at the nominal rate, data phase at the data rate for FD)
        self.busload_rx_arbitration_bits += arbitration_bits
        self.busload_rx_data_bits += data_phase_bits

        now = timestamp if timestamp is not None else time.time()
        key = (frame_id, bool(is_ext))
        if key not in self._rx_buffer:  # New frame
            f = self._rx_buffer[key] = {
                "count": 1,
                "dlc": dlc if dlc is not None else len(data),
                "data": data,
                "last_time": now,
                "periods": [0],
                "min": None,
                "max": None,
                "avg_period": None,
            }
        else:  # Known frame
            f = self._rx_buffer[key]
            f["count"] += 1
            period = (now - f["last_time"]) * 1000
            f["last_time"] = now
            f["dlc"] = len(data)
            f["data"] = data
            f["periods"].append(period)

            if f["min"] is None:  # first period
                f["min"] = period
            else:
                f["min"] = period if period < f["min"] else f["min"]

            if f["max"] is None:  # first period
                f["max"] = period
            else:
                f["max"] = period if period > f["max"] else f["max"]

            if f["avg_period"] is None:  # first period
                f["avg_period"] = period
            else:  # update the EMA
                f["avg_period"] = 0.1 * period + 0.9 * f["avg_period"]

            if (
                len(f["periods"]) > 20 or f["count"] < 5
            ):  # Keep the last 20 periods; drop the first 5 from the std-dev
                f["periods"].pop(0)  # drop the oldest

        # Log the frame that just arrived, stamped with its own time (TODO 5.3/5.4)
        self.log_frame_to_csv(
            frame_id=frame_id,
            is_ext=is_ext,
            data=data,
            dlc=f["dlc"],
            count=f["count"],
            avg_period=f["avg_period"],
            periods=f["periods"],
            timestamp=now,
        )

    def refresh_table(self):
        # Snapshot under the lock: the RX thread may add IDs meanwhile (TODO 5.2)
        with self._lock:
            snapshot = [
                (key, dict(f, periods=list(f["periods"])))
                for key, f in self._rx_buffer.items()
            ]
        # With sorting on, every setItem() re-sorts and the following setItem()
        # calls of the same row land on another ID's row (TODO 5.1)
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            self._fill_rows(snapshot)
        finally:
            self.table.setSortingEnabled(sorting)

    def _fill_rows(self, snapshot):
        for (frame_id, is_ext), f in snapshot:
            id_str = format_can_id(frame_id, is_ext)
            row = None
            # Find this ID's row (column 0)
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item and item.text() == id_str:
                    row = r
                    break
            if row is None:
                # new row
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, RX_COL_0_id, QTableWidgetItem(id_str))
            # Name from the DBC, refreshed every time
            msg_name = self._dbc_name(frame_id, is_ext)
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

    @staticmethod
    def _names_of(dbc):
        """(frame_id, is_ext) -> message name.

        cantools' get_message_by_frame_id() keeps one message per number, so a
        DBC with both std 0x123 and ext 0x123 would name one after the other.
        """
        db = getattr(dbc, "db", None)
        return {
            (m.frame_id, bool(m.is_extended_frame)): m.name
            for m in getattr(db, "messages", [])
        }

    def _dbc_name(self, frame_id, is_ext):
        """DBC message name, only if the DBC frame has the same ID format."""
        return self._dbc_names.get((frame_id, bool(is_ext)), "")

    def set_dbc(self, dbc):
        self.dbc = dbc
        self._dbc_names = self._names_of(dbc)
        # Names of the rows already in the table
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
            )  # green border
            self.btn_pause_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
                }
            """
            )  # blue border
            self.btn_stop_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
                }
            """
            )  # red border

            self.log_active = False
            self.log_paused = False

    def log_frame_to_csv(
        self,
        frame_id,
        data,
        dlc,
        count,
        avg_period,
        periods,
        timestamp=None,
        is_ext=False,
    ):
        """
        Logs a single CAN frame to CSV, if logging is active and not paused.
        Called with self._lock held; `timestamp` is the frame's own time
        (PCAN hardware clock, a constant offset from the PC clock).
        """
        if self.log_active and not self.log_paused and self.csv_writer:
            try:
                ts = timestamp if timestamp is not None else time.time()
                timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.%f")
                id_str = format_can_id(frame_id, is_ext)
                msg_name = self._dbc_name(frame_id, is_ext)
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
                log_exception(e)

    def start_log(self):  # start logging, open the CSV file
        if not self.csv_path:
            return
        # After a Stop the file starts over
        with self._lock:
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
        )  # green border

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
        )  # blue border

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
        )  # red border

    def pause_log(self):  # pause logging, keep the file open
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
            )  # green border

            self.btn_pause_log.setEnabled(False)
            self.btn_pause_log.setStyleSheet(
                """
                QPushButton {
                    background-color: #1565C0; color: white; border: 2px solid #1565C0; border-radius: 6px;
                }
            """
            )  # blue border and fill

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
            # The file stays open

    def stop_log(self):  # stop logging, close the file
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
        )  # green border

        self.btn_pause_log.setEnabled(False)
        self.btn_pause_log.setStyleSheet(
            """
            QPushButton {
                background-color: #3C3C3C; color: white; border: none; border-radius: 6px;
            }
        """
        )  # blue border

        self.btn_stop_log.setEnabled(False)
        self.btn_stop_log.setStyleSheet(
            """
            QPushButton {
                background-color: #B71C1C; color: white; border: 2px solid #B71C1C; border-radius: 6px;
            }
        """
        )  # red border and fill

        with self._lock:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None

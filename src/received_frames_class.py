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
    QTableView,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QStyle,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QTimer, Signal, QSortFilterProxyModel
import time
import csv
from collections import deque
from datetime import datetime

from src.busload import frame_bits
from src.exceptions_logger import log_throttled
from src.rx_model import (
    RxTableModel,
    SORT_ROLE,
    RX_COL_0_id,
    RX_COL_1_name,
    RX_COL_2_dlc,
    RX_COL_3_payload,
    RX_COL_4_count,
    RX_COL_5_period,
    RX_COL_6_min,
    RX_COL_7_max,
    RX_COL_8_dev_std,
    RX_COL_9_last_received,
)

# The GUI thread drains the RX queue and refreshes the touched rows this often
RX_DRAIN_MS = 100


class ReceivedFramesWindow(QWidget):
    # After each drain: {(frame_id, is_ext): latest payload} for the XMetro gauges
    frames_received = Signal(object)

    def __init__(self, dbc=None):
        super().__init__()
        self.dbc = dbc
        self._dbc_names = self._names_of(dbc)
        self.csv_path = None
        self.csv_file = None
        self.csv_writer = None
        self.log_active = False
        self.log_paused = False

        # Bits seen on the wire (received + own echoes) since the last
        # take_busload_bits(): at the nominal rate, at the CAN FD data rate
        self.busload_nominal_bits = 0
        self.busload_data_bits = 0

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

        # --- RX table: model in arrival order, the proxy sorts (TODO 5.8) ---
        self.model = RxTableModel(self)
        self.model.set_names(self._dbc_names)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setDynamicSortFilter(True)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        # Column widths
        self.table.setColumnWidth(RX_COL_0_id, 90)
        self.table.setColumnWidth(RX_COL_1_name, 100)
        self.table.setColumnWidth(RX_COL_2_dlc, 50)
        self.table.setColumnWidth(RX_COL_3_payload, 200)
        self.table.setColumnWidth(RX_COL_4_count, 70)
        self.table.setColumnWidth(RX_COL_5_period, 80)
        self.table.setColumnWidth(RX_COL_6_min, 80)
        self.table.setColumnWidth(RX_COL_7_max, 80)
        self.table.setColumnWidth(RX_COL_8_dev_std, 100)
        self.table.setColumnWidth(RX_COL_9_last_received, 140)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(RX_COL_0_id, Qt.SortOrder.AscendingOrder)

        layout.addWidget(self.table)
        self.setLayout(layout)

        # Filled by the RX thread, emptied by the GUI thread: deque append and
        # popleft are atomic, so the RX thread never waits on the GUI (TODO 1.8)
        self._queue = deque()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.drain)
        self.refresh_timer.start(RX_DRAIN_MS)

    def take_busload_bits(self):
        """(nominal-rate bits, data-rate bits) since the last call; resets them."""
        self.drain()
        bits = (self.busload_nominal_bits, self.busload_data_bits)
        self.busload_nominal_bits = self.busload_data_bits = 0
        return bits

    def clear_rx_table(self):
        self._queue.clear()
        self.model.clear()

    def push_frame(
        self,
        frame_id: int,
        data: bytes,
        dlc: int = None,
        is_fd: bool = False,
        timestamp: float = None,
        is_ext: bool = False,
        brs: bool = None,
        is_echo: bool = False,
    ):
        """RX-thread callback: queue the frame, nothing else (TODO 1.8).

        `timestamp` is the PCAN hardware time. Frames are keyed by (ID, is_ext):
        standard 0x123 and extended 0x00000123 are different frames (TODO 1.7).
        `is_echo` marks a frame this channel transmitted: it only counts for
        the busload. `brs` (bit-rate switch) defaults to `is_fd`.
        """
        self._queue.append(
            (
                frame_id,
                data,
                dlc,
                is_fd,
                time.time() if timestamp is None else timestamp,
                bool(is_ext),
                is_fd if brs is None else brs,
                is_echo,
            )
        )

    def drain(self):
        """GUI thread: statistics, busload, CSV and the touched rows of the table."""
        queue = self._queue
        n = len(queue)  # frames arriving meanwhile wait for the next drain
        if not n:
            return
        model = self.model
        writer = self.csv_writer if self.log_active and not self.log_paused else None
        latest = {}
        nominal_bits = data_bits = 0
        for _ in range(n):
            frame_id, data, dlc, is_fd, timestamp, is_ext, brs, is_echo = (
                queue.popleft()
            )
            data = bytes(data)
            nominal, data_rate = frame_bits(frame_id, data, is_fd, is_ext, brs)
            nominal_bits += nominal
            data_bits += data_rate
            if is_echo:  # own frame on the wire: busload only
                continue
            dlc = max(0, min(int(len(data) if dlc is None else dlc), 64))
            row = model.row_for(frame_id, is_ext)
            row.add(data, dlc, timestamp)
            latest[(frame_id, is_ext)] = data
            if writer is not None:
                self._log_row(writer, row, timestamp)
        self.busload_nominal_bits += nominal_bits
        self.busload_data_bits += data_bits
        model.commit()
        if writer is not None:
            try:
                self.csv_file.flush()
            except Exception as e:
                log_throttled("CSV", e)
        self.frames_received.emit(latest)

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

    def set_dbc(self, dbc):
        self.dbc = dbc
        self._dbc_names = self._names_of(dbc)
        self.model.set_names(self._dbc_names)  # rows already listed too (TODO 5.7)

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

    @staticmethod
    def _log_row(writer, row, timestamp):
        """One CSV line for the frame just added to `row`, with its own time
        (PCAN hardware clock, a constant offset from the PC clock; TODO 5.3/5.4)."""
        try:
            std_dev = row.std_dev()
            writer.writerow(
                [
                    datetime.fromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S.%f"),
                    row.id_text,
                    row.name,
                    row.dlc,
                    row.payload_text(),
                    row.count,
                    f"{row.avg:.1f}" if row.avg else "-",
                    f"{std_dev:.1f}" if std_dev else "-",
                ]
            )
        except Exception as e:
            log_throttled("CSV", e)

    def start_log(self):  # start logging, open the CSV file
        if not self.csv_path:
            return
        # Frames queued before the click are not part of the log
        self.drain()
        # After a Stop the file starts over
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
            self.drain()  # frames received before the click are logged
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
        self.drain()  # frames received before the click are logged
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

        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

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

import can
import threading
import sys
from typing import Callable, Optional
from src.PCANBasic import PCANBasic, PCAN_ERROR_OK, PCAN_ATTACHED_CHANNELS, PCAN_NONEBUS
from src.exceptions_logger import log_exception


class CANInterface:
    def __init__(self, channel: str, timing: "500000", is_fd=False):
        self.channel = channel
        self.timing = timing  # must be valid both if CAN or CANFD
        self.is_fd = is_fd
        self.bus = None
        self.receive_thread = None
        self.running = False
        self.receive_callback: Optional[Callable[[int, bytes], None]] = None

        self.open_bus()

    def open_bus(self):
        try:
            self.bus = can.Bus(
                channel=self.channel,
                interface="pcan",
                timing=self.timing,
                fd=self.is_fd,
                auto_reset=True,
                receive_own_messages=False,
            )

            self.running = True
            self.receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self.receive_thread.start()
        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def send_frame(self, frame_id, data, dlc=None, is_fd=False):
        try:
            if self.bus is None:
                print("[ERROR] CAN bus not initialized. Cannot send frame.")
                return

            # CAN-FD: dlc può essere fino a 64, CAN classico fino a 8
            if dlc is None:
                dlc = len(data)
            if not isinstance(data, (bytes, bytearray)):
                data = bytes(data)
            if len(data) < dlc:
                data = data + bytes([0x00] * (dlc - len(data)))
            elif len(data) > dlc:
                data = data[:dlc]

            msg = can.Message(
                arbitration_id=frame_id,
                data=data,
                is_extended_id=False,
                dlc=dlc,
                is_fd=is_fd,
                bitrate_switch=is_fd,
                check=True,
            )
            self.bus.send(msg)

        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def _receive_loop(self):
        while self.running:
            try:
                if self.bus is not None:
                    msg = self.bus.recv(1.0)
                    if msg and self.receive_callback:
                        self.receive_callback(
                            msg.arbitration_id, msg.data, msg.dlc, msg.is_fd
                        )
            except Exception as e:
                log_exception(__file__, sys._getframe().f_lineno, e)

    def set_receive_callback(self, callback: Optional[Callable[[int, bytes], None]]):
        self.receive_callback = callback
        self.receive_callback = callback

    def close(self):
        self.running = False
        if self.receive_thread:
            self.receive_thread.join(timeout=2)
        if self.bus:
            self.bus.shutdown()
            self.bus = None

    def stop_all(self):
        self.close()

    @staticmethod
    def get_available_channels() -> list[tuple[str, int]]:
        pcan = PCANBasic()
        available = []
        status, channels_info = pcan.GetValue(PCAN_NONEBUS, PCAN_ATTACHED_CHANNELS)
        if status == PCAN_ERROR_OK:
            for ch in channels_info:
                if ch.device_type == 0x05:  # PCAN_USB
                    # Only show channels that are available (not in use)
                    # 0x01 = available, 0x02 = occupied, 0x00 = unavailable
                    if ch.channel_condition == 0x01:  # PCAN_CHANNEL_AVAILABLE
                        name = ch.device_name.decode(errors="ignore")
                        display = f"USB {ch.channel_handle & 0x00F} - {name} (ID: 0x{ch.device_id:X})"
                        available.append((display, ch.channel_handle))
        return available

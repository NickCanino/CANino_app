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
from src.PCANBasic import (
    PCANBasic,
    PCAN_ERROR_OK,
    PCAN_ATTACHED_CHANNELS,
    PCAN_NONEBUS,
    PCAN_CHANNEL_FEATURES,
    FEATURE_FD_CAPABLE,
    TPCANHandle,
)
from src.exceptions_logger import log_exception


class CANInterface:
    # Set by get_available_channels() when the PEAK driver/DLL cannot be used
    scan_error: Optional[str] = None

    def __init__(self, channel: int, timing: can.BitTiming | can.BitTimingFd):
        self.channel = channel
        # python-can ignores anything that is not a BitTiming/BitTimingFd and
        # silently falls back to 500 kbit/s, so only timing objects are accepted
        if not isinstance(timing, (can.BitTiming, can.BitTimingFd)):
            raise TypeError(
                f"timing must be a can.BitTiming/BitTimingFd, got {timing!r}"
            )
        self.timing = timing
        self.is_fd = isinstance(timing, can.BitTimingFd)
        self.bus = None
        self.receive_thread = None
        self.running = False
        self.error_frames = 0
        self.receive_callback: Optional[Callable[[int, bytes], None]] = None

        self.open_bus()

    def open_bus(self):
        """Open the PCAN channel. Raises on failure so the caller can report it."""
        self.bus = can.Bus(
            channel=self.channel,
            interface="pcan",
            timing=self.timing,
            auto_reset=True,
            receive_own_messages=False,
        )

        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receive_thread.start()

    def send_frame(self, frame_id, data, dlc=None, is_fd=False, is_ext=False):
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
                is_extended_id=is_ext,
                dlc=dlc,
                is_fd=is_fd,
                bitrate_switch=is_fd,
                check=True,
            )
            self.bus.send(msg)

        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)

    def flush_tx(self) -> bool:
        """Drop frames still waiting to be transmitted; True on success.

        PcanBus has no flush_tx_buffer(), and CAN_Reset (PcanBus.reset) does not
        drop frames already handed to a PCAN-USB: on the bench 1,000 of 1,000
        queued frames still went out after it. Closing and reopening the
        channel drops them (0 of 5,000), at the cost of a ~0.4 s RX gap — so it
        is done only when the controller reports errors: on an error-free bus
        the queue drains as fast as it fills and nothing stale is left.
        """
        if self.bus is None:
            return True
        try:
            if self.bus.status() == PCAN_ERROR_OK:
                return True
            self.close()
            self.open_bus()
            return True
        except Exception as e:
            self.bus = None
            log_exception(__file__, sys._getframe().f_lineno, e)
            return False

    def _receive_loop(self):
        while self.running:
            try:
                if self.bus is not None:
                    # Short timeout: close() joins this thread, keep it responsive
                    msg = self.bus.recv(0.2)
                    if msg is not None and msg.is_error_frame:
                        # Bus-error report from the controller, not a data frame
                        # (TODO 1.13); kept for the future bus status (TODO 1.10)
                        self.error_frames += 1
                        continue
                    if msg and self.receive_callback:
                        self.receive_callback(
                            msg.arbitration_id,
                            msg.data,
                            msg.dlc,
                            msg.is_fd,
                            msg.timestamp,
                            msg.is_extended_id,
                        )
            except Exception as e:
                log_exception(__file__, sys._getframe().f_lineno, e)

    def set_receive_callback(self, callback: Optional[Callable[[int, bytes], None]]):
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
    def is_fd_capable(channel: int) -> bool:
        try:
            status, features = PCANBasic().GetValue(
                TPCANHandle(channel), PCAN_CHANNEL_FEATURES
            )
        except Exception as e:
            log_exception(__file__, sys._getframe().f_lineno, e)
            return False
        return status == PCAN_ERROR_OK and bool(features & FEATURE_FD_CAPABLE)

    @staticmethod
    def get_available_channels() -> list[tuple[str, int]]:
        CANInterface.scan_error = None
        available = []
        try:
            pcan = PCANBasic()
            status, channels_info = pcan.GetValue(PCAN_NONEBUS, PCAN_ATTACHED_CHANNELS)
        except Exception as e:
            # The vendor wrapper swallows a missing DLL and fails on first use
            CANInterface.scan_error = (
                "PCAN driver not found - install the PEAK-System device driver"
            )
            log_exception(__file__, sys._getframe().f_lineno, e)
            return available
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

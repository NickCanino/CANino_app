import can
import threading
from typing import Callable, Optional
from src.PCANBasic import PCANBasic, PCAN_ERROR_OK, PCAN_ATTACHED_CHANNELS, TPCANChannelInformation, PCAN_NONEBUS
from src.logger import log_exception

class CANInterface:
    def __init__(self, channel: str, bitrate: int = 500000):
        self.channel = channel
        self.bitrate = bitrate
        self.bus = None
        self.receive_thread = None
        self.running = False
        self.receive_callback: Optional[Callable[[int, bytes], None]] = None

        self.open_bus()

    def open_bus(self):
        try:
            self.bus = can.interface.Bus(
                channel=self.channel,
                bustype='pcan',
                bitrate=self.bitrate
            )
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
        except Exception as e:
            log_exception(e)

    def send_frame(self, frame_id, data, dlc=None):
        try:
            msg = can.Message(arbitration_id=frame_id, data=data, is_extended_id=False, dlc=dlc)
            self.bus.send(msg)
        except Exception as e:
            log_exception(e)

    def _receive_loop(self):
        while self.running:
            try:
                if self.bus is not None:
                    msg = self.bus.recv(1.0)
                    if msg and self.receive_callback:
                        self.receive_callback(msg.arbitration_id, msg.data)
            except Exception as e:
                log_exception(e)

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
                    name = ch.device_name.decode(errors="ignore")
                    display = f"USB {ch.channel_handle & 0x00F} - {name} (ID: 0x{ch.device_id:X})"
                    available.append((display, ch.channel_handle))
        return available
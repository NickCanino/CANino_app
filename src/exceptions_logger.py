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

import logging
import datetime
import os
import threading
import time

from src.utils import resource_path


try:
    with open(resource_path("VERSION"), encoding="utf-8") as f:
        __version__ = f.read().strip()
except Exception:
    __version__ = "0.0.0"

# Crea un nome file log con data e ora
log_dir = "log"
os.makedirs(log_dir, exist_ok=True)
log_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(log_dir, f"canino_app_v{__version__}_{log_time}.log")

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log_exception(filename="", line_number="", e=""):
    print(f"Exception occurred [{filename}:{line_number}]: {e}")
    logging.error("Exception occurred", exc_info=e)


class ThrottleFilter(logging.Filter):
    """Let one record per distinct message through every `interval` seconds.

    A failing bus raises on every send/recv: unthrottled, 3 IDs at 10 ms wrote
    55,205 tracebacks (33 MB) in 5 min, and python-can's "can.pcan" logger
    warns on every recv() while the bus is in error-warning (TODO 1.5).
    The next record that passes reports how many were dropped.
    """

    def __init__(self, interval: float = 1.0):
        super().__init__()
        self.interval = interval
        self._seen = {}
        self._lock = threading.Lock()

    def filter(self, record):
        key = (record.name, record.levelno, record.getMessage())
        now = time.monotonic()
        with self._lock:
            last, dropped = self._seen.get(key, (None, 0))
            if last is not None and now - last < self.interval:
                self._seen[key] = (last, dropped + 1)
                return False
            if len(self._seen) > 1000:  # bound the memory of distinct messages
                self._seen.clear()
            self._seen[key] = (now, 0)
        if dropped:
            record.msg = f"{record.getMessage()} (+{dropped} identical, not logged)"
            record.args = None
        return True


bus_logger = logging.getLogger("canino.bus")
bus_logger.addFilter(ThrottleFilter())
logging.getLogger("can.pcan").addFilter(ThrottleFilter())


def log_throttled(where: str, e: BaseException):
    """One log line (no traceback) per distinct bus error per second."""
    bus_logger.error("%s: %s: %s", where, type(e).__name__, e)

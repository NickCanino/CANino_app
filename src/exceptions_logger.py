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
import logging.handlers
import datetime
import glob
import os
import sys
import tempfile
import threading
import time

from src.utils import resource_path


try:
    with open(resource_path("VERSION"), encoding="utf-8") as f:
        __version__ = f.read().strip()
except Exception:
    __version__ = "0.0.0"

LOG_KEEP = 30  # newest log files kept; older ones are deleted at start-up
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s %(module)s:%(lineno)d: %(message)s"


def default_log_dir() -> str:
    """Per-user log folder (TODO 9.3); CANINO_LOG_DIR overrides it (tests).

    Logs used to go to ./log in the CWD - inside the OneDrive repo when run
    from source, next to the exe in dist/ - with one empty file per launch.
    """
    override = os.environ.get("CANINO_LOG_DIR")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "CANinoApp", "log")


def _prune_old_logs(directory: str, keep: int = LOG_KEEP):
    files = sorted(
        glob.glob(os.path.join(directory, "canino_app_*.log*")), key=os.path.getmtime
    )
    for old in files[:-keep] if keep else files:
        try:
            os.remove(old)
        except OSError:
            pass


log_dir = default_log_dir()
os.makedirs(log_dir, exist_ok=True)
_prune_old_logs(log_dir)
log_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(log_dir, f"canino_app_v{__version__}_{log_time}.log")

# delay=True: the file appears with the first record, so a clean session
# leaves nothing behind
_file_handler = logging.handlers.RotatingFileHandler(
    log_filename,
    maxBytes=LOG_MAX_BYTES,
    backupCount=2,
    encoding="utf-8",
    delay=True,
)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.addHandler(_file_handler)

# From source, warnings also reach the console; the windowed exe has none
if (
    not getattr(sys, "frozen", False)
    and sys.stderr is not None
    and os.environ.get("CANINO_LOG_CONSOLE", "1") != "0"
):
    _console = logging.StreamHandler()
    _console.setLevel(logging.WARNING)
    _console.setFormatter(
        logging.Formatter("[%(levelname)s] %(module)s:%(lineno)d: %(message)s")
    )
    _root.addHandler(_console)


def log_exception(e: BaseException):
    """Log `e` with its traceback, stamped with the caller's module:line (TODO 9.4)."""
    logging.getLogger("canino").error(
        "%s: %s", type(e).__name__, e, exc_info=e, stacklevel=2
    )


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

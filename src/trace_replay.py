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
"""Replay a recorded trace onto the bus, in recorded time (TODO 5.10).

A trace (`.trc`/`.asc`/`.blf`/`.log`) is read once with `can.LogReader`, then a
background thread sends the frames spaced by their recorded timestamps
(the `can.MessageSync` algorithm, with waits that stop() interrupts). Nothing here touches Qt: the GUI starts/stops the thread
and reads `sent`/`total`/`error`/`running` from its 100 ms refresh.
"""

import threading
import time

import can

from src.trace_log import TRACE_FORMATS

# Default cap on a single inter-frame wait: a longer idle gap in the recording
# is replayed as this long (MessageSync `skip`); None = recorded timing
MAX_GAP_S = 10.0
# Waits longer than this sleep on the stop event first (Event.wait oversleeps
# up to ~4 ms on Windows), then finish with time.sleep for precision
_COARSE_WAIT_S = 0.05


def load_trace(path):
    """Every message of a trace file, as a list (raises on a bad file)."""
    with can.LogReader(path) as reader:
        return list(reader)


class TraceReplayer:
    """One replay run of a trace file. Start once; poll the attributes."""

    def __init__(self, messages, send, loop=False, max_gap=MAX_GAP_S):
        # send(can.Message) -> bool; called in the replay thread
        self._messages = messages
        self._send = send
        self._loop = loop
        self._max_gap = max_gap
        self._stop = threading.Event()
        self._thread = None
        self.total = len(messages)
        self.sent = 0
        self.error = None
        self.running = False

    @staticmethod
    def is_trace(path) -> bool:
        import os

        return os.path.splitext(path or "")[1].lower() in TRACE_FORMATS

    def start(self):
        if self.running or not self._messages:
            return
        self.running = True
        self._thread = threading.Thread(
            target=self._run, name="canino-replay", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self.running = False

    def _run(self):
        try:
            while not self._stop.is_set():
                self._play_once()
                if not self._loop:
                    break
        except Exception as e:  # report to the GUI, never crash the thread
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.running = False

    def _play_once(self):
        """Send every message at its recorded offset; gaps > max_gap shrink."""
        start = time.perf_counter()
        t0 = None
        skipped = 0.0
        for msg in self._messages:
            if t0 is None:
                t0 = msg.timestamp
            wait = start + (msg.timestamp - t0 - skipped) - time.perf_counter()
            if self._max_gap and wait > self._max_gap:
                skipped += wait - self._max_gap
                wait = self._max_gap
            if wait > _COARSE_WAIT_S:
                if self._stop.wait(wait - _COARSE_WAIT_S):
                    return
                wait = start + (msg.timestamp - t0 - skipped) - time.perf_counter()
            if wait > 1e-4:
                time.sleep(wait)
            if self._stop.is_set():
                return
            self._send(msg)
            self.sent += 1

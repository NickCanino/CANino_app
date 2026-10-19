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
"""TX scheduler: one thread, absolute deadlines (TODO 2.11).

Every enabled row is a Job with a deadline on time.perf_counter_ns(); the next
deadline is the previous one + period, so timing errors never accumulate.
A deadline missed by more than a period (the thread was starved) is skipped,
keeping the row's phase, instead of being caught up with a burst (TODO 2.16).

The GUI thread adds, removes and retimes jobs; the thread only calls
`on_tick(entry)`, which must not touch Qt objects.

Windows: time.sleep() oversleeps by ~0.5 ms (high-resolution timer, Python
3.11+) and Condition.wait() by up to ~4 ms, so the thread sleeps until
SPIN_S before the deadline and spins the rest, and never waits on a condition.
"""

import heapq
import logging
import threading
import time

SPIN_S = 0.0006  # sleep until this close to the deadline, then spin
MAX_SLEEP_S = 0.005  # how late a newly added row may start at most

_log = logging.getLogger("canino.tx")


class Job:
    __slots__ = ("entry", "period_ns", "deadline", "seq", "generation", "skipped")

    def __init__(self, entry, period_ns, deadline, seq):
        self.entry = entry
        self.period_ns = period_ns
        self.deadline = deadline
        self.seq = seq  # tie-break: equal deadlines fire in add order
        self.generation = 0  # heap items of an older generation are stale
        self.skipped = 0  # deadlines dropped because the thread was late


class TxScheduler:
    # False: no thread, tests fire the jobs themselves with fire_all()
    threaded = True

    def __init__(self, on_tick):
        self._on_tick = on_tick
        self._lock = threading.Lock()
        self._heap = []  # (deadline, seq, generation, job)
        self._jobs = {}  # id(entry) -> Job
        self._seq = 0
        self._thread = None
        self._running = False

    # --- GUI thread ---

    def start(self):
        if self._running:
            return
        self._running = True
        if self.threaded:
            self._thread = threading.Thread(
                target=self._run, name="canino-tx", daemon=True
            )
            self._thread.start()

    def stop(self):
        """Stop the thread and drop every job; returns once no tick is running."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            self._heap.clear()
            self._jobs.clear()

    def add(self, entry):
        """Schedule an entry: the first frame goes out one period from now."""
        with self._lock:
            if id(entry) in self._jobs:
                return self._jobs[id(entry)]
            period = int(entry.period) * 1_000_000
            job = Job(entry, period, time.perf_counter_ns() + period, self._seq)
            self._seq += 1
            self._jobs[id(entry)] = job
            heapq.heappush(self._heap, (job.deadline, job.seq, job.generation, job))
            return job

    def remove(self, entry):
        with self._lock:
            job = self._jobs.pop(id(entry), None)
            if job is not None:
                job.generation += 1  # its heap item is skipped when popped

    def retime(self, entry):
        """New period: the next frame goes out one new period after the last one."""
        with self._lock:
            job = self._jobs.get(id(entry))
            if job is None:
                return
            period = int(entry.period) * 1_000_000
            job.deadline = max(
                job.deadline - job.period_ns + period, time.perf_counter_ns()
            )
            job.period_ns = period
            job.generation += 1
            heapq.heappush(self._heap, (job.deadline, job.seq, job.generation, job))

    def job(self, entry):
        return self._jobs.get(id(entry))

    def entries(self):
        with self._lock:
            return [j.entry for j in sorted(self._jobs.values(), key=lambda j: j.seq)]

    def fire_all(self):
        """Tests (threaded = False): one tick of every job, in add order."""
        for entry in self.entries():
            self._tick(entry)

    # --- TX thread ---

    def _tick(self, entry):
        try:
            self._on_tick(entry)
        except Exception as e:  # on_tick reports its own errors; never kill the thread
            _log.exception("TX tick of %r failed: %s", entry, e)

    def _run(self):
        while self._running:
            with self._lock:
                head = self._heap[0] if self._heap else None
            now = time.perf_counter_ns()
            if head is None:
                time.sleep(MAX_SLEEP_S)
                continue
            wait = (head[0] - now) / 1e9
            if wait > SPIN_S:
                time.sleep(min(wait - SPIN_S, MAX_SLEEP_S))
                continue
            while time.perf_counter_ns() < head[0]:
                pass  # the last fraction of a millisecond
            with self._lock:
                if not self._heap or self._heap[0] is not head:
                    continue  # changed meanwhile: look again
                heapq.heappop(self._heap)
                deadline, _, generation, job = head
                if generation != job.generation:
                    continue  # removed or retimed
            self._tick(job.entry)
            with self._lock:
                if job.generation != generation:
                    continue  # removed or retimed during the tick
                nxt = deadline + job.period_ns
                now = time.perf_counter_ns()
                if nxt <= now:  # starved for more than a period: skip, no burst
                    missed = (now - nxt) // job.period_ns + 1
                    job.skipped += missed
                    nxt += missed * job.period_ns
                job.deadline = nxt
                heapq.heappush(self._heap, (nxt, job.seq, job.generation, job))

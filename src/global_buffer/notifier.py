"""Cross-platform reader wakeup.

The default strategy is adaptive polling on the buffer's shared commit counter
(`latest_count`): the writer bumping that counter *is* the signal, so there are
no fragile named kernel objects to manage. When idle, the poll interval backs
off geometrically to ``MAX_INTERVAL`` so a quiescent reader does roughly one
atomic load every few milliseconds (negligible CPU). When samples are flowing,
the interval collapses back to ``MIN_INTERVAL`` and the reader keeps up at the
writer's rate.

A true 0-CPU kernel-blocking backend (Linux eventfd / pthread process-shared
condvar, Windows named semaphore) can be slotted in behind this same interface;
it is intentionally deferred until it can be verified on each target OS in CI.
"""
import time


class Poller:
    """Adaptive geometric backoff sleeper. Reset on activity, grow when idle."""

    MIN_INTERVAL = 50e-6      # 50 microseconds
    MAX_INTERVAL = 2e-3       # 2 milliseconds

    def __init__(self, min_interval=None, max_interval=None):
        self._min = self.MIN_INTERVAL if min_interval is None else min_interval
        self._max = self.MAX_INTERVAL if max_interval is None else max_interval
        self._cur = self._min

    def reset(self):
        self._cur = self._min

    def sleep(self):
        time.sleep(self._cur)
        self._cur = min(self._cur * 2.0, self._max)


def wait_for_count(get_count, last_count, timeout=None,
                   min_interval=None, max_interval=None, stop=None):
    """Block until ``get_count()`` exceeds ``last_count`` or ``timeout`` elapses.

    Returns the new count if progress was made, else ``None`` on timeout.
    ``stop`` is an optional callable; if it returns True the wait aborts and
    returns the current count immediately.
    """
    poller = Poller(min_interval, max_interval)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        cur = get_count()
        if cur > last_count:
            return cur
        if stop is not None and stop():
            return cur
        if deadline is not None and time.monotonic() >= deadline:
            return None
        poller.sleep()

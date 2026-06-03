import threading
import time

from global_buffer.notifier import Poller, wait_for_count


def test_poller_backoff_grows_and_resets():
    p = Poller(min_interval=0.0001, max_interval=0.0008)
    assert p._cur == 0.0001
    p.sleep()
    assert p._cur == 0.0002
    p.sleep()
    assert p._cur == 0.0004
    p.sleep()
    assert p._cur == 0.0008
    p.sleep()
    assert p._cur == 0.0008  # capped
    p.reset()
    assert p._cur == 0.0001


def test_wait_for_count_detects_progress():
    box = {"n": 0}

    def bump():
        time.sleep(0.05)
        box["n"] = 5

    t = threading.Thread(target=bump)
    t.start()
    got = wait_for_count(lambda: box["n"], last_count=0, timeout=2.0)
    t.join()
    assert got == 5


def test_wait_for_count_timeout_returns_none():
    got = wait_for_count(lambda: 0, last_count=0, timeout=0.05)
    assert got is None


def test_wait_for_count_immediate_when_already_ahead():
    got = wait_for_count(lambda: 9, last_count=3, timeout=1.0)
    assert got == 9


def test_wait_for_count_stop_aborts():
    got = wait_for_count(lambda: 0, last_count=0, timeout=5.0,
                         stop=lambda: True)
    assert got == 0

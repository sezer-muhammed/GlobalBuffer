import time

import numpy as np

import global_buffer as gb


def test_consumer_subclass_next_mode(tmp_name):
    class C(gb.Consumer):
        def callback(self):
            self.total = getattr(self, "total", 0) + int(self.data[0])

    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=8)
    ob = C.attach(tmp_name, mode="next")
    ob.start()
    time.sleep(0.05)
    for i in range(4):
        w.write(np.array([i + 1], dtype=np.int32))
    time.sleep(0.3)
    ob.stop()
    assert ob.total == 1 + 2 + 3 + 4
    w.close()
    w.unlink()


def test_consumer_latest_mode_sets_data_and_seq(tmp_name):
    class C(gb.Consumer):
        def callback(self):
            self.last_seq = self.seq
            self.last_val = int(self.data[0])

    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=4)
    ob = C.attach(tmp_name, mode="latest")
    ob.start()
    time.sleep(0.05)
    w.write(np.array([42], dtype=np.int32))
    time.sleep(0.2)
    ob.stop()
    assert ob.last_val == 42 and ob.last_seq == 0
    w.close()
    w.unlink()

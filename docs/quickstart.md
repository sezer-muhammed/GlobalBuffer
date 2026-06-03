# Quickstart

## Array stream (zero-copy)

Writer:

```python
import global_buffer as gb
import numpy as np

csi = gb.create("csi", gb.ArraySpec(dtype="complex64", shape=(64, 4)), capacity=8)

with csi.reserve() as slot:     # slot is an ndarray view into shared memory
    slot[:] = frame             # fill in place, no copy
# or: csi.write(frame)          # single-memcpy convenience form
```

Reader (any other process):

```python
r = gb.attach("csi")            # schema discovered from the segment
frame = r.latest()              # newest committed sample, or None
r.on_data(lambda sample, seq: process(sample), mode="latest")  # bg thread
```

## Message stream (pydantic)

```python
import pydantic, global_buffer as gb

class Status(pydantic.BaseModel):
    gain: float
    cam_on: bool

w = gb.create("status", Status, capacity=4, max_bytes=512)
w.write(Status(gain=1.2, cam_on=True))      # or a dict: {"gain": 1.2, "cam_on": True}

r = gb.attach("status", model=Status)        # schema mismatch -> raises on attach
msg = r.next(timeout=1.0)                     # validated Status instance
```

Attach **without** `model=` to get raw dicts instead of validated instances.

## OO consumer

```python
class CsiConsumer(gb.Consumer):
    def callback(self):                       # self.data and self.seq are set
        self.result = heavy(self.data)

ob = CsiConsumer.attach("csi", mode="latest")
ob.start()
...
ob.stop()
```

## Cleanup

```python
w.close()        # detach handle (segment survives)
w.unlink()       # owner removes the segment
gb.unlink("csi") # remove by name after a crash
```

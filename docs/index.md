# GlobalBuffer Documentation

Cross-platform, cross-process shared-memory ring buffer for Python — zero-copy
numpy arrays and pydantic messages, last-value or in-order reads, background
callbacks, near-0-CPU when idle.

`import global_buffer as gb`

## Contents

- [Installation](installation.md)
- [Quickstart](quickstart.md)
- [Concepts](concepts.md) — streams, slots, read modes, liveness
- [API reference](api.md)
- [Examples](examples.md) — including the benchmark writer/reader
- [Design](design.md) — architecture, memory layout, seqlock
- [Platform support](platform.md)
- [Development](development.md) — build, test, Docker, wheels

## 30-second tour

```python
import global_buffer as gb
import numpy as np

w = gb.create("csi", gb.ArraySpec("complex64", (64, 4)), capacity=8)
with w.reserve() as slot:        # zero-copy fill
    slot[:] = frame

r = gb.attach("csi")
frame = r.latest()               # newest sample
r.on_data(lambda s, seq: print(seq), mode="latest")
```

# Examples

All scripts live in `examples/`.

## Benchmark / showcase: `writer.py` + `reader.py`

Run one writer, then several readers in other terminals — each reader prints its
own throughput.

```bash
# terminal 1 — publish 4096-element float32 frames at 1000 Hz
python examples/writer.py --hz 1000 --size 4096

# terminal 2 — consume every frame in order, verify integrity
python examples/reader.py --mode next --verify

# terminal 3 — only ever read the newest frame
python examples/reader.py --mode latest
```

`writer.py` flags: `--name --hz` (0 = unthrottled) `--size` (elements/sample)
`--dtype --capacity --duration`.
`reader.py` flags: `--name --mode {next,latest} --verify --duration`.

By default the reader uses the **efficient** path — a background callback that
blocks until a new sample arrives (near-0 CPU when idle) and processes each sample
once — so its reported rate tracks the writer's real rate.

- **`next`** mode reports `overruns` (how far it fell behind); under a fast writer
  a slow `next` reader shows large `overruns` but `bad=0` — proof the ring is
  tear-free even while being lapped.
- **`latest`** mode reports `skipped` — frames the writer produced that this reader
  coalesced past (it only ever processes the newest). Its rate equals the number
  of *distinct* newest frames it actually handled.

### `--spin` (latest only) — raw reread bandwidth

`python examples/reader.py --mode latest --spin` busy-loops `latest()` as fast as
the CPU allows and counts every read. This produces a very large MB/s number, but
it is **rereading the same current frame repeatedly** and pins a CPU core — it
measures shared-memory reread bandwidth, **not** inter-process throughput. Use the
default (callback) path for real, efficient consumption.

## Focused examples

- `array_writer.py` / `array_reader.py` — 200 Hz CSI-style array stream with `reserve()` + `on_data`.
- `message_writer.py` / `message_reader.py` — 1 Hz pydantic `Status` stream.
- `consumer_oo.py` — self-contained `Consumer` subclass demo.

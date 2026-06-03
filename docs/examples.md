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

Each reader reports samples/s, MB/s, cumulative MB, and `overruns` (how far it
fell behind). Unthrottled on a laptop the writer pushes multiple GB/s; a `next`
reader that can't keep up shows large `overruns` but `bad=0` — proof the ring is
tear-free even under lapping.

## Focused examples

- `array_writer.py` / `array_reader.py` — 200 Hz CSI-style array stream with `reserve()` + `on_data`.
- `message_writer.py` / `message_reader.py` — 1 Hz pydantic `Status` stream.
- `consumer_oo.py` — self-contained `Consumer` subclass demo.

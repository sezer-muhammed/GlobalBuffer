# Development

## Build

```bash
python -m pip install -U pip setuptools wheel Cython numpy msgspec pydantic pytest
python setup.py build_ext --inplace
```

## Test

```bash
PYTHONPATH=src python -m pytest tests -v                       # full suite
PYTHONPATH=src python -m pytest tests -m "not crossproc_slow"  # skip long stress
```

Markers: `crossproc_slow` gates the high-rate no-torn-reads stress test.

## Docker

```bash
docker build -t globalbuffer . && docker run --rm globalbuffer   # runs fast tests
docker compose up                                                # writer + reader demo
```

## Wheels

`pyproject.toml` configures `cibuildwheel`. CI (`.github/workflows/`):

- `ci.yml` — test matrix on ubuntu/macos/windows × py3.9/3.11/3.12/3.13.
- `wheels.yml` — build wheels (incl. linux aarch64 via QEMU) + sdist on release.

## Layout invariant

`src/global_buffer/_core.pyx` mirrors a subset of the header offsets in
`layout.py` across the Python/Cython boundary. If you renumber a header field in
`layout.py`, update the `cdef enum` in `_core.pyx` to match.

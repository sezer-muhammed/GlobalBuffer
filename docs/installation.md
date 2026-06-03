# Installation

```bash
pip install GlobalBuffer
```

Prebuilt wheels cover CPython 3.9–3.13 on:

- manylinux **x86_64** and **aarch64** (Jetson)
- macOS **x86_64** and **arm64**
- Windows **amd64**

A source install needs a C11 compiler (the hot path is Cython/C).

## Dependencies

- `numpy` (array buffers, buffer-protocol views)
- `pydantic` v2 (message public API)
- `msgspec` (message wire codec)

`ctypes` is stdlib; nothing else is required at runtime.

## From source

```bash
git clone <repo> && cd GlobalBuffer
pip install -U pip setuptools wheel Cython numpy msgspec pydantic
python setup.py build_ext --inplace
PYTHONPATH=src python -c "import global_buffer as gb; print(gb.__version__)"
```

import glob as _glob
import os
import subprocess
import sys
import time

import numpy as np
import pytest

import global_buffer as gb

HELP = os.path.join(os.path.dirname(__file__), "_crossproc_helpers.py")
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
# Only override PYTHONPATH when the extension is built in-place (local dev / ci.yml).
# When running under cibuildwheel the wheel is installed into site-packages and
# the source tree has no _core.so, so we must NOT shadow it.
_ext_in_src = bool(
    _glob.glob(os.path.join(SRC, "global_buffer", "_core*.so"))
    or _glob.glob(os.path.join(SRC, "global_buffer", "_core*.pyd"))
)
ENV = dict(os.environ, PYTHONPATH=SRC) if _ext_in_src else dict(os.environ)


def _spawn(fn, *args):
    return subprocess.Popen([sys.executable, HELP, fn, *map(str, args)], env=ENV)


def test_crossproc_array_latest(tmp_path, tmp_name):
    out = tmp_path / "seen.txt"
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int64", (16,)), capacity=8)
    child = _spawn("array_reader_count", tmp_name, 50, str(out))
    time.sleep(0.5)
    for i in range(50):
        w.write(np.full(16, i, dtype=np.int64))
        time.sleep(0.005)
    child.wait(timeout=15)
    seen = int(out.read_text())
    assert seen >= 10
    w.close()
    w.unlink()


def test_crossproc_message_stream(tmp_path, tmp_name):
    import pydantic

    class Status(pydantic.BaseModel):
        gain: float
        cam_on: bool

    code = (
        "import global_buffer as gb, pydantic, time\n"
        "class Status(pydantic.BaseModel):\n"
        "    gain: float\n"
        "    cam_on: bool\n"
        f"r=gb.attach('{tmp_name}', model=Status)\n"
        "vals=[]\n"
        "import time\n"
        "deadline=time.monotonic()+10\n"
        "while len(vals)<5 and time.monotonic()<deadline:\n"
        "    try: m=r.next(timeout=1.0); vals.append(m.gain)\n"
        "    except gb.Empty: break\n"
        f"open(r'{tmp_path / 'msgs.txt'}','w').write(','.join(str(v) for v in vals))\n"
        "r.close()\n"
    )
    w = gb.create(name=tmp_name, schema=Status, capacity=8, max_bytes=256)
    child = subprocess.Popen([sys.executable, "-c", code], env=ENV)
    time.sleep(0.5)
    for i in range(5):
        w.write(Status(gain=float(i), cam_on=bool(i % 2)))
        time.sleep(0.05)
    child.wait(timeout=15)
    vals = [float(x) for x in (tmp_path / "msgs.txt").read_text().split(",") if x]
    assert vals == [0.0, 1.0, 2.0, 3.0, 4.0]
    w.close()
    w.unlink()


def test_crossproc_writer_death(tmp_name):
    code = (
        "import global_buffer as gb, numpy as np, time;"
        f"w=gb.create(name='{tmp_name}', schema=gb.ArraySpec('int32',(1,)), capacity=4);"
        "w.write(np.array([1],dtype=np.int32));"
        "time.sleep(30)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], env=ENV)
    # Poll until writer is alive (up to 10 s).  Python 3.9 on macOS spawns
    # subprocesses slowly due to notarization / dyld checks.
    deadline = time.monotonic() + 10
    r = None
    while time.monotonic() < deadline:
        time.sleep(0.2)
        try:
            if r is None:
                r = gb.attach(tmp_name)
            if r.writer_alive:
                break
        except gb.BufferNotFound:
            if r is not None:
                r.close()
                r = None
    assert r is not None and r.writer_alive is True, "writer did not come alive within 10 s"
    child.kill()
    child.wait()
    time.sleep(2.5)
    assert r.writer_alive is False
    r.close()
    gb.unlink(tmp_name)


@pytest.mark.crossproc_slow
def test_crossproc_no_torn_reads_highrate(tmp_path, tmp_name):
    out = tmp_path / "torn.txt"
    n = 5000
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int64", (256,)), capacity=16)
    child = _spawn("array_reader_torn", tmp_name, n, str(out))
    time.sleep(0.5)
    for i in range(n):
        w.write(np.full(256, i, dtype=np.int64))
    child.wait(timeout=40)
    count, bad, overruns = map(int, out.read_text().split(","))
    assert bad == 0, f"{bad} torn reads detected"
    assert count > 0
    w.close()
    w.unlink()

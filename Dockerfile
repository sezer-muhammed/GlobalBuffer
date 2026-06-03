# Build + test GlobalBuffer in a clean Linux environment.
FROM python:3.12-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -U pip setuptools wheel \
 && pip install --no-cache-dir Cython numpy msgspec pydantic pytest \
 && pip install --no-cache-dir -e . \
 && python setup.py build_ext --inplace

# Default: run the fast test suite (skips the long stress test).
CMD ["python", "-m", "pytest", "tests", "-v", "-m", "not crossproc_slow"]

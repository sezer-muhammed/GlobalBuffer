import itertools
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

_counter = itertools.count()


@pytest.fixture
def tmp_name():
    return f"gbtest_{os.getpid()}_{next(_counter)}"

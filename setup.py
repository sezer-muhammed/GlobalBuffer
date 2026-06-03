import sys

import numpy
from setuptools import Extension, setup
from Cython.Build import cythonize

if sys.platform == "win32":
    extra = ["/std:c11", "/O2"]
else:
    extra = ["-std=c11", "-O3"]

ext = Extension(
    "global_buffer._core",
    sources=["src/global_buffer/_core.pyx"],
    include_dirs=[numpy.get_include(), "src/global_buffer"],
    extra_compile_args=extra,
)

setup(ext_modules=cythonize([ext], language_level=3))

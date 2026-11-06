# SPDX-License-Identifier: MIT
"""Build hook: ship the C runtime inside the package.

The repository keeps the runtime at `runtime/`, beside `lib/`, because the
Makefile, the tests and the provenance checks all address it there. An
installed `yaccc` needs it *inside* the package instead, since that is the only
tree a wheel can carry, and the driver looks for `yaccc/runtime` first.

Copying at build time keeps one source of truth. `package_data` alone cannot do
it, because the directory is not under the package in the checkout.
"""
import glob
import os
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = os.path.dirname(os.path.abspath(__file__))


class build_py_with_runtime(build_py):
    """build_py, plus runtime/*.c and *.h copied into the package."""

    def run(self):
        super().run()
        dest = os.path.join(self.build_lib, 'yaccc', 'runtime')
        os.makedirs(dest, exist_ok=True)
        copied = 0
        for pattern in ('*.c', '*.h'):
            for src in sorted(glob.glob(os.path.join(ROOT, 'runtime', pattern))):
                shutil.copy2(src, dest)
                copied += 1
        if not copied:
            raise RuntimeError('no runtime sources found to package in %s/runtime'
                               % ROOT)


setup(cmdclass={'build_py': build_py_with_runtime})

# SPDX-License-Identifier: MIT
"""python -m yaccc, for a checkout or an installed package alike."""
import sys

from .driver import main

if __name__ == '__main__':
    sys.exit(main())

"""PyInstaller entry point (relative imports do not work on a module run as a script)."""

import sys

from jnvim.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

"""Allow ``python -m qcomdtgen``."""

import sys

from qcomdtgen.cli import main

if __name__ == "__main__":
    sys.exit(main())

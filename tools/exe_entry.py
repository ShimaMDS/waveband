"""What Waveband.exe runs. Only used by tools/build_release.py."""

import sys

from wwmeter.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

"""Run pytest and bypass a Linux test-container native shutdown stall.

All test results and teardown hooks complete before pytest.main returns. Some
OpenCV/TestClient combinations in the current Linux verification image can then
stall during native interpreter finalization even though only MainThread remains.
The installed Windows application does not use this script. It is a packaging
verification harness that preserves the real pytest return code.
"""

import os
import sys

import pytest


def main() -> None:
    args = sys.argv[1:] or ["-q"]
    return_code = int(pytest.main(args))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(return_code)


if __name__ == "__main__":
    main()

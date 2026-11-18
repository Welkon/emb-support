#!/usr/bin/env python3
"""Entry point for the ATK-Logic skill.

Kept tiny on purpose: the package under ``atklogic/`` holds the code, so tests
can import it without executing argument parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atklogic.commands import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

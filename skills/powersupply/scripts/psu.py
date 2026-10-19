#!/usr/bin/env python3
"""Generic programmable power-supply CLI for LAN, USB and serial instruments."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psuscpi.common import *  # noqa: F401,F403
from psuscpi.transport import *  # noqa: F401,F403
from psuscpi.dialects import *  # noqa: F401,F403
from psuscpi.cli import main  # noqa: F401


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        if os.environ.get("PSU_DEBUG"):
            raise
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

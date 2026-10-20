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


def _run_bridge() -> None:
    """Forward to the Windows interpreter when --bridge windows is given."""
    from psuscpi import bridge

    argv, win_python = bridge.extract_python_flag(sys.argv)
    sys.argv = argv
    requested = bridge.wants_bridge(sys.argv)
    if not requested:
        return
    if requested != bridge.BRIDGE_WINDOWS:
        print(json.dumps({"ok": False, "error":
                          f"unknown bridge '{requested}'; the only bridge is 'windows'"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(bridge.run(sys.argv, win_python))
    except (bridge.BridgeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "bridge": "windows"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _run_bridge()
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

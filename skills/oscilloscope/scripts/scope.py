#!/usr/bin/env python3
"""Generic oscilloscope CLI for LAN and USB instruments.

This is the stable entry point. The implementation is split into the
`scopescpi` package:

  common.py       configuration, output and framing helpers
  transport.py    raw SCPI socket, pyvisa, Linux usbtmc
  dialects/       one module per vendor dialect
  acquisition.py  waveform scaling, statistics, measurements
  cli.py          subcommands and argument parsing

All public names are re-exported here for backwards compatibility with
scripts that imported this file as a module.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scopescpi.common import *  # noqa: F401,F403
from scopescpi.common import _parse_rate, _parse_scaled  # noqa: F401
from scopescpi.transport import *  # noqa: F401,F403
from scopescpi.dialects import *  # noqa: F401,F403
from scopescpi.dialects import _q_first  # noqa: F401
from scopescpi.acquisition import *  # noqa: F401,F403
from scopescpi.acquisition import _edges  # noqa: F401
from scopescpi.cli import main  # noqa: F401


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # keep output machine-readable for agents
        if os.environ.get("SCOPE_DEBUG"):
            raise
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

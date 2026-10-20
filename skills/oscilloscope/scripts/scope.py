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
from scopescpi.dialects import _q_first, parse_wavedesc  # noqa: F401
from scopescpi.acquisition import *  # noqa: F401,F403
from scopescpi.acquisition import _edges  # noqa: F401
from scopescpi.quality import check as check_quality  # noqa: F401
from scopescpi.analysis import (  # noqa: F401
    advanced, decimate, load_npz, save_npz, spectrum, write_svg,
)
from scopescpi.transport import pick_single_resource  # noqa: F401
from scopescpi.wsl import (  # noqa: F401
    attach_hint, attach_scope_devices, ensure_scope_attached, is_wsl,
    list_devices, parse_usbipd, usbipd_path, windows_host_ip,
)

# Startup detection: cheap, no usbipd call. The attach happens lazily in connect().
WSL = is_wsl()
if WSL:
    os.environ.setdefault("SCOPE_WSL", "1")
from scopescpi.cli import main  # noqa: F401


def _ensure_runtime() -> None:
    """Run inside the skill venv when it exists, so pyvisa/pyusb are consistent."""
    if os.environ.get("SCOPE_NO_REEXEC"):
        return
    home = Path(os.environ.get("SCOPE_HOME", str(Path.home() / ".local/share/scope")))
    py = home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv_root = (home / "venv").resolve()
    if py.exists() and Path(sys.prefix).resolve() != venv_root:
        os.execv(str(py), [str(py), str(Path(__file__).resolve())] + sys.argv[1:])


if __name__ == "__main__":
    _ensure_runtime()
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

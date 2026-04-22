#!/usr/bin/env python3
"""Tektronix oscilloscope helper for VISA/SCPI control and waveform export."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PREAMBLE_FIELDS = {
    "x_increment": ("WFMPre:XINcr?", "WFMOutpre:XINcr?", "WFMPRE:XINCR?"),
    "x_zero": ("WFMPre:XZEro?", "WFMOutpre:XZEro?", "WFMPRE:XZERO?"),
    "point_offset": ("WFMPre:PT_Off?", "WFMOutpre:PT_Off?", "WFMPRE:PT_OFF?"),
    "y_multiplier": ("WFMPre:YMUlt?", "WFMOutpre:YMUlt?", "WFMPRE:YMULT?"),
    "y_zero": ("WFMPre:YZEro?", "WFMOutpre:YZEro?", "WFMPRE:YZERO?"),
    "y_offset": ("WFMPre:YOFf?", "WFMOutpre:YOFf?", "WFMPRE:YOFF?"),
    "record_length": (
        "WFMPre:NR_Pt?",
        "WFMOutpre:NR_Pt?",
        "WFMPRE:NR_PT?",
        "HORizontal:RECOrdlength?",
    ),
}


CONTROL_PLACEHOLDER_HELP = {
    "channel": "Analog channel selector such as CH1 or CH2.",
    "channel_number": "Numeric channel suffix derived from --channel.",
    "waveform": "Waveform selector such as CH1, CH2, MATH, REFA, REFB, or FFT.",
    "slot": "Slot selector used by MEAS<x> or TP<x> style commands.",
    "index": "Cursor index such as 1 or 2.",
    "value": "Raw SCPI value payload appended after the command header.",
}

CONTROL_STATUS_SUPPORTED = "supported"
CONTROL_STATUS_GUARDED = "guarded"
CONTROL_STATUS_UNSUPPORTED = "unsupported"

CONTROL_STATUS_HELP = {
    CONTROL_STATUS_SUPPORTED: "Verified on a live TBS1102B.",
    CONTROL_STATUS_GUARDED: "Has side effects or external dependencies and therefore requires explicit opt-in.",
    CONTROL_STATUS_UNSUPPORTED: "Rechecked on TBS1102B and confirmed unsupported or not applicable.",
}

TBS1102B_VALIDATION_DATE = "2026-04-22"
TBS1102B_VALIDATION_REPORT = (
    "captures/tbs1102b-control-full-hw-test-20260422-r2.json"
)
TBS1102B_RECHECK_REPORT = (
    "captures/tbs1102b-control-failed-recheck-20260422.json"
)

MONITOR_CONFIG_FIELDS = (
    "resource",
    "backend",
    "timeout_ms",
    "model",
    "channels",
    "outdir",
    "prefix",
    "start",
    "stop",
    "settle_ms",
    "show_hidden",
    "setup_channel",
    "ensure_visible",
    "channel_scale",
    "channel_position",
    "horizontal_scale",
    "trigger_type",
    "trigger_source",
    "trigger_level",
    "trigger_mode",
    "trigger_slope",
    "trigger_coupling",
    "pulse_when",
    "pulse_width",
    "pulse_polarity",
    "arm_stopafter",
    "auto_rearm",
    "mode",
    "query",
    "match",
    "match_mode",
    "initial_match",
    "poll_interval_ms",
    "max_polls",
    "duration_s",
    "max_events",
    "pre_write",
    "rearm_write",
    "wait_opc",
)

MONITOR_LIST_FIELDS = frozenset(("match", "pre_write", "rearm_write"))

MONITOR_DEFAULTS = {
    "resource": None,
    "backend": None,
    "timeout_ms": 5000,
    "model": "TBS1102B",
    "channels": "CH1",
    "outdir": "captures",
    "prefix": "monitor",
    "start": 1,
    "stop": None,
    "settle_ms": 0,
    "show_hidden": False,
    "setup_channel": None,
    "ensure_visible": False,
    "channel_scale": None,
    "channel_position": None,
    "horizontal_scale": None,
    "trigger_type": None,
    "trigger_source": None,
    "trigger_level": None,
    "trigger_mode": None,
    "trigger_slope": None,
    "trigger_coupling": None,
    "pulse_when": None,
    "pulse_width": None,
    "pulse_polarity": None,
    "arm_stopafter": None,
    "auto_rearm": False,
    "mode": "trigger",
    "query": None,
    "match": None,
    "match_mode": "exact",
    "initial_match": False,
    "poll_interval_ms": 200,
    "max_polls": None,
    "duration_s": None,
    "max_events": 1,
    "pre_write": None,
    "rearm_write": None,
    "wait_opc": False,
}

MONITOR_PRESETS = {
    "glitch-short": {
        "description": "Short glitch or narrow pulse monitoring with pulse-width trigger settings.",
        "monitor": {
            "mode": "trigger",
            "match": ["SAVE"],
            "ensure_visible": True,
            "trigger_type": "pulse",
            "trigger_mode": "NORMal",
            "pulse_when": "LESSthan",
            "pulse_width": "2.0E-6",
            "pulse_polarity": "POSitive",
            "horizontal_scale": "5.0E-6",
            "arm_stopafter": "SEQuence",
            "auto_rearm": True,
            "max_events": 5,
        },
        "recommended_overrides": [
            "--trigger-level",
            "--channel-scale",
            "--channel-position",
            "--trigger-source",
        ],
    },
    "power-on-spike": {
        "description": "Power-on spike or startup transient monitoring with edge single-sequence trigger settings.",
        "monitor": {
            "mode": "trigger",
            "match": ["SAVE"],
            "ensure_visible": True,
            "trigger_type": "edge",
            "trigger_mode": "NORMal",
            "trigger_slope": "RISE",
            "horizontal_scale": "1.0E-3",
            "arm_stopafter": "SEQuence",
            "max_events": 3,
        },
        "recommended_overrides": [
            "--trigger-level",
            "--channel-scale",
            "--trigger-source",
        ],
    },
    "intermittent-noise": {
        "description": "Intermittent noise monitoring with repeated waiting and automatic re-arm.",
        "monitor": {
            "mode": "trigger",
            "match": ["SAVE"],
            "ensure_visible": True,
            "trigger_type": "edge",
            "trigger_mode": "NORMal",
            "trigger_slope": "RISE",
            "horizontal_scale": "1.0E-4",
            "arm_stopafter": "SEQuence",
            "auto_rearm": True,
            "max_events": 10,
        },
        "recommended_overrides": [
            "--trigger-level",
            "--channel-scale",
            "--trigger-source",
            "--trigger-slope",
        ],
    },
    "missing-pulse": {
        "description": "Missing-pulse or stretched-pulse monitoring with long-width pulse trigger settings.",
        "monitor": {
            "mode": "trigger",
            "match": ["SAVE"],
            "ensure_visible": True,
            "trigger_type": "pulse",
            "trigger_mode": "NORMal",
            "pulse_when": "MOREthan",
            "pulse_width": "2.0E-4",
            "pulse_polarity": "POSitive",
            "horizontal_scale": "1.0E-3",
            "arm_stopafter": "SEQuence",
            "auto_rearm": True,
            "max_events": 5,
        },
        "recommended_overrides": [
            "--pulse-width",
            "--trigger-level",
            "--channel-scale",
            "--trigger-source",
        ],
    },
    "burst-pulse": {
        "description": "Burst-pulse monitoring for narrow anomalies inside a pulse train with automatic re-arm.",
        "monitor": {
            "mode": "trigger",
            "match": ["SAVE"],
            "ensure_visible": True,
            "trigger_type": "pulse",
            "trigger_mode": "NORMal",
            "pulse_when": "LESSthan",
            "pulse_width": "5.0E-6",
            "pulse_polarity": "POSitive",
            "horizontal_scale": "1.0E-4",
            "arm_stopafter": "SEQuence",
            "auto_rearm": True,
            "max_events": 5,
        },
        "recommended_overrides": [
            "--trigger-level",
            "--channel-scale",
            "--channel-position",
            "--trigger-source",
        ],
    },
}

MONITOR_ARM_VERIFY_ATTEMPTS = 2

TBS1102B_OPERATION_POLICIES = {
    "calibration.self": {
        "get": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "calibration.abort": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "calibration.continue": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "calibration.factory": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "calibration.internal": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "cursor.vbars.slope": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        }
    },
    "display.brightness": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "display.contrast": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "display.invert": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "filesystem.delete": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "filesystem.format": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "filesystem.mkdir": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "filesystem.rename": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "filesystem.rmdir": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "hardcopy": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "horizontal.delay": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        }
    },
    "horizontal.delay.position": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "horizontal.delay.scale": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "horizontal.view": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "limit.template": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "limit.template.save_first_source": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "limit.template.save_second_source": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "limit.template.save_source": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "pictbridge.defaults": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "recall.slot": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "recall.setup": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        },
    },
    "recall.waveform": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        },
    },
    "save.image": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "save.setup": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        },
    },
    "save.slot": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "save.waveform": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        },
    },
    "system.autoset": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "system.autoset.enable": {
        "get": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
        "set": {
            "status": CONTROL_STATUS_UNSUPPORTED,
            "reason": "See vendor documentation.",
        },
    },
    "system.ddt": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "system.factory": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "system.remark": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "system.reset": {
        "action": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
    "waveform.curve": {
        "set": {
            "status": CONTROL_STATUS_GUARDED,
            "reason": "See vendor documentation.",
        }
    },
}


def make_control_spec(
    key,
    group,
    description,
    *,
    query=None,
    set_command=None,
    action=None,
    placeholders=(),
    value_help=None,
    note=None,
    aliases=(),
):
    return {
        "key": key,
        "group": group,
        "description": description,
        "query": query,
        "set": set_command,
        "action": action,
        "placeholders": tuple(placeholders),
        "value_help": value_help,
        "note": note,
        "aliases": tuple(aliases),
    }


def state_control(
    key,
    group,
    header,
    description,
    *,
    placeholders=(),
    value_help=None,
    note=None,
    aliases=(),
):
    return make_control_spec(
        key,
        group,
        description,
        query=f"{header}?",
        set_command=f"{header} {{value}}",
        placeholders=placeholders,
        value_help=value_help,
        note=note,
        aliases=aliases,
    )


def query_control(
    key,
    group,
    command,
    description,
    *,
    placeholders=(),
    note=None,
    aliases=(),
):
    return make_control_spec(
        key,
        group,
        description,
        query=command,
        placeholders=placeholders,
        note=note,
        aliases=aliases,
    )


def action_control(
    key,
    group,
    command,
    description,
    *,
    placeholders=(),
    note=None,
    aliases=(),
):
    return make_control_spec(
        key,
        group,
        description,
        action=command,
        placeholders=placeholders,
        note=note,
        aliases=aliases,
    )


def query_action_control(
    key,
    group,
    header,
    description,
    *,
    placeholders=(),
    note=None,
    aliases=(),
):
    return make_control_spec(
        key,
        group,
        description,
        query=f"{header}?",
        action=header,
        placeholders=placeholders,
        note=note,
        aliases=aliases,
    )


CONTROL_SPEC_LIST = [
    query_control(
        "calibration.self",
        "calibration",
        "*CAL?",
        "See vendor documentation.",
    ),
    action_control(
        "calibration.abort",
        "calibration",
        "CALibrate:ABOrt",
        "See vendor documentation.",
    ),
    action_control(
        "calibration.continue",
        "calibration",
        "CALibrate:CONTINUE",
        "See vendor documentation.",
    ),
    action_control(
        "calibration.factory",
        "calibration",
        "CALibrate:FACtory",
        "See vendor documentation.",
    ),
    action_control(
        "calibration.internal",
        "calibration",
        "CALibrate:INTERNAL",
        "See vendor documentation.",
    ),
    query_control(
        "calibration.status",
        "calibration",
        "CALibrate:STATUS?",
        "See vendor documentation.",
    ),
    query_control(
        "diagnostic.result.flag",
        "calibration",
        "DIAg:RESUlt:FLAg?",
        "See vendor documentation.",
    ),
    query_control(
        "diagnostic.result.log",
        "calibration",
        "DIAg:RESUlt:LOG?",
        "See vendor documentation.",
    ),
    query_control(
        "errorlog.first",
        "calibration",
        "ERRLOG:FIRST?",
        "See vendor documentation.",
    ),
    query_control(
        "errorlog.next",
        "calibration",
        "ERRLOG:NEXT?",
        "See vendor documentation.",
    ),
    query_control(
        "counter",
        "counter",
        "COUNTERFreq?",
        "See vendor documentation.",
    ),
    state_control(
        "counter.channel.level",
        "counter",
        "COUNTERFreq:CH{channel_number}Level",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
    ),
    state_control(
        "counter.channel.state",
        "counter",
        "COUNTERFreq:CH{channel_number}State",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="ON|OFF",
    ),
    query_control(
        "counter.channel.value",
        "counter",
        "COUNTERFreq:CH{channel_number}Value?",
        "See vendor documentation.",
        placeholders=("channel",),
    ),
    state_control(
        "cursor",
        "cursor",
        "CURSor",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "cursor.hbars",
        "cursor",
        "CURSor:HBArs?",
        "See vendor documentation.",
    ),
    query_control(
        "cursor.hbars.delta",
        "cursor",
        "CURSor:HBArs:DELTa?",
        "See vendor documentation.",
    ),
    state_control(
        "cursor.hbars.position",
        "cursor",
        "CURSor:HBArs:POSITION{index}",
        "See vendor documentation.",
        placeholders=("index",),
        value_help="See vendor documentation.",
    ),
    query_control(
        "cursor.hbars.units",
        "cursor",
        "CURSor:HBArs:UNIts?",
        "See vendor documentation.",
    ),
    state_control(
        "cursor.select.source",
        "cursor",
        "CURSor:SELect:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|MATH|REFA|REFB",
    ),
    query_control(
        "cursor.vbars",
        "cursor",
        "CURSor:VBArs?",
        "See vendor documentation.",
    ),
    query_control(
        "cursor.vbars.delta",
        "cursor",
        "CURSor:VBArs:DELTa?",
        "See vendor documentation.",
        aliases=("cursor.vbars.hdelta",),
    ),
    query_control(
        "cursor.vbars.hpos",
        "cursor",
        "CURSor:VBArs:HPOS{index}?",
        "See vendor documentation.",
        placeholders=("index",),
    ),
    state_control(
        "cursor.vbars.position",
        "cursor",
        "CURSor:VBArs:POSITION{index}",
        "See vendor documentation.",
        placeholders=("index",),
        value_help="See vendor documentation.",
    ),
    query_control(
        "cursor.vbars.slope",
        "cursor",
        "CURSor:VBArs:SLOPE?",
        "See vendor documentation.",
    ),
    state_control(
        "cursor.vbars.units",
        "cursor",
        "CURSor:VBArs:UNIts",
        "See vendor documentation.",
        value_help="TIME|FREQuency",
    ),
    query_control(
        "cursor.vbars.vdelta",
        "cursor",
        "CURSor:VBArs:VDELTa?",
        "See vendor documentation.",
    ),
    query_control(
        "datalogging",
        "datalogging",
        "DATALOGging?",
        "See vendor documentation.",
    ),
    state_control(
        "datalogging.duration",
        "datalogging",
        "DATALOGging:DURAtion",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "datalogging.source",
        "datalogging",
        "DATALOGging:SOURCE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "datalogging.state",
        "datalogging",
        "DATALOGging:STATE",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    query_control(
        "display",
        "display",
        "DISplay?",
        "See vendor documentation.",
    ),
    state_control(
        "display.backlight",
        "display",
        "DISplay:BACKLight",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "display.brightness",
        "display",
        "DISplay:BRIGHTness",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "display.contrast",
        "display",
        "DISplay:CONTRast",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "display.format",
        "display",
        "DISplay:FORMat",
        "See vendor documentation.",
        value_help="YT|XY",
    ),
    state_control(
        "display.invert",
        "display",
        "DISplay:INVert",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "display.persistence",
        "display",
        "DISplay:PERSistence",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "display.style",
        "display",
        "DISplay:STYle",
        "See vendor documentation.",
        value_help="DOTS|VECTors",
    ),
    query_control(
        "fft",
        "fft",
        "FFT?",
        "See vendor documentation.",
    ),
    state_control(
        "fft.horizontal.position",
        "fft",
        "FFT:HORizontal:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "fft.horizontal.scale",
        "fft",
        "FFT:HORizontal:SCAle",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "fft.source",
        "fft",
        "FFT:SOURce",
        "See vendor documentation.",
        value_help="CH1|CH2",
    ),
    state_control(
        "fft.source_waveform",
        "fft",
        "FFT:SRCWFM",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "fft.vertical.position",
        "fft",
        "FFT:VERtical:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "fft.vertical.scale",
        "fft",
        "FFT:VERtical:SCAle",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "fft.window",
        "fft",
        "FFT:WIN",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "filesystem",
        "filesystem",
        "FILESystem?",
        "See vendor documentation.",
    ),
    state_control(
        "filesystem.cwd",
        "filesystem",
        "FILESystem:CWD",
        "See vendor documentation.",
        value_help='Path example: "/usb0/".',
    ),
    make_control_spec(
        "filesystem.delete",
        "filesystem",
        "Delete a file from external storage.",
        set_command="FILESystem:DELEte {value}",
        value_help='File path example: "/usb0/OLD.CSV".',
    ),
    query_control(
        "filesystem.dir",
        "filesystem",
        "FILESystem:DIR?",
        "See vendor documentation.",
    ),
    action_control(
        "filesystem.format",
        "filesystem",
        "FILESystem:FORMat",
        "See vendor documentation.",
        note="See vendor documentation.",
    ),
    query_control(
        "filesystem.freespace",
        "filesystem",
        "FILESystem:FREESpace?",
        "See vendor documentation.",
    ),
    make_control_spec(
        "filesystem.mkdir",
        "filesystem",
        "Create a directory on external storage.",
        set_command="FILESystem:MKDir {value}",
        value_help='Directory path example: "/usb0/DATA".',
    ),
    make_control_spec(
        "filesystem.rename",
        "filesystem",
        "Rename a file or directory on external storage.",
        set_command="FILESystem:REName {value}",
        value_help='Raw parameter example: "\"/usb0/A.CSV\",\"/usb0/B.CSV\"".',
    ),
    make_control_spec(
        "filesystem.rmdir",
        "filesystem",
        "Remove a directory from external storage.",
        set_command="FILESystem:RMDir {value}",
        value_help='Directory path example: "/usb0/OLD".',
    ),
    action_control(
        "hardcopy",
        "hardcopy",
        "HARDCopy",
        "See vendor documentation.",
    ),
    state_control(
        "hardcopy.button",
        "hardcopy",
        "HARDCopy:BUTTON",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "hardcopy.format",
        "hardcopy",
        "HARDCopy:FORMat",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "hardcopy.inksaver",
        "hardcopy",
        "HARDCopy:INKSaver",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "hardcopy.layout",
        "hardcopy",
        "HARDCopy:LAYout",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "hardcopy.port",
        "hardcopy",
        "HARDCopy:PORT",
        "See vendor documentation.",
        value_help="USB|RS232|GPIB|CENTronics",
    ),
    query_control(
        "horizontal",
        "horizontal",
        "HORizontal?",
        "See vendor documentation.",
    ),
    query_control(
        "horizontal.delay",
        "horizontal",
        "HORizontal:DELay?",
        "See vendor documentation.",
        note="See vendor documentation.",
    ),
    state_control(
        "horizontal.delay.position",
        "horizontal",
        "HORizontal:DELay:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
        note="See vendor documentation.",
    ),
    state_control(
        "horizontal.delay.scale",
        "horizontal",
        "HORizontal:DELay:SCAle",
        "See vendor documentation.",
        value_help="See vendor documentation.",
        aliases=("horizontal.delay.secdiv",),
        note="See vendor documentation.",
    ),
    query_control(
        "horizontal.main",
        "horizontal",
        "HORizontal:MAIn?",
        "See vendor documentation.",
    ),
    state_control(
        "horizontal.main.position",
        "horizontal",
        "HORizontal:MAIn:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "horizontal.main.scale",
        "horizontal",
        "HORizontal:MAIn:SCAle",
        "See vendor documentation.",
        value_help="See vendor documentation.",
        aliases=("horizontal.main.secdiv", "horizontal.scale", "horizontal.secdiv"),
    ),
    state_control(
        "horizontal.position",
        "horizontal",
        "HORizontal:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "horizontal.record_length",
        "horizontal",
        "HORizontal:RECOrdlength?",
        "See vendor documentation.",
    ),
    state_control(
        "horizontal.view",
        "horizontal",
        "HORizontal:VIEW",
        "See vendor documentation.",
        value_help="See vendor documentation.",
        note="See vendor documentation.",
    ),
    query_control(
        "limit",
        "limit",
        "LIMit?",
        "See vendor documentation.",
    ),
    query_control(
        "limit.result.fail",
        "limit",
        "LIMit:RESUlt:FAIL?",
        "See vendor documentation.",
    ),
    query_control(
        "limit.result.pass",
        "limit",
        "LIMit:RESUlt:PASS?",
        "See vendor documentation.",
    ),
    query_control(
        "limit.result.total",
        "limit",
        "LIMit:RESUlt:TOTAL?",
        "See vendor documentation.",
    ),
    state_control(
        "limit.save_image",
        "limit",
        "LIMit:SAVEIMAge",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "limit.save_waveform",
        "limit",
        "LIMit:SAVEWFM",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "limit.source",
        "limit",
        "LIMit:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2",
    ),
    state_control(
        "limit.state",
        "limit",
        "LIMit:STATE",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "limit.stopafter.mode",
        "limit",
        "LIMit:STOPAfter:MODe",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "limit.stopafter.time",
        "limit",
        "LIMit:STOPAfter:TIMe",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "limit.stopafter.violation",
        "limit",
        "LIMit:STOPAfter:VIOLation",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "limit.stopafter.waveform",
        "limit",
        "LIMit:STOPAfter:WAVEform",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    action_control(
        "limit.template",
        "limit",
        "LIMit:TEMPLate",
        "See vendor documentation.",
    ),
    state_control(
        "limit.template.source",
        "limit",
        "LIMit:TEMPLate:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|REFA|REFB",
    ),
    state_control(
        "limit.template.dual_source",
        "limit",
        "LIMit:TEMPlate:DUALSOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|REFA|REFB",
    ),
    action_control(
        "limit.template.save_first_source",
        "limit",
        "LIMit:TEMPLate:SAVEFIRSource",
        "See vendor documentation.",
    ),
    action_control(
        "limit.template.save_second_source",
        "limit",
        "LIMit:TEMPLate:SAVESECSource",
        "See vendor documentation.",
    ),
    action_control(
        "limit.template.save_source",
        "limit",
        "LIMit:TEMPLate:SAVESOUrce",
        "See vendor documentation.",
    ),
    state_control(
        "limit.template.tolerance.horizontal",
        "limit",
        "LIMit:TEMPLate:TOLerance:HORizontal",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "limit.template.tolerance.vertical",
        "limit",
        "LIMit:TEMPLate:TOLerance:VERTical",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "math",
        "math",
        "MATH?",
        "See vendor documentation.",
    ),
    state_control(
        "math.define",
        "math",
        "MATH:DEFINE",
        "See vendor documentation.",
        value_help='Expression example: "CH1-CH2".',
    ),
    query_control(
        "math.vertical",
        "math",
        "MATH:VERtical?",
        "See vendor documentation.",
    ),
    state_control(
        "math.vertical.position",
        "math",
        "MATH:VERtical:POSition",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "math.vertical.scale",
        "math",
        "MATH:VERtical:SCAle",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "measurement",
        "measurement",
        "MEASUrement?",
        "See vendor documentation.",
    ),
    action_control(
        "measurement.clear_snapshot",
        "measurement",
        "MEASUrement:CLEARSNAPSHOT",
        "See vendor documentation.",
    ),
    state_control(
        "measurement.gating",
        "measurement",
        "MEASUrement:GATing",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "measurement.immediate",
        "measurement",
        "MEASUrement:IMMed?",
        "See vendor documentation.",
    ),
    state_control(
        "measurement.immediate.source",
        "measurement",
        "MEASUrement:IMMed:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|MATH",
    ),
    state_control(
        "measurement.immediate.type",
        "measurement",
        "MEASUrement:IMMed:TYPe",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "measurement.immediate.units",
        "measurement",
        "MEASUrement:IMMed:UNIts?",
        "See vendor documentation.",
    ),
    query_control(
        "measurement.immediate.value",
        "measurement",
        "MEASUrement:IMMed:VALue?",
        "See vendor documentation.",
    ),
    query_control(
        "measurement.slot",
        "measurement",
        "MEASUrement:MEAS{slot}?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    state_control(
        "measurement.slot.source",
        "measurement",
        "MEASUrement:MEAS{slot}:SOUrce",
        "See vendor documentation.",
        placeholders=("slot",),
        value_help="CH1|CH2|MATH",
    ),
    state_control(
        "measurement.slot.type",
        "measurement",
        "MEASUrement:MEAS{slot}:TYPe",
        "See vendor documentation.",
        placeholders=("slot",),
        value_help="See vendor documentation.",
    ),
    query_control(
        "measurement.slot.units",
        "measurement",
        "MEASUrement:MEAS{slot}:UNIts?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "measurement.slot.value",
        "measurement",
        "MEASUrement:MEAS{slot}:VALue?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    action_control(
        "measurement.snapshot",
        "measurement",
        "MEASUrement:SNAPSHOT",
        "See vendor documentation.",
    ),
    state_control(
        "measurement.snapshot.source",
        "measurement",
        "MEASUrement:SNAPSOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|MATH",
    ),
    query_control(
        "system.autorange",
        "system",
        "AUTORange?",
        "See vendor documentation.",
    ),
    state_control(
        "system.autorange.settings",
        "system",
        "AUTORange:SETTings",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "system.autorange.state",
        "system",
        "AUTORange:STATE",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    action_control(
        "system.autoset",
        "system",
        "AUTOSet",
        "See vendor documentation.",
    ),
    state_control(
        "system.autoset.enable",
        "system",
        "AUTOSet:ENABLE",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    query_control(
        "system.autoset.signal",
        "system",
        "AUTOSet:SIGNAL?",
        "See vendor documentation.",
    ),
    state_control(
        "system.autoset.view",
        "system",
        "AUTOSet:VIEW",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "system.date",
        "system",
        "DATE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "system.ddt",
        "system",
        "*DDT",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    action_control(
        "system.factory",
        "system",
        "FACtory",
        "See vendor documentation.",
    ),
    state_control(
        "system.header",
        "system",
        "HEADer",
        "See vendor documentation.",
        value_help="ON|OFF",
        aliases=("system.hdr",),
    ),
    query_control(
        "system.id_short",
        "system",
        "ID?",
        "See vendor documentation.",
    ),
    query_control(
        "system.identify",
        "system",
        "*IDN?",
        "See vendor documentation.",
    ),
    state_control(
        "system.language",
        "system",
        "LANGuage",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    action_control(
        "system.lock",
        "system",
        "LOCk",
        "See vendor documentation.",
    ),
    query_control(
        "system.learn",
        "system",
        "*LRN?",
        "See vendor documentation.",
        aliases=("system.set",),
    ),
    make_control_spec(
        "system.remark",
        "system",
        "See vendor documentation.",
        set_command="REM {value}",
        value_help="See vendor documentation.",
        note="See vendor documentation.",
    ),
    action_control(
        "system.reset",
        "system",
        "*RST",
        "See vendor documentation.",
    ),
    state_control(
        "system.time",
        "system",
        "TIMe",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    action_control(
        "system.trigger",
        "system",
        "*TRG",
        "See vendor documentation.",
    ),
    query_control(
        "system.self_test",
        "system",
        "*TST?",
        "See vendor documentation.",
    ),
    action_control(
        "system.unlock",
        "system",
        "UNLock",
        "See vendor documentation.",
    ),
    state_control(
        "system.verbose",
        "system",
        "VERBose",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    action_control(
        "pictbridge.defaults",
        "pictbridge",
        "PICTBridge:DEF",
        "See vendor documentation.",
    ),
    state_control(
        "pictbridge.paper_size",
        "pictbridge",
        "PICTBridge:PAPERSIZE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "pictbridge.image_size",
        "pictbridge",
        "PICTBridge:IMAGESIZE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "pictbridge.paper_type",
        "pictbridge",
        "PICTBridge:PAPERTYPE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "pictbridge.print_quality",
        "pictbridge",
        "PICTBridge:PRINTQUAL",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "pictbridge.date_print",
        "pictbridge",
        "PICTBridge:DATEPRINT",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    state_control(
        "pictbridge.id_print",
        "pictbridge",
        "PICTBridge:IDPRINT",
        "See vendor documentation.",
        value_help="ON|OFF",
    ),
    make_control_spec(
        "recall.slot",
        "save",
        "See vendor documentation.",
        set_command="*RCL {value}",
        value_help="See vendor documentation.",
    ),
    state_control(
        "recall.setup",
        "save",
        "RECAll:SETUp",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "recall.waveform",
        "save",
        "RECAll:WAVEForm",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    make_control_spec(
        "save.slot",
        "save",
        "See vendor documentation.",
        set_command="*SAV {value}",
        value_help="See vendor documentation.",
    ),
    state_control(
        "save.image",
        "save",
        "SAVe:IMAge",
        "See vendor documentation.",
        value_help='Destination path example: "/usb0/SHOT001.PNG".',
    ),
    state_control(
        "save.image.file_format",
        "save",
        "SAVe:IMAge:FILEFormat",
        "See vendor documentation.",
        value_help="BMP|PNG|TIFF",
    ),
    state_control(
        "save.setup",
        "save",
        "SAVe:SETUp",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "save.waveform",
        "save",
        "SAVe:WAVEform",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "status.all_events",
        "status",
        "ALLEv?",
        "See vendor documentation.",
    ),
    query_control(
        "status.busy",
        "status",
        "BUSY?",
        "See vendor documentation.",
    ),
    action_control(
        "status.clear",
        "status",
        "*CLS",
        "See vendor documentation.",
    ),
    state_control(
        "status.dese",
        "status",
        "DESE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "status.ese",
        "status",
        "*ESE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "status.esr",
        "status",
        "*ESR?",
        "See vendor documentation.",
    ),
    query_control(
        "status.event",
        "status",
        "EVENT?",
        "See vendor documentation.",
    ),
    query_control(
        "status.event_message",
        "status",
        "EVMsg?",
        "See vendor documentation.",
    ),
    query_control(
        "status.event_queue_size",
        "status",
        "EVQty?",
        "See vendor documentation.",
    ),
    query_action_control(
        "status.operation_complete",
        "status",
        "*OPC",
        "See vendor documentation.",
    ),
    state_control(
        "status.psc",
        "status",
        "*PSC",
        "See vendor documentation.",
        value_help="0|1",
    ),
    state_control(
        "status.sre",
        "status",
        "*SRE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "status.stb",
        "status",
        "*STB?",
        "See vendor documentation.",
    ),
    action_control(
        "status.wait",
        "status",
        "*WAI",
        "See vendor documentation.",
    ),
    query_control(
        "trendplot",
        "trendplot",
        "TRENDPLOT?",
        "See vendor documentation.",
    ),
    query_control(
        "trendplot.state",
        "trendplot",
        "TRENDPLOT:STATE?",
        "See vendor documentation.",
    ),
    query_control(
        "trendplot.time",
        "trendplot",
        "TRENDPLOT:TIME?",
        "See vendor documentation.",
    ),
    query_control(
        "trendplot.slot.avg",
        "trendplot",
        "TRENDPLOT:TP{slot}:AVG?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "trendplot.slot.max",
        "trendplot",
        "TRENDPLOT:TP{slot}:MAX?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "trendplot.slot.min",
        "trendplot",
        "TRENDPLOT:TP{slot}:MIN?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "trendplot.slot.scale",
        "trendplot",
        "TRENDPLOT:TP{slot}:SCALE?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "trendplot.slot.scale_max",
        "trendplot",
        "TRENDPLOT:TP{slot}:SCALEMAX?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    query_control(
        "trendplot.slot.scale_min",
        "trendplot",
        "TRENDPLOT:TP{slot}:SCALEMIN?",
        "See vendor documentation.",
        placeholders=("slot",),
    ),
    state_control(
        "trendplot.slot.source",
        "trendplot",
        "TRENDPLOT:TP{slot}:SOURCE",
        "See vendor documentation.",
        placeholders=("slot",),
        value_help="See vendor documentation.",
    ),
    state_control(
        "trendplot.slot.type",
        "trendplot",
        "TRENDPLOT:TP{slot}:TYPe",
        "See vendor documentation.",
        placeholders=("slot",),
        value_help="See vendor documentation.",
    ),
    action_control(
        "trigger.force",
        "trigger",
        "TRIGger",
        "See vendor documentation.",
    ),
    query_action_control(
        "trigger.main",
        "trigger",
        "TRIGger:MAIn",
        "See vendor documentation.",
    ),
    query_control(
        "trigger.main.edge",
        "trigger",
        "TRIGger:MAIn:EDGE?",
        "See vendor documentation.",
    ),
    state_control(
        "trigger.main.edge.coupling",
        "trigger",
        "TRIGger:MAIn:EDGE:COUPling",
        "See vendor documentation.",
        value_help="AC|DC|HFRej|LFRej|NOISErej",
    ),
    state_control(
        "trigger.main.edge.slope",
        "trigger",
        "TRIGger:MAIn:EDGE:SLOpe",
        "See vendor documentation.",
        value_help="RISE|FALL",
    ),
    state_control(
        "trigger.main.edge.source",
        "trigger",
        "TRIGger:MAIn:EDGE:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|EXT|LINE",
    ),
    query_control(
        "trigger.main.frequency",
        "trigger",
        "TRIGger:MAIn:FREQuency?",
        "See vendor documentation.",
    ),
    query_control(
        "trigger.main.holdoff",
        "trigger",
        "TRIGger:MAIn:HOLDOff?",
        "See vendor documentation.",
    ),
    state_control(
        "trigger.main.holdoff.value",
        "trigger",
        "TRIGger:MAIn:HOLDOff:VALue",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "trigger.main.level",
        "trigger",
        "TRIGger:MAIn:LEVel",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "trigger.main.mode",
        "trigger",
        "TRIGger:MAIn:MODe",
        "See vendor documentation.",
        value_help="AUTO|NORMal",
    ),
    query_control(
        "trigger.main.pulse",
        "trigger",
        "TRIGger:MAIn:PULse?",
        "See vendor documentation.",
    ),
    state_control(
        "trigger.main.pulse.source",
        "trigger",
        "TRIGger:MAIn:PULse:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2",
    ),
    query_control(
        "trigger.main.pulse.width",
        "trigger",
        "TRIGger:MAIn:PULse:WIDth?",
        "See vendor documentation.",
    ),
    state_control(
        "trigger.main.pulse.width.polarity",
        "trigger",
        "TRIGger:MAIn:PULse:WIDth:POLarity",
        "See vendor documentation.",
        value_help="POSitive|NEGative",
    ),
    state_control(
        "trigger.main.pulse.width.when",
        "trigger",
        "TRIGger:MAIn:PULse:WIDth:WHEN",
        "See vendor documentation.",
        value_help="LESSthan|MOREthan|EQual|UNEQual",
    ),
    state_control(
        "trigger.main.pulse.width.value",
        "trigger",
        "TRIGger:MAIn:PULse:WIDth:WIDth",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "trigger.main.type",
        "trigger",
        "TRIGger:MAIn:TYPe",
        "See vendor documentation.",
        value_help="EDGE|PULSE|VIDeo",
    ),
    query_control(
        "trigger.main.video",
        "trigger",
        "TRIGger:MAIn:VIDeo?",
        "See vendor documentation.",
    ),
    state_control(
        "trigger.main.video.line",
        "trigger",
        "TRIGger:MAIn:VIDeo:LINE",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "trigger.main.video.polarity",
        "trigger",
        "TRIGger:MAIn:VIDeo:POLarity",
        "See vendor documentation.",
        value_help="NORMAL|INVERTED",
    ),
    state_control(
        "trigger.main.video.source",
        "trigger",
        "TRIGger:MAIn:VIDeo:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|EXT|LINE",
    ),
    state_control(
        "trigger.main.video.standard",
        "trigger",
        "TRIGger:MAIn:VIDeo:STANDard",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "trigger.main.video.sync",
        "trigger",
        "TRIGger:MAIn:VIDeo:SYNC",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "trigger.state",
        "trigger",
        "TRIGger:STATE?",
        "See vendor documentation.",
    ),
    query_control(
        "channel",
        "vertical",
        "CH{channel_number}?",
        "See vendor documentation.",
        placeholders=("channel",),
    ),
    state_control(
        "channel.bandwidth",
        "vertical",
        "CH{channel_number}:BANdwidth",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="ON|OFF",
    ),
    state_control(
        "channel.coupling",
        "vertical",
        "CH{channel_number}:COUPling",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="AC|DC|GND",
    ),
    state_control(
        "channel.current_probe",
        "vertical",
        "CH{channel_number}:CURRENTPRObe",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
    ),
    state_control(
        "channel.invert",
        "vertical",
        "CH{channel_number}:INVert",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="ON|OFF",
    ),
    state_control(
        "channel.position",
        "vertical",
        "CH{channel_number}:POSition",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
    ),
    state_control(
        "channel.probe",
        "vertical",
        "CH{channel_number}:PRObe",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
    ),
    state_control(
        "channel.scale",
        "vertical",
        "CH{channel_number}:SCAle",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
        aliases=("channel.volts",),
    ),
    state_control(
        "channel.yunit",
        "vertical",
        "CH{channel_number}:YUNit",
        "See vendor documentation.",
        placeholders=("channel",),
        value_help="See vendor documentation.",
    ),
    query_control(
        "select",
        "vertical",
        "SELect?",
        "See vendor documentation.",
    ),
    state_control(
        "select.waveform",
        "vertical",
        "SELect:{waveform}",
        "See vendor documentation.",
        placeholders=("waveform",),
        value_help="ON|OFF",
    ),
    state_control(
        "waveform.curve",
        "waveform",
        "CURVe",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.data",
        "waveform",
        "DATa",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.data.destination",
        "waveform",
        "DATa:DESTination",
        "See vendor documentation.",
        value_help="See vendor documentation.",
        aliases=("waveform.data.target",),
    ),
    state_control(
        "waveform.data.encoding",
        "waveform",
        "DATa:ENCdg",
        "See vendor documentation.",
        value_help="ASCII|RIBinary|RPBinary|SRIbinary|SRPbinary",
    ),
    state_control(
        "waveform.data.source",
        "waveform",
        "DATa:SOUrce",
        "See vendor documentation.",
        value_help="CH1|CH2|MATH|REFA|REFB",
    ),
    state_control(
        "waveform.data.start",
        "waveform",
        "DATa:STARt",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.data.stop",
        "waveform",
        "DATa:STOP",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.data.width",
        "waveform",
        "DATa:WIDth",
        "See vendor documentation.",
        value_help="1|2",
    ),
    query_control(
        "waveform.all",
        "waveform",
        "WAVFrm?",
        "See vendor documentation.",
    ),
    query_control(
        "waveform.preamble",
        "waveform",
        "WFMPre?",
        "See vendor documentation.",
    ),
    query_control(
        "waveform.preamble.waveform",
        "waveform",
        "WFMPre:{waveform}?",
        "See vendor documentation.",
        placeholders=("waveform",),
    ),
    state_control(
        "waveform.preamble.bit_nr",
        "waveform",
        "WFMPre:BIT_Nr",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.bn_fmt",
        "waveform",
        "WFMPre:BN_Fmt",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.byt_nr",
        "waveform",
        "WFMPre:BYT_Nr",
        "See vendor documentation.",
        value_help="1|2",
    ),
    state_control(
        "waveform.preamble.byt_or",
        "waveform",
        "WFMPre:BYT_Or",
        "See vendor documentation.",
        value_help="MSB|LSB",
    ),
    state_control(
        "waveform.preamble.encoding",
        "waveform",
        "WFMPre:ENCdg",
        "See vendor documentation.",
        value_help="ASCii|BINary",
    ),
    query_control(
        "waveform.preamble.record_length",
        "waveform",
        "WFMPre:NR_Pt?",
        "See vendor documentation.",
    ),
    query_control(
        "waveform.preamble.waveform.record_length",
        "waveform",
        "WFMPre:{waveform}:NR_Pt?",
        "See vendor documentation.",
        placeholders=("waveform",),
    ),
    state_control(
        "waveform.preamble.point_format",
        "waveform",
        "WFMPre:PT_Fmt",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    query_control(
        "waveform.preamble.point_offset",
        "waveform",
        "WFMPre:PT_Off?",
        "See vendor documentation.",
    ),
    query_control(
        "waveform.preamble.wfid",
        "waveform",
        "WFMPre:WFId?",
        "See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.x_increment",
        "waveform",
        "WFMPre:XINcr",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.x_unit",
        "waveform",
        "WFMPre:XUNit",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.x_zero",
        "waveform",
        "WFMPre:XZEro",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.y_multiplier",
        "waveform",
        "WFMPre:YMUlt",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.y_offset",
        "waveform",
        "WFMPre:YOFf",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.y_unit",
        "waveform",
        "WFMPre:YUNit",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
    state_control(
        "waveform.preamble.y_zero",
        "waveform",
        "WFMPre:YZEro",
        "See vendor documentation.",
        value_help="See vendor documentation.",
    ),
]


CONTROL_CATALOG = {}
CONTROL_ALIAS_MAP = {}
for spec in CONTROL_SPEC_LIST:
    key = spec["key"]
    lowered_key = key.lower()
    if lowered_key in CONTROL_CATALOG:
        raise RuntimeError(f"Duplicate control key: {key}")
    CONTROL_CATALOG[lowered_key] = spec
    for alias in spec["aliases"]:
        lowered_alias = alias.lower()
        if lowered_alias in CONTROL_ALIAS_MAP:
            raise RuntimeError(f"Duplicate control alias: {alias}")
        CONTROL_ALIAS_MAP[lowered_alias] = lowered_key


class ScopeError(RuntimeError):
    """Raised when the helper cannot complete a scope operation."""


def require_pyvisa():
    try:
        import pyvisa  # type: ignore
    except ImportError as exc:
        raise ScopeError(
            "pyvisa is required. Install it with 'python3 -m pip install pyvisa pyvisa-py'."
        ) from exc
    return pyvisa


def output_json(data):
    print(json.dumps(data, indent=2, sort_keys=True))


def strip_response(text):
    return text.strip()


def ensure_parent(path_str):
    path = Path(path_str)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_resource_manager(backend):
    pyvisa = require_pyvisa()
    return pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()


def is_tektronix_idn(text):
    return "TEKTRONIX" in text.upper()


def normalize_match_text(text):
    return "".join(char for char in text.upper() if char.isalnum())


def split_channels(raw_channels):
    channels = []
    for item in raw_channels.split(","):
        channel = item.strip().upper()
        if not channel:
            continue
        if channel not in ("CH1", "CH2"):
            raise ScopeError(f"Unsupported channel for TBS1102B capture: {channel}")
        if channel not in channels:
            channels.append(channel)
    if not channels:
        raise ScopeError("No valid channels were requested.")
    return channels


def scan_resources(manager, timeout_ms):
    results = []
    for resource in manager.list_resources():
        entry = {"resource": resource}
        transport = "usb" if resource.upper().startswith("USB") else "other"
        entry["transport"] = transport
        try:
            scope = manager.open_resource(resource)
            try:
                configure_scope(scope, timeout_ms)
                idn = query_text(scope, ("*IDN?",))
                entry["idn"] = idn
                entry["vendor"] = "tektronix" if is_tektronix_idn(idn) else "other"
            finally:
                scope.close()
        except Exception as exc:
            entry["error"] = str(exc)
        results.append(entry)
    return results


def matches_resource(entry, model=None, usb_only=False):
    if entry.get("vendor") != "tektronix":
        return False
    if usb_only and entry.get("transport") != "usb":
        return False
    if model and normalize_match_text(model) not in normalize_match_text(
        entry.get("idn", "")
    ):
        return False
    return True


def auto_detect_resource(backend, timeout_ms, model=None, usb_only=False):
    manager = build_resource_manager(backend)
    try:
        matches = [
            entry
            for entry in scan_resources(manager, timeout_ms)
            if matches_resource(entry, model=model, usb_only=usb_only)
        ]
    finally:
        manager.close()

    if not matches:
        scope_desc = model or "Tektronix scope"
        transport_desc = "USB " if usb_only else ""
        raise ScopeError(f"No {transport_desc}{scope_desc} resource was detected.")
    if len(matches) > 1:
        resources = ", ".join(entry["resource"] for entry in matches)
        raise ScopeError(
            f"Multiple matching resources detected. Re-run with --resource. Matches: {resources}"
        )
    return matches[0]["resource"], matches[0].get("idn")


def configure_scope(scope, timeout_ms):
    scope.timeout = timeout_ms
    if hasattr(scope, "chunk_size"):
        scope.chunk_size = max(getattr(scope, "chunk_size", 0), 1024 * 1024)
    if hasattr(scope, "read_termination"):
        scope.read_termination = "\n"
    if hasattr(scope, "write_termination"):
        scope.write_termination = "\n"
    if hasattr(scope, "clear"):
        try:
            scope.clear()
        except Exception:
            pass
    try:
        scope.write("HEADER 0")
    except Exception:
        pass


def open_scope(resource, backend, timeout_ms):
    manager = build_resource_manager(backend)
    try:
        scope = manager.open_resource(resource)
        configure_scope(scope, timeout_ms)
        return manager, scope
    except Exception:
        manager.close()
        raise


def close_scope(manager, scope):
    try:
        scope.close()
    finally:
        manager.close()


def control_groups():
    return sorted({spec["group"] for spec in CONTROL_SPEC_LIST})


def operation_field_name(operation):
    if operation == "get":
        return "query"
    if operation == "set":
        return "set"
    if operation == "action":
        return "action"
    raise ScopeError(f"Unknown control operation: {operation}")


def default_operation_policy():
    return {
        "status": CONTROL_STATUS_SUPPORTED,
        "reason": CONTROL_STATUS_HELP[CONTROL_STATUS_SUPPORTED],
        "validated_on": TBS1102B_VALIDATION_DATE,
        "report": TBS1102B_VALIDATION_REPORT,
    }


def get_operation_policy(spec, operation):
    if not spec.get(operation_field_name(operation)):
        return None

    policy = default_operation_policy()
    override = TBS1102B_OPERATION_POLICIES.get(spec["key"], {}).get(operation)
    if override:
        policy.update(override)
        if policy["status"] == CONTROL_STATUS_UNSUPPORTED:
            policy["report"] = TBS1102B_RECHECK_REPORT
        elif policy["status"] == CONTROL_STATUS_GUARDED:
            policy["report"] = TBS1102B_VALIDATION_REPORT
            policy.pop("validated_on", None)
    return policy


def exposed_operations(spec, include_hidden=False):
    operations = []
    for operation in control_operations(spec):
        policy = get_operation_policy(spec, operation)
        if policy is None:
            continue
        if include_hidden or policy["status"] == CONTROL_STATUS_SUPPORTED:
            operations.append(operation)
    return operations


def has_exposed_operations(spec, include_hidden=False):
    return bool(exposed_operations(spec, include_hidden=include_hidden))


def resolve_control_spec(key, include_hidden=False):
    lowered = key.strip().lower()
    canonical = CONTROL_ALIAS_MAP.get(lowered, lowered)
    spec = CONTROL_CATALOG.get(canonical)
    if spec is None:
        groups = ", ".join(control_groups())
        raise ScopeError(
            f"Unknown control key: {key}. Use 'control list' to inspect valid keys. Groups: {groups}"
        )
    if not has_exposed_operations(spec, include_hidden=include_hidden):
        raise ScopeError(
            f"Control key '{spec['key']}' is hidden for TBS1102B because every operation is unsupported or guarded. "
            "Re-run with '--all' to inspect the full family catalog, or use raw query/write if you need manual probing."
        )
    return spec


def normalize_channel(channel):
    text = channel.strip().upper()
    if text not in ("CH1", "CH2"):
        raise ScopeError(f"Unsupported channel: {channel}. Expected CH1 or CH2.")
    return text


def normalize_waveform(waveform):
    text = waveform.strip().upper()
    if text not in ("CH1", "CH2", "MATH", "REFA", "REFB", "FFT"):
        raise ScopeError(
            f"Unsupported waveform selector: {waveform}. Expected CH1, CH2, MATH, REFA, REFB, or FFT."
        )
    return text


def normalize_positive_int(name, value, allowed=None):
    if value is None:
        raise ScopeError(f"--{name.replace('_', '-')} is required for this control key.")
    if value <= 0:
        raise ScopeError(f"--{name.replace('_', '-')} must be greater than 0.")
    if allowed and value not in allowed:
        allowed_text = ", ".join(str(item) for item in allowed)
        raise ScopeError(f"--{name.replace('_', '-')} must be one of: {allowed_text}")
    return value


def build_control_context(args):
    context = {}

    channel = getattr(args, "channel", None)
    if channel:
        normalized_channel = normalize_channel(channel)
        context["channel"] = normalized_channel
        context["channel_number"] = normalized_channel[2:]

    waveform = getattr(args, "waveform", None)
    if waveform:
        context["waveform"] = normalize_waveform(waveform)

    slot = getattr(args, "slot", None)
    if slot is not None:
        context["slot"] = normalize_positive_int("slot", slot)

    index = getattr(args, "index", None)
    if index is not None:
        context["index"] = normalize_positive_int("index", index, allowed=(1, 2))

    return context


def format_control_command(template, args, value=None):
    context = build_control_context(args)
    if value is not None:
        context["value"] = value

    try:
        return template.format(**context)
    except KeyError as exc:
        missing = exc.args[0]
        placeholder_help = CONTROL_PLACEHOLDER_HELP.get(missing, missing)
        raise ScopeError(f"Missing control placeholder '{missing}': {placeholder_help}") from exc


def control_operations(spec):
    operations = []
    if spec.get("query"):
        operations.append("get")
    if spec.get("set"):
        operations.append("set")
    if spec.get("action"):
        operations.append("action")
    return operations


def serialize_control_spec(spec, include_hidden=False):
    placeholders = {
        name: CONTROL_PLACEHOLDER_HELP.get(name, name) for name in spec["placeholders"]
    }
    visible_operations = exposed_operations(spec, include_hidden=include_hidden)
    payload = {
        "key": spec["key"],
        "group": spec["group"],
        "description": spec["description"],
        "operations": visible_operations,
        "placeholders": placeholders,
        "aliases": list(spec["aliases"]),
        "tbs1102b_profile": {
            "validated_on": TBS1102B_VALIDATION_DATE,
            "report": TBS1102B_VALIDATION_REPORT,
        },
    }
    operation_policy = {}
    hidden_operations = []
    for operation in control_operations(spec):
        policy = get_operation_policy(spec, operation)
        if policy is None:
            continue
        if include_hidden or operation in visible_operations:
            operation_policy[operation] = policy
        else:
            hidden_operations.append(operation)

    payload["operation_policy"] = operation_policy

    if hidden_operations:
        payload["hidden_operations"] = hidden_operations

    if "get" in visible_operations and spec.get("query"):
        payload["query"] = spec["query"]
    if "set" in visible_operations and spec.get("set"):
        payload["set"] = spec["set"]
    if "action" in visible_operations and spec.get("action"):
        payload["action"] = spec["action"]
    if "set" in visible_operations and spec.get("value_help"):
        payload["value_help"] = spec["value_help"]
    if spec.get("note"):
        payload["note"] = spec["note"]
    if include_hidden:
        payload["tbs1102b_profile"]["recheck_report"] = TBS1102B_RECHECK_REPORT
    return payload


def ensure_control_allowed(spec, operation, allow_risky=False):
    policy = get_operation_policy(spec, operation)
    if policy is None:
        raise ScopeError(f"Control key '{spec['key']}' does not support {operation}.")

    if policy["status"] == CONTROL_STATUS_SUPPORTED:
        return policy

    if policy["status"] == CONTROL_STATUS_UNSUPPORTED:
        raise ScopeError(
            f"Control key '{spec['key']}' operation '{operation}' is unsupported on TBS1102B. {policy['reason']} "
            "Use raw query/write only if you need manual probing outside the verified profile."
        )

    if not allow_risky:
        raise ScopeError(
            f"Control key '{spec['key']}' operation '{operation}' is guarded on TBS1102B. {policy['reason']} "
            "Re-run with --allow-risky if you really want to execute it."
        )

    return policy


def add_control_selector_args(subparser):
    subparser.add_argument(
        "--channel",
        help="Channel selector for keys that use CH<x>, for example CH1 or CH2.",
    )
    subparser.add_argument(
        "--waveform",
        help="Waveform selector for keys that use SELect:<wfm> or WFMPre:<wfm>.",
    )
    subparser.add_argument(
        "--slot",
        type=int,
        help="Slot number for MEAS<x> or TP<x> commands.",
    )
    subparser.add_argument(
        "--index",
        type=int,
        help="Cursor index for POSITION1/POSITION2 style commands.",
    )


def command_control_list(args):
    selected_group = args.group.lower() if args.group else None
    if selected_group and selected_group not in control_groups():
        raise ScopeError(
            f"Unknown control group: {args.group}. Available groups: {', '.join(control_groups())}"
        )

    entries = []
    for spec in sorted(CONTROL_SPEC_LIST, key=lambda item: (item["group"], item["key"])):
        if selected_group and spec["group"] != selected_group:
            continue
        if not has_exposed_operations(spec, include_hidden=args.all):
            continue
        summary = {
            "key": spec["key"],
            "group": spec["group"],
            "operations": exposed_operations(spec, include_hidden=args.all),
            "description": spec["description"],
        }
        if args.all:
            summary["operation_policy"] = {
                operation: get_operation_policy(spec, operation)
                for operation in control_operations(spec)
            }
        if spec["aliases"]:
            summary["aliases"] = list(spec["aliases"])
        entries.append(summary)

    output_json(
        {
            "groups": control_groups(),
            "entries": entries,
            "tbs1102b_profile": {
                "validated_on": TBS1102B_VALIDATION_DATE,
                "report": TBS1102B_VALIDATION_REPORT,
                "default_visibility": "supported_only" if not args.all else "all",
            },
        }
    )
    return 0


def command_control_show(args):
    spec = resolve_control_spec(args.key, include_hidden=args.all)
    output_json(serialize_control_spec(spec, include_hidden=args.all))
    return 0


def command_control_get(scope, args, dry_run=False):
    spec = resolve_control_spec(args.key, include_hidden=args.allow_risky)
    ensure_control_allowed(spec, "get", allow_risky=args.allow_risky)

    command = format_control_command(spec["query"], args)
    if dry_run:
        output_json(
            {
                "resource": args.resource,
                "backend": args.backend or "default",
                "key": spec["key"],
                "operation": "get",
                "query": command,
            }
        )
        return 0

    response = query_text(scope, (command,))
    output_json(
        {
            "resource": args.resource,
            "key": spec["key"],
            "operation": "get",
            "query": command,
            "response": response,
        }
    )
    return 0


def join_control_values(values):
    if not values:
        raise ScopeError("control set requires at least one --value argument.")
    return " ".join(values)


def command_control_set(scope, args, dry_run=False):
    spec = resolve_control_spec(args.key, include_hidden=args.allow_risky)
    ensure_control_allowed(spec, "set", allow_risky=args.allow_risky)

    command = format_control_command(spec["set"], args, value=join_control_values(args.value))
    if dry_run:
        payload = {
            "resource": args.resource,
            "backend": args.backend or "default",
            "key": spec["key"],
            "operation": "set",
            "write": command,
        }
        if args.wait_opc:
            payload["post_query"] = ["*OPC?"]
        output_json(payload)
        return 0

    scope.write(command)
    payload = {
        "resource": args.resource,
        "key": spec["key"],
        "operation": "set",
        "write": command,
    }
    if args.wait_opc:
        payload["opc"] = query_text(scope, ("*OPC?",))
    output_json(payload)
    return 0


def command_control_action(scope, args, dry_run=False):
    spec = resolve_control_spec(args.key, include_hidden=args.allow_risky)
    ensure_control_allowed(spec, "action", allow_risky=args.allow_risky)

    command = format_control_command(spec["action"], args)
    if dry_run:
        payload = {
            "resource": args.resource,
            "backend": args.backend or "default",
            "key": spec["key"],
            "operation": "action",
            "write": command,
        }
        if args.wait_opc:
            payload["post_query"] = ["*OPC?"]
        output_json(payload)
        return 0

    scope.write(command)
    payload = {
        "resource": args.resource,
        "key": spec["key"],
        "operation": "action",
        "write": command,
    }
    if args.wait_opc:
        payload["opc"] = query_text(scope, ("*OPC?",))
    output_json(payload)
    return 0


def run_list(args):
    manager = build_resource_manager(args.backend)
    try:
        resources = list(manager.list_resources())
    finally:
        manager.close()
    output_json({"backend": args.backend or "default", "resources": resources})
    return 0


def run_scan(args):
    manager = build_resource_manager(args.backend)
    try:
        results = scan_resources(manager, args.timeout_ms)
    finally:
        manager.close()

    output_json({"backend": args.backend or "default", "resources": results})
    return 0


def scoped_operation(args, handler):
    if args.dry_run:
        return handler(None, args, dry_run=True)

    manager, scope = open_scope(args.resource, args.backend, args.timeout_ms)
    try:
        return handler(scope, args, dry_run=False)
    finally:
        close_scope(manager, scope)


def query_text(scope, commands):
    last_error = None
    for command in commands:
        try:
            return strip_response(scope.query(command))
        except Exception as exc:
            last_error = exc
    if len(commands) == 1:
        raise ScopeError(f"SCPI query failed: {commands[0]}") from last_error
    joined = " | ".join(commands)
    raise ScopeError(f"All SCPI query fallbacks failed: {joined}") from last_error


def query_float(scope, commands):
    text = query_text(scope, commands)
    try:
        return float(text)
    except ValueError as exc:
        joined = " | ".join(commands)
        raise ScopeError(f"Expected numeric response for {joined}, got: {text}") from exc


def command_idn(scope, args, dry_run=False):
    if dry_run:
        output_json(
            {
                "resource": args.resource,
                "backend": args.backend or "default",
                "queries": ["*IDN?"],
            }
        )
        return 0

    output_json({"idn": query_text(scope, ("*IDN?",)), "resource": args.resource})
    return 0


def command_query(scope, args, dry_run=False):
    if dry_run:
        output_json(
            {
                "resource": args.resource,
                "backend": args.backend or "default",
                "queries": [args.command],
            }
        )
        return 0

    print(query_text(scope, (args.command,)))
    return 0


def command_write(scope, args, dry_run=False):
    if dry_run:
        payload = {
            "resource": args.resource,
            "backend": args.backend or "default",
            "writes": [args.command],
        }
        if args.wait_opc:
            payload["post_query"] = ["*OPC?"]
        output_json(payload)
        return 0

    scope.write(args.command)
    if args.wait_opc:
        print(query_text(scope, ("*OPC?",)))
    return 0


def parse_ascii_curve(text):
    data = strip_response(text)
    if data.upper().startswith(":CURVE "):
        data = data.split(" ", 1)[1]
    if not data:
        raise ScopeError(
            "CURVE? returned no samples. On TBS1000B-family scopes, the selected DATA:SOURCE must be displayed."
        )
    try:
        return [float(item) for item in data.split(",") if item]
    except ValueError as exc:
        raise ScopeError("Failed to parse ASCII waveform samples from CURVE?.") from exc


def collect_preamble(scope):
    preamble = {}
    for key, commands in PREAMBLE_FIELDS.items():
        try:
            value = query_float(scope, commands)
        except ScopeError:
            if key == "record_length":
                continue
            raise
        preamble[key] = value
    return preamble


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("index", "time_s", "voltage_v", "raw_sample"))
        writer.writerows(rows)


def round_analysis(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(f"{value:.12g}")


def interpolate_crossing_time(t0, v0, t1, v1, threshold):
    dv = v1 - v0
    if dv == 0:
        return t1
    ratio = (threshold - v0) / dv
    return t0 + (t1 - t0) * ratio


def estimate_logic_levels(voltage_values):
    sorted_values = sorted(voltage_values)
    window = max(1, len(sorted_values) // 10)
    low_values = sorted_values[:window]
    high_values = sorted_values[-window:]
    low_level = sum(low_values) / len(low_values)
    high_level = sum(high_values) / len(high_values)
    return low_level, high_level


def pair_edge_durations(start_times, stop_times):
    durations = []
    stop_index = 0
    for start_time in start_times:
        while stop_index < len(stop_times) and stop_times[stop_index] <= start_time:
            stop_index += 1
        if stop_index >= len(stop_times):
            break
        durations.append(stop_times[stop_index] - start_time)
        stop_index += 1
    return durations


def calculate_waveform_analysis(time_values, voltage_values, preamble=None):
    if not voltage_values:
        raise ScopeError("No waveform samples available for analysis.")

    count = len(voltage_values)
    v_min = min(voltage_values)
    v_max = max(voltage_values)
    v_pp = v_max - v_min
    v_avg = sum(voltage_values) / count
    v_rms = math.sqrt(sum(value * value for value in voltage_values) / count)
    low_level, high_level = estimate_logic_levels(voltage_values)
    threshold = (low_level + high_level) / 2.0

    rising_times = []
    falling_times = []
    high_samples = 0

    for index, value in enumerate(voltage_values):
        if value >= threshold:
            high_samples += 1
        if index == 0:
            continue

        prev_v = voltage_values[index - 1]
        curr_v = value
        if prev_v < threshold <= curr_v:
            rising_times.append(
                interpolate_crossing_time(
                    time_values[index - 1],
                    prev_v,
                    time_values[index],
                    curr_v,
                    threshold,
                )
            )
        elif prev_v >= threshold > curr_v:
            falling_times.append(
                interpolate_crossing_time(
                    time_values[index - 1],
                    prev_v,
                    time_values[index],
                    curr_v,
                    threshold,
                )
            )

    estimated_period = None
    estimated_frequency = None
    if len(rising_times) >= 2:
        periods = [
            rising_times[index] - rising_times[index - 1]
            for index in range(1, len(rising_times))
            if rising_times[index] > rising_times[index - 1]
        ]
        if periods:
            estimated_period = sum(periods) / len(periods)
            if estimated_period > 0:
                estimated_frequency = 1.0 / estimated_period

    high_durations = pair_edge_durations(rising_times, falling_times)
    low_durations = pair_edge_durations(falling_times, rising_times)
    average_high_time = None
    average_low_time = None
    if high_durations:
        average_high_time = sum(high_durations) / len(high_durations)
    if low_durations:
        average_low_time = sum(low_durations) / len(low_durations)

    duration = None
    if len(time_values) >= 2:
        duration = time_values[-1] - time_values[0]

    sample_interval = None
    sample_rate = None
    if preamble and preamble.get("x_increment"):
        sample_interval = preamble["x_increment"]
        if sample_interval:
            sample_rate = 1.0 / sample_interval
    elif len(time_values) >= 2:
        sample_interval = time_values[1] - time_values[0]
        if sample_interval:
            sample_rate = 1.0 / sample_interval

    duty_cycle = None
    if count:
        duty_cycle = 100.0 * high_samples / count

    return {
        "sample_count": count,
        "duration_s": round_analysis(duration),
        "sample_interval_s": round_analysis(sample_interval),
        "sample_rate_hz": round_analysis(sample_rate),
        "threshold_mid_v": round_analysis(threshold),
        "high_level_estimate_v": round_analysis(high_level),
        "low_level_estimate_v": round_analysis(low_level),
        "rising_edges": len(rising_times),
        "falling_edges": len(falling_times),
        "estimated_period_s": round_analysis(estimated_period),
        "estimated_frequency_hz": round_analysis(estimated_frequency),
        "estimated_duty_cycle_percent": round_analysis(duty_cycle),
        "estimated_high_time_s": round_analysis(average_high_time),
        "estimated_low_time_s": round_analysis(average_low_time),
        "voltage": {
            "min_v": round_analysis(v_min),
            "max_v": round_analysis(v_max),
            "pp_v": round_analysis(v_pp),
            "avg_v": round_analysis(v_avg),
            "rms_v": round_analysis(v_rms),
        },
    }


def load_waveform_csv(path):
    time_values = []
    voltage_values = []
    raw_samples = []
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            time_values.append(float(row["time_s"]))
            voltage_values.append(float(row["voltage_v"]))
            raw_samples.append(float(row["raw_sample"]))
    if not time_values:
        raise ScopeError(f"CSV contains no waveform rows: {path}")
    return time_values, voltage_values, raw_samples


def build_waveform_report(analysis, metadata=None, csv_path=None):
    lines = []
    if metadata:
        source = metadata.get("source", "unknown")
        idn = metadata.get("idn", "unknown")
        resource = metadata.get("resource", "unknown")
        lines.append(f"Source: {source}")
        lines.append(f"Instrument: {idn}")
        lines.append(f"Resource: {resource}")
    elif csv_path:
        lines.append(f"Source CSV: {csv_path}")

    voltage = analysis["voltage"]
    lines.append(
        "Voltage: "
        f"min={voltage['min_v']} V, "
        f"max={voltage['max_v']} V, "
        f"pp={voltage['pp_v']} V, "
        f"avg={voltage['avg_v']} V, "
        f"rms={voltage['rms_v']} V"
    )
    lines.append(
        "Levels: "
        f"low={analysis['low_level_estimate_v']} V, "
        f"high={analysis['high_level_estimate_v']} V, "
        f"threshold={analysis['threshold_mid_v']} V"
    )
    lines.append(
        "Timing: "
        f"sample_rate={analysis['sample_rate_hz']} Hz, "
        f"duration={analysis['duration_s']} s, "
        f"period={analysis['estimated_period_s']} s, "
        f"frequency={analysis['estimated_frequency_hz']} Hz"
    )
    lines.append(
        "Pulse: "
        f"duty={analysis['estimated_duty_cycle_percent']} %, "
        f"high_time={analysis['estimated_high_time_s']} s, "
        f"low_time={analysis['estimated_low_time_s']} s"
    )
    lines.append(
        "Edges: "
        f"rising={analysis['rising_edges']}, "
        f"falling={analysis['falling_edges']}, "
        f"samples={analysis['sample_count']}"
    )

    if metadata:
        preamble = metadata.get("preamble", {})
        if preamble:
            lines.append(
                "Preamble: "
                f"x_increment={preamble.get('x_increment')}, "
                f"x_zero={preamble.get('x_zero')}, "
                f"y_multiplier={preamble.get('y_multiplier')}, "
                f"y_zero={preamble.get('y_zero')}, "
                f"y_offset={preamble.get('y_offset')}"
            )

    return "\n".join(lines)


def write_json_file(path, data):
    output_path = ensure_parent(path)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def write_text_file(path, text):
    output_path = ensure_parent(path)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n")
    return output_path


def make_capture_metadata(
    *,
    capture,
    resource,
    backend,
    idn,
    source,
    start,
    stop,
    extra_metadata=None,
):
    metadata = {
        "analysis": capture["analysis"],
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "resource": resource,
        "backend": backend or "default",
        "idn": idn,
        "source": source,
        "start": start,
        "stop": stop,
        "sample_count": capture["sample_count"],
        "preamble": capture["preamble"],
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return metadata


def save_capture_artifacts(output_dir, base_name, capture, metadata):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"{base_name}.csv"
    metadata_path = output_dir / f"{base_name}.json"
    report_path = output_dir / f"{base_name}-report.txt"

    write_csv(csv_path, capture["rows"])
    write_json_file(metadata_path, metadata)
    report_text = build_waveform_report(metadata["analysis"], metadata, str(csv_path))
    write_text_file(report_path, report_text)

    return {
        "csv": str(csv_path),
        "metadata": str(metadata_path),
        "report": str(report_path),
        "sample_count": capture["sample_count"],
        "source": metadata["source"],
    }


def apply_scope_writes(scope, commands, wait_opc=False):
    executed = []
    if not commands:
        return {"writes": executed}

    for command in commands:
        scope.write(command)
        executed.append(command)

    result = {"writes": executed}
    if wait_opc:
        result["opc"] = query_text(scope, ("*OPC?",))
    return result


def capture_selected_channels(
    scope,
    *,
    channels,
    output_dir,
    prefix,
    resource,
    backend,
    idn,
    start,
    stop,
    settle_ms,
    show_hidden,
    extra_metadata=None,
):
    captures = []
    skipped = []

    for channel in channels:
        displayed = query_text(scope, (f"SELECT:{channel}?",))
        if displayed not in ("0", "1"):
            raise ScopeError(f"Unexpected SELECT:{channel}? response: {displayed}")

        if displayed == "0":
            if show_hidden:
                scope.write(f"SELECT:{channel} ON")
            else:
                skipped.append({"channel": channel, "reason": "channel_not_displayed"})
                continue

        capture = capture_waveform(scope, channel, start, stop, settle_ms)
        metadata = make_capture_metadata(
            capture=capture,
            resource=resource,
            backend=backend,
            idn=idn,
            source=channel,
            start=start,
            stop=stop,
            extra_metadata=extra_metadata,
        )
        artifact = save_capture_artifacts(output_dir, f"{prefix}-{channel.lower()}", capture, metadata)
        artifact["channel"] = channel
        captures.append(artifact)

    return captures, skipped


def resolve_scope_resource(args):
    resolved_resource = args.resource
    detected_idn = None
    if not resolved_resource:
        resolved_resource, detected_idn = auto_detect_resource(
            args.backend,
            args.timeout_ms,
            model=args.model,
            usb_only=True,
        )
    return resolved_resource, detected_idn


def append_unique_write(commands, command):
    if command and command not in commands:
        commands.append(command)


def infer_monitor_setup_channel(args, channels):
    setup_channel = args.setup_channel or channels[0]
    return normalize_channel(setup_channel)


def infer_monitor_trigger_type(args):
    if args.trigger_type:
        return args.trigger_type
    if args.pulse_width is not None or args.pulse_when or args.pulse_polarity:
        return "pulse"
    if args.trigger_source or args.trigger_slope or args.trigger_coupling:
        return "edge"
    return None


def copy_monitor_value(value):
    if isinstance(value, list):
        return list(value)
    return value


def monitor_cli_overrides(args):
    overrides = {}
    for field in MONITOR_CONFIG_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            overrides[field] = copy_monitor_value(value)
    return overrides


def apply_monitor_overrides(target, values):
    for key, value in values.items():
        target[key] = copy_monitor_value(value)


def normalize_monitor_profile_list(name, value):
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise ScopeError(f"Monitor profile field '{name}' must be a string or string list.")

    normalized = []
    for item in items:
        if not isinstance(item, str):
            raise ScopeError(f"Monitor profile field '{name}' must contain only strings.")
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized or None


def serialize_monitor_preset(name):
    preset = MONITOR_PRESETS[name]
    payload = {
        "name": name,
        "description": preset["description"],
        "monitor": {
            key: copy_monitor_value(value)
            for key, value in preset["monitor"].items()
        },
    }
    if preset.get("recommended_overrides"):
        payload["recommended_overrides"] = list(preset["recommended_overrides"])
    return payload


def load_monitor_profile(profile_path):
    path = Path(profile_path).expanduser()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ScopeError(f"Monitor profile file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScopeError(f"Monitor profile is not valid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ScopeError("Monitor profile must be a JSON object.")

    profile_preset = payload.get("preset")
    if profile_preset is not None and not isinstance(profile_preset, str):
        raise ScopeError("Monitor profile field 'preset' must be a string.")

    monitor_payload = payload.get("monitor")
    if monitor_payload is None:
        monitor_payload = {
            key: value
            for key, value in payload.items()
            if key not in ("name", "description", "preset")
        }

    if not isinstance(monitor_payload, dict):
        raise ScopeError("Monitor profile field 'monitor' must be a JSON object.")

    unknown_keys = sorted(key for key in monitor_payload if key not in MONITOR_CONFIG_FIELDS)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ScopeError(f"Monitor profile contains unsupported fields: {joined}")

    normalized_monitor = {}
    for key, value in monitor_payload.items():
        if key in MONITOR_LIST_FIELDS:
            normalized_monitor[key] = normalize_monitor_profile_list(key, value)
        else:
            normalized_monitor[key] = value

    return {
        "path": str(path),
        "name": payload.get("name"),
        "description": payload.get("description"),
        "preset": profile_preset,
        "monitor": normalized_monitor,
    }


def resolve_monitor_config(args):
    profile_data = load_monitor_profile(args.profile) if args.profile else None

    preset_name = args.preset
    if preset_name is None and profile_data is not None:
        preset_name = profile_data.get("preset")

    preset_payload = None
    effective = {
        key: copy_monitor_value(value) for key, value in MONITOR_DEFAULTS.items()
    }

    if preset_name is not None:
        if preset_name not in MONITOR_PRESETS:
            choices = ", ".join(sorted(MONITOR_PRESETS))
            raise ScopeError(f"Unknown monitor preset '{preset_name}'. Available presets: {choices}")
        preset_payload = serialize_monitor_preset(preset_name)
        apply_monitor_overrides(effective, preset_payload["monitor"])

    if profile_data is not None:
        apply_monitor_overrides(effective, profile_data["monitor"])

    apply_monitor_overrides(effective, monitor_cli_overrides(args))

    resolved_args = argparse.Namespace(**vars(args))
    for key, value in effective.items():
        setattr(resolved_args, key, value)

    resolution = {
        "preset_name": preset_name,
        "preset": preset_payload,
        "profile": profile_data,
    }
    return resolved_args, resolution


def build_monitor_profile_payload(args, resolution):
    monitor = {}
    for field in MONITOR_CONFIG_FIELDS:
        monitor[field] = copy_monitor_value(getattr(args, field))

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "skill": "tektronix-scope",
        "model": args.model,
        "monitor": monitor,
    }
    if resolution.get("preset_name"):
        payload["preset"] = resolution["preset_name"]
    profile_info = resolution.get("profile")
    if profile_info:
        if profile_info.get("name"):
            payload["source_profile_name"] = profile_info["name"]
        payload["source_profile"] = profile_info["path"]
    return payload


def maybe_write_monitor_profile(args, resolution):
    if not args.save_profile:
        return None
    payload = build_monitor_profile_payload(args, resolution)
    return str(write_json_file(Path(args.save_profile).expanduser(), payload))


def normalize_stopafter_value(value):
    if value is None:
        return None
    text = value.strip().upper()
    if text in ("SEQUENCE", "SEQU"):
        return "SEQUENCE"
    if text in ("RUNSTOP", "RUNST"):
        return "RUNSTOP"
    return text


def expected_monitor_stopafter(args):
    return normalize_stopafter_value(args.arm_stopafter)


def snapshot_monitor_arm_state(scope):
    stopafter_raw = query_text(scope, ("ACQuire:STOPAfter?",))
    trigger_state_raw = query_text(scope, ("TRIGger:STATE?",))
    acquire_state_raw = query_text(scope, ("ACQuire:STATE?",))
    return {
        "stopafter": normalize_stopafter_value(stopafter_raw),
        "stopafter_raw": stopafter_raw.strip(),
        "trigger_state": trigger_state_raw.strip().upper(),
        "acquire_state": acquire_state_raw.strip(),
    }


def ensure_monitor_arm_state(
    scope,
    *,
    expected_stopafter,
    arm_writes,
    wait_opc,
):
    if expected_stopafter is None:
        return None

    verification = {
        "expected_stopafter": expected_stopafter,
        "attempts": [],
    }

    for attempt in range(1, MONITOR_ARM_VERIFY_ATTEMPTS + 1):
        observed = snapshot_monitor_arm_state(scope)
        assessment = {
            "attempt": attempt,
            "observed": observed,
            "ok": observed["stopafter"] == expected_stopafter,
        }
        if not assessment["ok"]:
            assessment["reason"] = (
                f"Expected STOPAfter {expected_stopafter}, got {observed['stopafter_raw'] or observed['stopafter']}."
            )
        verification["attempts"].append(assessment)

        if assessment["ok"]:
            verification["final"] = observed
            verification["ok"] = True
            return verification

        if attempt < MONITOR_ARM_VERIFY_ATTEMPTS and arm_writes:
            assessment["reapply"] = apply_scope_writes(
                scope,
                arm_writes,
                wait_opc=wait_opc,
            )

    verification["ok"] = False
    final_observed = verification["attempts"][-1]["observed"]
    raise ScopeError(
        "Monitor re-arm verification failed: "
        f"expected STOPAfter {expected_stopafter}, "
        f"got {final_observed['stopafter_raw'] or final_observed['stopafter']}. "
        f"TRIGger:STATE?={final_observed['trigger_state']}, "
        f"ACQuire:STATE?={final_observed['acquire_state']}."
    )


def build_monitor_setup_writes(args, channels):
    setup_channel = infer_monitor_setup_channel(args, channels)
    setup_writes = []
    arm_writes = []

    if args.ensure_visible:
        for channel in channels:
            append_unique_write(setup_writes, f"SELECT:{channel} ON")

    if args.channel_scale is not None:
        append_unique_write(setup_writes, f"{setup_channel}:SCAle {args.channel_scale}")
    if args.channel_position is not None:
        append_unique_write(setup_writes, f"{setup_channel}:POSition {args.channel_position}")
    if args.horizontal_scale is not None:
        append_unique_write(setup_writes, f"HORizontal:MAIn:SCAle {args.horizontal_scale}")

    trigger_type = infer_monitor_trigger_type(args)
    trigger_source = args.trigger_source or setup_channel
    if trigger_type == "edge":
        append_unique_write(setup_writes, "TRIGger:MAIn:TYPe EDGE")
        if args.trigger_source:
            append_unique_write(setup_writes, f"TRIGger:MAIn:EDGE:SOUrce {trigger_source}")
        if args.trigger_slope:
            append_unique_write(
                setup_writes,
                f"TRIGger:MAIn:EDGE:SLOpe {args.trigger_slope}",
            )
        if args.trigger_coupling:
            append_unique_write(
                setup_writes,
                f"TRIGger:MAIn:EDGE:COUPling {args.trigger_coupling}",
            )
    elif trigger_type == "pulse":
        append_unique_write(setup_writes, "TRIGger:MAIn:TYPe PULSE")
        append_unique_write(setup_writes, f"TRIGger:MAIn:PULse:SOUrce {trigger_source}")
        if args.pulse_when:
            append_unique_write(
                setup_writes,
                f"TRIGger:MAIn:PULse:WIDth:WHEN {args.pulse_when}",
            )
        if args.pulse_width is not None:
            append_unique_write(
                setup_writes,
                f"TRIGger:MAIn:PULse:WIDth:WIDth {args.pulse_width}",
            )
        if args.pulse_polarity:
            append_unique_write(
                setup_writes,
                f"TRIGger:MAIn:PULse:WIDth:POLarity {args.pulse_polarity}",
            )

    if args.trigger_level is not None:
        append_unique_write(setup_writes, f"TRIGger:MAIn:LEVel {args.trigger_level}")
    if args.trigger_mode:
        append_unique_write(setup_writes, f"TRIGger:MAIn:MODe {args.trigger_mode}")

    if args.arm_stopafter:
        append_unique_write(arm_writes, f"ACQuire:STOPAfter {args.arm_stopafter}")
        append_unique_write(arm_writes, "ACQuire:STATE RUN")

    return {
        "setup_channel": setup_channel,
        "setup_writes": setup_writes,
        "arm_writes": arm_writes,
    }


def normalize_monitor_state_values(values, defaults):
    raw_values = values or defaults
    normalized = []
    for value in raw_values:
        text = value.strip().upper()
        if not text:
            continue
        if text not in normalized:
            normalized.append(text)
    if not normalized:
        raise ScopeError("Monitor requires at least one non-empty match value.")
    return normalized


def match_monitor_response(current_value, previous_value, *, match_values, match_mode):
    current_text = current_value.strip().upper()
    previous_text = previous_value.strip().upper() if previous_value is not None else None

    if match_mode == "contains":
        matched = any(token in current_text for token in match_values)
        previously_matched = (
            any(token in previous_text for token in match_values)
            if previous_text is not None
            else False
        )
    else:
        matched = current_text in match_values
        previously_matched = previous_text in match_values if previous_text is not None else False

    return matched and not previously_matched


def monitor_event_base(args, poll_index, response):
    return {
        "detected_at_utc": datetime.now(timezone.utc).isoformat(),
        "poll_index": poll_index,
        "mode": args.mode,
        "response": response,
    }


def detect_monitor_event(scope, args, state, poll_index):
    if args.mode == "limit":
        response = query_text(scope, ("LIMit:RESUlt:FAIL?",))
        try:
            current_fail_count = int(float(response))
        except ValueError as exc:
            raise ScopeError(f"Expected integer-like LIMit:RESUlt:FAIL? response, got: {response}") from exc

        previous_fail_count = state["last_fail_count"]
        state["last_fail_count"] = current_fail_count
        if current_fail_count > previous_fail_count:
            event = monitor_event_base(args, poll_index, response)
            event["fail_count"] = current_fail_count
            event["fail_count_delta"] = current_fail_count - previous_fail_count
            return event
        return None

    command = args.query or "TRIGger:STATE?"
    response = query_text(scope, (command,))
    match_values = state["match_values"]
    previous_response = state["last_response"]
    state["last_response"] = response

    if match_monitor_response(
        response,
        previous_response,
        match_values=match_values,
        match_mode=args.match_mode,
    ):
        event = monitor_event_base(args, poll_index, response)
        event["query"] = command
        event["matched_values"] = match_values
        return event

    return None


def initialize_monitor_state(scope, args):
    state = {}

    if args.mode == "limit":
        baseline_text = query_text(scope, ("LIMit:RESUlt:FAIL?",))
        try:
            baseline_count = int(float(baseline_text))
        except ValueError as exc:
            raise ScopeError(
                f"Expected integer-like LIMit:RESUlt:FAIL? response, got: {baseline_text}"
            ) from exc
        state["last_fail_count"] = baseline_count
        state["baseline"] = {"query": "LIMit:RESUlt:FAIL?", "response": baseline_text}
        return state

    defaults = ["SAVE"] if args.mode == "trigger" else None
    if args.mode == "query" and not args.match:
        raise ScopeError("Query monitor mode requires at least one --match value.")
    state["match_values"] = normalize_monitor_state_values(args.match, defaults)

    command = args.query or "TRIGger:STATE?"
    if args.initial_match:
        state["last_response"] = None
        state["baseline"] = {"query": command, "response": None}
    else:
        baseline_response = query_text(scope, (command,))
        state["last_response"] = baseline_response
        state["baseline"] = {"query": command, "response": baseline_response}
    return state


def build_monitor_event_metadata(args, event_index, event):
    return {
        "monitor": {
            "event_index": event_index,
            "mode": args.mode,
            "query": event.get("query"),
            "response": event.get("response"),
            "matched_values": event.get("matched_values"),
            "fail_count": event.get("fail_count"),
            "fail_count_delta": event.get("fail_count_delta"),
            "poll_index": event["poll_index"],
            "poll_interval_ms": args.poll_interval_ms,
        }
    }


def command_monitor(args):
    if args.list_presets:
        output_json(
            {
                "presets": [
                    serialize_monitor_preset(name) for name in sorted(MONITOR_PRESETS)
                ]
            }
        )
        return 0

    if args.show_preset:
        if args.show_preset not in MONITOR_PRESETS:
            choices = ", ".join(sorted(MONITOR_PRESETS))
            raise ScopeError(
                f"Unknown monitor preset '{args.show_preset}'. Available presets: {choices}"
            )
        output_json(serialize_monitor_preset(args.show_preset))
        return 0

    args, monitor_resolution = resolve_monitor_config(args)
    channels = split_channels(args.channels)
    setup_plan = build_monitor_setup_writes(args, channels)
    expected_stopafter = expected_monitor_stopafter(args)
    effective_pre_writes = setup_plan["setup_writes"] + setup_plan["arm_writes"] + (args.pre_write or [])
    effective_rearm_writes = list(args.rearm_write or [])
    if args.auto_rearm:
        effective_rearm_writes = setup_plan["arm_writes"] + effective_rearm_writes

    saved_profile_path = maybe_write_monitor_profile(args, monitor_resolution)

    if args.dry_run:
        resource = args.resource or "auto-detect-usb-tektronix"
        base_output_dir = Path(args.outdir)
        events_log_path = base_output_dir / f"{args.prefix}-events.json"
        payload = {
            "backend": args.backend or "default",
            "resource": resource,
            "mode": args.mode,
            "channels": channels,
            "outdir": str(base_output_dir),
            "prefix": args.prefix,
            "poll_interval_ms": args.poll_interval_ms,
            "max_events": args.max_events,
            "max_polls": args.max_polls,
            "duration_s": args.duration_s,
            "show_hidden": args.show_hidden,
            "preset": monitor_resolution["preset_name"],
            "preset_details": monitor_resolution["preset"],
            "profile": monitor_resolution["profile"],
            "setup_channel": setup_plan["setup_channel"],
            "setup_writes": setup_plan["setup_writes"],
            "arm_writes": setup_plan["arm_writes"],
            "expected_stopafter": expected_stopafter,
            "pre_writes": args.pre_write or [],
            "effective_pre_writes": effective_pre_writes,
            "rearm_writes": args.rearm_write or [],
            "effective_rearm_writes": effective_rearm_writes,
            "saved_profile": saved_profile_path,
            "wait_opc": args.wait_opc,
            "start": args.start,
            "stop": args.stop,
            "events_log": str(events_log_path),
        }
        if args.mode == "limit":
            payload["query"] = "LIMit:RESUlt:FAIL?"
            payload["event_condition"] = "fail_count_increase"
        else:
            payload["query"] = args.query or "TRIGger:STATE?"
            payload["match_mode"] = args.match_mode
            payload["match"] = normalize_monitor_state_values(
                args.match,
                ["SAVE"] if args.mode == "trigger" else None,
            )
            payload["initial_match"] = args.initial_match
        output_json(payload)
        return 0

    resolved_resource, detected_idn = resolve_scope_resource(args)
    base_output_dir = Path(args.outdir)
    events_log_path = base_output_dir / f"{args.prefix}-events.json"

    manager, scope = open_scope(resolved_resource, args.backend, args.timeout_ms)
    try:
        idn = detected_idn or query_text(scope, ("*IDN?",))
        pre_write_result = apply_scope_writes(
            scope,
            effective_pre_writes,
            wait_opc=args.wait_opc,
        )
        pre_write_result["arm_verification"] = ensure_monitor_arm_state(
            scope,
            expected_stopafter=expected_stopafter,
            arm_writes=setup_plan["arm_writes"],
            wait_opc=args.wait_opc,
        )
        state = initialize_monitor_state(scope, args)

        started_at = time.time()
        poll_index = 0
        event_index = 0
        events = []

        while True:
            if args.max_polls is not None and poll_index >= args.max_polls:
                break
            if args.duration_s is not None and (time.time() - started_at) >= args.duration_s:
                break

            poll_index += 1
            event = detect_monitor_event(scope, args, state, poll_index)
            if event is not None:
                event_index += 1
                extra_metadata = build_monitor_event_metadata(args, event_index, event)
                captures, skipped = capture_selected_channels(
                    scope,
                    channels=channels,
                    output_dir=base_output_dir,
                    prefix=f"{args.prefix}-event{event_index:03d}",
                    resource=resolved_resource,
                    backend=args.backend,
                    idn=idn,
                    start=args.start,
                    stop=args.stop,
                    settle_ms=args.settle_ms,
                    show_hidden=args.show_hidden,
                    extra_metadata=extra_metadata,
                )
                report = {
                    "event_index": event_index,
                    "event": event,
                    "captures": captures,
                    "skipped": skipped,
                }
                if effective_rearm_writes:
                    report["rearm"] = apply_scope_writes(
                        scope,
                        effective_rearm_writes,
                        wait_opc=args.wait_opc,
                    )
                    report["rearm"]["arm_verification"] = ensure_monitor_arm_state(
                        scope,
                        expected_stopafter=expected_stopafter,
                        arm_writes=setup_plan["arm_writes"],
                        wait_opc=args.wait_opc,
                    )
                events.append(report)

                if event_index >= args.max_events:
                    break

            if args.poll_interval_ms:
                time.sleep(args.poll_interval_ms / 1000.0)

        summary = {
            "resource": resolved_resource,
            "backend": args.backend or "default",
            "idn": idn,
            "mode": args.mode,
            "channels": channels,
            "polls": poll_index,
            "events_detected": len(events),
            "duration_s": round(time.time() - started_at, 3),
            "preset": monitor_resolution["preset_name"],
            "preset_details": monitor_resolution["preset"],
            "profile": monitor_resolution["profile"],
            "saved_profile": saved_profile_path,
            "setup_channel": setup_plan["setup_channel"],
            "setup_writes": setup_plan["setup_writes"],
            "arm_writes": setup_plan["arm_writes"],
            "expected_stopafter": expected_stopafter,
            "pre_write": pre_write_result,
            "effective_rearm_writes": effective_rearm_writes,
            "baseline": state.get("baseline"),
            "events_log": str(write_json_file(events_log_path, {"events": events})),
            "events": events,
        }
        output_json(summary)
        return 0
    finally:
        close_scope(manager, scope)


def capture_waveform(scope, source, start, stop, settle_ms):
    writes = [
        f"DATA:SOURCE {source}",
        f"DATA:START {start}",
        "DATA:ENCdg ASCII",
        "DATA:WIDth 1",
    ]
    if stop is not None:
        writes.append(f"DATA:STOP {stop}")

    for command in writes:
        scope.write(command)

    if settle_ms:
        import time

        time.sleep(settle_ms / 1000.0)

    samples = parse_ascii_curve(scope.query("CURVE?"))
    preamble = collect_preamble(scope)

    y_multiplier = preamble["y_multiplier"]
    y_zero = preamble["y_zero"]
    y_offset = preamble["y_offset"]
    x_increment = preamble["x_increment"]
    x_zero = preamble["x_zero"]
    point_offset = preamble["point_offset"]

    rows = []
    time_values = []
    voltage_values = []
    for index, raw_sample in enumerate(samples):
        time_s = x_zero + (index - point_offset) * x_increment
        voltage_v = (raw_sample - y_offset) * y_multiplier + y_zero
        time_values.append(time_s)
        voltage_values.append(voltage_v)
        rows.append((index, f"{time_s:.12g}", f"{voltage_v:.12g}", f"{raw_sample:.12g}"))

    return {
        "analysis": calculate_waveform_analysis(time_values, voltage_values, preamble),
        "preamble": preamble,
        "rows": rows,
        "sample_count": len(samples),
        "writes": writes,
    }


def command_waveform(scope, args, dry_run=False):
    if dry_run:
        writes = [
            f"DATA:SOURCE {args.source}",
            f"DATA:START {args.start}",
            "DATA:ENCdg ASCII",
            "DATA:WIDth 1",
        ]
        if args.stop is not None:
            writes.append(f"DATA:STOP {args.stop}")
        output_json(
            {
                "resource": args.resource,
                "backend": args.backend or "default",
                "writes": writes,
                "queries": [
                    "WFMPre:*? with WFMOutpre/WFMPRE fallbacks",
                    "CURVE?",
                    "*IDN?",
                ],
                "outputs": {
                    "csv": args.csv,
                    "metadata": args.metadata,
                },
            }
        )
        return 0

    capture = capture_waveform(scope, args.source, args.start, args.stop, args.settle_ms)
    idn = query_text(scope, ("*IDN?",))
    metadata = make_capture_metadata(
        capture=capture,
        resource=args.resource,
        backend=args.backend,
        idn=idn,
        source=args.source,
        start=args.start,
        stop=args.stop,
    )

    csv_path = ensure_parent(args.csv)
    metadata_path = ensure_parent(args.metadata)
    write_csv(csv_path, capture["rows"])
    write_json_file(metadata_path, metadata)

    output_json(
        {
            "csv": str(csv_path),
            "metadata": str(metadata_path),
            "sample_count": capture["sample_count"],
            "source": args.source,
        }
    )
    return 0


def command_capture(args):
    channels = split_channels(args.channels)

    if args.dry_run:
        resource = args.resource or "auto-detect-usb-tektronix"
        captures = []
        for channel in channels:
            captures.append(
                {
                    "channel": channel,
                    "csv": str(Path(args.outdir) / f"{args.prefix}-{channel.lower()}.csv"),
                    "metadata": str(Path(args.outdir) / f"{args.prefix}-{channel.lower()}.json"),
                    "requires_displayed": not args.show_hidden,
                }
            )
        output_json(
            {
                "backend": args.backend or "default",
                "model": args.model,
                "resource": resource,
                "captures": captures,
                "writes": ["SELECT:<channel> ON"] if args.show_hidden else [],
            }
        )
        return 0

    resolved_resource, detected_idn = resolve_scope_resource(args)

    manager, scope = open_scope(resolved_resource, args.backend, args.timeout_ms)
    try:
        idn = detected_idn or query_text(scope, ("*IDN?",))
        captures, skipped = capture_selected_channels(
            scope,
            channels=channels,
            output_dir=args.outdir,
            prefix=args.prefix,
            resource=resolved_resource,
            backend=args.backend,
            idn=idn,
            start=args.start,
            stop=args.stop,
            settle_ms=args.settle_ms,
            show_hidden=args.show_hidden,
            extra_metadata={"auto_detected_resource": args.resource is None},
        )

        output_json(
            {
                "resource": resolved_resource,
                "idn": idn,
                "captures": captures,
                "skipped": skipped,
            }
        )
        return 0
    finally:
        close_scope(manager, scope)


def command_analyze(args):
    time_values, voltage_values, raw_samples = load_waveform_csv(args.csv)
    metadata = None
    preamble = None

    if args.metadata:
        with Path(args.metadata).open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        preamble = metadata.get("preamble")

    analysis = calculate_waveform_analysis(time_values, voltage_values, preamble)
    analysis["raw_sample"] = {
        "min": round_analysis(min(raw_samples)),
        "max": round_analysis(max(raw_samples)),
    }

    if metadata is not None and args.update_metadata:
        metadata["analysis"] = analysis
        with Path(args.metadata).open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if args.json:
        json_path = ensure_parent(args.json)
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(analysis, handle, indent=2, sort_keys=True)
            handle.write("\n")

    output_json(analysis)
    return 0


def command_report(args):
    metadata = None
    analysis = None

    if args.metadata:
        with Path(args.metadata).open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        analysis = metadata.get("analysis")

    if analysis is None:
        if not args.csv:
            raise ScopeError("Report requires --metadata or --csv.")
        time_values, voltage_values, raw_samples = load_waveform_csv(args.csv)
        preamble = metadata.get("preamble") if metadata else None
        analysis = calculate_waveform_analysis(time_values, voltage_values, preamble)
        analysis["raw_sample"] = {
            "min": round_analysis(min(raw_samples)),
            "max": round_analysis(max(raw_samples)),
        }

    report = build_waveform_report(analysis, metadata, args.csv)

    if args.output:
        output_path = ensure_parent(args.output)
        with output_path.open("w", encoding="utf-8") as handle:
            handle.write(report)
            handle.write("\n")

    print(report)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Remote-control Tektronix oscilloscopes and export waveform data."
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    list_parser = subparsers.add_parser("list", help="List VISA resources.")
    list_parser.add_argument("--backend", help="PyVISA backend such as @py.")
    list_parser.set_defaults(func=run_list)

    scan_parser = subparsers.add_parser(
        "scan",
        help="List VISA resources and query *IDN? where possible.",
    )
    scan_parser.add_argument("--backend", help="PyVISA backend such as @py.")
    scan_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=3000,
        help="Per-resource timeout in milliseconds.",
    )
    scan_parser.set_defaults(func=run_scan)

    def add_scope_args(subparser):
        subparser.add_argument("--resource", required=True, help="VISA resource string.")
        subparser.add_argument("--backend", help="PyVISA backend such as @py.")
        subparser.add_argument(
            "--timeout-ms",
            type=int,
            default=5000,
            help="Resource timeout in milliseconds.",
        )
        subparser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the intended SCPI sequence without touching hardware.",
        )

    idn_parser = subparsers.add_parser("idn", help="Query *IDN?.")
    add_scope_args(idn_parser)
    idn_parser.set_defaults(func=lambda args: scoped_operation(args, command_idn))

    query_parser = subparsers.add_parser("query", help="Send a single SCPI query.")
    add_scope_args(query_parser)
    query_parser.add_argument("command", help="SCPI query such as TRIGger:STATE?")
    query_parser.set_defaults(func=lambda args: scoped_operation(args, command_query))

    write_parser = subparsers.add_parser("write", help="Send a single SCPI write.")
    add_scope_args(write_parser)
    write_parser.add_argument("command", help="SCPI write such as ACQuire:STATE RUN")
    write_parser.add_argument(
        "--wait-opc",
        action="store_true",
        help="Query *OPC? after the write completes.",
    )
    write_parser.set_defaults(func=lambda args: scoped_operation(args, command_write))

    waveform_parser = subparsers.add_parser(
        "waveform",
        help="Capture ASCII waveform data and export CSV plus metadata JSON.",
    )
    add_scope_args(waveform_parser)
    waveform_parser.add_argument("--source", default="CH1", help="Waveform source, default CH1.")
    waveform_parser.add_argument("--start", type=int, default=1, help="DATA:START point.")
    waveform_parser.add_argument(
        "--stop",
        type=int,
        help="Optional DATA:STOP point. Omit to use the instrument default.",
    )
    waveform_parser.add_argument(
        "--settle-ms",
        type=int,
        default=0,
        help="Optional delay after setup writes before CURVE?.",
    )
    waveform_parser.add_argument("--csv", required=True, help="Output CSV path.")
    waveform_parser.add_argument("--metadata", required=True, help="Output metadata JSON path.")
    waveform_parser.set_defaults(func=lambda args: scoped_operation(args, command_waveform))

    capture_parser = subparsers.add_parser(
        "capture",
        help="Auto-detect a Tek USB scope and capture CH1/CH2 into an output directory.",
    )
    capture_parser.add_argument(
        "--resource",
        help="Optional VISA resource string. If omitted, auto-detect one Tek USB scope.",
    )
    capture_parser.add_argument("--backend", help="PyVISA backend such as @py.")
    capture_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="Resource timeout in milliseconds.",
    )
    capture_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended capture plan without touching hardware.",
    )
    capture_parser.add_argument(
        "--model",
        default="TBS1102B",
        help="Model substring used during auto-detection.",
    )
    capture_parser.add_argument(
        "--channels",
        default="CH1,CH2",
        help="Comma-separated channels to capture, default CH1,CH2.",
    )
    capture_parser.add_argument(
        "--outdir",
        default="captures",
        help="Directory for CSV and metadata JSON outputs.",
    )
    capture_parser.add_argument(
        "--prefix",
        default="capture",
        help="Filename prefix for generated capture files.",
    )
    capture_parser.add_argument("--start", type=int, default=1, help="DATA:START point.")
    capture_parser.add_argument(
        "--stop",
        type=int,
        help="Optional DATA:STOP point. Omit to use the instrument default.",
    )
    capture_parser.add_argument(
        "--settle-ms",
        type=int,
        default=0,
        help="Optional delay after setup writes before CURVE?.",
    )
    capture_parser.add_argument(
        "--show-hidden",
        action="store_true",
        help="Force hidden channels on before capture.",
    )
    capture_parser.set_defaults(func=command_capture)

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Poll scope state and auto-capture waveform evidence when an event is detected.",
    )
    monitor_parser.add_argument(
        "--resource",
        help="Optional VISA resource string. If omitted, auto-detect one Tek USB scope.",
    )
    monitor_parser.add_argument(
        "--backend",
        default=None,
        help="PyVISA backend such as @py.",
    )
    monitor_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=None,
        help="Resource timeout in milliseconds.",
    )
    monitor_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended monitor plan without touching hardware.",
    )
    monitor_parser.add_argument(
        "--preset",
        choices=tuple(sorted(MONITOR_PRESETS)),
        help="Apply a built-in monitor preset before any explicit CLI overrides.",
    )
    monitor_parser.add_argument(
        "--profile",
        help="Load monitor defaults from a JSON profile file. CLI options override profile values.",
    )
    monitor_parser.add_argument(
        "--save-profile",
        help="Write the effective monitor configuration to a JSON file after preset/profile resolution.",
    )
    monitor_parser.add_argument(
        "--list-presets",
        action="store_true",
        help="Print all built-in monitor presets and exit.",
    )
    monitor_parser.add_argument(
        "--show-preset",
        help="Print one built-in monitor preset and exit.",
    )
    monitor_parser.add_argument(
        "--model",
        default=None,
        help="Model substring used during auto-detection.",
    )
    monitor_parser.add_argument(
        "--channels",
        default=None,
        help="Comma-separated channels to capture on each event, default CH1.",
    )
    monitor_parser.add_argument(
        "--outdir",
        default=None,
        help="Directory for event capture artifacts.",
    )
    monitor_parser.add_argument(
        "--prefix",
        default=None,
        help="Filename prefix for monitor artifacts.",
    )
    monitor_parser.add_argument("--start", type=int, default=None, help="DATA:START point.")
    monitor_parser.add_argument(
        "--stop",
        type=int,
        help="Optional DATA:STOP point. Omit to use the instrument default.",
    )
    monitor_parser.add_argument(
        "--settle-ms",
        type=int,
        default=None,
        help="Optional delay after waveform setup writes before CURVE?.",
    )
    monitor_parser.add_argument(
        "--show-hidden",
        action="store_true",
        default=None,
        help="Force hidden channels on before capture.",
    )
    monitor_parser.add_argument(
        "--setup-channel",
        help="Channel used for vertical/trigger setup defaults. Defaults to the first capture channel.",
    )
    monitor_parser.add_argument(
        "--ensure-visible",
        action="store_true",
        default=None,
        help="Force all capture channels on before monitoring starts.",
    )
    monitor_parser.add_argument(
        "--channel-scale",
        help="Optional volts/div written to the setup channel before monitoring.",
    )
    monitor_parser.add_argument(
        "--channel-position",
        help="Optional vertical position written to the setup channel before monitoring.",
    )
    monitor_parser.add_argument(
        "--horizontal-scale",
        help="Optional seconds/div written to HORizontal:MAIn:SCAle before monitoring.",
    )
    monitor_parser.add_argument(
        "--trigger-type",
        choices=("edge", "pulse"),
        help="Optional trigger family to configure before monitoring.",
    )
    monitor_parser.add_argument(
        "--trigger-source",
        help="Optional trigger source such as CH1 or CH2.",
    )
    monitor_parser.add_argument(
        "--trigger-level",
        help="Optional trigger level written before monitoring.",
    )
    monitor_parser.add_argument(
        "--trigger-mode",
        choices=("AUTO", "NORMal"),
        help="Optional trigger mode written before monitoring.",
    )
    monitor_parser.add_argument(
        "--trigger-slope",
        choices=("RISE", "FALL"),
        help="Optional edge-trigger slope written before monitoring.",
    )
    monitor_parser.add_argument(
        "--trigger-coupling",
        choices=("AC", "DC", "HFRej", "LFRej", "NOISErej"),
        help="Optional edge-trigger coupling written before monitoring.",
    )
    monitor_parser.add_argument(
        "--pulse-when",
        choices=("LESSthan", "MOREthan", "EQual", "UNEQual"),
        help="Optional pulse-trigger width condition written before monitoring.",
    )
    monitor_parser.add_argument(
        "--pulse-width",
        help="Optional pulse-trigger width threshold written before monitoring.",
    )
    monitor_parser.add_argument(
        "--pulse-polarity",
        choices=("POSitive", "NEGative"),
        help="Optional pulse-trigger polarity written before monitoring.",
    )
    monitor_parser.add_argument(
        "--arm-stopafter",
        choices=("SEQuence", "RUNSTop"),
        help="Optional acquisition stop-after mode written before monitoring. Also sends ACQuire:STATE RUN.",
    )
    monitor_parser.add_argument(
        "--auto-rearm",
        action="store_true",
        default=None,
        help="Re-apply arm-stopafter writes after every captured event.",
    )
    monitor_parser.add_argument(
        "--mode",
        choices=("trigger", "limit", "query"),
        default=None,
        help="trigger polls TRIGger:STATE?, limit polls LIMit:RESUlt:FAIL?, query polls a custom SCPI query.",
    )
    monitor_parser.add_argument(
        "--query",
        help="Custom SCPI query used by --mode query. For trigger mode, omit to use TRIGger:STATE?.",
    )
    monitor_parser.add_argument(
        "--match",
        action="append",
        help="Expected query response. Repeat to allow multiple values. Trigger mode defaults to SAVE.",
    )
    monitor_parser.add_argument(
        "--match-mode",
        choices=("exact", "contains"),
        default=None,
        help="How --match values are compared against the query response.",
    )
    monitor_parser.add_argument(
        "--initial-match",
        action="store_true",
        default=None,
        help="Allow the very first matching response to fire an event instead of treating it as baseline state.",
    )
    monitor_parser.add_argument(
        "--poll-interval-ms",
        type=int,
        default=None,
        help="Delay between monitor polls in milliseconds.",
    )
    monitor_parser.add_argument(
        "--max-polls",
        type=int,
        help="Optional hard limit on total poll count.",
    )
    monitor_parser.add_argument(
        "--duration-s",
        type=float,
        help="Optional hard limit on total monitor duration in seconds.",
    )
    monitor_parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after this many events are captured, default 1.",
    )
    monitor_parser.add_argument(
        "--pre-write",
        action="append",
        help="SCPI write sent once before monitoring starts. Repeat as needed.",
    )
    monitor_parser.add_argument(
        "--rearm-write",
        action="append",
        help="SCPI write sent after each captured event, for example to re-arm single-sequence acquisition.",
    )
    monitor_parser.add_argument(
        "--wait-opc",
        action="store_true",
        default=None,
        help="Query *OPC? after batched pre-write or rearm-write commands.",
    )
    monitor_parser.set_defaults(func=command_monitor)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze an existing waveform CSV and emit a lightweight summary JSON.",
    )
    analyze_parser.add_argument("--csv", required=True, help="Waveform CSV path.")
    analyze_parser.add_argument(
        "--metadata",
        help="Optional metadata JSON path used to reuse preamble and update analysis.",
    )
    analyze_parser.add_argument(
        "--update-metadata",
        action="store_true",
        help="Write the computed analysis back into --metadata.",
    )
    analyze_parser.add_argument(
        "--json",
        help="Optional output path for the analysis JSON summary.",
    )
    analyze_parser.set_defaults(func=command_analyze)

    report_parser = subparsers.add_parser(
        "report",
        help="Render a human-readable waveform summary from metadata or CSV.",
    )
    report_parser.add_argument(
        "--csv",
        help="Optional waveform CSV path. Required when metadata does not already contain analysis.",
    )
    report_parser.add_argument(
        "--metadata",
        help="Optional metadata JSON path. Preferred because it can reuse the saved analysis block.",
    )
    report_parser.add_argument(
        "--output",
        help="Optional text output path for the rendered report.",
    )
    report_parser.set_defaults(func=command_report)

    control_parser = subparsers.add_parser(
        "control",
        help="Structured SCPI catalog for TBS1102B/TBS1000B command groups.",
    )
    control_subparsers = control_parser.add_subparsers(
        dest="control_command_name",
        required=True,
    )

    control_list_parser = control_subparsers.add_parser(
        "list",
        help="List catalogued SCPI control keys.",
    )
    control_list_parser.add_argument(
        "--group",
        help="Optional command group filter such as trigger, vertical, waveform, or status.",
    )
    control_list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include guarded or unsupported family commands that are hidden from the default TBS1102B profile.",
    )
    control_list_parser.set_defaults(func=command_control_list)

    control_show_parser = control_subparsers.add_parser(
        "show",
        help="Show one control key including SCPI template and placeholders.",
    )
    control_show_parser.add_argument(
        "--all",
        action="store_true",
        help="Inspect the full family catalog entry, including guarded or unsupported TBS1102B operations.",
    )
    control_show_parser.add_argument("key", help="Catalog key such as channel.scale.")
    control_show_parser.set_defaults(func=command_control_show)

    control_get_parser = control_subparsers.add_parser(
        "get",
        help="Query a catalogued control key.",
    )
    add_scope_args(control_get_parser)
    add_control_selector_args(control_get_parser)
    control_get_parser.add_argument(
        "--allow-risky",
        action="store_true",
        help="Allow guarded operations that are hidden from the default TBS1102B profile.",
    )
    control_get_parser.add_argument("key", help="Catalog key such as trigger.main.mode.")
    control_get_parser.set_defaults(
        func=lambda args: scoped_operation(args, command_control_get)
    )

    control_set_parser = control_subparsers.add_parser(
        "set",
        help="Write a catalogued control key with one or more raw SCPI value tokens.",
    )
    add_scope_args(control_set_parser)
    add_control_selector_args(control_set_parser)
    control_set_parser.add_argument(
        "--allow-risky",
        action="store_true",
        help="Allow guarded operations that are hidden from the default TBS1102B profile.",
    )
    control_set_parser.add_argument("key", help="Catalog key such as channel.scale.")
    control_set_parser.add_argument(
        "--value",
        action="append",
        required=True,
        help="Raw SCPI value token. Repeat to append multiple space-separated tokens.",
    )
    control_set_parser.add_argument(
        "--wait-opc",
        action="store_true",
        help="Query *OPC? after the write completes.",
    )
    control_set_parser.set_defaults(
        func=lambda args: scoped_operation(args, command_control_set)
    )

    control_action_parser = control_subparsers.add_parser(
        "action",
        help="Execute a catalogued action command with no value payload.",
    )
    add_scope_args(control_action_parser)
    add_control_selector_args(control_action_parser)
    control_action_parser.add_argument(
        "--allow-risky",
        action="store_true",
        help="Allow guarded operations that are hidden from the default TBS1102B profile.",
    )
    control_action_parser.add_argument("key", help="Catalog key such as system.autoset.")
    control_action_parser.add_argument(
        "--wait-opc",
        action="store_true",
        help="Query *OPC? after the write completes.",
    )
    control_action_parser.set_defaults(
        func=lambda args: scoped_operation(args, command_control_action)
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

"""Dialect registry and auto-detection from *IDN?."""

from __future__ import annotations

from ..common import die
from .base import Dialect
from .rigol import RigolDialect
from .keysight import KeysightDialect, RnsDialect
from .siglent import SiglentDialect
from .tektronix import TektronixDialect, _q_first
from .lecroy import LeCroyDialect, parse_wavedesc
from .gwinstek import GwInstekDialect
from .owon import OwonDialect, PeakTechDialect
from .hantek import HantekDialect
from .micsig import MicsigDialect
from .bkprecision import BkPrecisionDialect
from .unit import UnitDialect
from .fluke import FlukeDialect
from .yokogawa import YokogawaDialect
from .zlg import ZlgDialect
from .atten import AttenDialect

FAMILIES = {
    "rigol": RigolDialect,
    "keysight": KeysightDialect,
    "tektronix": TektronixDialect,
    "siglent": SiglentDialect,
    "lecroy": LeCroyDialect,
    "rns": RnsDialect,
    "gwinstek": GwInstekDialect,
    "yokogawa": YokogawaDialect,
    "owon": OwonDialect,
    "hantek": HantekDialect,
    "micsig": MicsigDialect,
    "bkprecision": BkPrecisionDialect,
    "unit": UnitDialect,
    "fluke": FlukeDialect,
    "zlg": ZlgDialect,
    "peaktech": PeakTechDialect,
    "atten": AttenDialect,
    "generic": Dialect,
}


def detect_family(idn: str) -> str:
    u = idn.upper()
    if "RIGOL" in u:
        return "rigol"
    if "KEYSIGHT" in u or "AGILENT" in u or "HEWLETT" in u:
        return "keysight"
    if "TEKTRONIX" in u or u.startswith("TEK") or " TEK" in u:
        return "tektronix"
    if "SIGLENT" in u:
        return "siglent"
    if "LECROY" in u:
        return "lecroy"
    if "ROHDE" in u or "R&S" in u:
        return "rns"
    if "GW INSTEK" in u or "GWINSTEK" in u or "GOOD WILL" in u:
        return "gwinstek"
    if "YOKOGAWA" in u:
        return "yokogawa"
    if "OWON" in u or "HANMATEK" in u:
        return "owon"
    if "HANTEK" in u:
        return "hantek"
    if "MICSIG" in u:
        return "micsig"
    if "B&K" in u or "BK PRECISION" in u or "BKP" in u:
        return "bkprecision"
    if "UNI-T" in u or "UNIT" in u:
        return "unit"
    if "FLUKE" in u:
        return "fluke"
    if "ZLG" in u or "ZHIYUAN" in u:
        return "zlg"
    if "PEAKTECH" in u:
        return "peaktech"
    if "ATTEN" in u:
        return "atten"
    return "generic"


def make_dialect(idn: str, family: str | None) -> Dialect:
    name = family or detect_family(idn)
    if name not in FAMILIES:
        die(f"unknown family '{name}'; choose from: {', '.join(FAMILIES)}")
    return FAMILIES[name](idn)


# ---------------------------------------------------------------- acquisition

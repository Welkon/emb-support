"""Power-supply dialects: per-channel or channel-selected SCPI command builders."""

from __future__ import annotations

from .common import fnum


class Dialect:
    name = "generic"
    channels = (1,)
    selected = False  # True if a channel-select command is required

    def select(self, n: int) -> str | None:
        return None

    def set_voltage(self, n, v): return f":VOLTage {fnum(v)}"
    def set_current(self, n, a): return f":CURRent {fnum(a)}"
    def get_voltage(self, n): return ":VOLTage?"
    def get_current(self, n): return ":CURRent?"
    def measure_voltage(self, n): return ":MEASure:VOLTage?"
    def measure_current(self, n): return ":MEASure:CURRent?"
    def measure_power(self, n): return ":MEASure:POWEr?"
    def output(self, n, on): return f":OUTPut {'ON' if on else 'OFF'}"
    def output_state(self, n): return ":OUTPut?"
    def ovp(self, n, v): return f":VOLTage:PROTection {fnum(v)}"
    def ocp(self, n, a): return f":CURRent:PROTection {fnum(a)}"


class RigolDp800(Dialect):
    name = "rigol"
    channels = (1, 2, 3)

    def set_voltage(self, n, v): return f":CHANnel{n}:VOLTage {fnum(v)}"
    def set_current(self, n, a): return f":CHANnel{n}:CURRent {fnum(a)}"
    def get_voltage(self, n): return f":CHANnel{n}:VOLTage?"
    def get_current(self, n): return f":CHANnel{n}:CURRent?"
    def measure_voltage(self, n): return f":MEASure:VOLTage? CHANnel{n}"
    def measure_current(self, n): return f":MEASure:CURRent? CHANnel{n}"
    def measure_power(self, n): return f":MEASure:POWEr? CHANnel{n}"
    def output(self, n, on): return f":OUTPut CHANnel{n},{'ON' if on else 'OFF'}"
    def output_state(self, n): return f":OUTPut? CHANnel{n}"
    def ovp(self, n, v): return f":CHANnel{n}:OVP {fnum(v)}"
    def ocp(self, n, a): return f":CHANnel{n}:OCP {fnum(a)}"


class KeysightE36xx(Dialect):
    name = "keysight"
    channels = (1, 2, 3)
    selected = True

    def select(self, n): return f":INSTrument:NSELect {n}"

    def set_voltage(self, n, v): return f":VOLTage {fnum(v)}"
    def set_current(self, n, a): return f":CURRent {fnum(a)}"
    def measure_voltage(self, n): return ":MEASure:VOLTage?"
    def measure_current(self, n): return ":MEASure:CURRent?"
    def ovp(self, n, v): return f":OUTPut:OVP:VOLTage {fnum(v)}"
    def ocp(self, n, a): return None  # model-dependent


class SiglentSpd(Dialect):
    name = "siglent"
    channels = (1, 2)

    def set_voltage(self, n, v): return f":CH{n}:VOLT {fnum(v)}"
    def set_current(self, n, a): return f":CH{n}:CURR {fnum(a)}"
    def get_voltage(self, n): return f":CH{n}:VOLT?"
    def get_current(self, n): return f":CH{n}:CURR?"
    def measure_voltage(self, n): return f":MEAS:VOLT? CH{n}"
    def measure_current(self, n): return f":MEAS:CURR? CH{n}"
    def measure_power(self, n): return f":MEAS:POW? CH{n}"
    def output(self, n, on): return f":OUTP CH{n},{'ON' if on else 'OFF'}"
    def output_state(self, n): return f":OUTP? CH{n}"


class RnsHmc(Dialect):
    name = "rns"
    channels = (1, 2, 3, 4)
    selected = True

    def select(self, n): return f":INSTrument:NSELect {n}"
    def output(self, n, on): return f":OUTPut:CHANnel{n}:STATe {'ON' if on else 'OFF'}"
    def output_state(self, n): return f":OUTPut:CHANnel{n}:STATe?"


class Korad(Dialect):
    name = "korad"
    channels = (1, 2)

    def set_voltage(self, n, v): return f"VSET{n}:{v:.2f}"
    def set_current(self, n, a): return f"ISET{n}:{a:.3f}"
    def get_voltage(self, n): return f"VSET{n}?"
    def get_current(self, n): return f"ISET{n}?"
    def measure_voltage(self, n): return f"VOUT{n}?"
    def measure_current(self, n): return f"IOUT{n}?"
    def measure_power(self, n): return None
    def output(self, n, on): return f"OUT{n}" if on else "OUT0"
    def output_state(self, n): return None
    def ovp(self, n, v): return None
    def ocp(self, n, a): return None


class GwInstek(Dialect):
    name = "gwinstek"
    channels = (1, 2)
    selected = True

    def select(self, n): return f":INSTrument:NSELect {n}"


class BkPrecision(Dialect):
    name = "bkprecision"
    channels = (1, 2, 3)
    selected = True

    def select(self, n): return f":INSTrument:NSELect {n}"


class Owon(Dialect):
    name = "owon"
    channels = (1, 2)

    def set_voltage(self, n, v): return f":CH{n}:VOLT {fnum(v)}"
    def set_current(self, n, a): return f":CH{n}:CURR {fnum(a)}"
    def get_voltage(self, n): return f":CH{n}:VOLT?"
    def get_current(self, n): return f":CH{n}:CURR?"
    def measure_voltage(self, n): return f":MEAS:VOLT? CH{n}"
    def measure_current(self, n): return f":MEAS:CURR? CH{n}"
    def output(self, n, on): return f":OUTP CH{n},{'ON' if on else 'OFF'}"
    def output_state(self, n): return f":OUTP? CH{n}"


class Itech(Dialect):
    name = "itech"
    channels = (1, 2, 3)
    selected = True

    def select(self, n): return f":INSTrument:NSELect {n}"
    def set_voltage(self, n, v): return f":VOLTage {fnum(v)}"
    def set_current(self, n, a): return f":CURRent {fnum(a)}"
    def measure_voltage(self, n): return ":MEASure:VOLTage?"
    def measure_current(self, n): return ":MEASure:CURRent?"
    def measure_power(self, n): return ":MEASure:POWer?"
    def output(self, n, on): return f":OUTPut {'ON' if on else 'OFF'}"
    def output_state(self, n): return ":OUTPut?"
    def ovp(self, n, v): return f":VOLTage:PROTection {fnum(v)}"
    def ocp(self, n, a): return f":CURRent:PROTection {fnum(a)}"


class AimTti(Dialect):
    name = "aimtti"
    channels = (1, 2)


class Generic(Dialect):
    name = "generic"


FAMILIES = {
    "rigol": RigolDp800,
    "keysight": KeysightE36xx,
    "siglent": SiglentSpd,
    "rns": RnsHmc,
    "korad": Korad,
    "gwinstek": GwInstek,
    "bkprecision": BkPrecision,
    "owon": Owon,
    "itech": Itech,
    "aimtti": AimTti,
    "generic": Generic,
}


def detect_family(idn: str) -> str:
    u = idn.upper()
    if "RIGOL" in u:
        return "rigol"
    if "KEYSIGHT" in u or "AGILENT" in u or "HEWLETT" in u:
        return "keysight"
    if "SIGLENT" in u:
        return "siglent"
    if "ROHDE" in u or "R&S" in u or "HAMEG" in u:
        return "rns"
    if "KORAD" in u or "TENMA" in u:
        return "korad"
    if "GW INSTEK" in u or "GWINSTEK" in u:
        return "gwinstek"
    if "B&K" in u or "BK PRECISION" in u:
        return "bkprecision"
    if "ITECH" in u:
        return "itech"
    if "OWON" in u:
        return "owon"
    if "AIM" in u or "TTI" in u:
        return "aimtti"
    return "generic"


def make_dialect(idn: str, family: str | None) -> Dialect:
    name = family or detect_family(idn)
    if name not in FAMILIES:
        raise ValueError(f"unknown family {name!r}; choose from {', '.join(FAMILIES)}")
    return FAMILIES[name]()

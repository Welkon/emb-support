"""Yokogawa DLM series."""

from __future__ import annotations

from .base import Dialect

class YokogawaDialect(Dialect):
    """Yokogawa DLM series: waveform uses :WAVeform:SEND? / model-specific setup."""

    name = "yokogawa"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Yokogawa DLM waveform transfer uses :WAVeform:SEND? and model-specific "
            "preamble commands; not implemented. Use scpi or the vendor tool.")

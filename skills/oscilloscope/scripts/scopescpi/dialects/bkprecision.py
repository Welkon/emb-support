"""BK Precision 2540/2560: LeCroy MAUI command set and WAVEDESC waveform format."""

from __future__ import annotations

from .lecroy import LeCroyDialect


class BkPrecisionDialect(LeCroyDialect):
    name = "bkprecision"

"""Data stimulus: PRBS bit streams, NRZ/PAM4 symbol levels and exact UI-delayed PWL sources.

The platform's `spicexplorer_waveview.stimulus`, imported under the names this repo uses. One
symbol sequence drives every source; an FFE tap is the same sequence delayed k UI, so the delay
is exact by construction rather than by an on-chip delay element.
"""

from __future__ import annotations

from spicexplorer_waveview.stimulus import (
    FORMATS,
    PRBS_TAPS,
    Data,
    ideal_waveform,
    prbs,
    pwl,
    symbols,
)

__all__ = ["Data", "prbs", "symbols", "pwl", "ideal_waveform", "PRBS_TAPS", "FORMATS"]

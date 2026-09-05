"""Symbol-aware NRZ/PAM4 eye metrics behind a Bessel-Thomson reference receiver.

The platform's `spicexplorer_waveview.eye`, imported under the names this repo uses. Importing
it also registers the `eye` measurement kind, so `{meas: vecp_db, out: v(pout), fmt: pam4,
rate_gbd: 10}` runs on `sim.dataset(run)` through `spicexplorer_waveview.measure_dataset`.
"""

from __future__ import annotations

from spicexplorer_waveview.eye import (
    EYE_MEASUREMENTS,
    FLOOR,
    OVERSAMPLE,
    PHASES,
    SAMPLE_HALF_UI,
    VECP_CAP_DB,
    bessel_lowpass,
    eye_metrics,
    fold,
    latency,
    levels,
    resample,
    rx_bandwidth,
)

__all__ = ["eye_metrics", "fold", "latency", "levels", "rx_bandwidth", "bessel_lowpass", "resample",
           "EYE_MEASUREMENTS", "VECP_CAP_DB", "OVERSAMPLE", "PHASES", "SAMPLE_HALF_UI", "FLOOR"]

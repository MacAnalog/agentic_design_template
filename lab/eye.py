"""Symbol-aware NRZ/PAM4 eye metrics behind a Bessel-Thomson reference receiver.

The bench generated the symbols, so samples are grouped by the *transmitted* symbol (latency by
cross-correlation, sampling phase swept over one UI) instead of clustered by level gaps; a
closed eye therefore returns finite numbers (eye height <= 0, VECP capped, width 0).
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .stimulus import Data, ideal_waveform

VECP_CAP_DB = 40.0
FLOOR = 1e-6            # level floor (fraction of full scale) keeping ER/OMA finite
SAMPLE_HALF_UI = 0.1    # +-window around the sampling instant for level statistics
PHASES = 40             # sampling phases swept over one UI
OVERSAMPLE = 200        # samples per UI after resampling


def resample(t: np.ndarray, x: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    tu = np.arange(t[0], t[-1], dt)
    return tu, np.interp(tu, t, x)


def bessel_lowpass(t: np.ndarray, x: np.ndarray, f3db: float, order: int = 4) -> np.ndarray:
    """Bessel-Thomson low-pass (unit dc gain, -3 dB at `f3db`) on a uniform grid; BT4 by default."""
    fs = 1.0 / (t[1] - t[0])
    b, a = signal.bessel(order, min(f3db / (fs / 2), 0.99), btype="low", analog=False, norm="mag")
    return signal.lfilter(b, a, x - x[0]) + x[0]


def rx_bandwidth(fmt: str, rate_gbd: float) -> float:
    """The reference receiver's -3 dB point: 0.75 x baud (NRZ), 0.5 x baud (PAM4)."""
    return (0.5 if fmt == "pam4" else 0.75) * rate_gbd * 1e9


def latency(t: np.ndarray, y: np.ndarray, data: Data) -> tuple[float, int]:
    """(delay s, polarity +-1) maximizing |correlation| of `y` with the ideal symbol waveform."""
    dt = t[1] - t[0]
    ideal = ideal_waveform(t, data)
    yy = y - y.mean()
    n_max = int(max(3 * data.ui, 2e-9) / dt) + 1
    best, lag, sign = -np.inf, 0, 1
    for k in range(n_max):
        c = float(np.dot(yy[k:], ideal[: len(yy) - k]))
        if abs(c) > best:
            best, lag, sign = abs(c), k, (1 if c >= 0 else -1)
    return lag * dt, sign


def levels(fmt: str) -> np.ndarray:
    return np.array([-1.0, 1.0]) if fmt == "nrz" else np.array([-1.0, -1 / 3, 1 / 3, 1.0])


def _groups(y, centers, half, sym_idx, nlv):
    """Samples within +-`half` indices of each symbol center, grouped by transmitted level; None if a level is empty."""
    g: list[list[np.ndarray]] = [[] for _ in range(nlv)]
    for k, c in enumerate(centers):
        lo, hi = max(c - half, 0), min(c + half + 1, len(y))
        if lo < hi:
            g[sym_idx[k]].append(y[lo:hi])
    return None if any(not x for x in g) else [np.concatenate(x) for x in g]


def _openings(g) -> list[float]:
    return [float(g[i + 1].min() - g[i].max()) for i in range(len(g) - 1)]


def eye_metrics(t: np.ndarray, x: np.ndarray, data: Data, *, filtered: bool = True,
                full_scale: float = 1.0) -> dict:
    """Scorecard of one eye on a unipolar signal (e.g. optical power; ER/OMA need a positive low level).

    Keys: eye_h_norm, eye_w_ui, vecp_db, er_db, oma_db (+ rlm, pam4_eye_heights for PAM4) and
    the sampling point found (sample_phase_ui, latency_ps, polarity, levels).
    """
    dt = data.ui / OVERSAMPLE
    tu, y = resample(t, x, dt)
    if filtered:
        y = bessel_lowpass(tu, y, rx_bandwidth(data.fmt, data.rate_gbd))
    lag, sign = latency(tu, y, data)
    lv = levels(data.fmt)
    ks = np.arange(data.n_warm, data.n)                       # the scored symbols
    sym_idx = [int(np.argmin(abs(lv - sign * s))) for s in data.syms[ks]]
    phases = np.linspace(0.0, 1.0, PHASES, endpoint=False)

    def centers(ph: float) -> np.ndarray:
        return np.rint((data.t0 + lag + (ks + ph) * data.ui - tu[0]) / dt).astype(int)

    half = round(SAMPLE_HALF_UI * OVERSAMPLE)
    best = None
    for ph in phases:
        g = _groups(y, centers(ph), half, sym_idx, len(lv))
        if g is None:
            continue
        h = _openings(g)
        if best is None or min(h) > best[1]:
            best = (float(ph), min(h), h, [float(z.mean()) for z in g])
    if best is None:
        return {"eye_h_norm": -1.0, "eye_w_ui": 0.0, "vecp_db": VECP_CAP_DB, "er_db": 0.0,
                "oma_db": -60.0, "ok": 0}
    ph, h_min, heights, means = best
    floor = FLOOR * full_scale
    p_hi, p_lo = max(means[-1], floor), max(means[0], floor)
    oma = p_hi - p_lo
    sub = oma / (len(lv) - 1)                                 # one ideal eye's amplitude
    open_ph = [p for p in phases
               if (g := _groups(y, centers(p), 1, sym_idx, len(lv))) is not None
               and min(_openings(g)) > 0]
    out = {"sample_phase_ui": ph, "latency_ps": float(lag * 1e12), "polarity": sign,
           "levels": means, "eye_h_norm": float(h_min / full_scale),
           "eye_w_ui": len(open_ph) / PHASES, "oma_norm": float(oma),
           "oma_db": float(10 * np.log10(max(oma, floor) / full_scale)),
           "er_db": float(10 * np.log10(p_hi / p_lo)),
           "vecp_db": float(min(10 * np.log10(sub / h_min), VECP_CAP_DB))
           if h_min > 0 and sub > 0 else VECP_CAP_DB,
           "ok": 1}
    if data.fmt == "pam4":
        amps = np.diff(means)
        out["pam4_eye_heights"] = heights
        out["rlm"] = float(3 * amps.min() / amps.sum()) if amps.sum() > 0 else 0.0
    return out


def fold(t: np.ndarray, x: np.ndarray, data: Data, *, filtered: bool = True,
         n_ui: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Eye-diagram coordinates (time within `n_ui` UI, value) over the scored window; for plots."""
    dt = data.ui / OVERSAMPLE
    tu, y = resample(t, x, dt)
    if filtered:
        y = bessel_lowpass(tu, y, rx_bandwidth(data.fmt, data.rate_gbd))
    w0, w1 = data.window()
    m = (tu >= w0) & (tu <= w1)
    return (tu[m] - data.t0) % (n_ui * data.ui), y[m]

"""Figures with the spec boxes drawn (findings-as-plots): spec bands, an eye, metric-vs-x series."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .eye import fold, rx_bandwidth  # noqa: E402
from .sim import H  # noqa: E402
from .stimulus import Data  # noqa: E402

plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 130})
SPEC = {r.key: r for r in H.spec}


def save(fig, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def spec_band(ax, key: str, *, axis: str = "y", color: str = "green") -> None:
    """Draw the bound of `key` and shade its passing side on `ax`; no-op if `key` is not in the spec."""
    r = SPEC.get(key)
    if r is None:
        return
    b, op = float(r.bound), r.op
    line, span = (ax.axhline, ax.axhspan) if axis == "y" else (ax.axvline, ax.axvspan)
    lo, hi = ax.get_ylim() if axis == "y" else ax.get_xlim()
    line(b, color="r", lw=0.8, ls="--")
    span(*((b, hi) if op.startswith(">") else (lo, b)), color=color, alpha=0.06)


def spec_text(metrics: dict, keys) -> str:
    """`label value unit (op bound)` per key, for a metrics box on a figure."""
    lines = []
    for k in keys:
        r, v = SPEC.get(k), metrics.get(k, float("nan"))
        lines.append(f"{r.label if r else k} {v:.2f} {r.unit if r else ''}"
                     + (f" ({r.op} {r.bound:g})" if r else ""))
    return "\n".join(lines)


def eye(t: np.ndarray, x: np.ndarray, data: Data, out: Path, *, title: str = "",
        metrics: dict | None = None, keys=(), ylabel: str = "signal") -> Path:
    """Two eye panels (unfiltered, after the reference receiver) with the spec box text drawn on."""
    fig, axs = plt.subplots(1, 2, figsize=(8, 3.2))
    bw = rx_bandwidth(data.fmt, data.rate_gbd) / (data.rate_gbd * 1e9)
    for ax, filt, panel in ((axs[0], False, "unfiltered"), (axs[1], True, f"after ref Rx (BT4, {bw:g} x baud)")):
        ph, y = fold(t, x, data, filtered=filt)
        ax.plot(ph * 1e12, y, ",", color="navy", alpha=0.35)
        ax.set_xlabel("time within 2 UI [ps]")
        ax.set_ylabel(ylabel)
        ax.set_title(panel, fontsize=8)
    if metrics and keys:
        axs[1].text(0.02, 0.98, spec_text(metrics, keys), transform=axs[1].transAxes, va="top",
                    fontsize=7, bbox={"boxstyle": "round", "fc": "white", "alpha": 0.8})
    fig.suptitle(f"{title} — {data.fmt.upper()} {data.rate_gbd:g} GBd PRBS{data.order}", fontsize=9)
    return save(fig, out)


def series(rows: list[dict], out: Path, *, x: str, ys, by: str = "label", title: str = "",
           logx: bool = False) -> Path:
    """One panel per metric in `ys`: metric vs `x` per `by` series, the spec band on every panel; rows are ledger dicts."""
    fig, axs = plt.subplots(1, len(ys), figsize=(3.2 * len(ys), 3.2), squeeze=False)
    labels = sorted({r.get(by, "") for r in rows}, key=str)
    for ax, y in zip(axs[0], ys):
        for name in labels:
            pts = sorted((r[x], r[y]) for r in rows
                         if r.get(by) == name and isinstance(r.get(y), (int, float)))
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-", ms=3, label=str(name))
        spec_band(ax, y)
        r = SPEC.get(y)
        ax.set_title(f"{y}: {r.label} {r.op} {r.bound:g}" if r else y, fontsize=8)
        if logx:
            ax.set_xscale("log")
        ax.set_xlabel(x)
    axs[0][0].legend(fontsize=6)
    fig.suptitle(title, fontsize=9)
    return save(fig, out)


def frontier(rows: list[dict], out: Path, *, x: str = "rate_gbd", ys, by: str = "label",
             title: str = "frontier") -> Path:
    """`series` on a log x axis: the metric-vs-rate frontier of every candidate."""
    return series(rows, out, x=x, ys=ys, by=by, title=title, logx=True)

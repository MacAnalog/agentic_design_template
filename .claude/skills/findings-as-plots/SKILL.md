---
name: findings-as-plots
description: Make every finding a table or a plot regenerated from simulated data — Bode/passband/noise/transient/eye figures with the spec boxes drawn, per-cell and overlay comparisons, and trade-off scatters — never a number typed into prose. Use when reporting an experiment, certifying a cell, comparing candidates, or when a reviewer asks to "see" a result.
---

# Findings as plots

A finding is a table or a plot; prose is interpretation only. Every figure is produced by code
from simulated data and can be regenerated from the ledger's deck hash — nothing is drawn by
hand and nothing is drawn from a number typed into a doc.

## Rules

1. **Draw the spec on the figure.** Shade the scored band, draw the ±box (flatness window,
   peaking ceiling, stopband floor), mark the crossing that defines the metric. A plot without
   the acceptance box shows a curve, not a verdict.
2. **Per-cell plus overlay.** Each candidate gets its own bode/passband/noise sheet; the set
   gets overlays on one axis (all passbands, all noise densities) and the trade-off scatters a
   decision is actually made on (headline metric vs power, vs area/capacitance), points labelled.
3. **Density for figures, not for scoring.** Re-simulate at figure density (`dec=200`) rather
   than plotting the search-density sweep; state the density in the caption.
4. **Headless, deterministic.** `matplotlib.use("Agg")`; one shared `_style` (grid, labels,
   font size, colour cycle) so figures from different scripts look like one report; fixed axes
   across a comparison so the eye compares curves, not scales.
5. **Filename = provenance.** `<cell>_<kind>.png` beside the scorecard, plus a `figs/` entry
   only for figures a doc cites; the caption names the ledger tag or deck hash.
6. **Raw-file evidence.** For the traces behind a number, the platform's `spicexplorer-waveview`
   `snapshot(raw)` stores a compact `.npz` and exports per-analysis PNG/HTML (Bode for ac/stb,
   time-domain for tran, log-log density for noise, spectrum for pss) with honest defaults
   (branch currents and zero traces excluded).

References: the LPF repo's `lab/plot.py` (`bode`, `passband`, `noise` with the S-boxes),
`scripts/plot_signoff.py` (per-cell + `all_*` overlays + `tradeoff.png`), the PAM-4 driver's
`report/build_report.py` (every tier through the same benches, figures + `data/*.csv` from one
command).

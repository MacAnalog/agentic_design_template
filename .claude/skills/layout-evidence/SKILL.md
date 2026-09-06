---
name: layout-evidence
description: Produce and review a layout as evidence — a measured brief, a parameterized generator (gdsfactory) built to GDS, rendered with PDK colours, DRC/current-density/LVS/PEX verdicts, the post-layout scorecard on the cell's own frozen benches, and a numbered review overlay — using the platform's spicexplorer-layout and spicexplorer-signoff packages and the workspace layout agents. Use when a signed-off schematic cell must become GDS, when a layout iteration needs a before/after record, or when a reviewer asks what the layout costs.
---

# Layout evidence

The layout of record is **code** (a generator whose parameters are the knobs), and every claim
about it is re-derived from that code: brief, GDS, render, DRC, current density, LVS, extraction,
post-layout metrics. The workspace `.claude/agents/layout-*` definitions carry the full procedure;
this file is the method and the gates a design repo owes.

## Flow

1. **Brief before drawing.** `layout-brief-author` runs the cell's frozen benches with injected
   parasitics and mismatch and returns per-net parasitic budgets, matching requirements, the
   **per-net DC current budget** (every net that carries real current, in amps), the two or three
   nets whose terminals must sit on the symmetry axis (measured in metric-per-fF), and explicit
   don't-cares. No layout starts without `BRIEF.md` — budgets read off a finished extraction
   cannot say whether the layout was the best available.
2. **Plan, then generate.** `layout-designer` writes `PLAN.md` (floorplan, power path, techniques)
   and `layout/gen_<cell>.py` (`LayoutParams` + `BOUNDS` + `build(params, sizing) → Component`).
   An autonomous run does not stall on a human gate: record the decisions taken without asking
   under **Assumed approvals** in `PLAN.md` and in the PR's Assumptions, and proceed.
   ```
   spicexplorer-layout build <gen.py> --png     # GDS + <cell>.png with PDK colours
   spicexplorer-layout knobs <gen.py>           # name / default / bounds
   ```
3. **Sign off.** `spicexplorer-signoff drc | lvs | pex` (KLayout runsets, kpex 2.5D) plus
   `spicexplorer_signoff.check_current_density`. LVS must match the netlist from the **certified
   binding** — never one the generator writes from its own device table — and must be run at a
   second sizing point the generator is expected to draw. Splice the extracted netlist into the
   cell's own benches and re-score through the **frozen** measurement path, so the pre and post
   columns are one comparison and not two.
4. **Record every iteration.** `spicexplorer-layout snapshot` stores generator + GDS + PNG +
   verdicts under `iterations/`; `diff it01 it02` writes the before|after PNG; the report table
   comes from `iterations-md`.
5. **Independent review.** `layout-reviewer` rebuilds from the committed generator, re-runs
   DRC/Jmax/LVS/PEX itself, and returns findings three ways: `REVIEW.md`, `REVIEW.yaml`
   (layout-review/1, geometry-anchored) and `REVIEW.png` (`spicexplorer-layout annotate`).
6. **Co-design** when post-layout specs fail: `layout-schematic-codesign` runs the joint
   sizing + knob search through `spicexplorer-optimize` (`sim_engine: layout`), then audits the
   winner — the distance to the nearest cliff on every moved knob, and the rows no objective
   scored.

## The gates a clean run still fails

- **Current density is nobody else's check.** A rule deck checks geometry, LVS checks
  connectivity, extraction models milliohms: a cell passes all three and every bench while
  12–28× over the Metal1 limit. Size the power path from the brief's current budget *before*
  drawing and reserve the floorplan room — widening rails in place afterwards buys 79–117 new
  width/space violations, because the pitches were sized for the thin rail.
- **A Metal1 short is DRC-invisible.** Overlapping metal merges into one legal polygon; only LVS
  sees it. A router needs a per-net obstacle map, and a guard no committed sizing exercises rots.
- **"0 violations" is usually `no_density=True`.** State the flag, and run with density on once.
- **Floorplan quality is a gate, not taste.** Named matching pattern (interdigitated or
  common-centroid) with the device sequence written down, dummies at the array edges, capacitors
  as unit-cell arrays inside a dummy ring, **closed** guard rings rather than periodic point taps,
  a pin frame with labels on the declared sides, a stated aspect ratio. A bare row is a FAIL row.
- **A technique is a knob and has a price.** Dummy rows cost area, coupling and phase — build,
  extract and bench them, and quote the price.
- **A spec that binds at corners pre-layout, re-measured only at nominal post-layout, is a hole.**

## Evidence a reviewer expects

- `layout.png` at readable scale plus per-finding zoom crops; the annotated render.
- The pre→post shift of every scored metric, with the per-net parasitic that explains it, at one
  stated extraction halo (kpex drops couplings beyond the sidewall halo, and the default can flatter).
- DRC/Jmax/LVS logs per tier, the extraction mode, the KLayout/kpex versions — and the blind
  spots stated rather than discovered: MIM stripped for extraction, well↔substrate junction
  capacitance in neither extractor nor model card, no inductance.
- Traps that fake a verdict: more than two concurrent KLayout jobs manufacture failures with
  *empty* violation lists, and a runner that reports a mismatch with an empty `reason` is a
  platform finding to file, not an environment quirk to work around.

References: the workspace `layout-*` agent definitions; `layout/gen_cell.py` and
`layout/signoff.py` in this repo are the skeletons the flow above fills in.

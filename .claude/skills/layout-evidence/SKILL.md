---
name: layout-evidence
description: Produce and review a layout as evidence — a parameterized generator (gdsfactory) built to GDS, rendered to PNG with PDK colours, DRC/LVS/PEX verdicts, the post-layout scorecard on the cell's own benches, and a numbered review overlay — using the platform's spicexplorer-layout and spicexplorer-signoff packages and the workspace layout agents. Use when a signed-off schematic cell must become GDS, when a layout iteration needs a before/after record, or when a reviewer asks what the layout costs.
---

# Layout evidence

The layout of record is **code** (a generator whose parameters are the knobs), and every claim
about it is re-derived from that code: GDS, render, DRC, LVS, extraction, post-layout metrics.

## Flow

1. **Brief before drawing.** The `layout-brief-author` agent (workspace `.claude/agents/`) runs
   the cell's frozen benches with injected parasitics and mismatch to produce per-net budgets,
   matching requirements and don't-cares. No layout starts without `BRIEF.md`.
2. **Generate.** `layout-designer` writes `gen_<cell>.py` (`LayoutParams` + `build(params,
   sizing) → Component`). Build, list knobs, render:
   ```
   spicexplorer-layout build <gen.py> --png     # GDS + <cell>.png with PDK colours
   spicexplorer-layout knobs <gen.py>           # name / default / bounds
   ```
3. **Sign off.** `spicexplorer-signoff drc | lvs | pex` (KLayout runsets, kpex 2.5D) return
   structured verdicts; LVS must match the certified netlist; splice the extracted netlist
   into the cell's own benches and re-score (post-layout scorecard beside the pre-layout one).
4. **Record every iteration.** `spicexplorer-layout snapshot` stores generator + GDS + PNG +
   verdicts under `iterations/`; `diff it01 it02` writes the before|after PNG; the report
   table comes from `iterations-md`.
5. **Independent review.** `layout-reviewer` rebuilds from the committed generator, re-runs
   DRC/LVS/PEX itself, and returns findings three ways: `REVIEW.md`, `REVIEW.yaml`
   (layout-review/1, geometry-anchored) and `REVIEW.png` (`spicexplorer-layout annotate`
   draws the numbered findings over the render).
6. **Co-design** when post-layout specs fail: `layout-schematic-codesign` runs the joint
   sizing + knob search through `spicexplorer-optimize` (`sim_engine: layout`).

## Evidence a reviewer expects

- `layout.png` at readable scale plus per-finding zoom crops; the annotated render.
- The pre→post shift of every scored metric, with the per-net parasitic that explains it.
- DRC/LVS logs per tier, the extraction mode and halo, the KLayout/kpex versions.

References: the PAM-4 driver `layout/` + `report/` (five tiers rebuilt and measured by one
command), the LPF repo `layout/H12-pdk-cap/` (brief → generator → iterations → review).

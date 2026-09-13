"""The design package: the code this design owns.

Three modules are yours to write, and they are the design:

* `dut`     — the sizing point, and the deck every bench is built from
* `metrics` — the scorecard: KEYMAP, check the box, log the row
* `bench`   — the reductions: waveform in, the number the spec is written in out

Three are generic and are imported as they are:

* `sim`  — this repo's simulator-lane policy (where runs go, which binary, which vars). It is a
  DISPATCHER: `lane:` in `harness.yaml` picks `sim_ngspice` (the default — native ngspice) or
  `sim_bridge` (a commercial kit, simulated on the EDA server through the lab's bridge), and
  `design.sim` IS that module. `pdk` goes with the bridge lane: which model library, which sections.
* `exp`  — labelled batches and their markdown tables
* `plot` — figures with the spec boxes drawn on them

Data stimulus (PRBS, NRZ/PAM4 symbols, UI-delayed PWL) and eye metrics live in the platform, in
`spicexplorer_waveview.stimulus` and `.eye`. A link-type design imports them directly; every
other design never sees them.
"""

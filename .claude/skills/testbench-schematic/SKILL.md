---
name: testbench-schematic
description: Draw a testbench as a schematic a reviewer can read — every source, load, probe and the DUT placed and wired as components, with only simulator directives and the .control block as text — then prove it netlists to the certified deck. Use when delivering a bench (op/ac/noise/transient) beside a cell of record, or when a bench exists only as a text deck.
---

# Testbench schematics

**Draw components, not text.** A bench that is one `code` block of SPICE text is not a
schematic; it is a deck with a frame around it. Place and wire every bench element; keep as
text only what has no symbol: `.option`/`.temp`/`.lib` directives and the `.control` block.

## Flow

1. **Start from the certified deck**, never from memory: the bench fragment and the `.control`
   block are lifted verbatim from the deck that certified the numbers, so the drawing's bench
   cannot drift from the bench of record.
2. **Place the DUT** as its `.sym` (pins in the subckt's port order — see `schematic-of-record`),
   then the sources (differential stimulus, bias reference), supplies, series current probes
   (a 0 V source per measured branch), loads and output ports. The platform generator places
   independent sources bottom-left and connects them by net name; move them next to what they
   drive — a reviewer reads the signal path left → right.
3. **Directives and control as text** in a `code`/`simulator_commands` symbol, placed where the
   reader expects it (bottom-right), one block per analysis (`ac`+`noise`, `op`, `tran`).
4. **Gate:** netlist the bench `.sch` and compare canonically to the certified deck (instance
   set, values, connectivity, the DUT call's net order). Then run both through the same
   measurement and require digit-level agreement.
5. **Render** to PNG headlessly, inspect with the Read tool, commit the PNG beside the `.sch`.

## What a reviewer looks for

- The measurement definition is visible: where the noise is input-referred, which probe carries
  only the core's supply current, what the balun gains are.
- Every value on the sheet is the deck's value (no retyped numbers).
- One bench sheet per analysis family; the DUT symbol identical across them.

References: the LPF repo's `signoff/<set>/<cell>_tb*.sch` + `scripts/build_signoff.py`
(op/ac/noise and coherent-transient benches with `.control` in the drawing), the PAM-4 driver's
`schematics/` (benches and DUT sheets side by side).

---
name: schematic-of-record
description: Turn a certified SPICE netlist into the human-readable xschem schematic (.sch/.sym) that is the repo's reviewable artefact of record, prove drawing ≡ netlist ≡ simulation, and commit a PNG render as evidence. Use whenever a delivered cell needs a schematic, a reviewer asks to "see the circuit", or a netlist-lane design must land as .sch.
---

# Schematic of record

**Generate, never transcribe.** Every size, net and model comes from the as-built netlist; the
drawing is a projection of it, and two gates prove the projection is faithful.

## Flow

1. **Draw from the netlist.** Start with the platform generator, which places rails, stacks,
   mirrored pairs and I/O ports and renders headlessly:
   ```
   uv run --project ../../spicexplorer-platform netlist2xschem <asbuilt.sp> --into <dut_subckt> \
       --name <cell> --out <dir>/<cell>.sch --render --out-image <dir>/<cell>.png
   ```
   For a topology with a known reviewer-friendly frame (stage A left / stage B right, halves
   mirrored about the centre line, caps drawn between the halves), write a small emitter that
   *asserts* each placement's expected net against the netlist — a cell whose connectivity
   differs fails loudly instead of drawing a lie (reference: the LPF repo's
   `scripts/draw_xschem.py`).
2. **Gate 1 — netlist identity.** Re-netlist the `.sch` (`xschem -n -q -x -o <dir> <cell>.sch`)
   and compare canonically against the as-built: same instance set, same model per instance,
   w/l/ng/m/values within 0.1 %, connectivity equal under a net bijection checked in both
   directions with interface nets pinned to identity (reference: `scripts/check_netlist.py`).
3. **Gate 2 — simulation parity.** Run the as-built and the xschem-emitted netlist through the
   same certification path in one batch; require digit-level agreement on every scorecard field.
   A disagreement is a drawing bug, never a tolerance to widen.
4. **Visual inspection is mandatory.** Open the PNG with the Read tool; iterate until it reads
   like a textbook schematic (no overlaps, symmetry evident, legible values). Commit the PNG
   beside the `.sch`; a `.sch` without a render left no evidence.
5. **Symbol.** Emit `<cell>.sym` with pins in the exact order the testbench's subckt call uses.
   A reordered pin list is a silent miswiring no cell-level diff catches — netlist the bench and
   check the `x…` call's net order.
6. **Annotate the operating point** (optional, reviewer gold): stamp Vds/Vdsat/Id/gm/ID per
   device as text elements only (reference: `scripts/annotate_op.py`); re-run both gates after.

## Traps that each cost a debug cycle

- xschem attributes are lowercase-sensitive (`W=` is silently ignored); wires connect only at
  segment endpoints; only `lab_pin`/`ipin`/`opin` name nets; `{}` inside `T{}` must be `()`.
- PDK devices that are `.subckt` wrappers netlist with an `X` prefix — name instances to match
  the as-built convention or Gate 1 fails for a cosmetic reason.
- Instance ORDER can be load-bearing in ngspice at loose default tolerances: emit devices in
  netlist order so the Newton trajectory is identical (measured: 6 µV on a gate net, fc −6.7 mHz).
- Headless render on a host whose xschem lacks cairo exports a broken SVG header; repair the
  viewBox and stroke widths before rasterizing (reference: `scripts/render_sch.py`).
- Sizes are read-only here. Fractional `m` or > 3-decimal sizes are a realization finding to
  report, not something to round silently.

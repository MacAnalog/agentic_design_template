# <cell> layout plan

KIND: PLAN (copy this file to `layout/<cell>/PLAN.md` and fill it in before the generator draws any
geometry; both lanes, `gen_cell.py` and `gen_cell_bridge.py`)

**Order.** `layout-brief-author` researches this block and writes `layout/<cell>/BRIEF.md`;
`layout-designer` writes this plan from that research; `layout-reviewer` reviews the plan, with
its own research of the block, before any geometry exists; the generator is written from the
approved plan; after each DRC, LVS, PEX and post-layout bench result the designer revisits the
plan's decisions in the revision log below, not only the geometry.

**Every decision names its reason** as a brief row (`BRIEF.md` table and row) or a measured number.
Matching patterns, dummies, shielding and guard rings are chosen per group for a reason this
block's research gives; none is applied because it is the usual choice.

**Kit facts are named, not written.** Layers are the layer keys of the kit file (`metal1`,
`pins.metal1`), rules are `kit.rule("<name>")`, and current limits come from the kit file or the
`pdk-<id>` skill; a limit neither carries is written `not in kit file`. No layer number, rule value
or device master is written here.

## 1. Research inputs

| brief row | finding (with number) | decision it drives (section) |
|---|---|---|
| | | |

Block properties the brief established: symmetry axes, sensitivity to process gradient, stress and
temperature, parasitic-sensitive nets and their budgets, electromigration nets, high-impedance
nodes and their leakage budget, RF or timing budgets where the block has them.

## 2. Outline and aspect

| item | value | because |
|---|---|---|
| outline (W x H, um) | | |
| aspect ratio ceiling | | |
| symmetry axis | | |

Floorplan sketch (ASCII): rows and columns, symmetry axis, capacitor arrays, well islands, pin
sides.

```
```

## 3. Device groups and matching patterns

| group | devices (netlist names) | tolerated mismatch (brief) | pattern | orientation | because |
|---|---|---|---|---|---|
| | | | | | |

## 4. Dummies

| group | dummies per row end | connected to | because |
|---|---|---|---|
| | | | |

## 5. Guard rings and taps

| well island | ring type (closed ring / taps) | width | tap pitch | because |
|---|---|---|---|---|
| | | | | |

## 6. Pin frame

| pin | side | layer key | width | because |
|---|---|---|---|---|
| | | | | |

## 7. Per-net metal stack

One row per net the brief ranks, every supply and bias net, and every net that carries more than
the kit's minimum-width current limit. Width follows from the net's worst DC (rms AC) current and
the layer's current limit; via count from the via limit.

| net | role (signal / supply / bias) | layer keys | worst current (brief) | width (um) | via count per transition | shield (layer key, tied to) | budget (brief) | because |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## 8. Generator knobs

| knob | default | range | section it implements |
|---|---|---|---|
| | | | |

Device sizes (W, L, fingers, m) come from the sizing file, never from a knob.

## 9. Out of scope

Fill and density, seal ring and pads, unless the brief asks for them.

## 10. Assumed approvals

Decisions taken without a human, each also listed in the PR's Assumptions.

## 11. Plan review

| round | reviewer | plan sha | verdict | findings |
|---|---|---|---|---|
| | | | | |

Geometry starts after a round whose verdict accepts the plan.

## 12. Revision log

One row per change to a decision above. The feedback is a DRC rule and count, an LVS mismatch, a
PEX attribution (which net, which coupling or resistance, its share of the metric's shift) or a
post-layout bench metric against its pre-layout value.

| rev | iteration | feedback (tool, finding, net, number) | section changed | before -> after | reason |
|---|---|---|---|---|---|
| | | | | | |

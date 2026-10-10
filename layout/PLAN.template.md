# <cell> layout plan

plan-version: 1

KIND: PLAN (copy this file to `layout/<cell>/PLAN.md` and fill it in before the generator draws any
geometry; both lanes, `gen_cell.py` and `gen_cell_bridge.py`)

**Order.** `layout-brief-author` researches this block and writes `layout/<cell>/BRIEF.md`;
`layout-designer` writes this plan from that research; `layout-reviewer` reviews the plan, with
its own research of the block, before any geometry exists; the generator is written from the
approved plan; after each DRC run, LVS compare, extraction and post-layout bench run and each review
round the designer revisits the plan's decisions in *Plan revisions* below, not only the geometry.
`plan-version:` is 1 for the first plan and goes up by one with each revision that changes a
decision.

**Every decision names its reason** as a `BRIEF.md` row (table and row), a `LAYOUT-RESEARCH.md`
section, or a measured number.
Matching patterns, dummies, shielding and guard rings are chosen per group for a reason this
block's research gives; none is applied because it is the usual choice.

**Kit facts are named, not written.** Layers are the layer keys of the kit file (`metal1`,
`pins.metal1`), rules are `kit.rule("<name>")`, and current limits come from the kit file or the
`pdk-<id>` skill; a limit neither carries is written `not in kit file`. No layer number, rule value
or device master is written here.

## 1. Research inputs

| `BRIEF.md` row or `LAYOUT-RESEARCH.md` section | finding (with number) | decision it drives (section) |
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

`layout-reviewer` reviews this plan in plan mode, with its own research of the block, and writes
`PLAN-REVIEW.md`; the designer commits it unchanged as `layout/<cell>/PLAN-REVIEW.md` beside this
file. Each finding is answered here, by a revision (raise `plan-version:`, add a *Plan revisions*
row citing the finding) or by the evidence that the decision holds. Before the second dispatch the
designer renames the committed first review to `layout/<cell>/PLAN-REVIEW-1.md`; the second review
is committed as `PLAN-REVIEW.md`.

| review round | finding | answer (plan-version raised to, or the evidence) |
|---|---|---|
| | | |

Geometry starts when the last line of `PLAN-REVIEW.md` is `ALL PASS (layout)`. If the second plan
review still has open findings, the designer stops and hands back with `PLAN-REVIEW-1.md` and
`PLAN-REVIEW.md`;
no geometry is drawn against a plan with open findings. The plan reviews are not geometry review
rounds: those are at most 4, counted separately.

## 12. Plan revisions

Revisited after each DRC run, LVS compare, extraction and post-layout bench run, and each review
round (plan and geometry). The feedback is attributed first: a DRC rule and count, an LVS mismatch,
a PEX attribution (which net, its extracted C or R against the brief's budget, the metric it moves
and its share of the shift), a post-layout bench metric against its pre-layout value, or a review
finding id. A changed decision raises `plan-version:` and adds one row. When no decision changes,
the row keeps the version, writes `geometry only` as the decision, and gives the reason the plan
decision still holds; a round with no row did not revisit the plan.

| version | round | decision (section, from -> to) | feedback that drove it | evidence path |
|---|---|---|---|---|
| | | | | |

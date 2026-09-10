# The layout of record

KIND: REFERENCE

**What belongs here:** what the generator produced and what the sign-off tools said about it. The
generator itself is code and stays in `layout/` at the repo root — this directory holds its output.

| file | what it is | produced by |
|---|---|---|
| `<cell>.gds` | the layout of record | `layout/gen_cell.py` |
| `<cell>.png` | the render a reviewer looks at | `layout/signoff.py` |
| `drc.txt`, `lvs.txt` | the clean reports, kept as evidence | `layout/signoff.py` |
| `<cell>.pex.sp` | the extracted netlist the post-layout fidelities simulate | `layout/signoff.py` |
| `params.json` | the generator parameters that produced this GDS | `layout/gen_cell.py` |

**`params.json` is what makes the GDS reproducible.** A layout whose parameters were not recorded
cannot be rebuilt, so it cannot be re-verified — and an unverifiable layout is not signed off.

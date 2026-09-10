# The topology of record

KIND: REFERENCE

**What belongs here:** the one netlist every fidelity in this tree was measured from, its human
readable sheet, and the sizing that produced it.

| file | what it is | produced by |
|---|---|---|
| `<design>.sp` | the as-built subckt — the netlist the benches instantiate | `<package>/dut.py`, written at certification |
| `<design>.sch` + `<design>.png` | the xschem sheet and its render, proven equal to the netlist | the `schematic-of-record` skill |
| `sizing.csv` | every device, its W/L, multiplicity and operating point | `make certify` |

**A hand drawing is not a schematic of record.** The sheet is generated from the certified netlist
with `spicexplorer-netlist2xschem` and proven equal to it; that proof is what makes the picture
evidence rather than decoration.

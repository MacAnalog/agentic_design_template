# Design reference

KIND: REFERENCE (curated semantic facts; the pack carries the constraints section in full)

Every entry below names where it came from: an experiment directory, a ledger tag, or a paper
handle from `pdf/INDEX.md`. When a later measurement contradicts an entry, supersede it here and
cite the run that overturned it. Deleting it instead leaves the next agent to repeat the attempt
that failed.

## Device map

<role → device, W/L, bias; the netlist of record and how `design.dut.Design` maps onto it>

Name each device exactly as the netlist of record does, so a reader can follow a role to a line in
that netlist. Give every bias current and voltage its conditions: supply, corner, temperature.

## Validated model

<the hand model that predicts the headline metric, and the measured error against simulation>

The error figure is what earns the heading. State the relation, the run it was compared against,
and how far it missed over what range. A relation quoted with no error against simulation tells
the reader nothing about how far to trust it.

## Facts that constrain every candidate

`make lint` fails when the pack retrieves no item from this section, so keep the items a `1.` list
at column 0 (or `**Cn — …**` paragraphs). Order the list by how much each item decides: the
constraint that rules out the most candidates comes first, the ones that only trim a range last.

1. <constraint one — the claim first, then its provenance (experiment, ledger tag, paper)>

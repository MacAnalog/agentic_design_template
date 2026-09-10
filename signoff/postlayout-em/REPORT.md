# Post-layout (EM) sign-off — <design>

KIND: REPORT (fidelity: layout of record, EM-solved interconnect and passives)

**Verdict: <met / not met> at <date>.** <One sentence: which spec rows passed, which did not, and
the one number a reader should remember.>

## Conditions

| condition | value |
|---|---|
| netlist | `../schematic/<design>.sp` |
| decks | `decks/` (sha-locked; `make freeze`); scorecard `decks/scorecard.json` |
| PDK / model revision | <name and revision — never model bytes> |
| supply, temperature | <e.g. 1.2 V, 27 °C> |
| corners run | <nominal only / the corner set> |
| simulator lane | <the lane, per `doc/environment.md`> |

## Scorecard

Regenerated from `scorecard.json` — do not retype these numbers.

| spec | requirement | measured | margin | verdict |
|---|---|---|---|---|
| <S1 gain> | <≥ 60 dB> | <> | <> | <> |

## Evidence

| claim | figure or table |
|---|---|
| <the headline claim> | `figs/<name>.png` |
| <the sweep behind it> | `tables/<name>.csv` |

## What this does not cover

- <the conditions nobody ran: corners, mismatch, post-layout — say it plainly>

# Target spec

**KIND: SPEC.** The acceptance box. Its machine twin is `spec:` in `harness.yaml`; every bound
below must appear there verbatim and vice versa (`make lint`).

| # | requirement | target | reference baseline | checked by | where the bound comes from |
|---|---|---|---|---|---|
| S1 | gain | ≥ 60 dB | — | `design.metrics.evaluate` | <paper handle / standard / allocated-from row> |
| S2 | phase margin | ≥ 60 deg | — | `design.metrics.evaluate` | <…> |
| S3 | power | ≤ 100 uW | — | `design.metrics.evaluate` | <…> |

Every bound cites its origin in the last column: a number with no origin is a preference, and
nobody downstream can tell which bounds are negotiable. Fill the reference column from the
certified scorecard once `make check` passes (`make lint` then holds the two in sync).

**If the reference is not at this challenge's operating point** — different supply, device family
or load — say so here and mark, per row, which bounds it legitimately sets and which come from
the literature instead. A yardstick quoted outside its conditions is not a yardstick.

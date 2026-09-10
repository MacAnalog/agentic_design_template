# Target spec

**KIND: SPEC.** The acceptance box. Its machine twin is `spec:` in `harness.yaml`; every bound
below must appear there as the same number, and vice versa (`make lint`).

| # | requirement | target | reference baseline | checked by | where the bound comes from |
|---|---|---|---|---|---|
| S1 | gain | ≥ 60 dB | — | `design.metrics.evaluate` | <paper handle / standard / allocated-from row> |
| S2 | phase margin | ≥ 60 deg | — | `design.metrics.evaluate` | <…> |
| S3 | power | ≤ 100 uW | — | `design.metrics.evaluate` | <…> |

The last column carries each bound's origin. A bound with no origin is a preference, and no
later reader can tell which bounds are negotiable. Fill the reference column from the
certified scorecard once `make check` passes (`make lint` then holds the two in sync).

**If the reference is not at this challenge's operating point** — different supply, device family
or load — record its conditions here. Then mark, per row, which bounds that reference sets and
which come from the literature instead, because a yardstick measured under other conditions sets no
bound at this one.

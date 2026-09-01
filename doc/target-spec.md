# Target spec

**KIND: SPEC.** The acceptance box. Its machine twin is `spec:` in `harness.yaml`; every bound
below must appear there verbatim and vice versa (`make lint`).

| # | requirement | target | reference baseline | checked by |
|---|---|---|---|---|
| S1 | gain | ≥ 60 dB | — | `lab.metrics.evaluate` |
| S2 | phase margin | ≥ 60 deg | — | `lab.metrics.evaluate` |
| S3 | power | ≤ 100 uW | — | `lab.metrics.evaluate` |

Fill the reference column from the certified scorecard once `make check` passes.

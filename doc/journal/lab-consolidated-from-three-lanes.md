# 2026-09-04 — lab consolidated from the LDO, transmitter and LPF lanes

KIND: journal entry | type: procedural | status: live

Three design repos had each rewritten the same simulation lane. The generic parts were first
consolidated into `lab/`, then (same day) moved into the platform; `lab/` now imports them and a
new repo copies the thin wrappers. The rest stays where the design is.

| module | from | what it is |
|---|---|---|
| `lab/sim.py` | LDO `lab/sim.py` (per-run dirs, fatal scan, `parse_measures`, doctor ok only on a parsed scalar); transmitter `lab/sim.py` (per-run `.spiceinit`, `raw()`, warnings recoverable); LPF `lab/ngspice.py` (the original: work dir per checkout, `extra_files`, `wall.txt`) | deck text → run dir; scalars parsed from the log; failed `.meas` → `Run.failed`; `spicelib.RawRead` (via the platform core) and waveview `WaveDataset` views of the rawfile. Now: this repo's where/which/what policy over the platform's `run_deck` (table below) |
| `lab/stimulus.py` | transmitter, verbatim | PRBS, NRZ/PAM4 symbols, UI-delayed PWL taps. Now a re-export of `spicexplorer_waveview.stimulus` |
| `lab/eye.py` | transmitter `lab/rx.py` | symbol-aware eye metrics + BT4 reference receiver; FFT latency search; OMA/VECP from unclamped level differences (any polarity), ER only for a unipolar input. Now a re-export of `spicexplorer_waveview.eye`, which also registers the `eye` measurement kind |
| `lab/exp.py` | transmitter | labelled batch (`run_batch(designs, score, prefix=, workers=)` takes the scorer instead of importing `metrics`), markdown tables, `out/` files |
| `lab/plot.py` | transmitter (`eye`, `frontier`); LPF (`bode`/`passband` spec boxes as the pattern) | `spec_band`, `spec_text`, `eye(t, x, data, out)`, `series`/`frontier(rows, out, ys=, by=)` |

Stays repo-specific: the PDK-device preflight deck (LV NMOS / HBT + diode / HV NMOS — passed to
`preflight(deck, expect)`), `lab/config.py` (PDK paths, lib names, corners), `lab/dut.py` +
`lab/deck.py` (the DUT and its benches), `lab/metrics.py` (measure → spec keys, the
`--certify`/`--check` drift tolerances), the LPF docker lane and its own rawfile reader, the
transmitter's `eo_s21`/`dc_transfer` figures and the `parallel.py` job cap.

Conventions carried over: `exp_env: FOO_EXP` names `FOO_NGSPICE` and `FOO_WORK`, so a repo that
switches keeps its environment variables — now the `sim_env`/`work_env` keys of `harness.yaml`,
defaulted by that prefix rule (`spicexplorer_harness.config`). New host requirement: `SPICE_USERINIT_DIR` must point
at the PDK's ngspice directory (its `.spiceinit` is copied into every run dir); `~/.spiceinit`
and a hard-coded binary path are no longer fallbacks.

## Switch-over per repo (proposed diffs, not applied)

**LDO** (`lab/sim.py` was the platform-wrapper lane)
- `lab/sim.py` → this repo's file (a wrapper over `spicexplorer_core.spice_engine.run_deck`). Env
  names unchanged (`LDO_NGSPICE`, `LDO_WORK` — `exp_env: LDO_EXP` defaults them; or set
  `sim_env`/`work_env` in `harness.yaml`).
- `lab/metrics.py` `run_decks`: `r.log_path` → `r.log`; `rec.update(..., rc=r.rc)`; the failed-`.meas`
  → NaN promotion now works as written (`Run.failed` is populated from the real ` meas … failed!`
  line). Keep the old "no scalar is a failure" rule with one line after `sim.run`:
  `if not r.measures and not r.failed: raise sim.SimError(...)`.
- `lab/config.py`: drop `WORK`, `NGSPICE` (use `sim.work()`, `sim.ngspice()`); `lab/sim.py` no
  longer imports `spicexplorer_analog_db.runner`.
- Doctor: `preflight(deck=<LV NMOS .op deck printing id_ua>, expect=("id_ua", <recorded value>, <tol>))`
  from a 3-line `__main__`. The wrapper's `*`-title requirement (journal item 4) no longer applies.

**Transmitter** (`lab/sim.py` was the subprocess lane; `rx.py`, `exp.py`, `plot.py` were the originals)
- `lab/sim.py` → this file plus one line: `SPICEINIT_EXTRA = "set ngbehavior=hsa"`. Delete
  `config.spiceinit()`, `config.ngspice()`, `config.WORK`. Deps: add `spicexplorer-waveview` (which
  brings scipy).
- `lab/stimulus.py` → this file (a re-export of `spicexplorer_waveview.stimulus`, same API).
  `lab/rx.py` → delete; `from .eye import eye_metrics, fold` (`spicexplorer_waveview.eye`);
  `eye_metrics(..., pin=)` → `full_scale=`; `p_levels` → `levels`; re-create the aliases in `measure_eye`:
  `v["er_pam4_db"] = v["er_db"]; v["pam4_ecp_db"] = v["vecp_db"]` (`metrics.py` SOFT keys, `doc/benches.md`).
- `lab/exp.py` → this file. Experiments 001–006: `exp.run_batch(designs, kind="frontier", prefix=…)` →
  `exp.run_batch(designs, partial(metrics.evaluate, kind="frontier"), prefix=…)`; rows keep `_v`
  (callers already pop it); every bare `exp.passes(r)` → `exp.passes(r, keys=("er_db", "vecp_db",
  "eye_w_ui", "epb_pj"))` or a 3-line local `passes`.
- `lab/plot.py` → this file + local `eo_s21`, `dc_transfer`, and a ~6-line `eye_from_run(rd, data, out, …)`
  that reads `v(pout)` off `sim.raw(rd)` and calls `plot.eye(t, x, data, out, metrics=, keys=)`;
  `plot.frontier(..., series="series")` → `by="series"`, `ys=` is required.
- `lab/parallel.py`: keep (its cap of 24) or drop for `exp.run_batch(workers=)`.

**LPF** — a shim, not a delete (19 importers of `lab.ngspice`: `run/plots/simulate/wall_time/preflight/SimError`)
- Add this `lab/sim.py`; `lab/ngspice.py` becomes: `SimError`, `deck_hash`, `preflight`, `wall_time`
  re-exported from `lab.sim` (`SimError` is the platform's `DeckRunError`; `deck_hash` stays the
  harness's — the same sha256 prefix `run_deck` names its directories by); `run()` delegates to
  `lab.sim.run` when `C.lane() == "native"` (returns the platform `RunResult`, `Path`-compatible)
  and keeps the docker branch otherwise;
  `plots(rd) = read_raw(sim._raw_path(rd, "sim.raw"))`; `simulate = plots(run(...))`.
- `lab/config.py`: `WORK` default `/tmp/lpf_work-…` → `sim.work()` (the lane rejects `/tmp`);
  `Makefile` doctor stays `python -m lab.ngspice` with the HV-NMOS deck passed to `preflight(deck, expect)`.

## Platform gaps — closed the same day (platform `feat/harness-spec-v2`)

Four of the five gaps landed in the platform and `lab/` now imports them:

| `lab/` name | platform home | note |
|---|---|---|
| `sim.run`, `sim.Run`, `sim.SimError` | `spicexplorer_core.spice_engine.run_deck` → `RunResult`, `DeckRunError` | `lab.sim.run` adds this repo's rule "no rawfile and no scalar is a failure" and passes `work()/runs`, `spiceinit()`, `ngspice()`, the `PDK`/`PDK_ROOT` defaults |
| `sim.parse_measures`, `sim.fatal_lines` | `spicexplorer_core.spice_engine.sim_log` (re-exported by `spicexplorer_waveview.logs` beside `parse_log_text`) | `classify_line` moved to core with them (core cannot import the viewer); the bare `doAnalyses`/`Transient solution failed`/`timestep too small`/`singular matrix` lines are errors now, `Warning:`-prefixed ones stay warnings |
| `sim.work`, `sim.ngspice`, `sim.userinit_dir`, `sim.spiceinit`, `sim._env`, `sim.preflight`, `sim.raw`, `sim.dataset`, `sim.wall_time`, `sim.PROBE`, `sim.SPICEINIT_EXTRA` | stay here | PDK/host policy of one design, not platform mechanism |
| `sim.LANE_ENV`, `sim.WORK_ENV` | `harness.yaml` `sim_env`/`work_env` (`spicexplorer_harness.config`, prefix-rule defaults, `FIX:` on a bad name) | the constants read `H.sim_env`/`H.work_env` |
| `stimulus.*` (`Data`, `prbs`, `symbols`, `pwl`, `ideal_waveform`) | `spicexplorer_waveview.stimulus` | verbatim |
| `eye.*` (`eye_metrics`, `fold`, `latency`, `levels`, `rx_bandwidth`, `bessel_lowpass`, `resample`, the constants) | `spicexplorer_waveview.eye` | also registers the `eye` measurement kind (`{meas: vecp_db, out, fmt, rate_gbd, …}` on `sim.dataset(run)`) |
| `exp.*`, `plot.*` | stay here | the ledger/batch/spec half is already the harness; the figures are this repo's spec boxes |

Still open: a docker ngspice lane so the LPF's can retire.

Procedural write (`lab/`, `Makefile`, `pyproject.toml`) — proposed for owner review per
CLAUDE.md rule 10.

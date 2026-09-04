# 2026-09-04 — lab consolidated from the LDO, transmitter and LPF lanes

KIND: journal entry | type: procedural | status: live

Three design repos had each rewritten the same simulation lane. The generic parts now live in
`lab/` and a new repo imports them; the rest stays where the design is.

| module | from | what it is |
|---|---|---|
| `lab/sim.py` | LDO `lab/sim.py` (per-run dirs, fatal scan, `parse_measures`, doctor ok only on a parsed scalar); transmitter `lab/sim.py` (per-run `.spiceinit`, `raw()`); LPF `lab/ngspice.py` (the original: work dir per checkout, `extra_files`, `wall.txt`) | deck text → run dir; scalars parsed from the log; `spicelib.RawRead` and waveview `WaveDataset` views of the rawfile |
| `lab/stimulus.py` | transmitter, verbatim | PRBS, NRZ/PAM4 symbols, UI-delayed PWL taps |
| `lab/eye.py` | transmitter `lab/rx.py` | symbol-aware eye metrics + BT4 reference receiver (`pin` → `full_scale`; the `er_pam4_db`/`pam4_ecp_db` aliases of `er_db`/`vecp_db` dropped) |
| `lab/exp.py` | transmitter | labelled batch (`run_batch(designs, score)` takes the scorer instead of importing `metrics`), markdown tables, `out/` files |
| `lab/plot.py` | transmitter (`eye`, `frontier`); LPF (`bode`/`passband` spec boxes as the pattern) | `spec_band`, `spec_text`, `eye`, `series`/`frontier` |

Stays repo-specific: the PDK-device preflight deck (LV NMOS / HBT + diode / HV NMOS — passed to
`preflight(deck, expect)`), `lab/config.py` (PDK paths, lib names, corners), `lab/dut.py` +
`lab/deck.py` (the DUT and its benches), `lab/metrics.py` (measure → spec keys, the
`--certify`/`--check` drift tolerances), the LPF docker lane and its own rawfile reader, the
transmitter's `eo_s21`/`dc_transfer` figures and the `parallel.py` job cap.

Convention carried over: `exp_env: LDO_EXP` names `LDO_NGSPICE` and `LDO_WORK`, so a repo that
switches to these modules keeps its environment variables.

Platform gaps met on the way, to open against the platform: a deck-string
`run(deck, label, workdir, spiceinit)` beside the file-centric `NGSpice_Wrapper`;
`parse_measures` beside `parse_log_text` in `spicexplorer_waveview.logs` (today only the
analog-db tier runner has it); `harness.yaml` has no `sim_env`/`work_env` key (the prefix rule
above stands in); eye metrics with known symbols as a waveview measurement.

Procedural write (`lab/`, `Makefile`, `pyproject.toml`) — proposed for owner review per
CLAUDE.md rule 10.

# (last updated 2026-10-14 evening: T1 done, T2 done, T3 running)

# StartScale v2 — implementation status against the Design & Implementation Guide

Audit date 2026-10-14. "Real" = needs the kind cluster (docker/kind/kubectl are **not installed on this
machine**, so nothing below that is marked *pending cluster* could be run here).

| Phase | Guide exit criterion | State | Evidence |
| --- | --- | --- | --- |
| 0 Literature lock | 25-paper table with an empty cell | **Not done** (no artefact in repo) | — |
| 1 Testbed | 5-node kind, registry, netem, 3 image sizes, stress-ng, Prometheus | **Partial.** Earlier work ran a 4-node kind with one small image and CPU/mem pressure YAMLs. Scripts for the full testbed now exist but were never run | `target-app/*.yaml`, `testbed/` |
| 2 Measurement harness | validated row per pod, all phases | **Partial.** `measure_harness.py` records request→ready only; no scheduled/pull/started phase split, no probe-quantisation term | `target-app/measure_harness.py` |
| 3 Dataset | ≥3,000 rows, >10× spread, data card | **Not met.** 150 events, one 80 MB-class image, ready latency 4.6–12.0 s (**2.6× spread**, so H1 is *not* supported by the data so far). Randomised factorial plan (850 runs, ~3,480 events) generated; execution *pending cluster* | `target-app/v3_master_150_*.csv`, `results/phase3_plan.csv` |
| 4 Readiness model | CQR coverage within 3 pts on condition split | **Done offline on the 150 events; exit criterion not met** (see below) | `startscale/readiness.py`, `results/exp_b_summary.csv` |
| 5 Traffic forecaster | forecasts at required horizon, error characterised | **Done** (seasonal-trend + Holt + oracle-with-noise) | `startscale/forecast.py` |
| 6 Controller | identical module on both adapters, no thrash | **Done for the twin; KubernetesAdapter written, untested** | `startscale/controller.py`, `kube_adapter.py`, `tests/` |
| 7 Placement | warm/cold pool experiment | Pre-pull + soft-affinity implemented; twin analogue run; **real run pending cluster** | `controller.py`, Exp F in `results/twin_report.md` |
| 8 Twin + sweep | calibration table, Pareto, ablations | Twin, risk/horizon sweeps and ablations **done**. **Calibration table (30 paired real/twin runs) not done** — needs cluster runs of the new controller | `startscale/twin.py`, `results/` |
| 9 Real headline experiments | 5 seeds × 6 workloads × 5 controllers | **Pending cluster** | — |
| 10 Artefacts/paper | Zenodo, GitHub, paper | Not started | — |

## Pre-existing work (before this session)
Ad-hoc pipeline: 150 labelled startup events (`v3_master_150_*`), GradientBoosting/RF comparisons, a hand-rolled
p90 offset "conformal" step (`conformal_quantile_calibration.py`), HPA baseline runs and trace replays
(NASA, Azure, WorldCup98), and `startscale_live_controller.py` (a script that predicts and prints a
SCALE_NOW / PREPARE / WAIT decision, with no ledger, no `ClusterAdapter`, no actuation).
Trace preprocessing (`preprocess_*.py`, parquet files) was already done.

## Added this session
* `startscale/` package: `readiness.py` (LightGBM pinball quantiles on a τ-grid + one-sided split-conformal
  correction, non-crossing), `predictor.py`, `ledger.py` (prob / count-all / ready-only), `forecast.py`,
  `controller.py` (compensate / hedge / reduce, horizon-matching, rails, hysteresis, coverage-triggered fallback),
  `baselines.py` (HPA v2 semantics, KEDA-style rate trigger), `adapter.py` (`ClusterAdapter`),
  `twin.py` (`SimAdapter`, SimPy), `kube_adapter.py`, `workloads.py` (6 synthetic + WorldCup98 + NASA).
* `experiments/`: B (predictor), C/D/E/F/G/J (twin sweeps), H/I/SHAP, analysis + figures, Phase-3 plan.
* `testbed/`: kind config, registry/netem/stress-ng/image-build scripts (unrun).
* `tests/`: 6 tests (coverage guarantee, ledger, seasonal forecaster, same controller in twin, soft affinity only).

## How to reproduce
```bash
cd Web_Autoscaling
.venv/bin/python -m pytest -q tests
.venv/bin/python experiments/exp_b_predictor.py
.venv/bin/python experiments/run_twin_sweeps.py        # ~10 min; add --quick for a smoke run
.venv/bin/python experiments/analyze_twin.py           # tables -> results/twin_report.md, figures -> results/figures/
.venv/bin/python experiments/exp_hi_drift_transfer_shap.py
```

## Results so far (read these before claiming anything)
Full tables: `results/twin_report.md`, `results/exp_b_summary.csv`, `results/offline_extras.md`. Figures: `results/figures/`.
All control results are from the **twin** (5,015 runs, 5 seeds, 8 workloads); none are real-cluster results.

**Measured data (Exp B, 150 events).** Latency spread is only 2.6×, so H1 (order-of-magnitude variation) is not supported by
the current testbed. On the condition-grouped split LightGBM q50 (MAE 0.83 s) does **not** beat the per-image median
(0.78 s) or the global mean; it wins only under random folds (0.53 vs 0.67 s), i.e. it interpolates. H3 is not shown.
Upper-quantile calibration is good (q90 coverage 0.92 grouped, 0.90 random), but the central 80% interval under-covers on
unseen conditions (0.63), so the "within 3 points on the held-out condition split" exit criterion is **not met** for intervals.
SHAP: `worker_cpu_mean` dominates; the cache flag is only 5th, which the weak cold/warm gap (6.6 s vs 6.0 s mean) explains.

**Twin (Exp C/D/G/F/E/J).**
* StartScale (τ=0.9, realistic forecaster) has lower SLO violation than every tuned HPA setting and KEDA-style trigger
  (extended-cold: 0.031 vs 0.039–0.077) at equal or lower replica-seconds. Pooled Mann–Whitney tests are **not
  significant** after Holm correction (workload heterogeneity: many workloads have ~0 violations for everyone).
* Most of the gain comes from forecasting, not readiness awareness: `forecast_only` is within 0.001–0.009 of StartScale on
  the realistic forecaster. With the controlled (oracle ±10%) forecaster the readiness lever shows clearly in the
  extended-cold profile: violation 0.003 at τ=0.9 vs 0.014 at τ=0.5, and τ traces a monotone SLO-cost trade-off.
* Ablations: removing compensation hurts (0.026 vs 0.014 measured; 0.042 vs 0.031 extended). The **ledger and the
  conformal layer show no measurable effect**, and **placement/pre-pull did not help in the sweep** (timing-only was
  better: 0.023 vs 0.031; Exp F likewise), contradicting H5 in the twin. Per the guide these components must earn their
  place or be cut; as implemented they have not yet. A single-seed oracle probe earlier did show a placement gain, so the
  heuristics (pre-pull trigger, node weights, 6-pods/node cap) are the first suspects, not the idea itself.
* Horizon-matching (E): on repeated bursts, violation falls from 0.20 (H=15 s) to ~0 (H=180 s) with the matched horizon
  at 0.02–0.07; on a smooth ramp nothing matters.
* Adversarial bursts (J): StartScale beats HPA at every period except 120–200 s at τ=0.9 (worse than τ=0.5),
  i.e. hedging high can cost more under periods near the dead time.
* Drift (ADWIN, twin analogue): fired 55 events after a simulated heavier-image change; stale q90 coverage 0.41, refit 0.65.

**Twin caveats.** Fluid per-second queue (not per-request); "extended" profile adds cold-pull time = size/bandwidth as an
*assumption* until Phase 3 runs; no sim-to-real calibration yet; `measured` and `extended` dead times are not from the
same experiment.

## Next steps (all need the cluster except the first)
1. Install docker/kind/kubectl; run `testbed/setup.sh`, build images, execute `results/phase3_plan.csv` (driver still to write).
2. Refit the model on the real factorial data, replace the `extended` assumption, rerun the sweeps.
3. Debug the placement/pre-pull heuristics; run Exp F on the real pools A/B; 30 paired runs for the calibration table.
4. Phase 0 literature table; Phase 9 headline runs.


## Next-guide (T-phases) tracker
| Phase | State |
| --- | --- |
| T0 consolidate | **Partial.** Local git repo created and committed (the dir had no git). `requirements-research.txt` pinned to the installed versions. **Not pushed:** the guide's remote (`dhanushdr4210-arch/web-Autoscaling`) is not configured here and `gh` is logged in as a different account (Eswar0811); no remote branches deleted. Legacy `target-app/` was **not** moved into the new tree because its scripts use relative paths. |
| T1 infrastructure | **Blocked.** No docker/kind/kubectl; needs an install decision (see below). `KubernetesAdapter` still untested. |
| T2 harden | **Code done, dry-run only.** `startscale/harness/collector.py` (single collector, `--limit`, `--resume`, `--dry-run`), `scripts/validate_dataset.py`, `scripts/build_master_dataset.py`; tests cover validator, resume and dry-run. Real mode untested; `t_ready_actual`, `probe_quantisation_s` and achieved pressure are still unrecorded (marked TODO in the collector). |
| T3 collection | Blocked on T1. |
| T4 refit | `experiments/exp_b_v5.py` ready; verified only on a synthetic fixture. |
| T5 recalibrate | Twin profile `empirical` (bootstraps v5 events by nearest image/cache/bandwidth cell) implemented and tested on the fixture. The 30-paired-run calibration table needs the cluster. |
| T6–T9 | Not started (depend on real data). The earlier twin findings (ledger/conformal null, H5 contradicted) remain **assumption-dependent** until T5/T6. |


## Update: T0–T3 progress
* **T0:** pushed to a new private repo `Eswar0811/startscale-v2` (not the guide's repo; no remote branches deleted).
* **T1 done.** Homebrew-installed docker/colima/kind/kubectl; Colima VM 6 CPU/10 GB; 5-node kind (v1.37, containerd 2.3). Verified:
  registry mirror pulls; registry bandwidth shaping (needed `--cap-add NET_ADMIN` and shaping **every** registry interface — a
  large cold pull is 23 s @1 Gbit vs 368 s @50 Mbit, 16×); `KubernetesAdapter` observe/add/remove/prepull on the live cluster.
  Fixed two real bugs this exposed: affinity patched into the pod template rolled out all pods (now steered by node
  `startscale/rank` labels with static preferred terms), and cache detection used the wrong image tag.
* **Image family (compressed, as pulled):** small ≈ 59 MB, large ≈ 2.18 GB (guide: ~80 MB / ~2.2 GB); `docker images` shows
  uncompressed 271 MB / 1.31 GB / 4.51 GB. Record these in the data card.
* **T2 done.** `startscale/harness/collector.py` (single collector) records app-side ready time (`APP_READY` log) → `probe_quantisation_s`,
  achieved CPU/memory per node, true image presence from the CRI. Validated on 12-run dry slices. Bugs found and fixed by the
  validator/dry runs: cold cells weren't cold (stopped containers pinned the image), the cache cleanup killed the
  stress pods, `kubectl set env` pressure injection never took effect (replaced by exec-driven levels; memory via RAM-backed
  emptyDir), a 2 GiB/node memory level OOM-killed the VM (now 1 GiB). Achieved pressure: CPU ≈ 6 / 47 / 80 %, memory ≈ 3 / 13 %.
  Self-inflicted: I deleted containerd content on worker3 early on and had to re-pull the pause image.
* **Known confounds for the data card:** all four kind nodes share one 6-CPU VM (pressure is cluster-wide contention);
  pod timestamps are 1 s resolution; docker-stats CPU% is of one core.
* **T3 running** (started 2026-10-14, unattended, `caffeinate`): `runs/sweep/20261014/` (events.csv, done.txt, collector.log).
  Resume with the same command + `--resume`. Validate daily: `python scripts/validate_dataset.py runs/sweep/20261014`.

## Update: pilot attempt 2026-10-14 (stopped — host disk full)
* T3 full run had died after 2 runs (Colima VM I/O errors; VM restarted). Pilot design built
  (`scripts/build_pilot_design.py` → `results/pilot_plan.csv`: 50 cells × 2 reps, ~460 events, est. 2.5 h) and started.
* Pilot got **2 runs** (11 events, validate clean) before the **Mac's disk filled** (460 GiB volume, ~98% used; Colima's disk
  image alone was ~45 GB, plus ~104 GB Downloads / ~68 GB Library / ~38 GB Desktop of the user's own data). Writes failed
  (ENOSPC), containerd returned I/O errors, the kind API became unreachable. Collector stopped. I freed ~10 GB
  (brew cache, `fstrim` of the VM); **no user files were touched**.
* **Cluster currently unhealthy; pilot not complete; Step 5 checks not run.** Pilot checks script is written
  (`scripts/pilot_checks.py`) but untested on real data.
* Needed before retrying: ≥ ~40 GB free on the host (4 workers each cache the 2.2 GB image + the registry copies + Colima growth),
  then `colima restart` / recreate the kind cluster (`kind delete cluster --name startscale && bash testbed/setup.sh`) and re-push images.

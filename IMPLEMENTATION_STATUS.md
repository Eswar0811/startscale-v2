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

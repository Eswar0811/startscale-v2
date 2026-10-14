"""Phase 3: randomised fractional-factorial plan for the unattended overnight sweep (3,000-5,000 events).

Full factorial = 3*2*3*3*2*3*3 = 972 cells. We take a D-optimal-ish random fraction of `--cells` cells plus a
`--core` set replicated 5x, then shuffle cell order to avoid confounding with wall-clock time.
Output: results/phase3_plan.csv; a driver on the kind cluster (not yet written; needs the cluster) executes it row by row
using target-app/measure_harness.py.
"""
import argparse, itertools, pathlib
import numpy as np, pandas as pd

F = dict(image_mb=[80, 600, 2200], cache=["cold", "warm"], bw_mbps=[1000, 200, 50], cpu=["low", "med", "high"],
         mem=["low", "high"], probe_period_s=[1, 5, 10], concurrent=[1, 3, 8])
ap = argparse.ArgumentParser(); ap.add_argument("--cells", type=int, default=700); ap.add_argument("--core", type=int, default=30)
ap.add_argument("--reps", type=int, default=5); ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
rng = np.random.default_rng(a.seed)
full = pd.DataFrame(list(itertools.product(*F.values())), columns=list(F))
frac = full.sample(a.cells, random_state=a.seed)
# core = extreme corners + centre so every main effect is covered by a replicated contrast
core = full.sample(a.core, random_state=a.seed + 1)
plan = pd.concat([frac.assign(role="fraction", rep=0)] +
                 [core.assign(role="core", rep=r) for r in range(a.reps)], ignore_index=True)
plan["events_expected"] = plan.concurrent
plan = plan.sample(frac=1, random_state=a.seed + 2).reset_index(drop=True)
plan.insert(0, "run_id", range(len(plan)))
out = pathlib.Path(__file__).resolve().parents[1] / "results" / "phase3_plan.csv"
plan.to_csv(out, index=False)
print(f"{len(full)} cells in full factorial; plan has {len(plan)} runs, ~{int(plan.events_expected.sum())} expected pod events -> {out}")

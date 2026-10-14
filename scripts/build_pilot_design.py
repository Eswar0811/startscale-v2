"""Pilot design: ~50 cells x 2 replicates, every factor level touched, key corners guaranteed, order randomised.
Subsamples results/phase3_plan.csv. Prints a wall-clock estimate and trims random-fill cells to fit --budget-hours."""
import argparse
import numpy as np, pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument("--budget-hours", type=float, default=3.0)
ap.add_argument("--cells", type=int, default=50); ap.add_argument("--reps", type=int, default=2)
a = ap.parse_args()
full = pd.read_csv("results/phase3_plan.csv").drop_duplicates(
    subset=["image_mb", "cache", "bw_mbps", "cpu", "mem", "probe_period_s", "concurrent"]).reset_index(drop=True)
COMPRESSED_MB = {80: 59, 600: 600, 2200: 2180}


def est_seconds(r):
    """Settling (~30 s) + pressure settle (10 s) + startup. Cold pulls share one shaped registry link across
    at most min(concurrent, 4) nodes, so wall time scales with that."""
    pull = 0.0 if r.cache == "warm" else COMPRESSED_MB[r.image_mb] * 8.0 / r.bw_mbps * min(r.concurrent, 4)
    return 45 + pull + (r.probe_period_s if r.probe_period_s > 1 else 0)


full["est_s"] = full.apply(est_seconds, axis=1)
FACT = ["image_mb", "cache", "bw_mbps", "cpu", "mem", "probe_period_s", "concurrent"]
touch = []
for f in FACT:
    for lv in full[f].unique():       # cheapest cell for each level (the time-hogs are covered by the corners)
        touch.append(full[full[f] == lv].nsmallest(1, "est_s"))
corner_masks = [
    (full.image_mb == 2200) & (full.cache == "cold") & (full.bw_mbps == 50) & (full.concurrent == 1),
    (full.image_mb == 80) & (full.cache == "warm") & (full.bw_mbps == 1000),
    (full.image_mb == 600) & (full.cache == "cold") & (full.bw_mbps == 200),
    (full.cpu == "high") & (full.mem == "high"),
    (full.image_mb == 2200) & (full.cache == "cold") & (full.bw_mbps == 1000),
]
corners = [full[m].sort_values("est_s").head(1) for m in corner_masks]
pilot = pd.concat(touch + corners).drop_duplicates(subset=FACT)
rest = full.drop(pilot.index, errors="ignore")
rest = rest[rest.est_s < 900]
c = rest[rest.cache == "cold"].sample(frac=1, random_state=42); w = rest[rest.cache == "warm"].sample(frac=1, random_state=43)
rest = pd.concat([c, w]).iloc[np.argsort(np.r_[np.arange(len(c)) * 2.0, np.arange(len(w)) * 2.0 + 1])]   # interleave
for _, r in rest.iterrows():
    if len(pilot) >= a.cells or pilot.est_s.sum() * a.reps > a.budget_hours * 3600:
        break
    pilot = pd.concat([pilot, r.to_frame().T])
pilot = pilot.drop(columns=["run_id", "rep", "role", "events_expected"], errors="ignore")
reps = pd.concat([pilot.assign(rep=k) for k in range(a.reps)], ignore_index=True)
for c in ("image_mb", "bw_mbps", "probe_period_s", "concurrent"):
    reps[c] = reps[c].astype(int)
reps["est_s"] = reps.est_s.astype(float)
reps = reps.sample(frac=1, random_state=7).reset_index(drop=True)
reps.insert(0, "run_id", range(len(reps))); reps["role"] = "pilot"
reps.to_csv("results/pilot_plan.csv", index=False)
print(f"{len(pilot)} cells x {a.reps} reps = {len(reps)} runs, ~{int(reps.concurrent.sum())} pod events; "
      f"estimated wall time {reps.est_s.sum() / 3600:.1f} h (slowest run {reps.est_s.max() / 60:.0f} min)")
for f in FACT:
    print(f, dict(pilot[f].value_counts().sort_index()))

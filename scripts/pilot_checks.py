"""Step 5 pilot checks. python scripts/pilot_checks.py runs/sweep/pilot_<ts> [more shard dirs...]"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "experiments"))
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

dirs = sys.argv[1:]
d = pd.concat([pd.read_csv(pathlib.Path(x) / "events.csv") for x in dirs], ignore_index=True)
ok = d[d.status == "ok"].copy()
print(f"{len(d)} events ({len(ok)} ok), {ok.run_id.nunique()} runs; status counts: {d.status.value_counts().to_dict()}")
out = pathlib.Path("results/pilot"); out.mkdir(parents=True, exist_ok=True)
ok.to_parquet(out / "pilot_master.parquet", index=False)

# 5.1 spread
y = ok.startup_latency_s
print(f"\n[5.1] latency min {y.min():.1f}s  median {y.median():.1f}s  p99 {y.quantile(.99):.1f}s  max {y.max():.1f}s")
print(f"      spread max/min = {y.max()/y.min():.1f}x ; p99/p01 = {y.quantile(.99)/y.quantile(.01):.1f}x")
print(ok.groupby(["image_mb", "cache", "bw_mbps"]).startup_latency_s.agg(["count", "median", "min", "max"]).round(1).to_string())
ok["g"] = ok.image_mb.astype(str) + "MB/" + ok.cache
ok.boxplot(column="startup_latency_s", by="g", rot=45, figsize=(8, 4.5)); plt.yscale("log"); plt.suptitle("")
plt.ylabel("startup latency (s, log)"); plt.tight_layout(); plt.savefig(out / "motivation.png", dpi=150); plt.close()

# 5.4 pressure separation
print("\n[5.4] achieved pressure by intended level (median / IQR):")
for lvl, col in (("cpu", "achieved_cpu_pct"), ("mem", "achieved_mem_pct")):
    print(ok.groupby(lvl)[col].describe()[["count", "25%", "50%", "75%"]].round(1).to_string())

# 5.2 model vs baselines (direction check only)
from exp_b_v5 import prep, evaluate
print("\n[5.2] model vs per-image baselines (direction check; noisy at pilot scale):")
s = evaluate(prep(out / "pilot_master.parquet"))
print(s.loc[(slice(None), ["global_median", "per_image_median", "per_image_cache_median", "lgbm_q50",
                           "conformal_q90", "conformal_80pct_interval"]), ["MAE", "coverage", "nominal"]].to_string())

# 5.3 empirical twin sanity: does the sampler reproduce the spread?
from startscale.twin import DeadTimeSampler
from startscale.adapter import NodeState
sm = DeadTimeSampler("empirical", seed=0, v5_path=str(out / "pilot_master.parquet"))
draw = np.array([sm.startup(NodeState("n", bool(rng_w), image_mb=im, bw_mbps=bw))
                 for im in (80, 600, 2200) for bw in (50, 200, 1000) for rng_w in (0, 1) for _ in range(20)])
print(f"\n[5.3] empirical twin draws: min {draw.min():.1f}s max {draw.max():.1f}s spread {draw.max()/draw.min():.1f}x "
      f"(real {y.max()/y.min():.1f}x)")

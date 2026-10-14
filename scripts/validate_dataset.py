"""Validate collector shards: python scripts/validate_dataset.py runs/sweep/<id>/ [--plan results/phase3_plan.csv]"""
import argparse, pathlib, sys
import numpy as np, pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("--plan")
a = ap.parse_args()
d = pd.read_csv(pathlib.Path(a.dir) / "events.csv")
errs = []
def chk(name, bad):
    n = int(bad.sum()) if hasattr(bad, "sum") else int(bad)
    if n: errs.append(f"{name}: {n} rows")
need = ["t_decision", "t_scheduled", "t_started", "t_ready_observed", "startup_latency_s"]
for c in need:
    chk(f"missing {c}", d[c].isna())
chk("status != ok", d.status != "ok")
cold = d.cache == "cold"
chk("cold cell but no Pulled event", cold & d.t_pull_end.isna())
# the kubelet dedupes concurrent pulls: only the pod that triggers the pull has a Pulling event, so require
# at least one per (run, node) rather than one per pod
g = d[cold].groupby(["run_id", "node"]).t_pull_start.apply(lambda x: x.notna().any())
chk("cold (run,node) with no Pulling event at all", (~g).sum())
chk("warm cell but node had no image", (~cold) & (d.node_had_image == 0))
order = ["t_decision", "t_scheduled", "t_started", "t_ready_observed"]
for x, y in zip(order, order[1:]):
    chk(f"timestamp order {x} > {y}", d[x] > d[y] + 1.0)      # 1 s clock granularity
chk("pull_end < pull_start", d.t_pull_end < d.t_pull_start)
chk("non-positive latency", d.startup_latency_s <= 0)
ORD = {"low": 0, "med": 1, "high": 2}
for col, ach in (("cpu", "achieved_cpu_pct"), ("mem", "achieved_mem_pct")):
    if d[ach].notna().any():
        lv = d.groupby(col)[ach].median().sort_index(key=lambda i: i.map(ORD))
        if not lv.is_monotonic_increasing:
            errs.append(f"achieved {col} pressure not ordered with intended level: {lv.to_dict()}")
if a.plan:
    plan = pd.read_csv(a.plan)
    missing = set(plan.run_id) - set(d.run_id)
    if missing and not (pathlib.Path(a.dir) / "done.txt").exists():
        errs.append(f"{len(missing)} planned runs have no rows")
print(f"{len(d)} events, {d.run_id.nunique()} runs")
if errs:
    print("FAIL"); [print(" -", e) for e in errs]; sys.exit(1)
print("OK")

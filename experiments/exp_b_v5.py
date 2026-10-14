"""T4: Experiment B on the real v5 dataset. python experiments/exp_b_v5.py data/startscale_readiness_v5.parquet

Same protocol as exp_b_predictor.py, richer features and meaningful per-image baselines. Splits: random 5-fold
vs grouped by factor cell (unseen conditions). Also reports the central-80% interval coverage that was 0.63
on the 150-event data, and a regime breakdown (cold/warm, per image) for H3.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
from sklearn.model_selection import KFold, GroupKFold
from startscale.readiness import QuantileReadiness, pinball, asymmetric_cost

ROOT = pathlib.Path(__file__).resolve().parents[1]
LVL = {"low": 0, "med": 1, "high": 2}
FEATS = ["image_mb", "cold", "bw_mbps", "cpu_lvl", "mem_lvl", "probe_period_s", "concurrent", "node_had_image"]


def prep(path):
    d = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    d = d[d.status == "ok"].copy() if "status" in d else d
    d["cold"] = (d.cache == "cold").astype(int)
    d["cpu_lvl"] = d.cpu.map(LVL); d["mem_lvl"] = d.mem.map({"low": 0, "high": 1})
    d["cell"] = d[["image_mb", "cache", "bw_mbps", "cpu", "mem", "probe_period_s", "concurrent"]].astype(str).agg("|".join, axis=1)
    d["y"] = d.startup_latency_s
    return d.reset_index(drop=True)


def evaluate(d):
    rows = []
    for split, sp, groups in (("random_5fold", KFold(5, shuffle=True, random_state=0), None),
                              ("grouped_by_cell", GroupKFold(5), d.cell.values)):
        for f, (tr, te) in enumerate(sp.split(d, groups=groups)):
            T, V = d.iloc[tr], d.iloc[te]; y = V.y.values
            base = {"global_median": np.full(len(V), T.y.median()),
                    "per_image_median": V.image_mb.map(T.groupby("image_mb").y.median()).fillna(T.y.median()).values,
                    "per_image_cache_median": V.set_index(["image_mb", "cold"]).index.map(
                        T.groupby(["image_mb", "cold"]).y.median()).to_series().fillna(T.y.median()).values}
            m = QuantileReadiness(seed=f).fit(T[FEATS].values, T.y.values)
            G = m.predict_grid(V[FEATS].values); tg = m.taus
            base["lgbm_q50"] = G[:, tg.index(0.5)]
            for k, p in base.items():
                rows.append(dict(split=split, fold=f, model=k, MAE=np.mean(np.abs(y - p)), asym=asymmetric_cost(y, p)))
                for reg, mask in ((f"cold", V.cold.values == 1), ("warm", V.cold.values == 0)):
                    if mask.sum():
                        rows.append(dict(split=split, fold=f, model=f"{k}@{reg}", MAE=np.mean(np.abs(y[mask] - p[mask]))))
            for tau in (0.5, 0.9, 0.95):
                q = G[:, tg.index(tau)]
                rows.append(dict(split=split, fold=f, model=f"conformal_q{int(tau*100)}", pinball=pinball(y, q, tau),
                                 coverage=float(np.mean(y <= q)), nominal=tau))
            lo, hi = G[:, tg.index(0.1)], G[:, tg.index(0.9)]
            rows.append(dict(split=split, fold=f, model="conformal_80pct_interval", coverage=float(np.mean((y >= lo) & (y <= hi))),
                             width=float(np.mean(hi - lo)), nominal=0.8))
    r = pd.DataFrame(rows)
    return r.groupby(["split", "model"]).mean(numeric_only=True).drop(columns="fold").round(3)


if __name__ == "__main__":
    d = prep(sys.argv[1])
    spread = d.y.quantile(0.99) / d.y.quantile(0.01)
    print(f"{len(d)} events; p01..p99 spread x{spread:.1f}")
    s = evaluate(d); pd.set_option("display.width", 200); print(s.to_string())
    s.to_csv(ROOT / "results" / "exp_b_v5_summary.csv")

"""Experiment B: predictor accuracy, coverage and baselines on the measured events.

Splits: random 5-fold (interpolation) vs grouped-by-condition (generalisation to
unseen cluster states). Baselines: global mean, per-image median, per-cache
median, EWMA over last k events, per-cell (condition) median.
"""
import sys, pathlib
import numpy as np, pandas as pd
from sklearn.model_selection import KFold, GroupKFold
from sklearn.linear_model import LinearRegression
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from startscale.readiness import QuantileReadiness, pinball, asymmetric_cost

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "target-app" / "v3_master_150_v3_spatial_features.csv"
FEATS = ["node_cpu_pct_v2", "node_memory_pct_v2", "worker_cpu_mean", "worker_memory_mean",
         "worker_memory_max", "worker_memory_std", "cpu_spatial_imbalance", "cold"]
TARGET = "request_to_ready_ms"


def load():
    d = pd.read_csv(DATA)
    d["cold"] = (d.image_cache_state.str.lower() == "cold").astype(int)
    d["y"] = d[TARGET] / 1000.0
    return d.reset_index(drop=True)


def ewma_pred(train, k=10, a=0.3):
    v = train.y.values[-k:]
    w = (1 - a) ** np.arange(len(v))[::-1]
    return float(np.sum(w * v) / np.sum(w))


def point_metrics(y, p):
    return dict(MAE=np.mean(np.abs(y - p)), RMSE=np.sqrt(np.mean((y - p) ** 2)),
                asym=asymmetric_cost(y, p))


def run(split_name, splitter, d, groups=None):
    rows = []
    for f, (tr, te) in enumerate(splitter.split(d, groups=groups) if groups is not None else splitter.split(d)):
        T, V = d.iloc[tr], d.iloc[te]
        y = V.y.values
        preds = {
            "global_mean": np.full(len(V), T.y.mean()),
            "global_median": np.full(len(V), T.y.median()),
            "per_image_median": V.image.map(T.groupby("image").y.median()).fillna(T.y.median()).values,
            "per_cache_median": V.cold.map(T.groupby("cold").y.median()).fillna(T.y.median()).values,
            "ewma_k10": np.full(len(V), ewma_pred(T)),
            "per_cell_median": V.source_condition.map(T.groupby("source_condition").y.median()).fillna(T.y.median()).values,
        }
        lr = LinearRegression().fit(T[FEATS], T.y); preds["linear"] = lr.predict(V[FEATS])
        qm = QuantileReadiness(seed=f).fit(T[FEATS].values, T.y.values)
        G = qm.predict_grid(V[FEATS].values); tg = qm.taus
        preds["lgbm_q50"] = G[:, tg.index(0.5)]
        for name, p in preds.items():
            rows.append(dict(split=split_name, fold=f, model=name, n=len(V), **point_metrics(y, p),
                             pinball_50=pinball(y, p, 0.5)))
        # interval quality at the nominal 90% one-sided and 80% central interval
        for tau in (0.5, 0.9, 0.95):
            q = G[:, tg.index(tau)]
            rows.append(dict(split=split_name, fold=f, model=f"lgbm_conformal_q{int(tau*100)}", n=len(V),
                             pinball=pinball(y, q, tau), coverage=float(np.mean(y <= q)), nominal=tau))
        lo, hi = G[:, tg.index(0.1)], G[:, tg.index(0.9)]
        rows.append(dict(split=split_name, fold=f, model="lgbm_conformal_80pct_interval", n=len(V),
                         coverage=float(np.mean((y >= lo) & (y <= hi))), width=float(np.mean(hi - lo)), nominal=0.8))
        # marginal empirical-interval baseline (no features)
        mlo, mhi = T.y.quantile(0.1), T.y.quantile(0.9)
        rows.append(dict(split=split_name, fold=f, model="marginal_empirical_80pct_interval", n=len(V),
                         coverage=float(np.mean((y >= mlo) & (y <= mhi))), width=float(mhi - mlo), nominal=0.8))
        # regime split (H3): cold vs warm
        for reg, mask in (("cold", V.cold.values == 1), ("warm", V.cold.values == 0)):
            if mask.sum():
                for name in ("per_image_median", "per_cache_median", "lgbm_q50"):
                    p = preds[name][mask]
                    rows.append(dict(split=split_name, fold=f, model=f"{name}@{reg}", n=int(mask.sum()),
                                     MAE=np.mean(np.abs(y[mask] - p))))
    return rows


if __name__ == "__main__":
    d = load()
    rows = run("random_5fold", KFold(5, shuffle=True, random_state=0), d)
    rows += run("grouped_by_condition", GroupKFold(5), d, groups=d.source_condition.values)
    r = pd.DataFrame(rows)
    r.to_csv(ROOT / "results" / "exp_b_folds.csv", index=False)
    s = r.groupby(["split", "model"]).agg(
        MAE=("MAE", "mean"), RMSE=("RMSE", "mean"), asym=("asym", "mean"), pinball=("pinball", "mean"),
        coverage=("coverage", "mean"), nominal=("nominal", "mean"), width=("width", "mean")).round(3)
    s.to_csv(ROOT / "results" / "exp_b_summary.csv")
    pd.set_option("display.width", 200)
    print(s.to_string())
    print("\nSpread of measured latency: min %.2fs median %.2fs max %.2fs (x%.1f)" %
          (d.y.min(), d.y.median(), d.y.max(), d.y.max() / d.y.min()))

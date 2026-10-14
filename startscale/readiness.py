"""Quantile readiness model (LightGBM, pinball loss) with split-conformal calibration.

`QuantileReadiness` fits one LightGBM model per quantile level on a grid, then
conformalises each level one-sided on a held-out calibration split:
    q_tau(x) <- q_tau(x) + Quantile_tau'(y_cal - q_tau(x_cal))
which gives finite-sample marginal coverage >= tau (CQR, one-sided form).
Quantile crossing is removed by a running maximum over the grid.
"""
from __future__ import annotations

import numpy as np
import lightgbm as lgb

TAU_GRID = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)


def pinball(y, q, tau):
    d = np.asarray(y) - np.asarray(q)
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def asymmetric_cost(y, pred, under_w=4.0, over_w=1.0):
    """Cost-weighted error: under-prediction (SLO risk) costs `under_w`x over-prediction."""
    d = np.asarray(y) - np.asarray(pred)
    return float(np.mean(np.where(d > 0, under_w * d, -over_w * d)))


class QuantileReadiness:
    def __init__(self, taus=TAU_GRID, conformal=True, cal_frac=0.3, seed=0, **lgb_kw):
        self.taus = tuple(taus)
        self.conformal = conformal
        self.cal_frac = cal_frac
        self.seed = seed
        self.lgb_kw = dict(n_estimators=120, learning_rate=0.05, num_leaves=8,
                           min_child_samples=5, subsample=0.8, subsample_freq=1,
                           colsample_bytree=0.9, verbose=-1, random_state=seed)
        self.lgb_kw.update(lgb_kw)
        self.models: dict[float, lgb.LGBMRegressor] = {}
        self.adj: dict[float, float] = {t: 0.0 for t in self.taus}

    def fit(self, X, y, groups=None):
        X = np.asarray(X, float); y = np.asarray(y, float)
        n = len(y)
        rng = np.random.default_rng(self.seed)
        idx = rng.permutation(n)
        if self.conformal and n >= 20:
            ncal = max(int(n * self.cal_frac), 5)
            cal, tr = idx[:ncal], idx[ncal:]
        else:
            cal, tr = idx[:0], idx
        for t in self.taus:
            m = lgb.LGBMRegressor(objective="quantile", alpha=t, **self.lgb_kw)
            m.fit(X[tr], y[tr])
            self.models[t] = m
        if len(cal):
            for t in self.taus:
                r = y[cal] - self.models[t].predict(X[cal])
                k = min(int(np.ceil((len(cal) + 1) * t)), len(cal))
                self.adj[t] = float(np.sort(r)[k - 1])
        return self

    def predict_grid(self, X):
        """Calibrated quantiles, shape (n, len(taus)), non-crossing and >= 0."""
        X = np.atleast_2d(np.asarray(X, float))
        Q = np.column_stack([self.models[t].predict(X) + self.adj[t] for t in self.taus])
        return np.maximum.accumulate(np.maximum(Q, 0.0), axis=1)

    def predict_quantile(self, X, tau):
        G = self.predict_grid(X)
        return np.array([np.interp(tau, self.taus, g) for g in G])

    def predict_interval(self, X, lo=0.05, hi=0.95):
        return self.predict_quantile(X, lo), self.predict_quantile(X, hi)

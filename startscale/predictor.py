"""Controller-facing readiness predictors (seconds), keyed by NodeState."""
from __future__ import annotations

import numpy as np
from .readiness import QuantileReadiness, TAU_GRID


class GridPredictor:
    """Wraps a fitted QuantileReadiness; memoises on a rounded NodeState."""

    def __init__(self, model: QuantileReadiness, conformal=True):
        self.model = model
        self.taus = np.array(model.taus)
        self.use_conformal = conformal
        self._cache: dict = {}

    def _grid(self, node):
        f = node.features()
        key = (f[0], round(f[1] / 5), round(f[2] / 5), f[3], f[4], f[5])
        g = self._cache.get(key)
        if g is None:
            if not self.use_conformal:   # ablation: raw (uncalibrated) quantiles
                X = np.atleast_2d(f)
                g = np.maximum.accumulate(np.maximum(np.column_stack(
                    [self.model.models[t].predict(X) for t in self.model.taus]), 0), axis=1)[0]
            else:
                g = self.model.predict_grid(f)[0]
            self._cache[key] = g
        return g

    def quantile(self, node, tau):
        return float(np.interp(tau, self.taus, self._grid(node)))

    def prob_ready_by(self, node, elapsed_s):
        g = self._grid(node)
        xs = np.concatenate([[0.0], g, [g[-1] * 1.5 + 1e-6]])
        ys = np.concatenate([[0.0], self.taus, [1.0]])
        return float(np.interp(elapsed_s, xs, ys))


class FixedPredictor:
    """Constant dead time (what HPA-style and fixed-lead controllers assume)."""

    def __init__(self, delta_s):
        self.delta = delta_s

    def quantile(self, node, tau):
        return self.delta

    def prob_ready_by(self, node, elapsed_s):
        return 1.0 if elapsed_s >= self.delta else 0.0

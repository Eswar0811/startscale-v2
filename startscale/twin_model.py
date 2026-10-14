"""Train the controller-facing readiness model on a Phase-3-style factorial drawn from the sampler."""
from __future__ import annotations

import functools

import numpy as np

from .adapter import NodeState
from .predictor import GridPredictor
from .readiness import QuantileReadiness
from .twin import DeadTimeSampler


def make_events(profile, n=4000, seed=0, v5_path=None):
    rng = np.random.default_rng(seed)
    s = DeadTimeSampler(profile, seed=seed, v5_path=v5_path)
    X, y = [], []
    for _ in range(n):
        node = NodeState("n", cache_warm=bool(rng.random() < 0.5), cpu_pct=float(rng.choice([5, 10, 20])),
                         mem_pct=float(rng.choice([10, 20])), starting=int(rng.choice([0, 1, 2, 3])),
                         image_mb=float(rng.choice([80, 300, 600, 1200, 2200])),
                         bw_mbps=float(rng.choice([50, 100, 200, 500, 1000])))
        if profile not in ("extended", "empirical"):
            node.image_mb, node.bw_mbps = 600.0, 100.0
        X.append(node.features()); y.append(s.startup(node))
    return np.array(X), np.array(y)


@functools.lru_cache(maxsize=8)
def fitted_model(profile, seed=0, v5_path=None):
    X, y = make_events(profile, seed=seed, v5_path=v5_path)
    return QuantileReadiness(seed=seed, n_estimators=150, num_leaves=12, min_child_samples=20).fit(X, y)


def predictor(profile, conformal=True, seed=0, v5_path=None):
    return GridPredictor(fitted_model(profile, seed, v5_path), conformal=conformal)

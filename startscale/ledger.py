"""Capacity ledger: C(t) = n_ready + sum_pending Pr[Delta_p <= t - t_p]."""
from __future__ import annotations

import math
from dataclasses import replace


class Ledger:
    """mode: 'prob' (full ledger), 'count_all' (pending counted as ready), 'ready_only'."""

    def __init__(self, mode="prob"):
        assert mode in ("prob", "count_all", "ready_only")
        self.mode = mode

    def capacity_at(self, obs, predictor, horizon_s):
        """Expected number of serving replicas at obs.t + horizon_s (excluding not-yet-created pods)."""
        if self.mode == "ready_only":
            return float(obs.ready)
        if self.mode == "count_all":
            return float(obs.ready + len(obs.pending))
        c = float(obs.ready)
        for p in obs.pending:
            elapsed = obs.t - p.t_created + horizon_s
            ns = replace(obs.nodes[p.node], cache_warm=not p.cold, starting=p.n_pulls)   # state at creation
            c += predictor.prob_ready_by(ns, elapsed)
        return c

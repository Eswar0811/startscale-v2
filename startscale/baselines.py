"""Baseline controllers on the same ClusterAdapter interface."""
from __future__ import annotations

import math
from collections import deque

import numpy as np


class HPA:
    """Kubernetes HPA (v2) semantics: desired = ceil(ready * util / target), computed on *ready* pods,
    with scale-down stabilisation window (max of recommendations) and scale-up rate policy.
    `metric='util'` is CPU-style utilisation; `metric='rate'` is a KEDA/Prometheus-style rps trigger."""

    def __init__(self, adapter, mu=20.0, target=0.6, min_replicas=2, max_replicas=60,
                 down_window=300.0, up_window=0.0, up_pct=1.0, up_pods=4, metric="util", rate_target=None,
                 period=15.0):
        self.ad, self.mu, self.target = adapter, mu, target
        self.minr, self.maxr = min_replicas, max_replicas
        self.down_window, self.up_window = down_window, up_window
        self.up_pct, self.up_pods = up_pct, up_pods
        self.metric = metric
        self.rate_target = rate_target or mu * target
        self.period = period
        self.rec: deque = deque()
        self.decisions = []

    def step(self):
        obs = self.ad.observe()
        cur = float(np.mean(obs.rps_history[-15:])) if obs.rps_history else 0.0
        ready = max(obs.ready, 1)
        if self.metric == "util":
            util = cur / (ready * self.mu)
            desired = math.ceil(ready * util / self.target)
        else:
            desired = math.ceil(cur / self.rate_target)
        desired = int(min(max(desired, self.minr), self.maxr))
        t = obs.t
        self.rec.append((t, desired))
        while self.rec and t - self.rec[0][0] > max(self.down_window, self.up_window, 1):
            self.rec.popleft()
        current = obs.ready + len(obs.pending)
        stab_down = max(r for tt, r in self.rec if t - tt <= self.down_window) if self.down_window else desired
        stab_up = min(r for tt, r in self.rec if t - tt <= self.up_window) if self.up_window else desired
        if desired > current:
            target_n = min(max(stab_up, current), self.maxr)
            lim = current + max(math.ceil(current * self.up_pct), self.up_pods)
            target_n = int(min(target_n, lim))
        elif desired < current:
            target_n = int(min(current, stab_down))
        else:
            target_n = current
        act = "hold"
        if target_n > current:
            self.ad.add_pods(target_n - current, None); act = "scale_up"
        elif target_n < current:
            self.ad.remove_pods(current - target_n); act = "scale_down"
        self.decisions.append((t, act, target_n))

    def sign_changes(self):
        s = [1 if a == "scale_up" else -1 for _, a, _ in self.decisions if a != "hold"]
        return sum(1 for a, b in zip(s, s[1:]) if a != b)

    prepull_count = 0
    fallback_count = 0

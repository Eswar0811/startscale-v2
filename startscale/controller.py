"""StartScale controller: compensate (lead time) + hedge (risk tau) + reduce (pre-pull, affinity).

Pure decision logic over a ClusterAdapter; no Kubernetes or SimPy imports.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

from .ledger import Ledger


@dataclass
class Config:
    tau: float = 0.9
    t_control: float = 15.0
    mu: float = 20.0                  # rps one ready replica sustains
    headroom: float = 1.15
    min_replicas: int = 2
    max_replicas: int = 60
    h_forecast: float = 0.0           # fixed horizon; 0 => derive from predictor (horizon-matching)
    enforce_horizon: bool = True      # H >= Delta_tau + T_control
    ledger_mode: str = "prob"
    compensation: bool = True         # False => horizon = T_control only (no lead time)
    placement: bool = True            # affinity weights
    prepull: bool = True
    prepull_max_nodes: int = 2
    slots_per_node: int = 6           # pods a warm node can host (pre-pull trigger heuristic)
    scale_down_cooldown: float = 120.0
    scale_up_cooldown: float = 0.0
    max_actions_per_min: int = 8
    max_step_up: int = 20
    coverage_window: int = 30
    min_coverage: float = 0.55        # rolling one-sided coverage below this => fallback
    fallback_util: float = 0.6
    fixed_lead: float | None = None   # fixed-lead compensation baseline (seconds)


@dataclass
class Decision:
    t: float
    action: str
    required: int
    capacity: float
    horizon: float
    delta_tau: float
    added: int = 0
    removed: int = 0
    prepulled: tuple = ()
    fallback: bool = False
    note: str = ""


class StartScaleController:
    def __init__(self, cfg: Config, adapter, predictor, forecaster, model_available=True):
        self.cfg, self.ad, self.pred, self.fc = cfg, adapter, predictor, forecaster
        self.ledger = Ledger(cfg.ledger_mode)
        self.model_available = model_available
        self.decisions: list[Decision] = []
        self.fallback_count = 0
        self._hits = deque(maxlen=cfg.coverage_window)
        self._pred_q: dict[int, float] = {}
        self._last_up = -1e9
        self._last_down = -1e9
        self._actions: deque = deque()
        self.prepulled_nodes: set[str] = set()
        self.prepull_count = 0

    # -- coverage monitoring ------------------------------------------------
    def _update_coverage(self, obs):
        for c in obs.completed:
            q = self._pred_q.pop(c.pod_id, None)
            if q is not None:
                self._hits.append(c.latency_s <= q)

    def rolling_coverage(self):
        return float(np.mean(self._hits)) if len(self._hits) >= 10 else None

    def _rate_ok(self, t):
        while self._actions and t - self._actions[0] > 60:
            self._actions.popleft()
        return len(self._actions) < self.cfg.max_actions_per_min

    # -- main step ----------------------------------------------------------
    def step(self) -> Decision:
        cfg, obs = self.cfg, self.ad.observe()
        self.prepulled_nodes &= {n for n, v in obs.nodes.items() if not v.cache_warm}
        self._update_coverage(obs)
        hist = obs.rps_history
        cur = float(np.mean(hist[-10:])) if hist else 0.0
        total = obs.ready + len(obs.pending)

        cov = self.rolling_coverage()
        fallback = (not self.model_available) or (cov is not None and cov < cfg.min_coverage)
        nodes = list(obs.nodes.values())

        if fallback:
            self.fallback_count += 1
            required = max(math.ceil(cur / (cfg.mu * cfg.fallback_util)), cfg.min_replicas)
            d = Decision(obs.t, "hold", required, float(total), cfg.t_control, 0.0, fallback=True,
                         note="fallback: utilisation scaling")
            return self._apply(obs, d, required, total_cap=float(obs.ready + len(obs.pending)),
                               node_w=None)

        # Delta_tau: tau-quantile of the readiness of a pod placed per the scheduling policy, i.e. the
        # mixture over candidate nodes (uniform for default spreading, affinity-weighted when steering)
        node_w = self._node_weights(nodes) if cfg.placement else None
        probs = np.array([node_w[n.name] for n in nodes]) if node_w else np.ones(len(nodes))
        probs = probs / probs.sum()
        delta_tau = self._mixture_quantile(nodes, probs, cfg.tau)
        if cfg.fixed_lead is not None:
            delta_tau = cfg.fixed_lead
        if not cfg.compensation:
            horizon = cfg.t_control
        elif cfg.h_forecast > 0 and not cfg.enforce_horizon:
            horizon = cfg.h_forecast
        else:
            horizon = delta_tau + cfg.t_control
            if cfg.h_forecast > 0:
                horizon = max(horizon, cfg.h_forecast)
        horizon = max(horizon, 1.0)

        path = self.fc.path(hist, horizon)
        f_peak = float(np.max(path)) if len(path) else cur
        f_peak = max(f_peak, cur)
        required = int(min(max(math.ceil(f_peak * cfg.headroom / cfg.mu), cfg.min_replicas),
                           cfg.max_replicas))
        cap = self.ledger.capacity_at(obs, self.pred, horizon)
        # new pods become ready within the horizon with prob ~tau; credit them accordingly
        d = Decision(obs.t, "hold", required, cap, horizon, delta_tau)
        return self._apply(obs, d, required, cap, node_w)

    def _mixture_quantile(self, nodes, probs, tau):
        hi = max(self.pred.quantile(n, 0.95) for n in nodes) * 1.5 + 1.0
        lo = 0.0
        for _ in range(30):
            mid = (lo + hi) / 2
            F = sum(p * self.pred.prob_ready_by(n, mid) for n, p in zip(nodes, probs))
            lo, hi = (mid, hi) if F < tau else (lo, mid)
        return hi

    def _node_weights(self, nodes):
        q = np.array([self.pred.quantile(n, self.cfg.tau) for n in nodes])
        q = np.maximum(q, 1e-3)
        w = np.clip(np.round(100 * q.min() / q), 1, 100)
        return {n.name: float(wi) for n, wi in zip(nodes, w)}

    def _apply(self, obs, d: Decision, required, total_cap, node_w):
        cfg, t = self.cfg, obs.t
        total = obs.ready + len(obs.pending)
        deficit = required - total_cap
        if d.fallback:
            deficit = required - total
        # --- scale up
        if deficit >= 1.0 - 1e-9 and t - self._last_up >= cfg.scale_up_cooldown and self._rate_ok(t):
            k = int(min(math.ceil(deficit), cfg.max_step_up, cfg.max_replicas - total))
            if k > 0:
                pods = self.ad.add_pods(k, node_w)
                for p in pods:
                    if not d.fallback:
                        ns = replace(obs.nodes[p.node], cache_warm=not p.cold, starting=p.n_pulls)
                        self._pred_q[p.pod_id] = self.pred.quantile(ns, 0.9)
                d.action, d.added = "scale_up", k
                self._last_up = t
                self._actions.append(t)
        # --- scale down (only when ready capacity exceeds the *peak* need over the horizon)
        elif (obs.ready - required >= max(2, math.ceil(0.1 * obs.ready)) and not obs.pending and t - self._last_down >= cfg.scale_down_cooldown
              and t - self._last_up >= cfg.scale_down_cooldown and self._rate_ok(t)):
            k = obs.ready - max(required, cfg.min_replicas)
            if k > 0:
                self.ad.remove_pods(k)
                d.action, d.removed = "scale_down", k
                self._last_down = t
                self._actions.append(t)
        # --- reduce lever: pre-pull onto cold nodes the forecast says we will need. Looks ahead by the
        # *cold* readiness quantile (longer than the warm lead time), costs only disk + registry bandwidth.
        if cfg.prepull and not d.fallback:
            cold = [n for n in obs.nodes.values() if not n.cache_warm and n.name not in self.prepulled_nodes]
            if cold:
                h_long = max(self.pred.quantile(n, cfg.tau) for n in cold) + cfg.t_control
                f_long = float(np.max(self.fc.path(obs.rps_history, h_long)))
                need = math.ceil(f_long * cfg.headroom / cfg.mu)
                warm_slots = sum(1 for n in obs.nodes.values() if n.cache_warm) * cfg.slots_per_node
                if need > min(max(total, warm_slots), cfg.max_replicas):
                    cold.sort(key=lambda n: self.pred.quantile(n, cfg.tau))
                    pick = [n.name for n in cold[:cfg.prepull_max_nodes]]
                    self.ad.prepull(pick)
                    self.prepulled_nodes.update(pick)
                    self.prepull_count += len(pick)
                    d.prepulled = tuple(pick)
        self.decisions.append(d)
        return d

    def sign_changes(self):
        s = [1 if d.action == "scale_up" else -1 for d in self.decisions if d.action in ("scale_up", "scale_down")]
        return sum(1 for a, b in zip(s, s[1:]) if a != b)

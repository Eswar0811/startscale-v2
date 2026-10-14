"""Calibrated discrete-event twin (SimPy).

Dead time is *sampled from the measured event distribution* conditioned on cache state and node
pressure (`DeadTimeSampler`), not a constant. Requests are modelled per second with a fluid queue
(Poisson arrivals, capacity = ready * mu), which keeps a run to milliseconds so the risk sweep is
affordable; this is the documented fidelity limit of the twin.

Profiles
  measured : bootstrap of the 150 real events (small testbed; ~2.6x spread).
  extended : measured startup + image-pull time on cold nodes = size/bandwidth (lognormal jitter).
             This is an *assumption* standing in for the Phase-3 factorial sweep (image size x
             bandwidth) that needs the kind cluster; results under it are labelled as such.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy as np
import pandas as pd
import simpy

from .adapter import ClusterAdapter, Observation, NodeState, PendingPod, Completed

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "target-app" / "v3_master_150_v3_spatial_features.csv"


class DeadTimeSampler:
    def __init__(self, profile="measured", seed=0, image_mb=600.0, bw_mbps=100.0):
        d = pd.read_csv(DATA)
        d["cold"] = (d.image_cache_state.str.lower() == "cold").astype(int)
        self.warm = d[d.cold == 0].request_to_ready_ms.values / 1000
        self.cold = d[d.cold == 1].request_to_ready_ms.values / 1000
        self.warm_cpu = d[d.cold == 0].node_cpu_pct_v2.values
        self.profile, self.image_mb, self.bw = profile, image_mb, bw_mbps
        self.rng = np.random.default_rng(seed)

    def pull_s(self, node: NodeState):
        mb = node.image_mb if node.image_mb else self.image_mb
        bw = node.bw_mbps if node.bw_mbps else self.bw
        # concurrent pulls share the registry link
        # registry link shared with the other nodes currently pulling
        return (mb * 8.0 / bw) * np.exp(self.rng.normal(0, 0.15)) * (node.starting + 1) ** 0.9 \
            if self.profile == "extended" else 0.0

    def startup(self, node: NodeState):
        """Seconds from creation to ready on `node` in its current state."""
        base = self.rng.choice(self.warm)          # container start + app init + probe quantisation
        base *= 1.0 + 0.004 * max(node.cpu_pct - 10, 0)          # node-pressure effect is weak in the measured data
        if self.profile == "extended":
            return base + (0.0 if node.cache_warm else self.pull_s(node))
        return float(self.rng.choice(self.warm if node.cache_warm else self.cold))


@dataclass
class TwinConfig:
    nodes: int = 4
    warm_nodes: int = 4
    mu: float = 20.0
    service_ms: float = 50.0
    slo_ms: float = 500.0
    queue_cap_s: float = 5.0
    init_replicas: int = 0            # 0 => sized for the trace's first-second demand
    profile: str = "measured"
    image_mb: float = 600.0
    bw_mbps: float = 100.0
    t_control: float = 15.0
    cpu_levels: tuple = (5.0, 10.0, 20.0)
    max_pods_per_node: int = 6
    cache_ttl: float = 120.0          # idle node loses its image (kubelet image GC) after this long


class SimAdapter(ClusterAdapter):
    def __init__(self, env: simpy.Environment, cfg: TwinConfig, sampler: DeadTimeSampler, rng):
        self.env, self.cfg, self.sampler, self.rng = env, cfg, sampler, rng
        self.nodes = {f"w{i}": NodeState(f"w{i}", cache_warm=i < cfg.warm_nodes,
                                          cpu_pct=float(rng.choice(cfg.cpu_levels)),
                                          mem_pct=float(rng.choice([10.0, 20.0])),
                                          image_mb=cfg.image_mb, bw_mbps=cfg.bw_mbps) for i in range(cfg.nodes)}
        self.ready: dict[int, str] = {}
        self.pending: dict[int, PendingPod] = {}
        self._cancel: set[int] = set()
        self._pid = 0
        self._done: list[Completed] = []
        self._idle_since: dict[str, float | None] = {n: None for n in self.nodes}
        self.pull_done: dict[str, float] = {}
        self.rps_history: list[float] = []
        self.pull_bytes_mb = 0.0
        self.prepull_disk_mb = 0.0
        self.pull_events = 0
        pool = list(self.nodes)[:max(cfg.warm_nodes, 1)]          # initial replicas live on pool A only
        for i in range(cfg.init_replicas):
            self._pid += 1
            self.ready[self._pid] = pool[i % len(pool)]
        for n in pool:
            self.nodes[n].cache_warm = True

    # ---- adapter surface -------------------------------------------------
    def _refresh_cache(self):
        cnt = {n: 0 for n in self.nodes}
        for n in list(self.ready.values()) + [p.node for p in self.pending.values()]:
            cnt[n] += 1
        for n, c in cnt.items():
            if c > 0:
                self._idle_since[n] = None
            elif self._idle_since[n] is None:
                self._idle_since[n] = self.env.now
            elif self.env.now - self._idle_since[n] > self.cfg.cache_ttl:
                self.nodes[n].cache_warm = False

    def observe(self):
        self._refresh_cache()
        done, self._done = self._done, []
        snap = {k: NodeState(**{**v.__dict__, "starting": self._others_pulling(k)}) for k, v in self.nodes.items()}
        return Observation(self.env.now, len(self.ready), list(self.pending.values()),
                           list(self.rps_history), snap, done)

    def _others_pulling(self, n):
        return sum(1 for m, t in self.pull_done.items() if m != n and t > self.env.now)

    def _place(self, k, weights):
        load = {n: 0 for n in self.nodes}
        for n in list(self.ready.values()) + [p.node for p in self.pending.values()]:
            load[n] += 1
        out = []
        for _ in range(k):
            mx = max(load.values()) + 1
            sc = {n: (weights[n] / 100.0 if weights else 0.0) + 0.5 * (1 - load[n] / mx)
                     + self.rng.uniform(0, 0.05) for n in self.nodes if load[n] < self.cfg.max_pods_per_node}
            if not sc:                       # cluster full: overflow onto least loaded node
                sc = {n: -load[n] for n in self.nodes}
            n = max(sc, key=sc.get)
            load[n] += 1
            out.append(n)
        return out

    def add_pods(self, k, node_weights=None):
        self._refresh_cache()
        created = []
        for n in self._place(k, node_weights):
            node = self.nodes[n]
            self._pid += 1
            pid = self._pid
            others = self._others_pulling(n)
            cold = not node.cache_warm
            if not cold:
                dt = self.sampler.startup(node)
            elif self.cfg.profile == "extended":
                base = self.sampler.startup(NodeState(n, True, node.cpu_pct, node.mem_pct))
                if self.pull_done.get(n, 0.0) > self.env.now:        # join the in-flight pull (kubelet dedupes)
                    dt = self.pull_done[n] - self.env.now + base
                else:
                    pull = self.sampler.pull_s(NodeState(n, False, node.cpu_pct, node.mem_pct, others,
                                                         node.image_mb, node.bw_mbps))
                    self._start_pull(n, pull); dt = pull + base
            else:
                dt = self.sampler.startup(node)
                if self.pull_done.get(n, 0.0) <= self.env.now:
                    self.pull_events += 1; self.pull_bytes_mb += node.image_mb
                    self.pull_done[n] = self.env.now + dt
            p = PendingPod(pid, n, self.env.now, cold=cold, n_pulls=others)
            self.pending[pid] = p
            self.env.process(self._become_ready(pid, n, dt))
            created.append(p)
        return created

    def _start_pull(self, n, dur, prepull=False):
        node = self.nodes[n]
        self.pull_done[n] = self.env.now + dur
        self.pull_bytes_mb += node.image_mb; self.pull_events += 1
        if prepull:
            self.prepull_disk_mb += node.image_mb
        self.env.process(self._finish_pull(n, dur))

    def _finish_pull(self, n, dur):
        yield self.env.timeout(dur)
        self.nodes[n].cache_warm = True

    def _become_ready(self, pid, n, dt):
        yield self.env.timeout(dt)
        node = self.nodes[n]
        if pid in self._cancel:
            self._cancel.discard(pid); return
        p = self.pending.pop(pid)
        self.ready[pid] = n
        node.cache_warm = True
        self._done.append(Completed(pid, n, self.env.now - p.t_created))

    def remove_pods(self, k):
        removed = 0
        for pid in sorted(self.pending, reverse=True):          # cancel newest pending first
            if removed >= k: break
            self._cancel.add(pid); del self.pending[pid]; removed += 1
        for pid in sorted(self.ready, reverse=True):
            if removed >= k: break
            del self.ready[pid]; removed += 1
        return removed

    def prepull(self, nodes):
        for n in nodes:
            node = self.nodes[n]
            if node.cache_warm or self.pull_done.get(n, 0.0) > self.env.now:
                continue
            if self.cfg.profile == "extended":
                dur = self.sampler.pull_s(NodeState(n, False, node.cpu_pct, node.mem_pct, self._others_pulling(n),
                                                    node.image_mb, node.bw_mbps))
            else:
                dur = float(self.sampler.rng.choice(self.sampler.cold))
            self._start_pull(n, dur, prepull=True)


def weighted_pct(x, w, q):
    if w.sum() <= 0: return 0.0
    o = np.argsort(x); x, w = x[o], w[o]
    c = np.cumsum(w) / w.sum()
    return float(x[np.searchsorted(c, q)])


def run_twin(trace, controller_factory, cfg: TwinConfig = None, seed=0, sampler_seed=None):
    """controller_factory(adapter) -> object with .step(), .decisions, .fallback_count, .prepull_count.
    Returns a metrics dict. The same controller code runs against KubernetesAdapter in production."""
    cfg = cfg or TwinConfig()
    rng = np.random.default_rng(seed)
    env = simpy.Environment()
    sampler = DeadTimeSampler(cfg.profile, seed=seed if sampler_seed is None else sampler_seed,
                              image_mb=cfg.image_mb, bw_mbps=cfg.bw_mbps)
    if cfg.init_replicas <= 0:
        import dataclasses, math
        cfg = dataclasses.replace(cfg, init_replicas=max(2, math.ceil(trace[0] / (cfg.mu * 0.6))))
    ad = SimAdapter(env, cfg, sampler, rng)
    ctl = controller_factory(ad)
    T = len(trace)
    lat = np.zeros(T); arr = np.zeros(T); viol = np.zeros(T); rep_ready = np.zeros(T); rep_total = np.zeros(T)
    deficit = np.zeros(T)
    st = {"backlog": 0.0}

    def ticker():
        for t in range(T):
            a = rng.poisson(trace[t])
            cap = len(ad.ready) * cfg.mu
            b = st["backlog"] + a
            served = min(b, cap)
            b -= served
            dropped = max(b - cap * cfg.queue_cap_s, 0.0) if cap > 0 else max(b - cfg.mu * cfg.queue_cap_s, 0.0)
            b -= dropped
            st["backlog"] = b
            wait_ms = 1000.0 * b / max(cap, 1e-9) if cap > 0 else 1e6
            l = cfg.service_ms + wait_ms
            lat[t], arr[t] = l, a
            viol[t] = (a * (l > cfg.slo_ms) + dropped * (l <= cfg.slo_ms)) if a else 0.0
            viol[t] = min(viol[t], a)
            rep_ready[t], rep_total[t] = len(ad.ready), len(ad.ready) + len(ad.pending)
            deficit[t] = float(trace[t] > cap)
            ad.rps_history.append(float(a))
            yield env.timeout(1.0)

    def loop():
        yield env.timeout(cfg.t_control)
        while True:
            ctl.step()
            yield env.timeout(cfg.t_control)

    env.process(ticker()); env.process(loop())
    env.run(until=T)
    tot = max(arr.sum(), 1)
    acts = [d for d in ctl.decisions if (getattr(d, "action", d[1] if isinstance(d, tuple) else "")) not in ("hold",)]
    return dict(
        slo_violation_rate=float(viol.sum() / tot),
        p95_ms=weighted_pct(lat, arr, 0.95), p99_ms=weighted_pct(lat, arr, 0.99),
        replica_seconds=float(rep_total.sum()), ready_replica_seconds=float(rep_ready.sum()),
        deficit_seconds=float(deficit.sum()),
        actions=len(acts), sign_changes=ctl.sign_changes(),
        sign_changes_per_min=ctl.sign_changes() / (T / 60.0),
        prepull_mb=ad.prepull_disk_mb, pull_mb=ad.pull_bytes_mb,
        fallbacks=getattr(ctl, "fallback_count", 0), prepull_count=getattr(ctl, "prepull_count", 0),
    )

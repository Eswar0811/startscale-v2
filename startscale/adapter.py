"""ClusterAdapter: the only surface the controller touches.

Two implementations share the identical decision code: `SimAdapter` (twin.py)
and `KubernetesAdapter` (kube_adapter.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class NodeState:
    name: str
    cache_warm: bool
    cpu_pct: float = 10.0
    mem_pct: float = 15.0
    starting: int = 0          # other nodes pulling the image concurrently (registry contention)
    image_mb: float = 80.0
    bw_mbps: float = 1000.0

    def features(self):
        return (float(self.cache_warm), self.cpu_pct, self.mem_pct, float(self.starting),
                self.image_mb, self.bw_mbps)


@dataclass
class PendingPod:
    pod_id: int
    node: str
    t_created: float
    cold: bool = False        # node cache state when the pod was created
    n_pulls: int = 0          # other nodes pulling concurrently at creation (registry contention)


@dataclass
class Completed:
    pod_id: int
    node: str
    latency_s: float


@dataclass
class Observation:
    t: float
    ready: int
    pending: list[PendingPod]
    rps_history: list[float]            # per-second observed request rate, oldest first
    nodes: dict[str, NodeState]
    completed: list[Completed] = field(default_factory=list)  # newly ready since last observe


class ClusterAdapter(ABC):
    @abstractmethod
    def observe(self) -> Observation: ...

    @abstractmethod
    def add_pods(self, k: int, node_weights: dict[str, float] | None = None) -> list[PendingPod]:
        """Create k pods. `node_weights` are *preferred* (soft) affinity weights 1..100."""

    @abstractmethod
    def remove_pods(self, k: int) -> int: ...

    @abstractmethod
    def prepull(self, nodes: list[str]) -> None: ...

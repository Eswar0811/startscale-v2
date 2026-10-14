"""KubernetesAdapter: runs the *same* controller code against a real cluster (kind).

Not exercised in this repo's CI (needs a cluster). Smoke-test with `python -m startscale.kube_adapter --dry-run`.
Actuation is direct patching of Deployment replicas / preferred node affinity / pre-pull Jobs; the
custom-metric + HPA path is the production story and is not used for experiments.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from .adapter import ClusterAdapter, Observation, NodeState, PendingPod, Completed


class KubernetesAdapter(ClusterAdapter):
    def __init__(self, deployment="startscale-target", namespace="default", image="localhost:5000/startscale-target:v1",
                 rps_source: Callable[[], float] = lambda: 0.0, image_mb=80.0, bw_mbps=1000.0,
                 worker_label="startscale/pool", dry_run=False):
        from kubernetes import client, config
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()
        self.core, self.apps, self.batch = client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api()
        self.client = client
        self.dep, self.ns, self.image = deployment, namespace, image
        self.rps_source, self.image_mb, self.bw = rps_source, image_mb, bw_mbps
        self.dry = dry_run
        self.hist: list[float] = []
        self._t0 = time.time()
        self._seen_ready: set[str] = set()
        self._created: dict[str, tuple[float, bool, int]] = {}   # pod name -> (t_created, cold, n_pulls)
        self._pod_ids: dict[str, int] = {}

    # -- helpers
    def _now(self):
        return time.time() - self._t0

    def _pid(self, name):
        return self._pod_ids.setdefault(name, len(self._pod_ids) + 1)

    def _image(self):
        return self.apps.read_namespaced_deployment(self.dep, self.ns).spec.template.spec.containers[0].image

    def _node_states(self):
        out = {}
        self.image = self._image()
        for n in self.core.list_node().items:
            if "node-role.kubernetes.io/control-plane" in (n.metadata.labels or {}):
                continue
            warm = any(self.image in (img.names or []) for img in (n.status.images or []))
            out[n.metadata.name] = NodeState(n.metadata.name, warm, image_mb=self.image_mb, bw_mbps=self.bw)
        return out

    def observe(self):
        self.hist.append(float(self.rps_source()))
        nodes = self._node_states()
        pods = self.core.list_namespaced_pod(self.ns, label_selector=f"app={self.dep}").items
        ready, pending, done = 0, [], []
        for p in pods:
            if p.metadata.deletion_timestamp:
                continue
            conds = {c.type: c for c in (p.status.conditions or [])}
            is_ready = conds.get("Ready") is not None and conds["Ready"].status == "True"
            if is_ready:
                ready += 1
                if p.metadata.name not in self._seen_ready and p.metadata.name in self._created:
                    t_ready = conds["Ready"].last_transition_time
                    t_c = p.metadata.creation_timestamp
                    done.append(Completed(self._pid(p.metadata.name), p.spec.node_name or "",
                                          (t_ready - t_c).total_seconds()))   # 1 s resolution (see guide)
                self._seen_ready.add(p.metadata.name)
            else:
                t_c, cold, npull = self._created.get(p.metadata.name, (self._now(), False, 0))
                node = p.spec.node_name or next(iter(nodes))
                pending.append(PendingPod(self._pid(p.metadata.name), node, t_c, cold, npull))
        return Observation(self._now(), ready, pending, list(self.hist), nodes, done)

    RANK_WEIGHTS = (100, 50, 25, 10)

    def ensure_affinity_template(self):
        """One-time setup: static *preferred* affinity terms on node label startscale/rank=r1..r4.
        The controller then steers placement by relabelling nodes, so no pod-template change (and no
        rollout of running pods) ever happens at control time. Preferences, never `required`."""
        terms = [{"weight": w, "preference": {"matchExpressions": [
            {"key": "startscale/rank", "operator": "In", "values": [f"r{i + 1}"]}]}}
            for i, w in enumerate(self.RANK_WEIGHTS)]
        patch = {"spec": {"template": {"spec": {"affinity": {"nodeAffinity": {
            "preferredDuringSchedulingIgnoredDuringExecution": terms}}}}}}
        self.apps.patch_namespaced_deployment(self.dep, self.ns, patch)

    def _set_rank_labels(self, node_weights):
        order = sorted(node_weights, key=lambda n: -node_weights[n])
        for i, n in enumerate(order):
            rank = f"r{min(i, len(self.RANK_WEIGHTS) - 1) + 1}"
            self.core.patch_node(n, {"metadata": {"labels": {"startscale/rank": rank}}})

    def _scale(self, replicas):
        if not self.dry:
            self.apps.patch_namespaced_deployment_scale(self.dep, self.ns, {"spec": {"replicas": int(replicas)}})

    def _current(self):
        return self.apps.read_namespaced_deployment(self.dep, self.ns).spec.replicas or 0

    def add_pods(self, k, node_weights=None):
        if node_weights and not self.dry:
            self._set_rank_labels(node_weights)
        before = {p.metadata.name for p in self.core.list_namespaced_pod(self.ns, label_selector=f"app={self.dep}").items}
        nodes = self._node_states()
        npull = 0
        self._scale(self._current() + k)
        time.sleep(1.0)
        out = []
        for p in self.core.list_namespaced_pod(self.ns, label_selector=f"app={self.dep}").items:
            if p.metadata.name in before:
                continue
            node = p.spec.node_name or next(iter(nodes))
            cold = not nodes.get(node, NodeState(node, True)).cache_warm
            self._created[p.metadata.name] = (self._now(), cold, npull)
            out.append(PendingPod(self._pid(p.metadata.name), node, self._now(), cold, npull))
        return out

    def remove_pods(self, k):
        self._scale(max(self._current() - k, 0))
        return k

    def prepull(self, nodes):
        V = self.client
        for n in nodes:
            job = V.V1Job(
                metadata=V.V1ObjectMeta(generate_name=f"prepull-{n}-"[:50]),
                spec=V.V1JobSpec(ttl_seconds_after_finished=60, backoff_limit=0, template=V.V1PodTemplateSpec(
                    spec=V.V1PodSpec(restart_policy="Never", node_selector={"kubernetes.io/hostname": n},
                                     containers=[V.V1Container(name="pull", image=self.image,
                                                               image_pull_policy="IfNotPresent",
                                                               command=["python", "-c", "pass"])]))))
            if not self.dry:
                self.batch.create_namespaced_job(self.ns, job)


if __name__ == "__main__":
    import sys
    a = KubernetesAdapter(dry_run="--dry-run" in sys.argv)
    print(a.observe())

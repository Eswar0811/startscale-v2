"""Single Phase-3 collector (replaces the measure_*/collect_* family for the factorial sweep).

For each plan row: set bandwidth + pressure, set image/probe period, force cold or warm cache, scale
0 -> `concurrent`, and record per-pod phase timestamps from pod status + kubelet events.

    python -m startscale.harness.collector --plan results/phase3_plan.csv --out runs/sweep/20261020 --resume
    python -m startscale.harness.collector --plan results/phase3_plan.csv --out /tmp/x --limit 10 --dry-run

Resume: a run_id is recorded in <out>/done.txt only after its rows are flushed, so a kill mid-run re-executes
just that run. REAL MODE IS UNTESTED (no cluster was available when written); --dry-run prints the exact
commands. Timestamps: pod conditions are 1 s resolution; Pulling/Pulled events likewise (see guide Phase 2).
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import subprocess
import time
from datetime import datetime, timezone

import pandas as pd

TAG = {80: "small", 600: "medium", 2200: "large"}
CPU_LOAD = {"low": 0, "med": 40, "high": 80}
MEM_BYTES = {"low": "0", "high": "1G"}
REPO = "localhost:5000/startscale-target"
NS, DEP = "default", "startscale-target"
FIELDS = ["run_id", "rep", "role", "image_mb", "cache", "bw_mbps", "cpu", "mem", "probe_period_s", "concurrent",
          "pod_name", "node", "t_decision", "t_scheduled", "t_pull_start", "t_pull_end", "t_started",
          "t_ready_actual", "t_ready_observed", "probe_quantisation_s", "startup_latency_s",
          "achieved_cpu_pct", "achieved_mem_pct", "node_had_image", "status"]


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


class Runner:
    def __init__(self, dry):
        self.dry = dry

    def sh(self, cmd, check=True, capture=False):
        if self.dry:
            print("DRY>", cmd)
            return ""
        r = subprocess.run(cmd, shell=True, check=check, text=True, capture_output=capture)
        return r.stdout if capture else ""

    def kjson(self, args):
        if self.dry:
            return {"items": []}
        return json.loads(self.sh(f"kubectl {args} -o json", capture=True))


def workers(R):
    if R.dry:
        return ["startscale-worker", "startscale-worker2", "startscale-worker3", "startscale-worker4"]
    return R.sh("kind get nodes --name startscale | grep worker", capture=True).split()


def prepare(R, row, nodes):
    tag = TAG[int(row.image_mb)]
    R.sh(f"bash testbed/netem.sh {int(row.bw_mbps)}")
    R.sh(f"kubectl set env ds/stress-ng CPU_LOAD={CPU_LOAD[row.cpu]} MEM_BYTES={MEM_BYTES[row.mem]}")
    R.sh(f"kubectl scale deploy/{DEP} --replicas=0 && kubectl wait --for=delete pod -l app={DEP} --timeout=120s", check=False)
    for n in nodes:
        if row.cache == "cold":
            # stopped containers pin the image; remove them first, then every tag of the family
            R.sh(f"docker exec {n} sh -c 'crictl ps -a -q | xargs -r crictl rm -f; crictl pods -q | xargs -r crictl rmp -f'", check=False)
            for t in TAG.values():
                R.sh(f"docker exec {n} crictl rmi {REPO}:{t}", check=False)
        else:
            R.sh(f"docker exec {n} crictl pull {REPO}:{tag}", check=False)
    patch = {"spec": {"template": {"spec": {"containers": [{
        "name": DEP, "image": f"{REPO}:{tag}", "imagePullPolicy": "IfNotPresent",
        "readinessProbe": {"httpGet": {"path": "/readyz", "port": 8000}, "periodSeconds": int(row.probe_period_s),
                           "initialDelaySeconds": 0, "failureThreshold": 1}}]}}}}
    R.sh(f"kubectl patch deploy/{DEP} -p '{json.dumps(patch)}'")


def nodes_with_image(R, nodes, tag):
    """Ground truth from the CRI (not the plan): which workers actually hold the image right now."""
    if R.dry:
        return set()
    return {n for n in nodes if f"{REPO}" in R.sh(f"docker exec {n} crictl images {REPO}:{tag}", check=False, capture=True)
            and tag in R.sh(f"docker exec {n} crictl images {REPO}:{tag}", check=False, capture=True)}


def node_load(R, nodes):
    """Achieved pressure per worker (docker stats of the kind node containers): {node: (cpu%, mem%)}."""
    if R.dry:
        return {}
    out = {}
    for line in R.sh("docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemPerc}}'", capture=True).splitlines():
        n, c, m = line.split()
        if n in nodes:
            out[n] = (float(c.strip('%')), float(m.strip('%')))
    return out


def collect_rows(R, row, t_decision, nodes_had_image, load):
    deadline = time.time() + 600
    pods = []
    while not R.dry and time.time() < deadline:
        pods = [p for p in R.kjson(f"get pods -l app={DEP}")["items"]
                if not p["metadata"].get("deletionTimestamp")
                and ts(p["metadata"]["creationTimestamp"]) >= int(t_decision) - 1]   # this run's pods only
        ready = [p for p in pods if any(c["type"] == "Ready" and c["status"] == "True"
                                         for c in p.get("status", {}).get("conditions", []))]
        if len(ready) >= int(row.concurrent):
            break
        time.sleep(1)
    events = R.kjson("get events --field-selector involvedObject.kind=Pod")["items"] if not R.dry else []
    out = []
    for p in pods:
        name = p["metadata"]["name"]
        conds = {c["type"]: ts(c.get("lastTransitionTime")) for c in p["status"].get("conditions", [])}
        cs = (p["status"].get("containerStatuses") or [{}])[0]
        started = ts(((cs.get("state") or {}).get("running") or {}).get("startedAt"))
        ev = {e["reason"]: ts(e.get("lastTimestamp") or e.get("eventTime"))
              for e in events if e["involvedObject"]["name"] == name}
        node = p["spec"].get("nodeName", "")
        ready_obs = conds.get("Ready")
        app_ready = None
        if not R.dry:
            for line in R.sh(f"kubectl logs {name}", check=False, capture=True).splitlines():
                if line.startswith("APP_READY ts="):
                    app_ready = float(line.split("=")[1])
        out.append(dict(
            pod_name=name, node=node, t_decision=ts(p["metadata"]["creationTimestamp"]), t_scheduled=conds.get("PodScheduled"),
            t_pull_start=ev.get("Pulling"), t_pull_end=ev.get("Pulled"), t_started=started,
            t_ready_actual=app_ready,
            t_ready_observed=ready_obs,
            probe_quantisation_s=(ready_obs - app_ready) if (ready_obs and app_ready) else None,
            # t_decision := pod creationTimestamp (same 1 s-resolution clock as the pod conditions)
            startup_latency_s=(ready_obs - ts(p["metadata"]["creationTimestamp"])) if ready_obs else None,
            achieved_cpu_pct=load.get(node, (None, None))[0], achieved_mem_pct=load.get(node, (None, None))[1],
            node_had_image=int(node in nodes_had_image),
            status="ok" if ready_obs else "timeout"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int); ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    plan = pd.read_csv(a.plan)
    done_f = out / "done.txt"
    done = set(done_f.read_text().split()) if a.resume and done_f.exists() else set()
    shard = out / "events.csv"
    new = not shard.exists() or not a.resume
    R = Runner(a.dry_run)
    nodes = workers(R)
    n_run = 0
    with open(shard, "w" if new else "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for row in plan.itertuples():
            if str(row.run_id) in done:
                continue
            if a.limit and n_run >= a.limit:
                break
            prepare(R, row, nodes)
            had = nodes_with_image(R, nodes, TAG[int(row.image_mb)])
            if row.cache == "cold" and had and not a.dry_run:
                print(f"WARN run {row.run_id}: cold cell but image present on {sorted(had)}")
            load = node_load(R, nodes)
            t_dec = time.time()
            R.sh(f"kubectl scale deploy/{DEP} --replicas={int(row.concurrent)}")
            for r in collect_rows(R, row, t_dec, had, load):
                w.writerow({**{k: getattr(row, k, None) for k in ("run_id", "rep", "role", "image_mb", "cache",
                                                                 "bw_mbps", "cpu", "mem", "probe_period_s", "concurrent")}, **r})
            fh.flush()
            with open(done_f, "a") as d:
                d.write(f"{row.run_id}\n")
            n_run += 1
    print(f"executed {n_run} runs -> {shard}")


if __name__ == "__main__":
    main()

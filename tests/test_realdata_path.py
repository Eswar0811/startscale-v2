"""Exercises the T2/T4/T5 code path end-to-end on a SYNTHETIC v5-schema fixture (not real data)."""
import pathlib, subprocess, sys
import numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "experiments"))


def fixture(tmp, n=600):
    from startscale.twin import DeadTimeSampler
    from startscale.adapter import NodeState
    rng = np.random.default_rng(0); s = DeadTimeSampler("extended", 0); rows = []
    for i in range(n):
        im, bw, cold = int(rng.choice([80, 600, 2200])), int(rng.choice([1000, 200, 50])), bool(rng.random() < .5)
        y = s.startup(NodeState("n", not cold, image_mb=im, bw_mbps=bw))
        t0 = 1e9 + i * 100
        rows.append(dict(run_id=i, rep=0, role="fraction", image_mb=im, cache="cold" if cold else "warm", bw_mbps=bw,
                         cpu=str(rng.choice(["low", "med", "high"])), mem=str(rng.choice(["low", "high"])),
                         probe_period_s=int(rng.choice([1, 5, 10])), concurrent=int(rng.choice([1, 3, 8])),
                         pod_name=f"p{i}", node="w", t_decision=t0, t_scheduled=t0 + 1,
                         t_pull_start=t0 + 1 if cold else None, t_pull_end=t0 + y * .8 if cold else None,
                         t_started=t0 + y * .9, t_ready_actual=None, t_ready_observed=t0 + y,
                         probe_quantisation_s=None, startup_latency_s=y, achieved_cpu_pct=None, achieved_mem_pct=None,
                         node_had_image=int(not cold), status="ok"))
    p = tmp / "events.csv"; pd.DataFrame(rows).to_csv(p, index=False); return tmp, p


def test_validator_and_exp_b_v5(tmp_path):
    d, p = fixture(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_dataset.py"), str(d)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    from exp_b_v5 import prep, evaluate
    s = evaluate(prep(p))
    assert "lgbm_q50" in s.index.get_level_values(1)


def test_validator_catches_missing_phase(tmp_path):
    d, p = fixture(tmp_path, 50)
    df = pd.read_csv(p); df.loc[0, "t_started"] = None; df.to_csv(p, index=False)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_dataset.py"), str(d)], capture_output=True, text=True)
    assert r.returncode == 1


def test_twin_empirical_profile_runs(tmp_path):
    d, p = fixture(tmp_path)
    from startscale.twin import TwinConfig, run_twin
    from startscale import workloads as W
    from startscale.controller import StartScaleController, Config
    from startscale.forecast import SeasonalTrendForecaster
    from startscale.twin_model import predictor
    tr = W.make("spike", 0)
    pr = predictor("empirical", v5_path=str(p))
    f = lambda ad: StartScaleController(Config(mu=20, tau=0.9), ad, pr, SeasonalTrendForecaster())
    r = run_twin(tr, f, TwinConfig(profile="empirical", v5_path=str(p), warm_nodes=1), seed=0)
    assert 0 <= r["slo_violation_rate"] <= 1


def test_collector_resume(tmp_path):
    cmd = [sys.executable, "-m", "startscale.harness.collector", "--plan", str(ROOT / "results/phase3_plan.csv"),
           "--out", str(tmp_path), "--dry-run"]
    subprocess.run(cmd + ["--limit", "3"], cwd=ROOT, check=True, capture_output=True)
    subprocess.run(cmd + ["--limit", "2", "--resume"], cwd=ROOT, check=True, capture_output=True)
    assert len((tmp_path / "done.txt").read_text().split()) == 5

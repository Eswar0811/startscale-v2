import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from startscale.adapter import NodeState, Observation, PendingPod
from startscale.ledger import Ledger
from startscale.predictor import FixedPredictor
from startscale.readiness import QuantileReadiness, pinball
from startscale.forecast import SeasonalTrendForecaster
from startscale.controller import Config, StartScaleController
from startscale.twin import TwinConfig, run_twin
from startscale import workloads as W


def test_pinball_asymmetry():
    assert pinball([10], [8], 0.9) > pinball([10], [12], 0.9)


def test_conformal_coverage_synthetic():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(3000, 3)); y = 5 + 2 * X[:, 0] + rng.gamma(2, 1, 3000)
    tr, te = slice(0, 2000), slice(2000, None)
    m = QuantileReadiness(cal_frac=0.3).fit(X[tr], y[tr])
    cov = np.mean(y[te] <= m.predict_quantile(X[te], 0.9))
    assert abs(cov - 0.9) < 0.04


def test_ledger_counts_pending_by_probability():
    n = NodeState("a", True)
    obs = Observation(10.0, 3, [PendingPod(1, "a", 5.0)], [], {"a": n})
    p = FixedPredictor(20.0)
    assert Ledger("prob").capacity_at(obs, p, 0) == 3.0          # elapsed 5 < 20
    assert Ledger("prob").capacity_at(obs, p, 15) == 4.0         # by horizon the pod is ready
    assert Ledger("count_all").capacity_at(obs, p, 0) == 4.0
    assert Ledger("ready_only").capacity_at(obs, p, 15) == 3.0


def test_seasonal_forecaster_finds_period():
    t = np.arange(900); x = 80 + 220 * ((t % 240) < 90)
    f = SeasonalTrendForecaster().path(list(x[:900]), 120)
    assert f[:60].max() > 250 or f.max() > 250   # 900 % 240 = 180 -> next burst at 960 (h=60)


def test_same_controller_runs_in_twin_without_thrash():
    from experiments.common import make_factory  # noqa
    tr = W.make("spike", 0)
    r = run_twin(tr, make_factory("startscale", "measured", tr, 0, tau=0.9), TwinConfig(), seed=0)
    assert r["slo_violation_rate"] < 0.2 and r["sign_changes"] <= 6 and r["fallbacks"] == 0


def test_no_hard_affinity_in_kube_adapter():
    src = (pathlib.Path(__file__).resolve().parents[1] / "startscale" / "kube_adapter.py").read_text()
    assert "required" not in src.replace("never `required`", "")

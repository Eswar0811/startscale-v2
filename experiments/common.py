import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from startscale.controller import StartScaleController, Config
from startscale.baselines import HPA
from startscale.forecast import HoltForecaster, OracleForecaster, SeasonalTrendForecaster
from startscale.predictor import FixedPredictor
from startscale.twin import TwinConfig, run_twin
from startscale.twin_model import predictor
from startscale import workloads as W

RES = ROOT / "results"; RES.mkdir(exist_ok=True)

# HPA settings (published verbatim in results/baseline_settings.md): tuned in tune_hpa.py
HPA_TUNED = dict(target=0.6, down_window=120.0, up_pct=1.0, up_pods=10)


def startscale(cfg_kw=None, profile="measured", conformal=True, forecaster="holt", noise=0.0, trace=None):
    def f(ad, seed=0, trace=trace):
        kw = dict(cfg_kw or {})
        cfg = Config(mu=ad.cfg.mu, **kw)
        fc = OracleForecaster(trace, noise, seed) if forecaster == "oracle" else SeasonalTrendForecaster()
        return StartScaleController(cfg, ad, predictor(profile, conformal), fc)
    return f


def make_factory(kind, profile="measured", trace=None, seed=0, **kw):
    if kind == "hpa":
        return lambda ad: HPA(ad, mu=ad.cfg.mu, **{**HPA_TUNED, **kw})
    if kind == "keda":   # rate-triggered scaler with the same stabilisation semantics
        return lambda ad: HPA(ad, mu=ad.cfg.mu, metric="rate", rate_target=ad.cfg.mu * 0.75,
                              down_window=120.0, up_pct=1.0, up_pods=10)
    if kind == "forecast_only":   # predictive, readiness-blind: fixed 30 s horizon, no lead/ledger
        return lambda ad: StartScaleController(
            Config(mu=ad.cfg.mu, compensation=True, enforce_horizon=False, h_forecast=30.0,
                   ledger_mode="count_all", placement=False, prepull=False, fixed_lead=0.0, **kw),
            ad, predictor(profile), SeasonalTrendForecaster())
    if kind == "fixed_lead":      # compensation with a constant lead = median measured dead time
        return lambda ad: StartScaleController(
            Config(mu=ad.cfg.mu, ledger_mode="count_all", placement=False, prepull=False,
                   fixed_lead=kw.pop("lead", 6.0), **kw), ad, FixedPredictor(kw.get("lead", 6.0)),
            SeasonalTrendForecaster())
    if kind == "startscale":
        return lambda ad: startscale(kw, profile, trace=trace)(ad, seed)
    if kind == "startscale_oracle":   # controlled forecast error (sensitivity / frontier studies)
        noise = kw.pop("noise", 0.0)
        return lambda ad: startscale(kw, profile, forecaster="oracle", noise=noise, trace=trace)(ad, seed)
    raise ValueError(kind)

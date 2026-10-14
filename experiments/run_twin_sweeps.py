"""Experiments C/D/E/F/G/J in the twin. Usage: python run_twin_sweeps.py [--quick]"""
import itertools, sys, time
from common import *
from startscale.forecast import SeasonalTrendForecaster
import pandas as pd

QUICK = "--quick" in sys.argv
SEEDS = range(2) if QUICK else range(5)
EVAL_WL = W.SYNTHETIC + ["trace_worldcup", "trace_nasa"]
TAUS = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
PROFILES = {"measured": TwinConfig(profile="measured", warm_nodes=2),
            "extended_cold": TwinConfig(profile="extended", warm_nodes=1)}   # 600 MB @100 Mbit; idle nodes lose cache


def go(label, prof, wl, seed, factory_kw, cfg=None, trace=None, **extra):
    cfg = cfg or PROFILES[prof]
    tr = trace if trace is not None else W.make(wl, seed)
    f = make_factory(factory_kw.pop("kind"), cfg.profile, tr, seed, **factory_kw) if "kind" in factory_kw else None
    r = run_twin(tr, f, cfg, seed=seed)
    return dict(arm=label, profile=prof, workload=wl, seed=seed, **extra, **r)


def main():
    rows = []
    t0 = time.time()
    # ---- Tuning set for HPA (seeds 100+, disjoint from evaluation) -> frontier of HPA settings
    hpa_rows = []
    for prof, wl, seed in itertools.product(PROFILES, EVAL_WL, range(100, 102)):
        for tgt, win in itertools.product([0.4, 0.5, 0.6, 0.7, 0.8], [60.0, 120.0, 300.0]):
            hpa_rows.append(go(f"hpa_t{tgt}_w{int(win)}", prof, wl, seed,
                               dict(kind="hpa", target=tgt, down_window=win), tgt=tgt, win=win))
    pd.DataFrame(hpa_rows).to_csv(RES / "tune_hpa.csv", index=False)
    # ---- C/D: controller comparison + risk sweep
    for prof, wl, seed in itertools.product(PROFILES, EVAL_WL, SEEDS):
        for tgt in (0.5, 0.6, 0.7, 0.8):
            rows.append(go(f"hpa_t{tgt}", prof, wl, seed, dict(kind="hpa", target=tgt), exp="C", tau=np.nan))
        for k in ("keda", "forecast_only", "fixed_lead"):
            rows.append(go(k, prof, wl, seed, dict(kind=k), exp="C", tau=np.nan))
        for tau in TAUS:
            rows.append(go("startscale", prof, wl, seed, dict(kind="startscale", tau=tau), exp="D", tau=tau))
            rows.append(go("startscale_timing_only", prof, wl, seed,
                           dict(kind="startscale", tau=tau, placement=False, prepull=False), exp="D", tau=tau))
            # controlled forecast error: oracle + 10% noise (isolates the readiness side of the loop)
            rows.append(go("startscale[oracle10]", prof, wl, seed,
                           dict(kind="startscale_oracle", tau=tau, noise=0.1), exp="D", tau=tau))
            rows.append(go("startscale_timing_only[oracle10]", prof, wl, seed,
                           dict(kind="startscale_oracle", tau=tau, noise=0.1, placement=False, prepull=False),
                           exp="D", tau=tau))
    print("C/D done", round(time.time() - t0), "s")
    # ---- G: ablations at tau=0.9
    abl = {"full": {}, "no_ledger(ready_only)": dict(ledger_mode="ready_only"),
           "no_ledger(count_all)": dict(ledger_mode="count_all"),
           "no_compensation": dict(compensation=False), "no_placement": dict(placement=False, prepull=False),
           "no_prepull": dict(prepull=False), "no_affinity": dict(placement=False)}
    for prof, wl, seed in itertools.product(PROFILES, EVAL_WL, SEEDS):
        for name, kw in abl.items():
            rows.append(go("startscale:" + name, prof, wl, seed, dict(kind="startscale", tau=0.9, **kw), exp="G", tau=0.9))
        # no conformal: raw quantiles
        tr = W.make(wl, seed); cfg = PROFILES[prof]
        f = lambda ad: StartScaleController(Config(mu=ad.cfg.mu, tau=0.9), ad, predictor(cfg.profile, conformal=False), SeasonalTrendForecaster())
        rows.append(dict(arm="startscale:no_conformal", profile=prof, workload=wl, seed=seed, exp="G", tau=0.9,
                         **run_twin(tr, f, cfg, seed=seed)))
    print("G done", round(time.time() - t0), "s")
    # ---- F: placement steering under cold caches (twin analogue; real-cluster run pending)
    for prof, wl, seed in itertools.product(["extended_cold"], ["spike", "repeated_bursts", "trace_worldcup"], SEEDS):
        for arm, kw in {"F1_blind": dict(kind="forecast_only"),
                        "F2_timing_only": dict(kind="startscale", tau=0.9, placement=False, prepull=False),
                        "F3_timing_plus_placement": dict(kind="startscale", tau=0.9)}.items():
            rows.append(go(arm, prof, wl, seed, kw, exp="F", tau=0.9))
    # ---- E: horizon-matching sweep. oracle forecaster => forecast error is zero/controlled
    cfgE = TwinConfig(profile="extended", warm_nodes=0)
    for wl, seed, noise in itertools.product(["ramp", "repeated_bursts"], SEEDS, [0.0, 0.1]):
        tr = W.make(wl, seed)
        for H in (5, 15, 30, 60, 90, 120, 180):
            f = lambda ad, H=H, tr=tr, noise=noise, seed=seed: StartScaleController(
                Config(mu=ad.cfg.mu, tau=0.9, h_forecast=H, enforce_horizon=False, ledger_mode="count_all",
                       placement=False, prepull=False),
                ad, predictor("extended"), OracleForecaster(tr, noise, seed))
            rows.append(dict(arm="E_horizon", profile="extended_cold0", workload=wl, seed=seed, exp="E",
                             H=H, noise=noise, tau=0.9, **run_twin(tr, f, cfgE, seed=seed)))
        f = lambda ad, tr=tr, noise=noise, seed=seed: StartScaleController(
            Config(mu=ad.cfg.mu, tau=0.9, ledger_mode="count_all", placement=False, prepull=False),
            ad, predictor("extended"),
            OracleForecaster(tr, noise, seed))
        rows.append(dict(arm="E_matched", profile="extended_cold0", workload=wl, seed=seed, exp="E",
                         H=-1, noise=noise, tau=0.9, **run_twin(tr, f, cfgE, seed=seed)))
    # ---- J: adversarial repeated bursts, period swept around the measured dead time
    for period, seed in itertools.product([60, 90, 120, 150, 200, 300], SEEDS):
        tr = W.repeated_bursts(None, period=period, width=period // 2, offset=60)
        for arm, kw in {"hpa_t0.6": dict(kind="hpa"), "startscale_t0.9": dict(kind="startscale", tau=0.9),
                        "startscale_t0.5": dict(kind="startscale", tau=0.5)}.items():
            rows.append(go(arm, "extended_cold", "adv_bursts", seed, kw, trace=tr, exp="J", period=period))
    df = pd.DataFrame(rows)
    df.to_csv(RES / ("twin_runs_quick.csv" if QUICK else "twin_runs.csv"), index=False)
    print(len(df), "runs in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()

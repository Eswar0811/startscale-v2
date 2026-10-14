"""Offline experiments: SHAP attribution, node-transfer (I), and drift detection with ADWIN (H, twin analogue)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
from exp_b_predictor import load, FEATS
import pandas as pd, shap
from river.drift import ADWIN
from startscale.readiness import QuantileReadiness, pinball
from startscale.twin_model import make_events

out = []
def P(s=""): print(s); out.append(s)

d = load()
# ---- Attribution (SHAP on the median model, all measured events)
m = QuantileReadiness(taus=(0.5, 0.9), conformal=False, seed=0).fit(d[FEATS].values, d.y.values)
sv = shap.TreeExplainer(m.models[0.9]).shap_values(d[FEATS].values)
imp = pd.Series(np.abs(sv).mean(0), index=FEATS).sort_values(ascending=False)
P("## SHAP attribution (mean |SHAP|, seconds, LightGBM q0.90, measured events)\n"); P(imp.round(3).to_string()); P()

# ---- Experiment I: transfer across nodes (train on two nodes, test on the third), with conformal coverage
P("## Experiment I: transfer across nodes (train others -> test node)\n")
rows = []
for node in d.node_name.unique():
    tr, te = d[d.node_name != node], d[d.node_name == node]
    q = QuantileReadiness(seed=0).fit(tr[FEATS].values, tr.y.values)
    g = q.predict_grid(te[FEATS].values); t = q.taus
    rows.append(dict(test_node=node, n=len(te), MAE_q50=np.mean(np.abs(te.y - g[:, t.index(0.5)])),
                     MAE_global_median=np.mean(np.abs(te.y - tr.y.median())),
                     coverage_q90=float(np.mean(te.y.values <= g[:, t.index(0.9)])), nominal=0.9))
P(pd.DataFrame(rows).round(3).to_string(index=False)); P()

# ---- Drift: stream of residuals; at event 1500 a heavier image ships (profile switches to 'extended')
P("## Drift experiment (twin analogue of mid-run image change)\n")
Xa, ya = make_events("measured", n=2000, seed=1)
Xb, yb = make_events("extended", n=2000, seed=2)
train = slice(0, 1000)
model = QuantileReadiness(seed=0, n_estimators=100, num_leaves=12, min_child_samples=20).fit(Xa[train], ya[train])
X = np.vstack([Xa[1000:], Xb[:1500]]); y = np.concatenate([ya[1000:], yb[:1500]])
change_at = len(Xa) - 1000
adw = ADWIN(delta=0.002); det = None; refits = []; buf = []
miss = []
for i in range(len(y)):
    q90 = model.predict_quantile(X[i:i+1], 0.9)[0]
    err = float(y[i] > q90)                       # coverage-violation stream (should average 0.1)
    adw.update(err); miss.append(err)
    buf.append(i)
    if adw.drift_detected and i >= change_at - 50:
        det = i; break
if det is not None:
    lat = det - change_at
    P(f"change at event {change_at}; ADWIN fired at event {det} (detection latency {lat} events)")
    idx = np.arange(det - 200, det) if det > 200 else np.arange(0, det)
    # incremental refit: recent window + original calibration data
    Xr = np.vstack([Xa[:1000], X[change_at:det]]); yr = np.concatenate([ya[:1000], y[change_at:det]])
    new = QuantileReadiness(seed=0, n_estimators=100, num_leaves=12, min_child_samples=20).fit(Xr, yr)
    post = slice(det, det + 400)
    cov_old = np.mean(y[post] <= model.predict_quantile(X[post], 0.9)); cov_new = np.mean(y[post] <= new.predict_quantile(X[post], 0.9))
    P(f"post-detection q90 coverage over next 400 events: stale model {cov_old:.2f}, refit {cov_new:.2f} (nominal 0.90)")
else:
    P("ADWIN did not fire")
P("\nDetection latency is reported in events (~pod creations); a wall-clock figure needs the cluster run.")
(RES / "offline_extras.md").write_text("\n".join(out))

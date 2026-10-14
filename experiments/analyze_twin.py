"""Tables, statistics and figures from results/twin_runs.csv."""
from common import RES
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import mannwhitneyu

d = pd.read_csv(RES / "twin_runs.csv")
FIG = RES / "figures"; FIG.mkdir(exist_ok=True)
out = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)

def cliff(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float((np.sum(a[:, None] > b[None]) - np.sum(a[:, None] < b[None])) / (len(a) * len(b)))

def holm(p):
    o = np.argsort(p); m = len(p); adj = np.empty(m); run = 0
    for r, i in enumerate(o):
        run = max(run, (m - r) * p[i]); adj[i] = min(run, 1)
    return adj

M = ["slo_violation_rate", "p99_ms", "replica_seconds", "sign_changes_per_min"]
# ---------------- Figure: SLO-cost Pareto frontier (paper's carrying plot)
for prof in d.profile.unique():
    x = d[(d.profile == prof) & d.exp.isin(["C", "D"])]
    if x.empty: continue
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, ttl, arms in ((axes[0], "realistic forecaster (seasonal-trend)", ["startscale", "startscale_timing_only"]),
                          (axes[1], "controlled forecast error (oracle, 10% noise)",
                           ["startscale[oracle10]", "startscale_timing_only[oracle10]"])):
        for arm, c in zip(arms, ["C0", "C1"]):
            g = x[x.arm == arm].groupby("tau")[["replica_seconds", "slo_violation_rate"]].mean().sort_index()
            ax.plot(g.replica_seconds, g.slo_violation_rate, "-o", c=c, ms=4, label=arm.split("[")[0])
            for t, r in g.iterrows():
                if t in (0.05, 0.5, 0.9, 0.95): ax.annotate(f"τ={t}", (r.replica_seconds, r.slo_violation_rate), fontsize=7)
        h = x[x.arm.str.startswith("hpa_t")].groupby("arm")[["replica_seconds", "slo_violation_rate"]].mean()
        ax.plot(h.replica_seconds, h.slo_violation_rate, "s--", c="gray", label="HPA (target sweep)")
        for a in ["keda", "forecast_only", "fixed_lead"]:
            g = x[x.arm == a][["replica_seconds", "slo_violation_rate"]].mean()
            ax.plot(g.replica_seconds, g.slo_violation_rate, "*", ms=11, label=a)
        ax.set_xlabel("replica-seconds (cost proxy)"); ax.set_title(ttl, fontsize=9); ax.grid(alpha=.3)
    axes[0].set_ylabel("SLO violation rate"); axes[0].legend(fontsize=7)
    fig.suptitle(f"SLO–cost frontier, twin, profile={prof} (mean over 8 workloads × seeds)")
    fig.tight_layout(); fig.savefig(FIG / f"pareto_{prof}.png", dpi=150); plt.close(fig)

# ---------------- Controller comparison with stats at tau=0.9 and best-HPA
P("## Experiment C/D: controller comparison (mean over workloads×seeds; twin)\n")
for prof in d.profile.unique():
    x = d[(d.profile == prof) & d.exp.isin(["C", "D"])]
    if x.empty: continue
    sub = x[(x.tau.isna()) | (x.tau.isin([0.5, 0.9, 0.95]))]
    tab = sub.groupby(["arm", "tau"], dropna=False)[M].mean().round(3)
    P(f"### profile = {prof}\n"); P(tab.to_string()); P("")
    ref = x[(x.arm == "startscale") & (x.tau == 0.9)].set_index(["workload", "seed"]).slo_violation_rate
    rows = []
    for a in sorted(x[x.tau.isna()].arm.unique()):
        b = x[x.arm == a].set_index(["workload", "seed"]).slo_violation_rate.reindex(ref.index)
        try:
            u = mannwhitneyu(ref.values, b.values, alternative="less")
            rows.append((a, u.pvalue, cliff(ref.values, b.values), ref.mean() - b.mean()))
        except ValueError:
            pass
    if rows:
        ps = holm(np.array([r[1] for r in rows]))
        P(f"Mann–Whitney U, StartScale(τ=0.9) violation rate < baseline (n={len(ref)} runs each), Holm-adjusted:\n")
        for (a, p, cd, dm), pa in zip(rows, ps):
            P(f"- vs {a}: Δmean={dm:+.4f}, Cliff's δ={cd:+.2f}, p_holm={pa:.3g}")
        P("")

# ---------------- E: horizon matching
e = d[d.exp == "E"]
if not e.empty:
    P("## Experiment E: horizon-matching (twin, all-cold cluster, timing lever only)\n")
    g = e.groupby(["workload", "noise", "H"])["slo_violation_rate"].mean().unstack("H").round(3)
    P(g.to_string()); P("(H = -1 is the matched horizon Δ_τ + T_control)\n")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, wl in zip(axes, ["ramp", "repeated_bursts"]):
        for noise, c in ((0.0, "C0"), (0.1, "C3")):
            s = e[(e.workload == wl) & (e.noise == noise) & (e.H > 0)].groupby("H").slo_violation_rate.mean()
            ax.plot(s.index, s.values, "-o", c=c, label=f"forecast noise {noise}")
            m = e[(e.workload == wl) & (e.noise == noise) & (e.H == -1)].slo_violation_rate.mean()
            ax.axhline(m, c=c, ls=":", lw=1)
        ax.set_title(wl); ax.set_xlabel("forecast horizon H (s)  — dotted: matched Δ_τ+T"); ax.grid(alpha=.3)
    axes[0].set_ylabel("SLO violation rate"); axes[0].legend()
    fig.tight_layout(); fig.savefig(FIG / "horizon_matching.png", dpi=150); plt.close(fig)

# ---------------- G: ablations
g_ = d[d.exp == "G"]
if not g_.empty:
    P("## Experiment G: ablations (τ=0.9; twin)\n")
    for prof in g_.profile.unique():
        t = g_[g_.profile == prof].groupby("arm")[["slo_violation_rate", "replica_seconds", "sign_changes_per_min", "prepull_mb"]].mean().round(4)
        P(f"### {prof}\n"); P(t.to_string()); P("")

# ---------------- F: placement
f = d[d.exp == "F"]
if not f.empty:
    P("## Experiment F: placement steering under cold caches (twin analogue; real-cluster run pending)\n")
    t = f.groupby(["workload", "arm"])[["slo_violation_rate", "p95_ms", "deficit_seconds", "replica_seconds", "prepull_mb", "pull_mb"]].mean().round(3)
    P(t.to_string()); P("")

# ---------------- J: adversarial
j = d[d.exp == "J"]
if not j.empty:
    P("## Experiment J: adversarial repeated bursts (period swept; twin)\n")
    t = j.groupby(["period", "arm"])[["slo_violation_rate", "replica_seconds", "pull_mb", "sign_changes_per_min"]].mean().round(3)
    P(t.to_string()); P("")
    fig, ax = plt.subplots(figsize=(5.5, 3.8))
    for arm in j.arm.unique():
        s = j[j.arm == arm].groupby("period").slo_violation_rate.mean(); ax.plot(s.index, s.values, "-o", label=arm)
    ax.set_xlabel("burst period (s)"); ax.set_ylabel("SLO violation rate"); ax.legend(fontsize=7); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(FIG / "adversarial_period.png", dpi=150); plt.close(fig)

(RES / "twin_report.md").write_text("\n".join(out))

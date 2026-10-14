"""Six synthetic shapes + two rescaled real traces. All return a per-second rps array."""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DUR = 1800


def steady(rng, dur=DUR, base=100.0):
    return np.full(dur, base)


def ramp(rng, dur=DUR, lo=60.0, hi=300.0):
    return np.linspace(lo, hi, dur)


def spike(rng, dur=DUR, base=80.0, peak=300.0, at=600, width=240):
    x = np.full(dur, base); x[at:at + width] = peak
    return x


def repeated_bursts(rng, dur=DUR, base=80.0, peak=300.0, period=240, width=90, offset=300):
    x = np.full(dur, base)
    for s in range(offset, dur, period):
        x[s:s + width] = peak
    return x


def step_down(rng, dur=DUR, hi=300.0, lo=100.0):
    x = np.full(dur, hi); x[dur // 2:] = lo
    return x


def random_walk(rng, dur=DUR, lo=60.0, hi=300.0):
    z = np.cumsum(rng.normal(0, 0.06, dur))
    z = (z - z.min()) / max(np.ptp(z), 1e-9)
    return lo + (hi - lo) * np.convolve(z, np.ones(30) / 30, mode="same")


def _rescale(x, lo=60.0, hi=300.0):
    x = np.asarray(x, float)
    return lo + (hi - lo) * (x - x.min()) / max(np.ptp(x), 1e-9)


def trace_worldcup(rng, dur=DUR):
    d = pd.read_parquet(ROOT / "worldcup98_full_1min.parquet")
    v = d.requests_per_minute.values.astype(float)
    m = dur // 60
    i = int(np.argmax(v)); s = max(0, min(i - m // 2, len(v) - m))
    w = v[s:s + m]
    return _rescale(np.interp(np.arange(dur), np.arange(m) * 60 + 30, w))


def trace_nasa(rng, dur=DUR):
    d = pd.read_parquet(ROOT / "nasa_jul95_arrivals_1s.parquet")
    v = d.requests_per_second.values.astype(float)
    k = np.ones(30) / 30
    sm = np.convolve(v, k, mode="same")
    # busiest rising window: maximise the swing within the window
    stride = 600
    best = max(range(0, len(sm) - dur, stride), key=lambda s: np.ptp(sm[s:s + dur]))
    return _rescale(sm[best:best + dur])


WORKLOADS = {"steady": steady, "ramp": ramp, "spike": spike, "repeated_bursts": repeated_bursts,
             "step_down": step_down, "random_walk": random_walk,
             "trace_worldcup": trace_worldcup, "trace_nasa": trace_nasa}
SYNTHETIC = ["steady", "ramp", "spike", "repeated_bursts", "step_down", "random_walk"]


def make(name, seed=0, **kw):
    return WORKLOADS[name](np.random.default_rng(seed), **kw)

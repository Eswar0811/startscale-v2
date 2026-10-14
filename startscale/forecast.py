"""Deliberately simple short-horizon traffic forecasters (not the contribution)."""
from __future__ import annotations

import numpy as np


class HoltForecaster:
    """Damped-trend Holt smoothing on the observed per-second rate."""

    def __init__(self, alpha=0.15, beta=0.05, phi=0.98, smooth=5):
        self.alpha, self.beta, self.phi, self.smooth = alpha, beta, phi, smooth

    def path(self, history, horizon_s):
        """Forecast for h = 1..horizon_s seconds ahead."""
        h = np.asarray(history[-600:], float)
        if len(h) == 0:
            return np.zeros(max(int(horizon_s), 1))
        if len(h) > self.smooth:
            k = np.ones(self.smooth) / self.smooth
            h = np.convolve(h, k, mode="valid")
        level, trend = h[0], 0.0
        for x in h[1:]:
            prev = level
            level = self.alpha * x + (1 - self.alpha) * (level + self.phi * trend)
            trend = self.beta * (level - prev) + (1 - self.beta) * self.phi * trend
        steps = np.arange(1, max(int(np.ceil(horizon_s)), 1) + 1)
        damp = np.cumsum(self.phi ** steps)
        return np.maximum(level + trend * damp, 0.0)


class OracleForecaster:
    """Reads the true future from the trace with multiplicative noise (sensitivity studies only)."""

    def __init__(self, trace, noise=0.0, seed=0):
        self.trace, self.noise = np.asarray(trace, float), noise
        self.rng = np.random.default_rng(seed)

    def path(self, history, horizon_s):
        t = len(history)
        n = max(int(np.ceil(horizon_s)), 1)
        fut = self.trace[t:t + n]
        if len(fut) < n:
            fut = np.concatenate([fut, np.full(n - len(fut), self.trace[-1])])
        return np.maximum(fut * (1 + self.noise * self.rng.standard_normal()), 0.0)


def mape(actual, pred):
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    m = a > 1e-9
    return float(np.mean(np.abs(a[m] - p[m]) / a[m]))


class SeasonalTrendForecaster:
    """Seasonal-naive (period found by ACF) blended with a local linear trend.

    forecast(h) = max(trend(h), seasonal(h)). Period needs >= 2 observed cycles and ACF > `acf_min`;
    until then it is a pure local-trend forecaster. The max() is deliberate: under-forecasting costs
    SLO violations, over-forecasting costs replica-seconds, and the controller's risk knob handles the rest.
    """

    def __init__(self, win=90, smooth=5, acf_min=0.5, min_period=60, max_period=600, max_hist=1800):
        self.win, self.smooth, self.acf_min = win, smooth, acf_min
        self.pmin, self.pmax, self.max_hist = min_period, max_period, max_hist
        self._period = None
        self._period_t = -1e9

    def _smooth(self, h):
        k = np.ones(self.smooth) / self.smooth
        return np.convolve(h, k, mode="valid") if len(h) > self.smooth else h

    def _find_period(self, s):
        x = s - s.mean()
        v = float(np.dot(x, x))
        if v < 1e-9 or len(s) < 2 * self.pmin + 10:
            return None
        best, bp = 0.0, None
        for p in range(self.pmin, min(self.pmax, len(s) // 2) + 1, 2):
            a = float(np.dot(x[:-p], x[p:])) / v * len(s) / (len(s) - p)
            if a > best:
                best, bp = a, p
        return bp if best >= self.acf_min else None

    def path(self, history, horizon_s):
        n = max(int(np.ceil(horizon_s)), 1)
        h = np.asarray(history[-self.max_hist:], float)
        if len(h) == 0:
            return np.zeros(n)
        s = self._smooth(h)
        tail = s[-self.win:]
        level = float(np.mean(s[-self.smooth:]))
        slope = 0.0
        if len(tail) >= 20:
            slope = float(np.polyfit(np.arange(len(tail)), tail, 1)[0])
        steps = np.arange(1, n + 1)
        trend = np.maximum(level + max(slope, 0.0) * steps, 0.0)
        if len(h) - self._period_t >= 30:
            self._period, self._period_t = self._find_period(s), len(h)
        if self._period is None:
            return trend
        p, off = self._period, self.smooth - 1
        idx = len(s) - 1 + steps - p
        # step back by whole periods until the index lies in observed history
        while np.any(idx >= len(s)):
            idx = np.where(idx >= len(s), idx - p, idx)
        idx = np.clip(idx, 0, len(s) - 1)
        return np.maximum(trend, s[idx.astype(int)])

"""Transforms, shock scores, curve and regime calculations.

Kept free of I/O so every number can be unit-tested against a fixed series.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from .catalog import PERIODS_PER_YEAR, Indicator

Z_WINDOW_YEARS = 3


def transform(s: pd.Series, kind: str, freq: str) -> pd.Series:
    if kind == "level":
        out = s
    elif kind == "diff":
        out = s.diff()
    elif kind == "mom_pct":
        out = s.pct_change() * 100
    elif kind == "yoy":
        out = s.pct_change(PERIODS_PER_YEAR[freq]) * 100
    elif kind == "saar":
        out = ((s / s.shift()) ** PERIODS_PER_YEAR[freq] - 1) * 100
    else:
        raise ValueError(f"unknown transform {kind!r}")
    return out.dropna()


def rolling_z(x: pd.Series, window: int) -> float:
    """z-score of the last observation against the ``window`` observations before it."""
    hist = x.iloc[-window - 1:-1]
    sd = hist.std(ddof=1)
    if len(hist) < max(8, window // 3) or not sd or math.isnan(sd):
        return float("nan")
    return float((x.iloc[-1] - hist.mean()) / sd)


def largest_since(x: pd.Series) -> pd.Timestamp | None:
    """Most recent earlier date with a move at least as large in the same direction.

    None means nothing comparable in the sample, i.e. the largest on record.
    """
    latest = x.iloc[-1]
    prior = x.iloc[:-1]
    if latest == 0:
        return prior.index[-1] if len(prior) else None
    hits = prior[prior >= latest] if latest > 0 else prior[prior <= latest]
    return hits.index[-1] if len(hits) else None


@dataclass
class Reading:
    key: str
    name: str
    unit: str
    period: str  # ISO date of the observation
    value: float
    prior_value: float
    change: float
    innovation: float
    innovation_kind: str
    z_score: float
    percentile: float  # share of history with a smaller absolute move
    largest_since: str | None
    sample_start: str

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = None if math.isnan(v) else round(v, 4)
        return d


def read_indicator(ind: Indicator, raw: pd.Series) -> Reading:
    s = raw * ind.scale
    head = transform(s, ind.headline, ind.freq)
    innov = transform(s, ind.innovation, ind.freq)
    window = Z_WINDOW_YEARS * PERIODS_PER_YEAR[ind.freq]
    latest = innov.iloc[-1]
    abs_hist = innov.iloc[:-1].abs()
    since = largest_since(innov)
    return Reading(
        key=ind.key,
        name=ind.name,
        unit=ind.unit,
        period=head.index[-1].date().isoformat(),
        value=float(head.iloc[-1]),
        prior_value=float(head.iloc[-2]),
        change=float(head.iloc[-1] - head.iloc[-2]),
        innovation=float(latest),
        innovation_kind=ind.innovation,
        z_score=rolling_z(innov, window),
        percentile=float((abs_hist < abs(latest)).mean() * 100),
        largest_since=since.date().isoformat() if since is not None else None,
        sample_start=innov.index[0].date().isoformat(),
    )


@dataclass
class Curve:
    date: str
    y3m: float
    y2y: float
    y10y: float
    spread_10y_3m_bp: float
    spread_10y_2y_bp: float
    inverted: bool  # on the 10y-3m measure, the one with the better recession record
    regime_since: str  # first day of the current sign of 10y-3m
    change_10y_1m_bp: float

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def yield_curve(y3m: pd.Series, y2y: pd.Series, y10y: pd.Series) -> Curve:
    df = pd.concat({"3m": y3m, "2y": y2y, "10y": y10y}, axis=1).dropna()
    last = df.iloc[-1]
    spread = (df["10y"] - df["3m"]) * 100
    sign = spread >= 0
    flips = sign.ne(sign.shift())
    regime_start = flips[flips].index[-1]
    month_ago = df["10y"].iloc[-22] if len(df) > 22 else df["10y"].iloc[0]
    return Curve(
        date=df.index[-1].date().isoformat(),
        y3m=float(last["3m"]),
        y2y=float(last["2y"]),
        y10y=float(last["10y"]),
        spread_10y_3m_bp=float(spread.iloc[-1]),
        spread_10y_2y_bp=float((last["10y"] - last["2y"]) * 100),
        inverted=bool(spread.iloc[-1] < 0),
        regime_since=regime_start.date().isoformat(),
        change_10y_1m_bp=float((last["10y"] - month_ago) * 100),
    )


REGIMES = {
    (True, False): "goldilocks",
    (True, True): "reflation",
    (False, True): "stagflation",
    (False, False): "disinflationary slowdown",
}


def momentum(yoy: pd.Series, lookback: int = 6) -> pd.Series:
    """3-month average of a YoY rate minus the same average ``lookback`` months earlier."""
    smooth = yoy.rolling(3).mean()
    return (smooth - smooth.shift(lookback)).dropna()


def macro_regime(production: pd.Series, core_prices: pd.Series) -> dict:
    """Growth/inflation quadrant from the direction of IP and core CPI momentum."""
    g = momentum(transform(production, "yoy", "M"))
    i = momentum(transform(core_prices, "yoy", "M"))
    both = pd.concat({"g": g, "i": i}, axis=1).dropna()
    labels = [REGIMES[(gv > 0, iv > 0)] for gv, iv in zip(both["g"], both["i"])]
    current = labels[-1]
    streak = 0
    for lab in reversed(labels):
        if lab != current:
            break
        streak += 1
    return {
        "regime": current,
        "as_of": both.index[-1].date().isoformat(),
        "growth_momentum_pp": round(float(both["g"].iloc[-1]), 3),
        "inflation_momentum_pp": round(float(both["i"].iloc[-1]), 3),
        "months_in_regime": streak,
        "previous_regime": next((lab for lab in reversed(labels) if lab != current), None),
    }

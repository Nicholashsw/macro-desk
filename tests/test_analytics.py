import math

import numpy as np
import pandas as pd
import pytest

from macro_desk import analytics
from macro_desk.catalog import INDICATORS, resolve


def monthly(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_yoy_and_mom():
    s = monthly([100 * 1.01 ** i for i in range(25)])
    assert analytics.transform(s, "mom_pct", "M").iloc[-1] == pytest.approx(1.0)
    assert analytics.transform(s, "yoy", "M").iloc[-1] == pytest.approx((1.01 ** 12 - 1) * 100)


def test_saar_quarterly():
    s = pd.Series([100.0, 101.0], index=pd.date_range("2024-01-01", periods=2, freq="QS"))
    assert analytics.transform(s, "saar", "Q").iloc[-1] == pytest.approx((1.01 ** 4 - 1) * 100)


def test_rolling_z_excludes_latest():
    rng = np.random.default_rng(0)
    x = monthly(list(rng.normal(0, 1, 36)) + [5.0])
    hist = x.iloc[:-1]
    assert analytics.rolling_z(x, 36) == pytest.approx((5 - hist.mean()) / hist.std(ddof=1))


def test_rolling_z_short_history_is_nan():
    assert math.isnan(analytics.rolling_z(monthly([1, 2, 3]), 36))


def test_largest_since_same_direction():
    x = monthly([0.1, 0.9, -2.0, 0.2, 0.3, 0.8])
    assert analytics.largest_since(x) == x.index[1]  # the earlier -2.0 is the wrong sign
    assert analytics.largest_since(monthly([0.1, 0.2, 0.5])) is None


def test_curve_inversion_and_regime_start():
    idx = pd.bdate_range("2024-01-01", periods=40)
    y3m = pd.Series(5.0, index=idx)
    y10 = pd.Series([4.5] * 30 + [5.4] * 10, index=idx)
    c = analytics.yield_curve(y3m, pd.Series(4.8, index=idx), y10)
    assert not c.inverted
    assert c.spread_10y_3m_bp == pytest.approx(40)
    assert c.regime_since == idx[30].date().isoformat()


def test_regime_quadrant():
    n = 30
    ip = monthly([100 * 1.004 ** (i * i / 10) for i in range(n)])  # accelerating growth
    core = monthly([100 * 1.002 ** i for i in range(n)])  # steady prices
    out = analytics.macro_regime(ip, core)
    assert out["growth_momentum_pp"] > 0
    assert out["regime"] in {"goldilocks", "reflation"}


@pytest.mark.parametrize("phrase,key", [
    ("inflation", "cpi"), ("core cpi", "core_cpi"), ("what's the jobs report", "payrolls"),
    ("the ten year yield", "treasury_10y"), ("Core PCE", "core_pce"), ("jobless claims", "jobless_claims"),
    ("unemploymnet rate", "unemployment"),
])
def test_resolve(phrase, key):
    assert resolve(phrase).key == key


def test_resolve_unknown():
    assert resolve("bitcoin price") is None


def test_every_indicator_reads_from_snapshot():
    from macro_desk.data import FredStore
    store = FredStore(offline=True)
    for ind in INDICATORS.values():
        r = analytics.read_indicator(ind, store.get(ind.series_id).series)
        assert not math.isnan(r.value)
        assert 0 <= r.percentile <= 100

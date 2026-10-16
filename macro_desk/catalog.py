"""Indicator definitions.

Each indicator has two views of the same FRED series:

* ``headline``   - the number people quote (CPI year-on-year, payrolls change, ...)
* ``innovation`` - the fresh information in the latest print, which is what we
  z-score. For a YoY inflation series that is the month-on-month change, not the
  change in the YoY rate, because base effects would otherwise dominate.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

# periods per year, used for YoY and for the 3-year z-score window
PERIODS_PER_YEAR = {"D": 252, "W": 52, "M": 12, "Q": 4}


@dataclass(frozen=True)
class Indicator:
    key: str
    series_id: str
    name: str
    freq: str
    headline: str  # yoy | mom_pct | diff | level | saar
    innovation: str  # mom_pct | diff | saar
    unit: str  # percent | thousand | index
    scale: float = 1.0  # applied to raw values before transforms (e.g. claims -> thousands)
    hawkish_when_up: bool = True  # direction used to phrase the briefing
    aliases: tuple[str, ...] = field(default_factory=tuple)


INDICATORS: dict[str, Indicator] = {
    i.key: i
    for i in [
        Indicator("cpi", "CPIAUCSL", "headline CPI inflation", "M", "yoy", "mom_pct", "percent",
                  aliases=("inflation", "cpi", "consumer prices", "headline inflation")),
        Indicator("core_cpi", "CPILFESL", "core CPI inflation", "M", "yoy", "mom_pct", "percent",
                  aliases=("core inflation", "core cpi", "underlying inflation")),
        Indicator("core_pce", "PCEPILFE", "core PCE inflation", "M", "yoy", "mom_pct", "percent",
                  aliases=("pce", "core pce", "fed's inflation gauge", "fed inflation")),
        Indicator("unemployment", "UNRATE", "the unemployment rate", "M", "level", "diff", "percent",
                  hawkish_when_up=False,
                  aliases=("unemployment", "jobless rate", "unemployment rate")),
        Indicator("payrolls", "PAYEMS", "nonfarm payrolls", "M", "diff", "diff", "thousand",
                  aliases=("jobs", "jobs report", "payrolls", "nfp", "employment", "hiring")),
        Indicator("industrial_production", "INDPRO", "industrial production", "M", "yoy", "mom_pct", "percent",
                  aliases=("industrial production", "factory output", "manufacturing output", "production")),
        Indicator("retail_sales", "RSAFS", "retail sales", "M", "mom_pct", "mom_pct", "percent",
                  aliases=("retail sales", "consumer spending", "shopping", "sales")),
        Indicator("jobless_claims", "ICSA", "initial jobless claims", "W", "level", "diff", "thousand",
                  scale=1e-3, hawkish_when_up=False,
                  aliases=("claims", "jobless claims", "initial claims", "layoffs")),
        Indicator("gdp", "GDPC1", "real GDP growth", "Q", "saar", "saar", "percent",
                  aliases=("gdp", "growth", "economic growth", "output")),
        Indicator("fed_funds", "FEDFUNDS", "the fed funds rate", "M", "level", "diff", "percent",
                  aliases=("fed funds", "interest rates", "policy rate", "fed rate", "the fed")),
        Indicator("breakeven_10y", "T10YIE", "ten-year breakeven inflation", "D", "level", "diff", "percent",
                  aliases=("breakevens", "inflation expectations", "breakeven")),
        Indicator("treasury_3m", "DGS3MO", "the three-month Treasury yield", "D", "level", "diff", "percent",
                  aliases=("3 month", "three month", "bills", "t-bill")),
        Indicator("treasury_2y", "DGS2", "the two-year Treasury yield", "D", "level", "diff", "percent",
                  aliases=("2 year", "two year", "twos")),
        Indicator("treasury_10y", "DGS10", "the ten-year Treasury yield", "D", "level", "diff", "percent",
                  aliases=("10 year", "ten year", "tens", "bond yields", "treasuries")),
    ]
}

_LOOKUP: dict[str, str] = {}
for _ind in INDICATORS.values():
    for _name in (_ind.key, _ind.key.replace("_", " "), _ind.series_id.lower(), *_ind.aliases):
        _LOOKUP[_name.lower()] = _ind.key


def resolve(query: str) -> Indicator | None:
    """Map free text from a voice request onto an indicator.

    Exact alias first, then substring, then fuzzy match. Returns None when
    nothing is close, so the caller can list what is supported.
    """
    q = " ".join(query.lower().replace("-", " ").replace("_", " ").split())
    if q in _LOOKUP:
        return INDICATORS[_LOOKUP[q]]
    # longest alias contained in the query wins ("core cpi" beats "cpi")
    hits = [alias for alias in _LOOKUP if alias in q]
    if hits:
        return INDICATORS[_LOOKUP[max(hits, key=len)]]
    close = difflib.get_close_matches(q, _LOOKUP.keys(), n=1, cutoff=0.75)
    return INDICATORS[_LOOKUP[close[0]]] if close else None

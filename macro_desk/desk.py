"""The four things the desk can answer. Each returns a dict with a ``speech``
field (what Alexa should say) plus the numbers behind it.
"""

from __future__ import annotations

import math

from . import analytics, speech
from .catalog import INDICATORS, Indicator, resolve
from .data import FredStore

BRIEFING_SET = ("cpi", "core_cpi", "core_pce", "payrolls", "unemployment",
                "retail_sales", "industrial_production", "jobless_claims", "gdp")


class UnknownIndicator(ValueError):
    pass


class Desk:
    def __init__(self, store: FredStore | None = None):
        self.store = store or FredStore()

    # -- helpers ---------------------------------------------------------
    def _lookup(self, query: str) -> Indicator:
        ind = resolve(query)
        if ind is None:
            names = ", ".join(sorted(i.name for i in INDICATORS.values()))
            raise UnknownIndicator(f"I don't track '{query}'. I can cover {names}.")
        return ind

    def _read(self, ind: Indicator) -> tuple[analytics.Reading, str]:
        fetched = self.store.get(ind.series_id)
        return analytics.read_indicator(ind, fetched.series), fetched.source

    # -- tools -----------------------------------------------------------
    def indicators(self) -> dict:
        items = [{"key": i.key, "name": i.name, "frequency": i.freq, "fred_series": i.series_id,
                  "say_it_as": list(i.aliases[:3])} for i in INDICATORS.values()]
        return {"speech": f"I track {len(items)} US indicators, from CPI and payrolls to Treasury yields.",
                "indicators": items}

    def indicator(self, query: str) -> dict:
        ind = self._lookup(query)
        r, source = self._read(ind)
        text = " ".join(t for t in (speech.headline(ind, r), speech.surprise(ind, r)) if t)
        return {"speech": text, "reading": r.to_dict(), "data_source": source}

    def shock(self, query: str) -> dict:
        ind = self._lookup(query)
        r, source = self._read(ind)
        text = speech.surprise(ind, r, always=True, named=True) or "There isn't enough history to score this move."
        return {"speech": text, "reading": r.to_dict(), "window_years": analytics.Z_WINDOW_YEARS,
                "method": ("z-score of the latest innovation (monthly change for inflation and output, "
                           "level change for rates and jobs) against the prior three years of innovations"),
                "data_source": source}

    def curve(self) -> dict:
        legs = [self.store.get(s) for s in ("DGS3MO", "DGS2", "DGS10")]
        c = analytics.yield_curve(*(f.series for f in legs))
        source = "live" if all(f.source == "live" for f in legs) else "snapshot"
        return {"speech": speech.curve(c), "curve": c.to_dict(), "data_source": source}

    def regime(self) -> dict:
        ip, core = self.store.get("INDPRO"), self.store.get("CPILFESL")
        r = analytics.macro_regime(ip.series, core.series)
        return {"speech": speech.regime(r), **r,
                "method": "sign of 6-month change in 3-month average YoY industrial production and core CPI",
                "data_source": "live" if ip.source == core.source == "live" else "snapshot"}

    def briefing(self, top_n: int = 3) -> dict:
        readings = []
        for key in BRIEFING_SET:
            ind = INDICATORS[key]
            r, _ = self._read(ind)
            if r.z_score is not None and not math.isnan(r.z_score):
                readings.append((ind, r))
        readings.sort(key=lambda pair: abs(pair[1].z_score), reverse=True)
        # lead with what actually moved; on a quiet month still say something
        movers = [p for p in readings if abs(p[1].z_score) >= 1][:top_n] or readings[:1]

        parts = ["Here's your macro briefing."]
        for ind, r in movers:
            parts.append(speech.headline(ind, r))
            s = speech.surprise(ind, r)
            if s:
                parts.append(s)
        curve = self.curve()
        regime = self.regime()
        parts.append(curve["speech"].split(". ")[0] + ".")
        parts.append(regime["speech"])
        return {
            "speech": " ".join(parts),
            "movers": [{"indicator": ind.key, "z_score": round(r.z_score, 2), "period": r.period}
                       for ind, r in movers],
            "curve": curve["curve"],
            "regime": regime["regime"],
        }

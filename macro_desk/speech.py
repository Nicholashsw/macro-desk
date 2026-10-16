"""Turn readings into sentences that sound right when read aloud.

Rules of thumb: one number per clause, no symbols, round to what a person would
say, and only mention the shock score when it is worth hearing.
"""

from __future__ import annotations

import math
from datetime import date

from .analytics import Curve, Reading
from .catalog import Indicator

_QUARTERS = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def period_phrase(ind: Indicator, iso: str) -> str:
    d = _d(iso)
    if ind.freq == "Q":
        return f"the {_QUARTERS[(d.month - 1) // 3 + 1]} quarter of {d.year}"
    if ind.freq == "W":
        return f"the week ending {d:%B} {d.day}"
    if ind.freq == "D":
        return f"{d:%B} {d.day}"
    return f"{d:%B} {d.year}"


def month_year(iso: str) -> str:
    d = _d(iso)
    return f"{d:%B} {d.year}"


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def pct(v: float, dp: int = 1) -> str:
    return f"{v:.{dp}f} percent"


def thousands(v: float) -> str:
    return f"{abs(round(v)):,.0f} thousand"


def bp(v: float) -> str:
    n = abs(round(v))
    return f"{n} basis point" + ("" if n == 1 else "s")


def _move(change: float, unit_word: str, tol: float) -> str:
    if abs(change) < tol:
        return "unchanged"
    return f"{'up' if change > 0 else 'down'} {unit_word}"


def headline(ind: Indicator, r: Reading) -> str:
    when = period_phrase(ind, r.period)
    if ind.headline == "yoy":
        if abs(r.change) < 0.05:
            return f"{cap(ind.name)} held at {pct(r.value)} year on year in {when}."
        prev = "up from" if r.change > 0 else "down from"
        return f"{cap(ind.name)} was {pct(r.value)} year on year in {when}, {prev} {pct(r.prior_value)}."
    if ind.headline == "diff" and ind.unit == "thousand":
        verb = "added" if r.value >= 0 else "lost"
        prior_verb = "a gain of" if r.prior_value >= 0 else "a loss of"
        return (f"The economy {verb} {thousands(r.value)} jobs in {when}, "
                f"after {prior_verb} {thousands(r.prior_value)} the month before.")
    if ind.headline == "mom_pct":
        verb = "rose" if r.value >= 0 else "fell"
        return f"{cap(ind.name)} {verb} {pct(abs(r.value))} in {when}, after {pct(r.prior_value)} the month before."
    if ind.headline == "saar":
        verb = "grew" if r.value >= 0 else "contracted"
        return (f"{cap(ind.name.replace(" growth", ""))} {verb} at a {pct(abs(r.value))} annualized rate "
                f"in {when}, after {pct(r.prior_value)}.")
    # levels
    if ind.unit == "thousand":
        move = _move(r.change, f"{thousands(r.change)}", 0.5)
        return f"{cap(ind.name)} were {thousands(r.value)} in {when}, {move} on the week."
    if ind.freq == "D":
        move = _move(r.change * 100, bp(r.change * 100), 0.5)
        return f"{cap(ind.name)} was {pct(r.value, 2)} on {when}, {move} on the day."
    dp = 2 if ind.key == "fed_funds" else 1
    move = _move(r.change, f"{abs(r.change):.{dp}f} points", 0.5 * 10 ** -dp)
    return f"{cap(ind.name)} was {pct(r.value, dp)} in {when}, {move} on the month."


def describe_z(z: float) -> str:
    a = abs(z)
    if a < 1:
        return "an ordinary move"
    if a < 2:
        return "a bigger than usual move"
    if a < 3:
        return "an unusually large move"
    return "an extreme move"


def _innovation_phrase(ind: Indicator, r: Reading) -> str:
    v = r.innovation
    if ind.innovation == "mom_pct":
        return f"the monthly change of {pct(v)}" if ind.headline != "mom_pct" else f"the {pct(v)} move"
    if ind.innovation == "saar":
        return f"the {pct(v)} growth rate"
    if ind.unit == "thousand":
        return f"the {thousands(v)} {'rise' if v >= 0 else 'drop'}" if ind.key != "payrolls" else f"the {thousands(v)} print"
    word = "rise" if v >= 0 else "drop"
    if ind.freq == "D":
        return f"the {abs(round(v * 100))} basis point {word}"
    dp = 2 if ind.key == "fed_funds" else 1
    return f"the {abs(v):.{dp}f} point {word}"


def surprise(ind: Indicator, r: Reading, always: bool = False, named: bool = False) -> str:
    """Shock sentence. Returns an empty string for ordinary moves unless ``always``."""
    if r.z_score is None or math.isnan(r.z_score):
        return ""
    if abs(r.z_score) < 1 and not always:
        return ""
    lead = _innovation_phrase(ind, r)
    lead = f"For {ind.name}, {lead}" if named else cap(lead)
    text = (f"{lead} was {describe_z(r.z_score)}, {abs(r.z_score):.1f} standard deviations "
            f"{'above' if r.z_score > 0 else 'below'} its three-year average")
    if r.largest_since is None:
        text += f", the largest in the data back to {_d(r.sample_start).year}"
    else:
        gap_days = (_d(r.period) - _d(r.largest_since)).days
        if gap_days > 365:
            direction = "rise" if r.innovation > 0 else "drop"
            text += f", the biggest {direction} since {month_year(r.largest_since)}"
    return text + "."


def curve(c: Curve) -> str:
    since = month_year(c.regime_since)
    if c.inverted:
        shape = f"inverted, with ten-year yields {bp(c.spread_10y_3m_bp)} below three-month bills, and has been since {since}"
    else:
        shape = f"upward sloping, with ten-year yields {bp(c.spread_10y_3m_bp)} above three-month bills, and has been since {since}"
    move = c.change_10y_1m_bp
    tail = ("The ten-year is little changed over the past month."
            if abs(move) < 5 else
            f"The ten-year is {'up' if move > 0 else 'down'} {bp(move)} over the past month at {pct(c.y10y, 2)}.")
    return f"The yield curve is {shape}. {tail}"


def _trend(v: float, up: str, down: str, flat: str, band: float = 0.1) -> str:
    return up if v > band else down if v < -band else flat


def regime(r: dict) -> str:
    g = _trend(r["growth_momentum_pp"], "growth is picking up", "growth is slowing", "growth is roughly flat")
    i = _trend(r["inflation_momentum_pp"], "core inflation is accelerating", "core inflation is cooling",
               "core inflation is roughly steady")
    months = r["months_in_regime"]
    span = "as of the latest data" if months == 1 else f"for {months} months running"
    return f"The economy reads as {r['regime']}: {g} and {i}, {span}."

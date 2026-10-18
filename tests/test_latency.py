"""Alexa+ requires a round trip under 500 ms, so no request may wait on FRED."""

import threading
import time

import httpx
import pytest

from macro_desk.data import FredStore
from macro_desk.desk import Desk


@pytest.fixture
def slow_fred(monkeypatch):
    calls = []
    release = threading.Event()

    def hang(*args, **kwargs):
        calls.append(kwargs.get("params", {}).get("id"))
        release.wait(5)
        raise httpx.ConnectTimeout("FRED unreachable")

    monkeypatch.setattr(httpx, "get", hang)
    yield calls
    release.set()


def test_cold_briefing_answers_from_snapshot_without_waiting(slow_fred):
    desk = Desk(FredStore(offline=False))
    start = time.perf_counter()
    out = desk.briefing()
    elapsed = time.perf_counter() - start
    assert out["speech"].startswith("Here's your macro briefing")
    assert elapsed < 0.5, f"briefing took {elapsed:.3f}s"
    time.sleep(0.05)
    assert slow_fred, "a background refresh should have been started"


def test_warm_calls_are_fast():
    desk = Desk(FredStore(offline=True))
    desk.briefing()
    for fn, args in [(desk.briefing, ()), (desk.indicator, ("cpi",)), (desk.shock, ("jobs",)),
                     (desk.curve, ()), (desk.regime, ())]:
        start = time.perf_counter()
        fn(*args)
        assert time.perf_counter() - start < 0.25


def test_failed_refresh_keeps_serving_and_backs_off(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", fail)
    store = FredStore(offline=False)
    store.refresh(["CPIAUCSL"])
    hit = store.get("CPIAUCSL")
    assert hit.source == "snapshot"
    assert not store._due("CPIAUCSL", hit)  # inside the retry window


def test_successful_refresh_replaces_snapshot(monkeypatch):
    class Resp:
        text = "observation_date,CPIAUCSL\n2026-01-01,100.0\n2026-02-01,101.0\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    store = FredStore(offline=False)
    store.refresh(["CPIAUCSL"])
    hit = store.get("CPIAUCSL")
    assert hit.source == "live"
    assert hit.series.iloc[-1] == 101.0

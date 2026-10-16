"""FRED loader.

Uses the public fredgraph CSV endpoint, which needs no API key. Every series
falls back to the snapshot bundled in ``macro_desk/data`` if the network call
fails, so a voice request never dead-ends on an upstream outage. Set
``MACRO_DESK_OFFLINE=1`` to use the snapshot only (tests, demos, air-gapped).
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SNAPSHOT_DIR = Path(__file__).parent / "data"
START = "2000-01-01"


@dataclass
class Fetched:
    series: pd.Series
    source: str  # "live" or "snapshot"
    fetched_at: float


def _parse(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), na_values=["."])
    df.columns = ["date", "value"]
    s = pd.Series(df["value"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]), name="value")
    return s.dropna()


class FredStore:
    def __init__(self, ttl_seconds: float | None = None, offline: bool | None = None, timeout: float = 8.0):
        self.ttl = ttl_seconds if ttl_seconds is not None else float(os.getenv("MACRO_DESK_TTL", 3 * 3600))
        self.offline = offline if offline is not None else os.getenv("MACRO_DESK_OFFLINE") == "1"
        self.timeout = timeout
        self._cache: dict[str, Fetched] = {}
        self._lock = threading.Lock()

    def get(self, series_id: str) -> Fetched:
        with self._lock:
            hit = self._cache.get(series_id)
            if hit and time.time() - hit.fetched_at < self.ttl:
                return hit

        fetched = self._load(series_id)
        with self._lock:
            self._cache[series_id] = fetched
        return fetched

    def refresh(self, series_ids: list[str], workers: int = 8) -> None:
        """Fetch many series in parallel and replace the cache.

        A cold briefing touches a dozen series; done serially that is ~10s, which
        is longer than a voice assistant will wait. Run this at startup and on a timer.
        """
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for sid, fetched in zip(series_ids, pool.map(self._load, series_ids)):
                with self._lock:
                    self._cache[sid] = fetched

    def keep_warm(self, series_ids: list[str]) -> threading.Thread:
        def loop() -> None:
            while True:
                try:
                    self.refresh(series_ids)
                except Exception:  # never let the refresher die
                    log.exception("background refresh failed")
                time.sleep(max(self.ttl / 2, 60))

        t = threading.Thread(target=loop, name="fred-refresh", daemon=True)
        t.start()
        return t

    def _load(self, series_id: str) -> Fetched:
        if not self.offline:
            try:
                resp = httpx.get(FRED_CSV, params={"id": series_id, "cosd": START}, timeout=self.timeout)
                resp.raise_for_status()
                return Fetched(_parse(resp.text), "live", time.time())
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("FRED fetch failed for %s, using snapshot: %s", series_id, exc)
        path = SNAPSHOT_DIR / f"{series_id}.csv"
        return Fetched(_parse(path.read_text()), "snapshot", time.time())

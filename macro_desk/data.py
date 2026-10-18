"""FRED loader.

Uses the public fredgraph CSV endpoint, which needs no API key.

Requests never wait on the network. The cache is primed from the snapshot
bundled in ``macro_desk/data`` and refreshed from FRED in the background
(stale-while-revalidate), so every call answers in milliseconds even on a cold
start or during an upstream outage. Alexa+ expects a round trip under 500 ms.
Set ``MACRO_DESK_OFFLINE=1`` to use the snapshot only (tests, demos, air-gapped).
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
RETRY_AFTER = 300.0  # seconds to wait before retrying a failed live fetch


@dataclass
class Fetched:
    series: pd.Series
    source: str  # "live" or "snapshot"
    fetched_at: float  # 0 for snapshot data, so it is always due a refresh


def _parse(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), na_values=["."])
    df.columns = ["date", "value"]
    s = pd.Series(df["value"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]), name="value")
    return s.dropna()


def load_snapshot(series_id: str) -> Fetched:
    return Fetched(_parse((SNAPSHOT_DIR / f"{series_id}.csv").read_text()), "snapshot", 0.0)


class FredStore:
    def __init__(self, ttl_seconds: float | None = None, offline: bool | None = None, timeout: float = 8.0):
        self.ttl = ttl_seconds if ttl_seconds is not None else float(os.getenv("MACRO_DESK_TTL", 3 * 3600))
        self.offline = offline if offline is not None else os.getenv("MACRO_DESK_OFFLINE") == "1"
        self.timeout = timeout
        self._cache: dict[str, Fetched] = {}
        self._next_try: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fred")

    def get(self, series_id: str) -> Fetched:
        """Current data for a series. Never blocks on the network."""
        with self._lock:
            hit = self._cache.get(series_id)
        if hit is None:
            hit = load_snapshot(series_id)
            with self._lock:
                hit = self._cache.setdefault(series_id, hit)
        if self._due(series_id, hit):
            self._schedule(series_id)
        return hit

    def prime(self, series_ids: list[str]) -> None:
        """Load snapshots for every series so the first request is as fast as the rest."""
        for sid in series_ids:
            self.get(sid)

    def refresh(self, series_ids: list[str]) -> None:
        """Fetch many series from FRED in parallel and wait for them."""
        for _ in self._pool.map(self._refresh_one, series_ids):
            pass

    def keep_warm(self, series_ids: list[str]) -> threading.Thread:
        """Prime from the snapshot, then refresh from FRED on a timer, for long-running hosts."""
        self.prime(series_ids)

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

    # -- internals -------------------------------------------------------
    def _due(self, series_id: str, hit: Fetched) -> bool:
        if self.offline:
            return False
        now = time.time()
        with self._lock:
            return (now - hit.fetched_at >= self.ttl and now >= self._next_try.get(series_id, 0.0)
                    and series_id not in self._inflight)

    def _schedule(self, series_id: str) -> None:
        with self._lock:
            if series_id in self._inflight:
                return
            self._inflight.add(series_id)
        self._pool.submit(self._refresh_one, series_id, True)

    def _refresh_one(self, series_id: str, scheduled: bool = False) -> None:
        try:
            if self.offline:
                return
            try:
                resp = httpx.get(FRED_CSV, params={"id": series_id, "cosd": START}, timeout=self.timeout)
                resp.raise_for_status()
                fetched = Fetched(_parse(resp.text), "live", time.time())
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("FRED fetch failed for %s, keeping cached data: %s", series_id, exc)
                with self._lock:
                    self._next_try[series_id] = time.time() + RETRY_AFTER
                return
            with self._lock:
                self._cache[series_id] = fetched
        finally:
            if scheduled:
                with self._lock:
                    self._inflight.discard(series_id)

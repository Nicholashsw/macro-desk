"""Re-download the bundled FRED snapshot used for offline runs and tests.

    python scripts/refresh_snapshot.py
"""

import httpx

from macro_desk.catalog import INDICATORS
from macro_desk.data import FRED_CSV, SNAPSHOT_DIR, START


def main() -> None:
    for sid in sorted({i.series_id for i in INDICATORS.values()}):
        resp = httpx.get(FRED_CSV, params={"id": sid, "cosd": START}, timeout=30)
        resp.raise_for_status()
        (SNAPSHOT_DIR / f"{sid}.csv").write_text(resp.text)
        last = resp.text.strip().splitlines()[-1]
        print(f"{sid:10s} {last}")


if __name__ == "__main__":
    main()

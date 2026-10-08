import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend import signals
from backend.alerts import Monitor, Store
from backend.config import get_settings

NY = ZoneInfo("America/New_York")


def _candles(closes, start="2025-01-01", vol=None):
    t = pd.date_range(start, periods=len(closes), freq="B")
    return [{"time": t[i].date().isoformat(), "open": c, "high": c * 1.005, "low": c * 0.995,
             "close": c, "volume": (vol[i] if vol is not None else 1e6)} for i, c in enumerate(closes)]


def test_confirmed_drops_today_only_during_session():
    cs = _candles([1, 2, 3], start="2026-10-06")         # 10-06, 10-07, 10-08
    during = datetime(2026, 10, 8, 11, 0, tzinfo=NY)
    after = datetime(2026, 10, 8, 16, 30, tzinfo=NY)
    assert signals.confirmed_candles(cs, "US", during)[-1]["time"] == "2026-10-07"
    assert signals.confirmed_candles(cs, "US", after)[-1]["time"] == "2026-10-08"


def test_golden_cross_detected_once_with_stats():
    # 하락 120일 → 상승 120일: 20일선이 60일선을 한 번 위로 뚫는다
    closes = list(np.linspace(150, 100, 120)) + list(np.linspace(100, 160, 120))
    r = signals.detect(_candles(closes), "US", datetime(2030, 1, 1, tzinfo=NY))
    gcs = [e for e in r["events"] if e["type"] == "gc"]
    assert len(gcs) == 1 and gcs[0]["dir"] == "bull"
    st = r["stats"]["gc"]
    assert st["count"] == 1 and st["n20"] == 1 and st["avg20"] > 0 and st["up20"] == 1


def test_volume_spike_and_52w_high():
    closes = [100.0] * 260 + [101.0]
    vol = [1e6] * 260 + [3e6]
    r = signals.detect(_candles(closes, vol=vol), "US", datetime(2030, 1, 1, tzinfo=NY))
    last = [e for e in r["events"] if e["time"] == r["confirmed_through"]]
    types = {e["type"] for e in last}
    assert {"vol_spike", "high52"} <= types
    assert "3.0배" in next(e for e in last if e["type"] == "vol_spike")["note"]


def test_monitor_sends_signal_once_even_after_restart(tmp_path):
    store = Store(tmp_path)
    store.set_watchlist(["X"])
    ev = {"key": "X:sig:gc:2026-10-07", "type": "signal-bull", "kind": "signal", "symbol": "X",
          "name": "X", "title": "X 골든크로스", "body": "..."}
    make = lambda: Monitor(get_settings(), store, lambda s: ("X", "USD", {}),
                           lambda syms: {"X": 100.0}, lambda c: str, lambda s: [dict(ev)])
    assert len(asyncio.run(make().tick())) == 1
    assert asyncio.run(make().tick()) == []          # 새 Monitor(=재시작)여도 기록에 있으면 안 보냄

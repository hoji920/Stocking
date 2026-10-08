import asyncio
import json

from backend import bars
from backend.realtime import Hub


def _min(ts, o, h, l, c, v=1.0):
    return {"time": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_aggregate_minutes_to_5m_in_kst():
    base = 1_760_000_100 - 1_760_000_100 % 300 + 300 - 9 * 3600 % 300   # KST 기준 5분 경계에 맞추기 귀찮으니 아래서 검증
    raw = [_min(base + 60 * i, 10 + i, 11 + i, 9 + i, 10.5 + i) for i in range(10)]
    out = bars.aggregate_minutes(raw, 5)
    assert sum(b["volume"] for b in out) == 10
    for b in out:
        assert b["time"] % 300 == 0                     # 5분 경계
    first = out[0]
    members = [r for r in raw if (r["time"] + bars.KST_SHIFT) - (r["time"] + bars.KST_SHIFT) % 300 == first["time"]]
    assert first["open"] == members[0]["open"] and first["close"] == members[-1]["close"]
    assert first["high"] == max(m["high"] for m in members)


def test_aggregate_days_week_month_year():
    days = [{"time": d, "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5, "volume": 1}
            for i, d in enumerate(["2026-09-28", "2026-09-29", "2026-10-01", "2026-10-02", "2026-10-05", "2027-01-04"])]
    w = bars.aggregate_days(days, "1w")
    assert [b["time"] for b in w] == ["2026-09-28", "2026-10-05", "2027-01-04"]
    assert w[0]["open"] == 0 and w[0]["close"] == 3.5 and w[0]["volume"] == 4
    m = bars.aggregate_days(days, "1M")
    assert [b["time"] for b in m] == ["2026-09-28", "2026-10-01", "2027-01-04"]
    y = bars.aggregate_days(days, "1y")
    assert [b["time"] for b in y] == ["2026-09-28", "2027-01-04"]
    assert y[0]["high"] == 5 and y[0]["low"] == -1


def test_hub_routes_latest_tick_only_to_interested():
    async def run():
        hub = Hub(lambda: "t")
        a, qa = hub.add({"AAPL"})
        b, qb = hub.add({"005930", "NVDA"})
        assert hub.declaration() == [{"type": "trade:kr", "codes": ["005930"]},
                                     {"type": "trade:us", "codes": ["AAPL", "NVDA"]}]
        for p in ("1", "2", "3"):
            hub.on_frame(json.dumps({"type": "message", "topic": "trade:us:AAPL",
                                     "data": {"price": p, "volume": "1", "timestamp": "2026-10-08T23:30:00+09:00", "currency": "USD"}}))
        hub.flush()
        assert qa.get_nowait()["AAPL"]["price"] == 3.0     # 묶어서 최신값만
        assert qb.empty()
        # 거부된 종목은 다음 선언에서 빠진다
        hub.on_frame(json.dumps({"type": "subscriptions", "subscribed": [], "rejected": [
            {"target": "trade:us:NVDA", "code": "stock-not-found", "message": "x"}]}))
        assert "NVDA" not in hub.desired()
        # 새 구독자는 마지막 체결을 바로 받는다
        _, qc = hub.add({"AAPL"})
        assert qc.get_nowait()["AAPL"]["price"] == 3.0
        hub.remove(a)
        assert "AAPL" in hub.desired()                     # c 가 아직 보고 있음
    asyncio.run(run())

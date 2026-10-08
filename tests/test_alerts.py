import asyncio

from backend.alerts import Monitor, Store, detect, subject
from backend.config import get_settings

LEVELS = {
    "support": [{"price": 100.0, "touches": 3}],
    "resistance": [{"price": 110.0, "touches": 2}],
}
fmt = lambda p: f"${p:.2f}"


def types(events):
    return sorted(e["type"] for e in events)


def test_breakout_and_breakdown():
    assert types(detect("X", "X", 109.0, 111.0, LEVELS, 0.5, fmt)) == ["breakout"]
    assert types(detect("X", "X", 101.0, 99.0, LEVELS, 0.5, fmt)) == ["breakdown"]
    assert types(detect("X", "X", 99.0, 100.5, LEVELS, 0.1, fmt)) == ["reclaim"]


def test_near_without_cross():
    ev = detect("X", "X", 105.0, 109.2, LEVELS, 1.0, fmt)
    assert types(ev) == ["near"]
    assert "저항선" in ev[0]["title"] and "$110.00" in ev[0]["body"]


def test_labeled_line():
    lv = {"support": [{"id": "auto-support", "price": 100.0, "touches": 3, "label": "상승 추세선"}]}
    ev = detect("X", "애플", 101.0, 99.0, lv, 0.5, fmt)[0]
    assert ev["title"] == "X 상승 추세선 이탈"
    assert ev["key"] == "X:breakdown:auto-support"
    mine = {"resistance": [{"id": "d1", "price": 110.0, "touches": 0, "label": "내 추세선"}]}
    ev = detect("X", "애플", 105.0, 109.5, mine, 1.0, fmt)[0]
    assert ev["title"] == "X 내 추세선 근접" and "과거" not in ev["body"]


def test_josa():
    assert subject("마이크로소프트") == "마이크로소프트가"
    assert subject("애플") == "애플이"
    assert subject("Tesla") == "Tesla이(가)"


def test_nothing_in_middle_and_first_tick_no_cross():
    assert detect("X", "X", 104.0, 105.0, LEVELS, 1.0, fmt) == []
    assert detect("X", "X", None, 111.0, LEVELS, 0.5, fmt) == []   # 직전가 없으면 돌파 판정 안 함


def test_monitor_cooldown_and_persist(tmp_path):
    store = Store(tmp_path)
    store.set_watchlist(["X"])
    prices = iter([{"X": 105.0}, {"X": 111.0}, {"X": 109.0}, {"X": 111.0}])
    m = Monitor(get_settings(), store, lambda s: ("X", "USD", LEVELS),
                lambda syms: next(prices), lambda c: fmt)

    async def run():
        return [await m.tick() for _ in range(4)]

    ticks = asyncio.run(run())
    assert ticks[0] == []
    assert types(ticks[1]) == ["breakout"]
    assert types(ticks[2]) == ["reject"]        # 선을 건넌 틱엔 근접 대신 돌파/복귀만
    assert ticks[3] == []                       # 같은 날 같은 선 돌파는 한 번만
    assert len(store.alerts()) == 2

import asyncio
from dataclasses import replace

from backend import movers
from backend.alerts import Monitor, Store
from backend.config import get_settings
from backend.news import NewsItem


def test_move_step_and_key():
    assert movers.move_step(-3.4, 3) == 1
    assert movers.move_step(-6.1, 3) == 2
    assert movers.move_step(2.9, 3) == 0
    assert movers.move_event_key("X", -3.4, 1, "2026-10-08") == "X:move:down:1:2026-10-08"


def test_explain_without_news_or_llm_never_invents():
    s = replace(get_settings(), openai_api_key="")
    r = movers.explain(s, symbol="X", name="X", market="US", change_pct=-4, market_change_pct=-0.2, items=[])
    assert r["found"] is False and "찾지 못했어요" in r["reason"] and r["sources"] == []
    item = NewsItem(title="t", summary="s", date="2026-10-08", source="src", url="http://u")
    r = movers.explain(s, symbol="X", name="X", market="US", change_pct=-4, market_change_pct=None, items=[item])
    assert r["found"] is False and r["sources"][0]["url"] == "http://u"     # 키 없으면 제목만 참고로


def test_monitor_move_alert_once_and_skips_llm_when_seen(tmp_path):
    store = Store(tmp_path)
    store.set_watchlist(["X"])
    calls = []

    def check_move(symbol, price, seen):
        key = movers.move_event_key(symbol, -3.5, 1, "2026-10-08")
        if seen(key):
            return []
        calls.append(symbol)                     # 여기가 뉴스·LLM 부르는 자리
        return [{"key": key, "type": "move-down", "kind": "move", "symbol": symbol, "name": symbol,
                 "title": "X -3.50% 급락", "body": "...", "sources": []}]

    make = lambda: Monitor(get_settings(), store, lambda s: ("X", "USD", {}), lambda syms: {"X": 96.5},
                           lambda c: str, None, check_move)
    assert len(asyncio.run(make().tick())) == 1
    assert asyncio.run(make().tick()) == []      # 재시작해도 같은 단계는 다시 안 보냄
    assert calls == ["X"]                        # 이유 찾기도 한 번만

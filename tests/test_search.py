from backend.config import market_of
from backend.search import build_universe, resolve, search

ROWS = {
    "NASDAQ": [{"symbol": "AAPL", "name": "애플", "securityType": "STOCK"},
               {"symbol": "NVDA", "name": "엔비디아", "securityType": "STOCK"},
               {"symbol": "A", "name": "애질런트", "securityType": "STOCK"}],
    "NYSE": [{"symbol": "AFL", "name": "애플랙", "securityType": "STOCK"}],
    "KOSPI": [{"symbol": "448540", "name": "ACE 엔비디아채권혼합", "securityType": "ETF"},
              {"symbol": "005930", "name": "삼성전자", "securityType": "STOCK"}],
}


def _universe():
    def fetch(market):
        if market == "AMEX":
            raise RuntimeError("down")     # 한 거래소 실패해도 계속
        return ROWS.get(market, [])
    return build_universe(fetch)


def test_rank_exact_name_and_ticker_first():
    u = _universe()
    assert [s["symbol"] for s in search(u, "애플")][:2] == ["AAPL", "AFL"]
    assert search(u, "엔비디아")[0]["symbol"] == "NVDA"
    assert search(u, "nvda")[0]["symbol"] == "NVDA"
    assert search(u, "a")[0]["symbol"] == "A"
    assert search(u, "삼성 전자")[0]["symbol"] == "005930"     # 띄어쓰기 무시
    assert search(u, "   ") == []


def test_resolve():
    u = _universe()
    assert resolve(u, "엔비디아")["symbol"] == "NVDA"
    assert resolve(u, "없는종목") is None


def test_market_of_new_kr_codes():
    assert market_of("005930") == "KR"
    assert market_of("0047P0") == "KR"
    assert market_of("AAPL") == "US"
    assert market_of("BRK.B") == "US"

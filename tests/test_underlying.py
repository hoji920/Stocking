from backend import macro, underlying


def info(name, lev="1", t="ETF"):
    return {"securityType": t, "englishName": name, "leverageFactor": lev}


def test_resolve_common_etfs():
    r = lambda s, n, lev="1": underlying.resolve(s, info(n, lev))
    assert r("BITX", "2X BITCOIN STRATEGY ETF", "2")["key"] == "bitcoin"
    assert r("SOXL", "DIREXION SHARES ETF TRUST DAILY SEMICONDUCTOR BULL 3X SHS", "3")["leverage"] == 3
    assert r("TSLL", "DIREXION DAILY TSLA BULL 2X SHARES", "2")["quote"] == "TSLA"
    assert r("TQQQ", "PROSHARES TRUST ULTRAPRO QQQ USD", "3")["key"] == "nasdaq"
    assert r("TLT", "iShares 20+ Year Treasury Bond ETF")["key"] == "ust"
    assert r("USO", "UNITED STATES OIL FUND LP UNITS(POST REV SPLIT)")["key"] == "oil"
    sqqq = r("SQQQ", "PROSHARES ULTRAPRO SHORT QQQ", "-3")
    assert sqqq["inverse"] and sqqq["leverage"] == 3
    assert "반대로" in underlying.describe(sqqq)


def test_not_etf_or_unknown():
    assert underlying.resolve("AAPL", {"securityType": "STOCK", "englishName": "APPLE INC"}) is None
    assert underlying.resolve("XYZ", info("SOME METALS MINING ETF")) is None     # METALS ≠ META


def test_macro_vs_toss_symbols():
    assert macro.is_macro("^IXIC") and macro.is_macro("NQ=F") and macro.is_macro("BTC-USD")
    assert not macro.is_macro("TLT")        # 토스에서 거래되는 ETF 는 토스로
    assert not macro.is_macro("AAPL")

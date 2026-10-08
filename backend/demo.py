"""토스 키 없을 때 화면 확인용 가짜 일봉. 실제 시세 아님."""
from __future__ import annotations
import zlib
from datetime import date, timedelta

import numpy as np

_DEMO_NAMES = {"005930": "삼성전자(데모)", "000660": "SK하이닉스(데모)",
               "AAPL": "Apple(데모)", "NVDA": "NVIDIA(데모)", "TSLA": "Tesla(데모)"}


def demo_info(symbol: str, market: str) -> dict:
    return {"symbol": symbol, "name": _DEMO_NAMES.get(symbol, f"{symbol}(데모)"),
            "currency": "KRW" if market == "KR" else "USD"}


def demo_candles(symbol: str, market: str, days: int = 300) -> list[dict]:
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    price = 70000.0 if market == "KR" else 180.0
    # 박스권 + 추세가 섞이게: 평균회귀 항으로 지지/저항이 생기도록
    anchor = price
    out, d = [], date.today() - timedelta(days=int(days * 1.45))
    while len(out) < days:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if len(out) % 90 == 0:
            anchor *= rng.choice([0.9, 1.0, 1.12])
        drift = (anchor - price) / anchor * 0.08
        ret = drift + rng.normal(0, 0.017)
        o = price
        c = price * (1 + ret)
        h = max(o, c) * (1 + abs(rng.normal(0, 0.007)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.007)))
        r = (lambda x: round(x)) if market == "KR" else (lambda x: round(x, 2))
        out.append({"time": d.isoformat(), "open": r(o), "high": r(h), "low": r(lo),
                    "close": r(c), "volume": float(rng.integers(5e5, 5e6))})
        price = c
    return out

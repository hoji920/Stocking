"""시장·매크로 지표 (지수, 선물, 미국 국채 금리, 원자재, 환율, 코인).

토스 Open API 의 시장 지표는 국내 지수·국채 8종뿐이라, 미국 지수·선물·금리·원자재는 yfinance(야후 파이낸스)를 쓴다.
- 개인용 로컬 앱 전용. 서비스로 배포하려면 라이선스 있는 데이터로 바꿔야 한다.
- 실시간 아님(몇 분 지연될 수 있음). 1분 캐시.
"""
from __future__ import annotations
import math
import threading
import time

import pandas as pd

# (그룹, [(야후 심볼, 이름, 단위)]). 단위: pt=지수포인트, pct=금리(%), usd, krw
CATALOG: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("미국 지수", [("^IXIC", "나스닥 종합", "pt"), ("^GSPC", "S&P 500", "pt"), ("^DJI", "다우존스", "pt"),
                ("^RUT", "러셀 2000", "pt"), ("^SOX", "필라델피아 반도체", "pt"), ("^VIX", "VIX 공포지수", "pt")]),
    ("미국 선물", [("NQ=F", "나스닥100 선물", "pt"), ("ES=F", "S&P500 선물", "pt"), ("YM=F", "다우 선물", "pt"),
                ("RTY=F", "러셀2000 선물", "pt")]),
    ("미국 국채", [("^IRX", "3개월 금리", "pct"), ("^FVX", "5년 금리", "pct"), ("^TNX", "10년 금리", "pct"),
                ("^TYX", "30년 금리", "pct")]),
    ("원자재", [("CL=F", "WTI 원유", "usd"), ("BZ=F", "브렌트유", "usd"), ("GC=F", "금", "usd"),
             ("HG=F", "구리", "usd"), ("NG=F", "천연가스", "usd")]),
    ("환율·코인", [("DX-Y.NYB", "달러인덱스", "pt"), ("KRW=X", "원/달러", "krw"), ("BTC-USD", "비트코인", "usd"),
               ("ETH-USD", "이더리움", "usd")]),
    ("국내", [("^KS11", "코스피", "pt"), ("^KQ11", "코스닥", "pt")]),
]
BY_SYMBOL = {s: (name, unit, group) for group, rows in CATALOG for s, name, unit in rows}

# 토스에서 거래되는 ETF 로 보는 '실시간' 시장 (토스 WebSocket 체결로 바로바로 바뀜). 야후 지표는 몇 분 지연
LIVE_ETFS = [("QQQ", "나스닥100"), ("SPY", "S&P500"), ("IWM", "러셀2000"), ("SOXX", "반도체"),
             ("TLT", "장기국채"), ("USO", "원유"), ("GLD", "금"), ("IBIT", "비트코인")]   # 묶음 이름이 '실시간 ETF'


def is_macro(symbol: str) -> bool:
    """야후로 차트를 그려야 하는 지표인가. TLT 처럼 토스에서 거래되는 ETF(알파벳 티커)는 토스로 본다 (실시간·보유·알림 다 되게)."""
    return symbol in BY_SYMBOL and not symbol.isalpha()


_yf_lock = threading.Lock()


def _download(symbols: list[str], period: str, interval: str = "1d"):
    """yfinance 는 동시에 여러 스레드에서 부르면 내부 공유 상태가 섞여 결과가 비거나 엉킨다
    (시장 탭 갱신과 차트 요청이 겹칠 때 실제로 발생) → 한 번에 하나씩."""
    import yfinance as yf
    with _yf_lock:
        df = yf.download(symbols, period=period, interval=interval, progress=False, auto_adjust=False,
                         group_by="column", threads=True)
    if df.empty:
        raise RuntimeError(f"야후에서 데이터가 비어서 왔어요: {', '.join(symbols)}")
    if not isinstance(df.columns, pd.MultiIndex):          # 버전에 따라 단일 종목은 1단 컬럼
        df.columns = pd.MultiIndex.from_product([df.columns, symbols])
    return df


_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def quotes() -> list[dict]:
    """그룹별 현재값·전일 대비·한 달 미니차트."""
    def fetch():
        closes = _download(list(BY_SYMBOL), "1mo")["Close"]
        groups = []
        for group, rows in CATALOG:
            items = []
            for sym, name, unit in rows:
                s = closes[sym].dropna() if sym in closes else []
                if len(s) < 2:
                    items.append({"symbol": sym, "name": name, "unit": unit, "error": True})
                    continue
                last, prev = float(s.iloc[-1]), float(s.iloc[-2])
                items.append({
                    "symbol": sym, "name": name, "unit": unit,
                    "last": last, "prev": prev,
                    "change": last - prev,
                    "change_pct": (last / prev - 1) * 100 if prev else 0.0,
                    "change_bp": (last - prev) * 100 if unit == "pct" else None,   # 금리는 bp 로
                    "date": s.index[-1].date().isoformat(),
                    "spark": [round(float(v), 4) for v in s.tolist()[-22:]],
                })
            groups.append({"group": group, "items": items})
        return groups
    return _cached("quotes", 60, fetch)


def change_pct(symbol: str) -> float | None:
    """한 지표의 전일 대비 % (기초자산 움직임 비교용)."""
    for g in quotes():
        for it in g["items"]:
            if it["symbol"] == symbol and not it.get("error"):
                return it["change_pct"]
    try:
        s = _download([symbol], "5d")["Close"][symbol].dropna()
        return float(s.iloc[-1] / s.iloc[-2] - 1) * 100 if len(s) >= 2 else None
    except Exception:
        return None


def daily_candles(symbol: str, years: int = 10) -> list[dict]:
    """차트용 일봉 (앱의 캔들 형식)."""
    def fetch():
        df = _download([symbol], f"{years}y")
        out = []
        for ts, row in df.iterrows():
            o, h, l, c = (float(row[(k, symbol)]) for k in ("Open", "High", "Low", "Close"))
            if any(math.isnan(x) for x in (o, h, l, c)):
                continue
            v = row[("Volume", symbol)]
            out.append({"time": ts.date().isoformat(), "open": o, "high": h, "low": l, "close": c,
                        "volume": 0.0 if v != v else float(v)})
        return out
    return _cached(f"candles:{symbol}:{years}", 300, fetch)

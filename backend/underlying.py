"""ETF 의 기초자산 알아내기 → '왜 움직였지?'에서 기초자산 움직임·뉴스까지 보기.

토스 종목 정보의 영문 이름(englishName)과 레버리지 배수(leverageFactor)로 판단한다.
  BITX "2X BITCOIN STRATEGY ETF" (2배)        → 비트코인
  SOXL "... SEMICONDUCTOR BULL 3X ..." (3배)  → 반도체
  TSLL "DIREXION DAILY TSLA BULL 2X" (2배)    → TSLA (개별 주식)
"""
from __future__ import annotations
import re

# (이름에서 찾을 패턴, 기초자산). quote = macro 심볼(야후) 또는 토스 종목, related = 뉴스 볼 관련 종목
RULES: list[tuple[str, dict]] = [
    (r"BITCOIN|\bBTC\b", {"key": "bitcoin", "label": "비트코인", "quote": "BTC-USD", "news_category": "crypto",
                          "keywords": ["bitcoin", "btc", "crypto"], "related": ["IBIT", "MSTR", "COIN"]}),
    (r"ETHER|ETHEREUM|\bETH\b", {"key": "ether", "label": "이더리움", "quote": "ETH-USD", "news_category": "crypto",
                                 "keywords": ["ether", "ethereum", "crypto"], "related": ["ETHA", "COIN"]}),
    (r"SEMICONDUCTOR|\bSEMI|\bSOX", {"key": "semis", "label": "필라델피아 반도체 지수", "quote": "^SOX", "news_category": "general",
                                     "keywords": ["chip", "semiconductor", "nvidia", "tsmc", "amd"], "related": ["NVDA", "AMD", "AVGO", "TSM"]}),
    (r"\bQQQ\b|NASDAQ|\bNDX\b", {"key": "nasdaq", "label": "나스닥100 선물", "quote": "NQ=F", "news_category": "general",
                                 "keywords": ["nasdaq", "tech stocks", "wall street"], "related": ["QQQ", "NVDA", "MSFT", "AAPL"]}),
    (r"RUSSELL|\bIWM\b|SMALL ?CAP", {"key": "russell", "label": "러셀2000 선물", "quote": "RTY=F", "news_category": "general",
                                     "keywords": ["russell", "small-cap", "small cap"], "related": ["IWM"]}),
    (r"S&P|\bSPX\b|\bSPY\b|\b500\b", {"key": "sp500", "label": "S&P500 선물", "quote": "ES=F", "news_category": "general",
                                       "keywords": ["s&p 500", "stocks", "wall street"], "related": ["SPY"]}),
    (r"\bDOW\b", {"key": "dow", "label": "다우 선물", "quote": "YM=F", "news_category": "general",
                  "keywords": ["dow"], "related": ["DIA"]}),
    (r"TREASURY|\bBOND|\bTLT\b|\bTMF\b", {"key": "ust", "label": "미국 10년 금리", "quote": "^TNX", "news_category": "general",
                                          "keywords": ["treasury", "yield", "bond", "fed"], "related": ["TLT"],
                                          "note": "금리가 오르면 국채 가격(국채 ETF)은 내려요"}),
    (r"\bOIL\b|CRUDE|\bWTI\b", {"key": "oil", "label": "WTI 원유", "quote": "CL=F", "news_category": "general",
                                "keywords": ["oil", "crude", "opec", "brent"], "related": ["XOM", "CVX"]}),
    (r"\bGOLD\b", {"key": "gold", "label": "금", "quote": "GC=F", "news_category": "general",
                   "keywords": ["gold"], "related": ["GLD", "NEM"]}),
    (r"NATURAL GAS", {"key": "natgas", "label": "천연가스", "quote": "NG=F", "news_category": "general",
                      "keywords": ["natural gas", "lng"], "related": ["UNG"]}),
]
COMPANY_WORDS = {"TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "AMAZON": "AMZN", "MICROSOFT": "MSFT",
                 "META": "META", "ALPHABET": "GOOGL", "GOOGLE": "GOOGL", "PALANTIR": "PLTR", "COINBASE": "COIN",
                 "MICROSTRATEGY": "MSTR", "STRATEGY INC": "MSTR", "BROADCOM": "AVGO", "NETFLIX": "NFLX"}
SINGLE_TICKERS = {"TSLA", "NVDA", "AAPL", "AMZN", "MSFT", "META", "GOOGL", "PLTR", "COIN", "MSTR", "AVGO", "NFLX",
                  "AMD", "SMCI", "ARM", "MU", "INTC", "BABA", "UBER", "HOOD", "CRWV", "IONQ", "RGTI", "SOFI"}


def resolve(symbol: str, info: dict) -> dict | None:
    """ETF 면 기초자산 정보, 아니면 None."""
    if info.get("securityType") not in ("ETF", "FOREIGN_ETF", "ETN"):
        return None
    name = (info.get("englishName") or info.get("name") or "").upper()
    lev = info.get("leverageFactor")
    try:
        lev = float(lev) if lev not in (None, "") else 1.0
    except ValueError:
        lev = 1.0
    inverse = lev < 0 or bool(re.search(r"\bBEAR\b|\bSHORT\b|INVERSE", name))
    base = {"leverage": abs(lev), "inverse": inverse}
    # 개별 주식 레버리지 ETF (TSLL, NVDL ...): 이름 속 티커/회사명
    for tok in re.findall(r"\b[A-Z]{2,5}\b", name):
        if tok in SINGLE_TICKERS and tok != symbol:
            return {**base, "key": tok, "label": tok, "quote": tok, "quote_is_stock": True,
                    "news_category": None, "keywords": [], "related": [tok]}
    for word, tk in COMPANY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", name) and tk != symbol:      # META 가 METALS 에 걸리지 않게
            return {**base, "key": tk, "label": tk, "quote": tk, "quote_is_stock": True,
                    "news_category": None, "keywords": [], "related": [tk]}
    for pattern, spec in RULES:
        if re.search(pattern, name):
            return {**base, **spec, "quote_is_stock": False}
    return None


def describe(u: dict) -> str:
    lev = f"{u['leverage']:g}배" if u["leverage"] != 1 else ""
    direction = "반대로(인버스) " if u["inverse"] else ""
    return f"{u['label']}을(를) {direction}{lev} 따라가는 ETF".replace("  ", " ")

"""종목 이름/티커 검색. 토스 /stocks/all 전체 목록을 하루 한 번 받아 메모리에서 찾는다."""
from __future__ import annotations

US_MARKETS = ["NASDAQ", "NYSE", "AMEX", "US_ETC"]
KR_MARKETS = ["KOSPI", "KOSDAQ", "KR_ETC"]


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


def build_universe(fetch_market) -> list[dict]:
    """fetch_market(market) -> [{symbol, name, securityType, ...}]. 미국 먼저."""
    out = []
    for market in US_MARKETS + KR_MARKETS:
        try:
            rows = fetch_market(market)
        except Exception as error:      # 한 거래소 실패해도 나머지로 검색되게
            print(f"[search] {market} 목록 실패: {error}")
            continue
        for r in rows:
            out.append({"symbol": r["symbol"], "name": r.get("name") or r["symbol"],
                        "market": market, "type": r.get("securityType", "")})
    return out


def search(universe: list[dict], query: str, limit: int = 12) -> list[dict]:
    q = _norm(query)
    if not q:
        return []
    qu = q.upper()
    scored = []
    for i, s in enumerate(universe):
        sym, name = s["symbol"].upper(), _norm(s["name"])
        if sym == qu:
            rank = 0
        elif name == q:
            rank = 1
        elif sym.startswith(qu):
            rank = 2 + len(sym) / 100          # 짧은 티커 먼저 (A → AAPL 보다 A)
        elif name.startswith(q):
            rank = 3 + len(name) / 100
        elif q in name:
            rank = 4 + len(name) / 100
        else:
            continue
        if s["type"] not in ("STOCK", "FOREIGN_STOCK", "ETF", "FOREIGN_ETF", "DEPOSITARY_RECEIPT"):
            rank += 1                           # 워런트·ETN 등은 뒤로
        scored.append((rank, i, s))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [s for _, _, s in scored[:limit]]


def resolve(universe: list[dict], token: str) -> dict | None:
    """붙여넣은 한 토큰(티커 또는 이름)을 종목 하나로. 애매하면 첫 번째."""
    hits = search(universe, token, limit=1)
    return hits[0] if hits else None

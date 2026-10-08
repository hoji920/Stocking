"""급등락 감지 + '왜 움직였지?' (뉴스로 이유 찾기).

- 감지: 전일 종가 대비 ±threshold% 를 넘을 때. 더 크게 움직이면 한 단계씩(3% → 6% → 9%) 다시.
- 이유: 그 종목 최근 뉴스 + 시장 전체 움직임(미국 SPY / 국내 KODEX200) 을 LLM 에 주고,
  **주어진 기사 안에서만** 원인을 고르게 한다. 근거가 없으면 '못 찾음'이라고 말하게 한다 (창작 금지).
- LLM 키가 없으면 최근 기사 제목만 붙인다.
"""
from __future__ import annotations
import json
import math
from datetime import date, datetime, timedelta

from backend import news
from backend.config import Settings

MARKET_PROXY = {"US": ("SPY", "S&P500(SPY)"), "KR": ("069500", "코스피200(KODEX 200)")}


def move_step(change_pct: float, threshold: float) -> int:
    """몇 번째 단계인지: 3% 기준이면 -3.4% → 1, -6.1% → 2, +2% → 0."""
    if threshold <= 0:
        return 0
    return int(math.floor(abs(change_pct) / threshold))


def move_event_key(symbol: str, change_pct: float, step: int, day: str) -> str:
    return f"{symbol}:move:{'up' if change_pct > 0 else 'down'}:{step}:{day}"


def recent_news(settings: Settings, market: str, symbol: str, name: str, days: int = 3,
                underlying: dict | None = None) -> list[news.NewsItem]:
    """그 종목 뉴스 + (ETF 면) 기초자산 시장 뉴스 + 관련 종목 뉴스. 같은 기사는 하나만."""
    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as error:      # 뉴스가 안 돼도 알림 자체는 보낸다
            print(f"[movers] {symbol} 뉴스 실패: {error}")
            return []
    items = safe(news.fetch_us_news, settings, symbol, limit=10, days=days) if market == "US" \
        else safe(news.fetch_kr_news, settings, name, limit=10)
    if underlying:
        if underlying.get("news_category"):
            items += safe(news.fetch_market_news, settings, underlying["news_category"], underlying["keywords"], limit=8, days=days)
        for rel in underlying.get("related", [])[:3]:
            items += safe(news.fetch_us_news, settings, rel, limit=4, days=days)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.date, reverse=True):
        if it.date >= cutoff and it.url not in seen:
            seen.add(it.url)
            out.append(it)
    return out[:18]


_SYSTEM = (
    "너는 주식 초보자에게 '오늘 왜 이 종목이 움직였는지'를 설명하는 도우미다.\n"
    "규칙:\n"
    "1) 반드시 주어진 기사 안에서만 이유를 찾는다. 기사에 없는 사실을 만들지 않는다.\n"
    "2) 이 움직임을 설명할 만한 기사가 없으면 found=false 로 하고, 시장 전체 움직임으로 설명되는지만 말한다.\n"
    "3) 시장 전체도 비슷하게 움직였으면 그 점을 먼저 말한다. 단, 시장 움직임이 종목 움직임의 절반도 안 되면 "
    "시장 탓으로 설명하지 않는다.\n"
    "4) found=false 이면 reason 은 '이 움직임을 설명하는 뉴스를 찾지 못했어요.'로 시작한다.\n"
    "4-1) ETF 라서 기초자산 정보가 주어지면, 기초자산이 왜 움직였는지를 기사에서 찾고 "
    "'기초자산이 움직였고 이 ETF는 그걸 N배로 따라가서'처럼 연결해 설명한다. 이것도 기사에 근거가 있어야 found=true.\n"
    "    기초자산 등락과 ETF 등락은 기준 시각이 달라(예: 코인은 24시간, ETF 는 전일 종가 기준) 배수가 숫자로 맞지 않는다. "
    "'2배로 따라가며 -2.3%'처럼 숫자를 배수로 연결하지 않는다.\n"
    "5) 매수/매도 권유, 앞으로의 전망은 쓰지 않는다. 쉬운 한국어, 1~2문장, 정중체.\n"
    'JSON 으로만 답한다: {"found": true|false, "reason": "...", "sources": [기사 번호들], "confidence": "높음|보통|낮음"}'
)


def explain(settings: Settings, *, symbol: str, name: str, market: str, change_pct: float,
            market_change_pct: float | None, items: list[news.NewsItem],
            underlying: dict | None = None, underlying_change_pct: float | None = None) -> dict:
    """{reason, found, confidence, sources:[{title,url,source,date}], market_change_pct, underlying...}"""
    from backend import underlying as und
    proxy_label = MARKET_PROXY[market][1]
    mkt = f"{market_change_pct:+.2f}%" if market_change_pct is not None else "알 수 없음"
    base = {"market_change_pct": market_change_pct, "market_label": proxy_label,
            "underlying": ({"label": underlying["label"], "describe": und.describe(underlying),
                            "change_pct": underlying_change_pct, "note": underlying.get("note")} if underlying else None)}
    und_line = ""
    if underlying:
        uc = f"{underlying_change_pct:+.2f}%" if underlying_change_pct is not None else "알 수 없음"
        und_line = (f"이 종목은 {und.describe(underlying)}다. 같은 시간 {underlying['label']}: {uc}."
                    + (f" 참고: {underlying['note']}." if underlying.get("note") else "") + "\n")
    if not items:
        return {**base, "found": False, "confidence": "낮음", "sources": [],
                "reason": f"최근 3일 안에 이 종목 관련 뉴스를 찾지 못했어요. 같은 시간 {proxy_label}는 {mkt}예요."}
    as_source = lambda it: {"title": it.title, "url": it.url, "source": it.source, "date": it.date}
    if not settings.summary_enabled:
        return {**base, "found": False, "confidence": "낮음", "sources": [as_source(it) for it in items[:3]],
                "reason": f"OPENAI_API_KEY 가 없어 이유를 정리하지 못했어요. 최근 기사 제목을 참고하세요. 같은 시간 {proxy_label}는 {mkt}예요."}
    block = "\n".join(f"[{i}] ({it.date}, {it.source}) {it.title}\n    {it.summary[:300]}" for i, it in enumerate(items, 1))
    user = (f"종목: {name} ({symbol})\n오늘 움직임: 전일 종가 대비 {change_pct:+.2f}%\n{und_line}"
            f"같은 시간 시장 전체({proxy_label}): {mkt}\n\n최근 기사 {len(items)}건:\n{block}")
    try:
        from openai import OpenAI
        resp = OpenAI(api_key=settings.openai_api_key).chat.completions.create(
            model=settings.openai_model, temperature=0.1, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as error:
        return {**base, "found": False, "confidence": "낮음", "sources": [as_source(it) for it in items[:3]],
                "reason": f"이유 정리에 실패했어요 ({type(error).__name__}). 최근 기사 제목을 참고하세요."}
    idx = [i for i in data.get("sources", []) if isinstance(i, int) and 1 <= i <= len(items)]
    return {**base, "found": bool(data.get("found")) and bool(idx), "confidence": data.get("confidence", "낮음"),
            "reason": str(data.get("reason", "")).strip() or "이유를 정리하지 못했어요.",
            "sources": [as_source(items[i - 1]) for i in idx[:3]]}


def event(symbol: str, name: str, change_pct: float, step: int, day: str, why: dict, fmt_price: str) -> dict:
    down = change_pct < 0
    mkt = why.get("market_change_pct")
    mkt_txt = f" · {why['market_label']} {mkt:+.2f}%" if mkt is not None else ""
    return {
        "key": move_event_key(symbol, change_pct, step, day),
        "type": "move-down" if down else "move-up",
        "kind": "move",
        "symbol": symbol,
        "name": name,
        "title": f"{symbol} {change_pct:+.2f}% {'급락' if down else '급등'}{mkt_txt}",
        "body": f"{why['reason']} (현재가 {fmt_price})",
        "sources": why.get("sources", []),
        "found": why.get("found", False),
        "at_day": day,
        "created": datetime.now().isoformat(timespec="seconds"),
    }

"""종목 뉴스 수집 + LLM 요약.

- 국내: 네이버 뉴스 검색 API (종목명으로 검색)
- 미국: Finnhub company-news (yfinance 뉴스는 2026-10 기준 빈 리스트만 와서 교체)
- 요약: OpenAI. 기사별 호재/악재/중립 태그 + 3줄 요약. 키 없으면 요약 생략.
"""
from __future__ import annotations
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from backend.config import Settings


@dataclass
class NewsItem:
    title: str
    summary: str
    date: str          # YYYY-MM-DD
    source: str
    url: str
    sentiment: str = "중립"


_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


def fetch_kr_news(settings: Settings, query: str, limit: int = 15) -> list[NewsItem]:
    if not settings.naver_enabled:
        return []
    resp = httpx.get(
        "https://openapi.naver.com/v1/search/news.json",
        params={"query": query, "display": limit, "sort": "date"},
        headers={"X-Naver-Client-Id": settings.naver_client_id,
                 "X-Naver-Client-Secret": settings.naver_client_secret},
        timeout=10.0,
    )
    resp.raise_for_status()
    items = []
    for it in resp.json().get("items", []):
        link = it.get("originallink") or it.get("link", "")
        items.append(NewsItem(
            title=_clean(it.get("title", "")),
            summary=_clean(it.get("description", "")),
            date=parsedate_to_datetime(it["pubDate"]).date().isoformat(),
            source=re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", link),
            url=link,
        ))
    return items


def fetch_us_news(settings: Settings, symbol: str, limit: int = 15, days: int = 30) -> list[NewsItem]:
    if not settings.finnhub_enabled:
        return []
    today = date.today()
    resp = httpx.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": symbol, "from": (today - timedelta(days=days)).isoformat(), "to": today.isoformat()},
        headers={"X-Finnhub-Token": settings.finnhub_api_key},
        timeout=10.0,
    )
    resp.raise_for_status()
    raw = sorted(resp.json(), key=lambda it: it.get("datetime", 0), reverse=True)
    return [
        NewsItem(
            title=it["headline"],
            summary=it.get("summary", ""),
            date=datetime.fromtimestamp(it["datetime"], tz=timezone.utc).date().isoformat(),
            source=it.get("source", ""),
            url=it.get("url", ""),
        )
        for it in raw[:limit] if it.get("headline")
    ]


def fetch_market_news(settings: Settings, category: str, keywords: list[str], limit: int = 10,
                      days: int = 3) -> list[NewsItem]:
    """Finnhub 시장 뉴스(general / crypto) 중 키워드가 들어간 것만. ETF 기초자산 뉴스용."""
    if not settings.finnhub_enabled:
        return []
    resp = httpx.get("https://finnhub.io/api/v1/news", params={"category": category},
                     headers={"X-Finnhub-Token": settings.finnhub_api_key}, timeout=10.0)
    resp.raise_for_status()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    out = []
    for it in sorted(resp.json(), key=lambda x: x.get("datetime", 0), reverse=True):
        text = f"{it.get('headline', '')} {it.get('summary', '')}".lower()
        if it.get("datetime", 0) < cutoff or not any(k in text for k in keywords):
            continue
        out.append(NewsItem(title=it["headline"], summary=it.get("summary", ""),
                            date=datetime.fromtimestamp(it["datetime"], tz=timezone.utc).date().isoformat(),
                            source=it.get("source", ""), url=it.get("url", "")))
        if len(out) >= limit:
            break
    return out


_SYSTEM = (
    "너는 주식 초보자를 돕는 뉴스 정리 도우미다. 주어진 기사만 근거로 한국어로 답한다.\n"
    "원칙: 없는 사실 창작 금지. 매수/매도 권유 금지. 쉬운 말로, 전문용어는 풀어서.\n"
    "JSON 으로만 답한다: {\"lines\": [3줄 요약 문자열 3개], "
    "\"tone\": \"긍정|중립|부정\", \"sentiments\": [기사 번호 순서대로 \"호재|악재|중립\"]}"
)


def summarize(settings: Settings, name: str, items: list[NewsItem]) -> dict | None:
    if not settings.summary_enabled or not items:
        return None
    from openai import OpenAI
    block = "\n".join(f"[{i}] ({it.date}, {it.source}) {it.title}\n    {it.summary[:300]}"
                      for i, it in enumerate(items, 1))
    try:
        resp = OpenAI(api_key=settings.openai_api_key).chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": f"종목: {name}\n기사 {len(items)}건:\n{block}"}],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as error:
        return {"lines": [f"요약 실패 ({type(error).__name__})"], "tone": "중립"}
    for it, s in zip(items, data.get("sentiments", [])):
        if s in ("호재", "악재", "중립"):
            it.sentiment = s
    return {"lines": data.get("lines", [])[:3], "tone": data.get("tone", "중립")}


def get_news(settings: Settings, market: str, symbol: str, name: str) -> dict:
    items = fetch_kr_news(settings, name) if market == "KR" else fetch_us_news(settings, symbol)
    summary = summarize(settings, name, items)
    return {
        "items": [asdict(it) for it in items],
        "summary": summary,
        "source_enabled": settings.naver_enabled if market == "KR" else settings.finnhub_enabled,
        "summary_enabled": settings.summary_enabled,
    }

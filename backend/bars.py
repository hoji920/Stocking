"""봉 단위 변환. 토스 API 는 1분봉·일봉만 주므로 나머지는 여기서 묶는다.

- 분봉: time = 유닉스 초. 차트가 시각을 UTC 로 그리기 때문에, 한국 시간으로 보이도록 +9시간 해서 내보낸다
  (토스 앱처럼 미국주식도 한국 시간 축).
- 일·주·월·년봉: time = 'YYYY-MM-DD' (그 기간 첫 거래일).
"""
from __future__ import annotations
from datetime import date

KST_SHIFT = 9 * 3600

# interval → (원천, 묶는 크기(분), 원천 페이지 수)
MINUTE = {"1m": (1, 2), "3m": (3, 3), "5m": (5, 5), "15m": (15, 10), "30m": (30, 15), "60m": (60, 30)}
DAILY = {"1d": 2, "1w": 10, "1M": 25, "1y": 60}   # 일봉 페이지 수 (200일/페이지)
INTERVALS = list(MINUTE) + list(DAILY)
UNIT_WORD = {"1m": "분", "3m": "봉", "5m": "봉", "15m": "봉", "30m": "봉", "60m": "봉",
             "1d": "일", "1w": "주", "1M": "개월", "1y": "년"}


def _merge(group: list[dict], time) -> dict:
    return {
        "time": time,
        "open": group[0]["open"],
        "high": max(b["high"] for b in group),
        "low": min(b["low"] for b in group),
        "close": group[-1]["close"],
        "volume": sum(b["volume"] for b in group),
    }


def aggregate_minutes(bars: list[dict], size: int) -> list[dict]:
    """1분봉(유닉스 초) → size 분봉, 한국 시간으로 이동."""
    step = size * 60
    out: list[dict] = []
    group: list[dict] = []
    key = None
    for b in bars:
        t = b["time"] + KST_SHIFT
        k = t - t % step
        if key is not None and k != key:
            out.append(_merge(group, key))
            group = []
        key = k
        group.append(b)
    if group:
        out.append(_merge(group, key))
    return out


def _period(day: str, interval: str) -> str:
    d = date.fromisoformat(day)
    if interval == "1w":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if interval == "1M":
        return day[:7]
    if interval == "1y":
        return day[:4]
    return day


def aggregate_days(bars: list[dict], interval: str) -> list[dict]:
    """일봉 → 주/월/년봉. time 은 그 기간 첫 거래일."""
    if interval == "1d":
        return bars
    out: list[dict] = []
    group: list[dict] = []
    key = None
    for b in bars:
        k = _period(b["time"], interval)
        if key is not None and k != key:
            out.append(_merge(group, group[0]["time"]))
            group = []
        key = k
        group.append(b)
    if group:
        out.append(_merge(group, group[0]["time"]))
    return out

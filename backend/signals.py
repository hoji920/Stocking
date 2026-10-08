"""매매 신호 감지 (확정 봉 기준) + 과거 성적.

- '확정'만 다룬다: 장중인 오늘 봉은 빼고 계산 (confirmed_candles).
- 각 신호는 '그 일이 처음 일어난 날' 하나의 이벤트. 상태(과열 중 등)가 아니다.
- 과거 성적: 같은 종목에서 그 신호가 난 뒤 5·20거래일 수익률. 추천이 아니라 과거 통계.
"""
from __future__ import annotations
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend import analysis
from backend import patterns as chart_patterns

# id → (이름, 방향, 차트 글자, 설명). 방향: bull=상승 쪽 신호, bear=하락 쪽, info=방향 없음
CATALOG: dict[str, dict] = {
    "gc":          {"name": "골든크로스 (20·60일)", "dir": "bull", "short": "골든",
                    "desc": "20일 평균선이 60일 평균선을 위로 뚫었어요. 단기 흐름이 중기 흐름보다 강해졌다는 뜻이에요."},
    "dc":          {"name": "데드크로스 (20·60일)", "dir": "bear", "short": "데드",
                    "desc": "20일 평균선이 60일 평균선을 아래로 뚫었어요. 단기 흐름이 약해졌다는 뜻이에요."},
    "gc_long":     {"name": "장기 골든크로스 (50·200일)", "dir": "bull", "short": "장기골든",
                    "desc": "50일선이 200일선을 위로 뚫었어요. 미국 시장에서 가장 많이 언급되는 장기 상승 신호예요."},
    "dc_long":     {"name": "장기 데드크로스 (50·200일)", "dir": "bear", "short": "장기데드",
                    "desc": "50일선이 200일선을 아래로 뚫었어요. 장기 흐름이 꺾였다는 신호로 많이 봐요."},
    "rsi_os_exit": {"name": "RSI 과매도 탈출", "dir": "bull", "short": "RSI↑",
                    "desc": "RSI가 30 아래(과매도)에 있다가 다시 30 위로 올라왔어요. 과매도 구간을 벗어났다는 뜻이에요."},
    "rsi_ob_exit": {"name": "RSI 과열 해소", "dir": "bear", "short": "RSI↓",
                    "desc": "RSI가 70 위(과열)에 있다가 다시 70 아래로 내려왔어요. 과열 구간을 벗어났다는 뜻이에요."},
    "macd_up":     {"name": "MACD 상향 교차", "dir": "bull", "short": "MACD↑",
                    "desc": "MACD선이 시그널선을 위로 뚫었어요. 오르는 힘이 세지기 시작했다고 보는 사람이 많아요. 아주 자주 나오는 신호예요."},
    "macd_down":   {"name": "MACD 하향 교차", "dir": "bear", "short": "MACD↓",
                    "desc": "MACD선이 시그널선을 아래로 뚫었어요. 오르는 힘이 약해지기 시작했다고 보는 사람이 많아요. 아주 자주 나오는 신호예요."},
    "high52":      {"name": "52주 신고가", "dir": "bull", "short": "신고가",
                    "desc": "종가가 최근 1년 중 가장 높아요. 위에 막힐 가격대(저항)가 없는 상태예요."},
    "low52":       {"name": "52주 신저가", "dir": "bear", "short": "신저가",
                    "desc": "종가가 최근 1년 중 가장 낮아요. 아래에 받쳐줄 가격대(지지)가 없는 상태예요."},
    "vol_spike":   {"name": "거래량 급증", "dir": "info", "short": "거래량",
                    "desc": "거래량이 최근 20일 평균의 2배를 넘었어요. 큰 뉴스나 큰손 매매가 있었을 수 있어요. 그날 캔들 색이 방향이에요."},
    "tl_up":       {"name": "추세선 위로 돌파", "dir": "bull", "short": "추세↑",
                    "desc": "고점들을 이은 추세선(저항)을 종가로 뚫고 올라갔어요. 하락 추세선이었다면 흐름이 바뀌는 신호로 많이 봐요."},
    "tl_down":     {"name": "추세선 아래로 이탈", "dir": "bear", "short": "추세↓",
                    "desc": "저점들을 이은 추세선(지지) 아래로 종가가 내려갔어요. 상승 추세선이었다면 오르던 흐름이 깨졌다는 신호로 많이 봐요."},
    "ch_up":       {"name": "채널 천장 돌파", "dir": "bull", "short": "채널↑",
                    "desc": "평행 채널의 천장을 종가로 뚫고 올라갔어요. 평소보다 오르는 힘이 세다는 뜻이에요."},
    "ch_down":     {"name": "채널 바닥 이탈", "dir": "bear", "short": "채널↓",
                    "desc": "평행 채널의 바닥 아래로 종가가 내려갔어요. 지금까지의 통로가 깨졌다는 뜻이에요."},
}
# 차트 패턴 돌파 (backend.patterns) 도 같은 신호 틀로: 마커·과거 성적·알림
CATALOG.update({pid: {**p, "dir": "bull"} for pid, p in chart_patterns.CATALOG.items()})

DEFAULT_ALERT_TYPES = ["gc", "dc", "gc_long", "dc_long", "high52", "low52", "tl_up", "tl_down", "ch_up", "ch_down"]

_SESSION = {  # 정규장 마감 (+10분 여유) — 이 시각 전의 '오늘 봉'은 미확정
    "US": (ZoneInfo("America/New_York"), dtime(16, 10)),
    "KR": (ZoneInfo("Asia/Seoul"), dtime(15, 40)),
}
_PATTERN_LOOKBACK = 90     # 추세선·채널 이탈은 최근 이만큼만 되짚는다 (봉마다 추세선을 다시 구해서 무겁다)
_DEDUPE_BARS = 10          # 같은 신호가 이 봉 수 안에 또 나오면 첫 번째만


def market_today(market: str) -> str:
    """그 시장 기준 오늘 날짜 (미국은 뉴욕 날짜)."""
    return datetime.now(_SESSION[market][0]).date().isoformat()


def confirmed_candles(candles: list[dict], market: str, now: datetime | None = None) -> list[dict]:
    """장 마감 전이면 오늘 봉을 뺀다."""
    if not candles:
        return candles
    tz, close_at = _SESSION[market]
    now = (now or datetime.now(tz)).astimezone(tz)
    if candles[-1]["time"] == now.date().isoformat() and now.time() < close_at:
        return candles[:-1]
    return candles


def _cross_up(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift() if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift() <= b_prev)


def _cross_down(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift() if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift() >= b_prev)


def _indicator_events(df: pd.DataFrame) -> list[tuple[int, str, str]]:
    """(봉 index, 신호 id, 추가 설명)"""
    c, v = df["close"], df["volume"]
    out: list[tuple[int, str, str]] = []

    def add(mask: pd.Series, sid: str, note=lambda i: ""):
        for i in np.flatnonzero(mask.fillna(False).to_numpy()):
            out.append((int(i), sid, note(int(i))))

    s20, s60 = analysis.sma(c, 20), analysis.sma(c, 60)
    add(_cross_up(s20, s60), "gc")
    add(_cross_down(s20, s60), "dc")
    s50, s200 = analysis.sma(c, 50), analysis.sma(c, 200)
    add(_cross_up(s50, s200), "gc_long")
    add(_cross_down(s50, s200), "dc_long")

    r = analysis.rsi(c)
    add(_cross_up(r, 30.0), "rsi_os_exit")
    add(_cross_down(r, 70.0), "rsi_ob_exit")

    ema = lambda s, n: s.ewm(span=n, adjust=False).mean()
    macd = ema(c, 12) - ema(c, 26)
    sig = ema(macd, 9)
    warm = pd.Series(np.arange(len(df)) >= 35, index=df.index)   # EMA 안정화 전 교차는 버림
    add(_cross_up(macd, sig) & warm, "macd_up")
    add(_cross_down(macd, sig) & warm, "macd_down")

    prior_max = c.shift().rolling(252, min_periods=252).max()
    prior_min = c.shift().rolling(252, min_periods=252).min()
    # '처음' 신고가만: 직전 5봉 안에 신고가가 없었을 때
    new_hi, new_lo = c > prior_max, c < prior_min
    recent = lambda m: m.astype(float).shift().rolling(5, min_periods=1).max().fillna(0).astype(bool)
    add(new_hi & ~recent(new_hi), "high52")
    add(new_lo & ~recent(new_lo), "low52")

    avg_vol = v.shift().rolling(20, min_periods=20).mean()
    ratio = v / avg_vol
    add(ratio >= 2, "vol_spike",
        lambda i: f"평소의 {ratio.iloc[i]:.1f}배, {'양봉(상승 마감)' if c.iloc[i] >= df['open'].iloc[i] else '음봉(하락 마감)'}")
    return out


def _pattern_events(df: pd.DataFrame) -> list[tuple[int, str, str]]:
    """k번째 봉 종가가, k-1번째까지로 구한 추세선/채널선을 0.5% 넘게 건넜는지."""
    out: list[tuple[int, str, str]] = []
    n = len(df)
    close = df["close"].to_numpy()
    for k in range(max(60, n - _PATTERN_LOOKBACK), n):
        sub = df.iloc[:k]
        tls = analysis.find_trendlines(sub)
        if not tls:
            continue
        pat = analysis.trend_pattern(tls, float(close[k - 1]))
        squeeze = pat and "수렴" in pat["title"]
        for tl in tls:
            per_bar = tl["slope_pct"] / 100 * tl["price"]
            prev_line, line = tl["price"], tl["price"] + per_bar
            if tl["kind"] == "resistance" and close[k - 1] <= prev_line and close[k] > line * 1.005:
                out.append((k, "tl_up", "수렴 패턴을 위로 뚫었어요" if squeeze else tl["label"]))
            if tl["kind"] == "support" and close[k - 1] >= prev_line and close[k] < line * 0.995:
                out.append((k, "tl_down", "수렴 패턴을 아래로 뚫었어요" if squeeze else tl["label"]))
        ch = analysis.find_channel(sub, tls)
        if ch:
            slope = (ch["base"][1]["value"] - ch["base"][0]["value"])
            span = sub["time"].tolist().index(ch["base"][1]["time"]) - sub["time"].tolist().index(ch["base"][0]["time"])
            per_bar = slope / span if span else 0
            up_prev, lo_prev = ch["upper"], ch["lower"]
            if close[k - 1] <= up_prev and close[k] > (up_prev + per_bar) * 1.005 and ch["base_kind"] == "support":
                out.append((k, "ch_up", ch["label"]))
            if close[k - 1] >= lo_prev and close[k] < (lo_prev + per_bar) * 0.995 and ch["base_kind"] == "resistance":
                out.append((k, "ch_down", ch["label"]))
    return out


def _dedupe(events: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    last_at: dict[str, int] = {}
    kept = []
    for i, sid, note in sorted(events):
        if sid in last_at and i - last_at[sid] < _DEDUPE_BARS:
            continue
        last_at[sid] = i
        kept.append((i, sid, note))
    return kept


def _stats(df: pd.DataFrame, events: list[tuple[int, str, str]]) -> dict[str, dict]:
    close = df["close"].to_numpy()
    n = len(close)
    out: dict[str, dict] = {}
    for sid in CATALOG:
        idx = [i for i, s, _ in events if s == sid]
        res = {"count": len(idx)}
        for h in (5, 20):
            rets = [close[i + h] / close[i] - 1 for i in idx if i + h < n]
            res[f"n{h}"] = len(rets)
            res[f"avg{h}"] = round(float(np.mean(rets)) * 100, 2) if rets else None
            res[f"up{h}"] = int(sum(r > 0 for r in rets))
        out[sid] = res
    return out


def detect(candles: list[dict], market: str, now: datetime | None = None) -> dict:
    """확정 봉 기준 전체 신호 + 종류별 과거 성적."""
    conf = confirmed_candles(candles, market, now)
    if len(conf) < 70:
        return {"events": [], "stats": {}, "confirmed_through": conf[-1]["time"] if conf else None}
    df = analysis.to_frame(conf)
    events = _dedupe(_indicator_events(df) + _pattern_events(df) + chart_patterns.events(df))
    return {
        "events": [{
            "time": df["time"].iloc[i], "type": sid, "dir": CATALOG[sid]["dir"],
            "name": CATALOG[sid]["name"], "short": CATALOG[sid]["short"], "note": note,
            "up_candle": bool(df["close"].iloc[i] >= df["open"].iloc[i]),
        } for i, sid, note in events],
        "stats": _stats(df, events),
        "confirmed_through": df["time"].iloc[-1],
    }

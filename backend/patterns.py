"""차트 패턴 인식 (일봉): 이중 바닥, 역헤드앤숄더, 상승 삼각수렴, 상승 깃발형, 컵앤핸들.

원칙
- 미래 정보 없음: 봉 k 에서 쓰는 스윙 포인트는 k 시점에 이미 확정된 것만 (스윙 i 는 i + W 봉에 확정).
- 이벤트 = '돌파한 날'. 돌파일 거래량이 20일 평균의 1.5배 이상이면 '거래량 동반'.
- 이름과 해석은 사람들이 흔히 쓰는 것. 실제로 맞는지는 research/patterns_backtest.py 로 검증한 숫자를 따로 보여준다.
"""
from __future__ import annotations
import math

import numpy as np
import pandas as pd

from backend import analysis

W = 4                 # 스윙 판정 좌우 봉 수 (작을수록 잔파동까지 잡음)
MAX_AGE = 40          # 마지막 구성 포인트 이후 이 봉 수 안에 돌파해야 같은 패턴으로 봄
VOL_MULT = 1.5

CATALOG = {
    "pat_db":   {"name": "이중 바닥 (W)", "short": "쌍바닥",
                 "desc": "비슷한 가격에서 두 번 바닥을 찍고, 그 사이 고점(넥라인)을 종가로 넘었어요. 바닥권에서 하락이 멈췄다는 신호로 많이 봐요."},
    "pat_ihs":  {"name": "역헤드앤숄더", "short": "역H&S",
                 "desc": "왼쪽 어깨-머리(가장 낮은 바닥)-오른쪽 어깨 모양 뒤, 두 반등 고점을 이은 넥라인을 종가로 넘었어요. 하락 추세가 끝나는 신호로 많이 봐요."},
    "pat_asc":  {"name": "상승 삼각수렴", "short": "상승삼각",
                 "desc": "고점은 같은 가격에서 막히고 저점은 점점 높아지다가, 그 수평 저항선을 종가로 넘었어요. 매수세가 강해지는 모양으로 많이 봐요."},
    "pat_flag": {"name": "상승 깃발형", "short": "깃발",
                 "desc": "가파르게 오른(깃대) 뒤 거래량이 줄면서 살짝 내려가는 좁은 구간(깃발)을 만들고, 그 윗선을 종가로 넘었어요. 2차 상승의 시작으로 많이 봐요."},
    "pat_cup":  {"name": "컵앤핸들", "short": "컵핸들",
                 "desc": "U자 모양으로 내려갔다 올라온 컵과 짧은 조정(손잡이) 뒤, 컵 오른쪽 테두리 가격을 종가로 넘었어요. 상승이 이어지는 모양으로 많이 봐요."},
}


def evidence() -> dict[str, dict]:
    """research/patterns_backtest.py 결과(있으면)를 패턴별로: 화면에 '검증해보니' 숫자를 같이 보여주기 위해."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "research" / "results" / "patterns.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    cols = ["n", "x20", "x20_lo", "x20_hi", "win20", "x60", "x60_lo", "x60_hi", "p20_holm"]
    return {r["type"]: {c: (None if pd.isna(r.get(c)) else float(r[c])) for c in cols if c in r}
            for r in df.to_dict("records")}


# ── 스윙(지그재그) ──
def pivots(df: pd.DataFrame, w: int = W) -> list[dict]:
    """고점·저점이 번갈아 나오는 스윙 목록. 같은 종류가 연달아 나오면 더 극단적인 것만."""
    raw = sorted(analysis.swing_points(df, w), key=lambda p: (p[0], p[2] == "low"))
    out: list[dict] = []
    for i, p, t in raw:
        if out and out[-1]["t"] == t:
            if (t == "high" and p > out[-1]["p"]) or (t == "low" and p < out[-1]["p"]):
                out[-1] = {"i": i, "p": p, "t": t}
            continue
        out.append({"i": i, "p": p, "t": t})
    return out


class _Ctx:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.o, self.h, self.l, self.c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        self.v = df["volume"].to_numpy(dtype=float)
        self.atr = analysis.atr(df).bfill().to_numpy()
        self.vavg = pd.Series(self.v).shift().rolling(20, min_periods=10).mean().to_numpy()
        self.piv = pivots(df)
        self.n = len(df)

    def known(self, k: int) -> list[dict]:
        """봉 k 시점에 확정된 스윙들."""
        return [p for p in self.piv if p["i"] + W <= k]

    def vol_ok(self, k: int) -> bool:
        a = self.vavg[k]
        return bool(a and not math.isnan(a) and self.v[k] >= VOL_MULT * a)

    def cross_up(self, k: int, level_k: float, level_prev: float) -> bool:
        return self.c[k] > level_k and self.c[k - 1] <= level_prev

    def t(self, i: int):
        return analysis._t(self.df, i)


# ── 패턴별 판정. 반환: [{type, anchors(id 용), level_at(j), lines, last_i}] (돌파 전 구조만) ──
def _double_bottoms(x: _Ctx, piv: list[dict], k: int) -> list[dict]:
    out = []
    for a, b, c in zip(piv, piv[1:], piv[2:]):
        if not (a["t"] == "low" and b["t"] == "high" and c["t"] == "low"):
            continue
        atr, avg = x.atr[c["i"]], (a["p"] + c["p"]) / 2
        if not (10 <= c["i"] - a["i"] <= 100 and k - c["i"] <= MAX_AGE):
            continue
        if abs(a["p"] - c["p"]) > max(0.03 * avg, 0.75 * atr):            # 두 바닥이 비슷
            continue
        if b["p"] - max(a["p"], c["p"]) < max(0.05 * avg, 2 * atr):        # 가운데 반등이 충분
            continue
        if x.h[max(0, a["i"] - 40): a["i"]].max(initial=0) < a["p"] + 3 * x.atr[a["i"]]:   # 앞에 하락이 있었어야 '바닥'
            continue
        if x.l[c["i"] + 1: k].min(initial=np.inf) < min(a["p"], c["p"]) - 0.5 * atr:      # 두 번째 바닥 뒤에 더 빠지면 무효
            continue
        neck = b["p"]
        out.append({"type": "pat_db", "anchors": (a["i"], c["i"]), "level_at": lambda j, v=neck: v, "last_i": c["i"],
                    "lines": [("모양", [(a["i"], a["p"]), (b["i"], b["p"]), (c["i"], c["p"])]), ("넥라인", [(b["i"], neck)])]})
    return out


def _inv_head_shoulders(x: _Ctx, piv: list[dict], k: int) -> list[dict]:
    out = []
    for s in range(len(piv) - 4):
        l1, h1, l2, h2, l3 = piv[s: s + 5]
        if [p["t"] for p in (l1, h1, l2, h2, l3)] != ["low", "high", "low", "high", "low"]:
            continue
        atr, avg = x.atr[l3["i"]], (l1["p"] + l3["p"]) / 2
        if not (15 <= l3["i"] - l1["i"] <= 150 and k - l3["i"] <= MAX_AGE):
            continue
        if not (l2["p"] < l1["p"] - 0.5 * atr and l2["p"] < l3["p"] - 0.5 * atr):    # 머리가 가장 낮음
            continue
        if abs(l1["p"] - l3["p"]) > max(0.05 * avg, 1.5 * atr):                      # 어깨 높이 비슷
            continue
        ratio = (l2["i"] - l1["i"]) / max(l3["i"] - l2["i"], 1)
        if not 0.4 <= ratio <= 2.5:                                                  # 좌우 대칭 비슷
            continue
        if abs(h2["p"] - h1["p"]) > 0.08 * avg:                                      # 넥라인이 너무 기울면 제외
            continue
        if x.h[max(0, l1["i"] - 40): l1["i"]].max(initial=0) < l1["p"] + 3 * x.atr[l1["i"]]:
            continue
        slope = (h2["p"] - h1["p"]) / (h2["i"] - h1["i"])
        level = lambda j, h1=h1, slope=slope: h1["p"] + slope * (j - h1["i"])
        out.append({"type": "pat_ihs", "anchors": (l1["i"], l2["i"], l3["i"]), "level_at": level, "last_i": l3["i"],
                    "lines": [("모양", [(p["i"], p["p"]) for p in (l1, h1, l2, h2, l3)]), ("넥라인", [(h1["i"], h1["p"])], slope)]})
    return out


def _ascending_triangles(x: _Ctx, piv: list[dict], k: int) -> list[dict]:
    out = []
    recent = [p for p in piv if p["i"] >= k - 100]
    highs = [p for p in recent if p["t"] == "high"]
    for start in range(len(highs) - 1):
        hs = highs[start:]
        level = float(np.mean([p["p"] for p in hs]))
        atr = x.atr[hs[-1]["i"]]
        if any(abs(p["p"] - level) > max(0.015 * level, 0.75 * atr) for p in hs):    # 고점들이 같은 가격대
            continue
        lows = [p for p in recent if p["t"] == "low" and p["i"] > hs[0]["i"]]
        if len(lows) < 2 or any(b["p"] < a["p"] + 0.3 * atr for a, b in zip(lows, lows[1:])):   # 저점이 점점 높아짐
            continue
        last_i = max(hs[-1]["i"], lows[-1]["i"])
        if hs[-1]["i"] - hs[0]["i"] < 15 or k - last_i > 30:
            continue
        if level - lows[0]["p"] < 2 * atr:                                           # 삼각형이 너무 납작하면 제외
            continue
        out.append({"type": "pat_asc", "anchors": (hs[0]["i"], lows[0]["i"]), "level_at": lambda j, v=level: v,
                    "last_i": last_i,
                    "lines": [("저항선", [(hs[0]["i"], level)]), ("저점선", [(p["i"], p["p"]) for p in lows])]})
        break                                                                         # 가장 긴 것 하나
    return out


def _bull_flags(x: _Ctx, k: int) -> list[dict]:
    out = []
    for e in range(k - 21, k - 5):                     # e = 깃대 끝(깃발 시작), 깃발 = e+1 .. k-1 (최소 5봉)
        if e < 20:
            continue
        flag = slice(e + 1, k)
        if x.h[e] < x.h[e - 3: k].max():                # 깃대 끝이 그 뒤로도 최고점
            continue
        s = e - 15 + int(np.argmin(x.l[e - 15: e - 2]))   # 깃대 시작 = 직전 최저점
        pole = x.h[e] - x.l[s]
        if pole < max(0.10 * x.l[s], 4 * x.atr[e]):      # 짧은 기간에 크게 오름
            continue
        fl, fh = x.l[flag], x.h[flag]
        if fl.min() < x.h[e] - 0.5 * pole:              # 깃발이 깃대 절반 아래로 내려가면 무효
            continue
        idx = np.arange(e + 1, k)
        slope, icpt = np.polyfit(idx, fh, 1)
        if slope > 0.1 * x.atr[e]:                     # 깃발은 평평하거나 살짝 내려가야
            continue
        if x.v[flag].mean() >= x.v[s: e + 1].mean():    # 깃발 구간 거래량이 줄어야
            continue
        upper = lambda j, slope=slope, icpt=icpt: icpt + slope * j
        # 돌파 = 윗선보다 0.25 ATR 이상 위에서 마감 (깃발 안의 작은 반등이 윗선을 살짝 넘는 걸 돌파로 보지 않게)
        margin = 0.25 * x.atr[e]
        level = lambda j, upper=upper, margin=margin: upper(j) + margin
        out.append({"type": "pat_flag", "anchors": (s, e), "level_at": level, "last_i": k - 1,
                    "lines": [("깃대", [(s, x.l[s]), (e, x.h[e])]), ("깃발 윗선", [(e + 1, float(upper(e + 1)))], slope)]})
        break
    return out


def _cup_handles(x: _Ctx, piv: list[dict], k: int) -> list[dict]:
    out = []
    highs = [p for p in piv if p["t"] == "high" and p["i"] >= k - 200]
    for r2 in reversed(highs):
        if not 5 <= k - r2["i"] <= 30:                  # 손잡이 길이
            continue
        for r1 in highs:
            span = r2["i"] - r1["i"]
            if not 30 <= span <= 150 or abs(r2["p"] - r1["p"]) > 0.05 * r1["p"]:
                continue
            seg_l = x.l[r1["i"]: r2["i"] + 1]
            if x.h[r1["i"] + 1: r2["i"]].max(initial=0) > max(r1["p"], r2["p"]) * 1.01:   # 컵 안에 테두리보다 높은 봉 X
                continue
            bottom_rel = int(np.argmin(seg_l))
            bottom = float(seg_l[bottom_rel])
            depth = (r1["p"] - bottom) / r1["p"]
            if not 0.12 <= depth <= 0.40:
                continue
            if not 0.2 <= bottom_rel / span <= 0.8:     # 바닥이 가운데쯤
                continue
            lower30 = bottom + 0.3 * (r1["p"] - bottom)
            if (x.c[r1["i"]: r2["i"] + 1] <= lower30).mean() < 0.15:   # V 가 아니라 U: 바닥권에 머문 시간이 있어야
                continue
            handle_low = x.l[r2["i"] + 1: k].min(initial=np.inf)
            hd = (r2["p"] - handle_low) / (r2["p"] - bottom)
            if not 0.08 <= hd <= 0.5:                   # 손잡이는 컵 윗부분에서 짧게
                continue
            if x.h[r2["i"] + 1: k].max(initial=0) > r2["p"]:
                continue
            rim = r2["p"]
            out.append({"type": "pat_cup", "anchors": (r1["i"], r2["i"]), "level_at": lambda j, v=rim: v, "last_i": r2["i"],
                        "lines": [("컵", [(r1["i"], r1["p"]), (r1["i"] + bottom_rel, bottom), (r2["i"], r2["p"])]),
                                  ("테두리", [(r1["i"], rim)])]})
            return out
    return out


def _structures(x: _Ctx, k: int) -> list[dict]:
    known = x.known(k)
    piv = known[-14:]                                   # 최근 스윙만 (W/쌍바닥/삼각형은 길어야 100봉 안팎)
    return (_double_bottoms(x, piv, k) + _inv_head_shoulders(x, piv, k) + _ascending_triangles(x, piv, k)
            + _bull_flags(x, k) + _cup_handles(x, known, k))   # 컵은 150봉까지 → 전체 스윙에서


# ── 과거 전체: 돌파 이벤트 (신호·검증용) ──
def events(df: pd.DataFrame, start: int = 60) -> list[tuple[int, str, str]]:
    """[(돌파 봉 k, 패턴 id, 메모)]. 같은 패턴(구성 포인트가 같은)은 한 번만."""
    if len(df) < start + 5:
        return []
    x = _Ctx(df)
    seen: set = set()
    out = []
    for k in range(start, x.n):
        for s in _structures(x, k):
            key = (s["type"], s["anchors"])
            if key in seen:
                continue
            if x.cross_up(k, s["level_at"](k), s["level_at"](k - 1)):
                seen.add(key)
                out.append((k, s["type"], "거래량 동반" if x.vol_ok(k) else "거래량 부족"))
    return out


# ── 지금 차트: 형성 중이거나 최근 돌파한 패턴 (그리기용) ──
def current(df: pd.DataFrame, fmt, recent_break: int = 10) -> list[dict]:
    if len(df) < 70:
        return []
    x = _Ctx(df)
    n = x.n
    found: dict = {}
    # 최근 돌파: 지난 recent_break 봉 안에서 돌파한 구조
    for k in range(max(60, n - recent_break), n):
        for s in _structures(x, k):
            key = (s["type"], s["anchors"])
            if key not in found and x.cross_up(k, s["level_at"](k), s["level_at"](k - 1)):
                found[key] = (s, k)
    # 형성 중: 지금 기준으로 구조는 맞고 아직 돌파선 아래
    for s in _structures(x, n - 1):
        key = (s["type"], s["anchors"])
        if key not in found and x.c[-1] <= s["level_at"](n - 1):
            found[key] = (s, None)

    out = []
    for (ptype, _), (s, k) in found.items():
        end = n - 1
        lines = []
        for spec in s["lines"]:
            label, pts = spec[0], spec[1]
            if len(pts) == 1:                            # 한 점 + (기울기) → 오늘까지 연장되는 선
                i0, v0 = pts[0]
                slope = spec[2] if len(spec) > 2 else 0.0
                pts = [(i0, v0), (end, v0 + slope * (end - i0))]
            lines.append({"label": label, "points": [{"time": x.t(i), "value": round(float(v), 4)} for i, v in pts]})
        level_now = float(s["level_at"](end))
        cat = CATALOG[ptype]
        status = "돌파" if k is not None else "형성 중"
        vol = (x.vol_ok(k) if k is not None else None)
        dist = float((level_now / x.c[-1] - 1) * 100)
        why = (f"{x.t(k)}에 돌파선({fmt(level_now)})을 종가로 넘었어요. " + ("돌파한 날 거래량이 평소의 1.5배 이상이었어요." if vol
               else "돌파한 날 거래량은 평소 수준이었어요(거래량 없는 돌파는 속임수인 경우가 많다고 보는 사람이 많아요).")) \
            if k is not None else f"돌파선 {fmt(level_now)}까지 {dist:+.1f}%. 넘어설 때 거래량이 붙는지 보는 사람이 많아요."
        out.append({"id": f"{ptype}-{s['anchors'][0]}", "type": ptype, "name": cat["name"], "status": status,
                    "break_time": x.t(k) if k is not None else None, "volume_confirmed": vol,
                    "level": round(level_now, 4), "distance_pct": round(dist, 2), "why": why, "desc": cat["desc"],
                    "lines": lines, "start": x.t(min(i for spec in s["lines"] for i, _ in spec[1]))})
    out.sort(key=lambda p: (p["status"] != "돌파", p["distance_pct"]))
    return out

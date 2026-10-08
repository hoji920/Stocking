"""자동으로 그은 선이 실제로 지지/저항 역할을 했는지 검증 (walk-forward, 미래 정보 없음).

방법
- 과거 시점 t 마다, t 까지의 데이터(최근 400봉)만으로 앱과 똑같이 선을 긋는다
  (수평 지지/저항 후보, 추세선 후보, 채널 평행선).
- t 이후 20봉 안에 가격이 선에 닿으면(0.25 ATR 이내) 결과 판정:
    지켜짐(bounce): 선이 깨지기 전에 반대 방향으로 1 ATR 이상 튕김
    깨짐(break):    종가가 선 너머로 0.5 ATR 이상
  지켜진 비율 = bounce / (bounce + break)
- 대조군: 같은 시점·같은 기울기, 현재가와의 거리(ATR 단위)만 같은 종류의 선들끼리 섞은 '근거 없는 선'.
  → 기하학적 우연(1 ATR 튕김 vs 0.5 ATR 깨짐의 비대칭)으로 나오는 기본 비율을 빼고 보려는 것.

실행: python -m research.backtest_lines   (Stocking 폴더에서)
결과: research/results/*.csv, research/results/summary.md
"""
from __future__ import annotations
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import analysis  # noqa: E402

DATA = ROOT / "research" / "data"          # 토스 시세 캐시 (개인용, 커밋 금지)
OUT = ROOT / "research" / "results"

US = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V", "UNH", "XOM", "JNJ", "PG",
      "HD", "KO", "PEP", "COST", "WMT", "NFLX", "AMD", "INTC", "CSCO", "ORCL", "CRM", "ADBE", "QCOM", "BA",
      "SPY", "QQQ"]
KR = ["005930", "000660", "035420", "005380", "051910", "068270", "035720", "105560", "055550", "012330"]

LOOKBACK = 400       # 앱이 일봉 분석에 쓰는 길이와 같게
STEP = 10            # 평가 시점 간격 (봉)
HORIZON = 20         # 선에 닿기를 기다리는 기간
FOLLOW = 20          # 닿은 뒤 결과를 기다리는 기간
TOUCH, BOUNCE, BREAK = 0.25, 1.0, 0.5   # ATR 배수


def fetch_all(pages: int = 10) -> dict[str, list[dict]]:
    DATA.mkdir(parents=True, exist_ok=True)
    from backend.config import get_settings
    from backend.toss_client import TossClient
    client = None
    out = {}
    for s in US + KR:
        path = DATA / f"{s}.json"
        if path.exists() and time.time() - path.stat().st_mtime < 86400:
            out[s] = json.loads(path.read_text())
            continue
        client = client or TossClient(get_settings())
        candles = client.daily_candles(s, pages)
        path.write_text(json.dumps(candles))
        out[s] = candles
    return out


def _lines_at(sub: pd.DataFrame) -> list[dict]:
    """t 시점(=sub 마지막 봉)에 앱이 긋는 선들. value(k) = k봉 뒤 선의 값."""
    lines = []
    lv = analysis.find_levels(sub)
    for kind in ("support", "resistance"):
        for rank, l in enumerate(lv[kind], 1):
            lines.append({"type": "level", "kind": kind, "rank": rank, "stars": l["stars"],
                          "touches": l["touches"], "v0": l["price"], "slope": 0.0})
    cands = analysis.trendline_candidates(sub)
    for kind in ("support", "resistance"):
        for c in cands[kind]:
            lines.append({"type": "trend", "kind": kind, "rank": c["rank"], "stars": c["stars"],
                          "touches": c["touches"], "v0": c["price"], "slope": c["slope_pct"] / 100 * c["price"]})
    ch = analysis.find_channel(sub, cands["support"][:1] + cands["resistance"][:1])
    if ch:
        b = ch["base"]
        span = sub["time"].tolist().index(b[1]["time"]) - sub["time"].tolist().index(b[0]["time"])
        slope = (b[1]["value"] - b[0]["value"]) / span if span else 0.0
        lines.append({"type": "channel", "kind": ch["other_kind"], "rank": 1, "stars": ch["stars"],
                      "touches": 0, "v0": ch["other_price"], "slope": slope})
    return lines


def simulate(high, low, close, t: int, v0: float, slope: float, kind: str, a: float) -> str:
    """선이 t 이후에 어떻게 됐는지: no_touch / bounce / break / unresolved."""
    return simulate_at(high, low, close, t, v0, slope, kind, a)[0]


def simulate_at(high, low, close, t: int, v0: float, slope: float, kind: str, a: float) -> tuple[str, int | None]:
    """(결과, 결과가 확정된 봉 index). 깨짐이면 종가가 선을 넘어간 그 봉."""
    n = len(close)
    sign = 1 if kind == "support" else -1          # 지지선은 위로 튕겨야, 저항선은 아래로
    for k in range(1, HORIZON + 1):
        i = t + k
        if i >= n:
            return "no_touch", None
        line = v0 + slope * k
        near = low[i] <= line + TOUCH * a if sign == 1 else high[i] >= line - TOUCH * a
        if not near:
            continue
        for j in range(i, min(i + FOLLOW, n - 1) + 1):
            lj = v0 + slope * (j - t)
            if sign * (close[j] - lj) <= -BREAK * a:
                return "break", j
            if j > i and sign * ((high[j] if sign == 1 else low[j]) - lj) >= BOUNCE * a:
                return "bounce", j
        return "unresolved", None
    return "no_touch", None


def eval_symbol(args) -> list[dict]:
    symbol, candles = args
    df = analysis.to_frame(candles)
    atr_s = analysis.atr(df).to_numpy()
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    rows = []
    for t in range(300, len(df) - HORIZON - FOLLOW, STEP):
        sub = df.iloc[max(0, t - LOOKBACK + 1): t + 1].reset_index(drop=True)
        a = float(atr_s[t])
        if not a or math.isnan(a):
            continue
        for ln in _lines_at(sub):
            dist = (ln["v0"] - close[t]) / a                 # 현재가와의 거리, ATR 단위 (지지<0, 저항>0)
            if (ln["kind"] == "support" and dist >= 0) or (ln["kind"] == "resistance" and dist <= 0):
                continue
            rows.append({**ln, "symbol": symbol, "t": t, "date": df["time"].iloc[t], "atr": a, "dist": dist,
                         "outcome": simulate(high, low, close, t, ln["v0"], ln["slope"], ln["kind"], a)})
    return rows


def add_controls(real: pd.DataFrame, data: dict[str, list[dict]], seed: int = 7) -> pd.DataFrame:
    """대조군: (선 종류, 지지/저항) 안에서 거리만 무작위로 섞은 선. 시점·기울기는 그대로."""
    rng = random.Random(seed)
    arrays = {}
    for s, c in data.items():
        df = analysis.to_frame(c)
        arrays[s] = (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())
    ctrl = real.copy()
    for (typ, kind), idx in real.groupby(["type", "kind"]).groups.items():
        d = list(real.loc[idx, "dist"])
        rng.shuffle(d)
        ctrl.loc[idx, "dist"] = d
    outs = []
    for r in ctrl.itertuples():
        h, l, c = arrays[r.symbol]
        v0 = c[r.t] + r.dist * r.atr
        outs.append(simulate(h, l, c, r.t, v0, r.slope, r.kind, r.atr))
    ctrl["outcome"] = outs
    ctrl["stars"] = 0
    return ctrl


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def two_prop_p(k1: int, n1: int, k2: int, n2: int) -> float:
    if not n1 or not n2:
        return float("nan")
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan")
    z = (k1 / n1 - k2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))          # 양측 p


def rate_table(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by):
        b, k = int((g.outcome == "bounce").sum()), int((g.outcome == "break").sum())
        touched = int(g.outcome.isin(["bounce", "break", "unresolved"]).sum())
        lo, hi = wilson(b, b + k)
        rows.append({**dict(zip(by, key if isinstance(key, tuple) else (key,))),
                     "lines": len(g), "touched": touched, "bounce": b, "breaks": k,
                     "respect": b / (b + k) if b + k else float("nan"), "ci_lo": lo, "ci_hi": hi})
    return pd.DataFrame(rows)


def main() -> None:
    t0 = time.time()
    data = fetch_all()
    print(f"[data] {len(data)} 종목, 평균 {np.mean([len(v) for v in data.values()]):.0f}봉 ({time.time() - t0:.0f}s)")
    with ProcessPoolExecutor() as ex:
        parts = list(ex.map(eval_symbol, data.items()))
    real = pd.DataFrame([r for p in parts for r in p])
    print(f"[eval] 선 {len(real)}개 ({time.time() - t0:.0f}s)")
    ctrl = add_controls(real, data)
    print(f"[ctrl] 대조군 완료 ({time.time() - t0:.0f}s)")

    OUT.mkdir(parents=True, exist_ok=True)
    real.to_csv(OUT / "lines_real.csv", index=False)
    ctrl.to_csv(OUT / "lines_control.csv", index=False)

    real["group"], ctrl["group"] = "자동 선", "대조군"
    both = pd.concat([real, ctrl])
    by_type = rate_table(both, ["type", "kind", "group"])
    by_star = rate_table(real, ["type", "stars"])
    by_rank = rate_table(real, ["type", "rank"])
    by_mkt = rate_table(both.assign(market=both.symbol.str[0].str.isdigit().map({True: "KR", False: "US"})),
                        ["market", "group"])
    for name, tb in [("by_type", by_type), ("by_stars", by_star), ("by_rank", by_rank), ("by_market", by_mkt)]:
        tb.to_csv(OUT / f"{name}.csv", index=False)

    # p-value: 자동 선 vs 대조군 (선 종류·지지/저항별)
    tests = []
    for (typ, kind), g in by_type.groupby(["type", "kind"]):
        r = g[g.group == "자동 선"].iloc[0]
        c = g[g.group == "대조군"].iloc[0]
        tests.append({"type": typ, "kind": kind, "real": r.respect, "control": c.respect,
                      "diff_pp": (r.respect - c.respect) * 100, "n_real": r.bounce + r.breaks,
                      "n_ctrl": c.bounce + c.breaks,
                      "p": two_prop_p(int(r.bounce), int(r.bounce + r.breaks), int(c.bounce), int(c.bounce + c.breaks))})
    tests = pd.DataFrame(tests)
    tests.to_csv(OUT / "tests.csv", index=False)

    pct = lambda x: "-" if pd.isna(x) else f"{x * 100:.1f}%"
    lines = [f"# 자동 선 백테스트 결과\n",
             f"- 종목 {len(data)}개 (미국 {len(US)}, 국내 {len(KR)}), 평가 시점 {real[['symbol', 't']].drop_duplicates().shape[0]}개, 선 {len(real)}개",
             f"- 판정: 20봉 안에 0.25 ATR 이내로 닿으면, 이후 1 ATR 튕김(지켜짐) vs 종가 0.5 ATR 돌파(깨짐)",
             f"- 실행 {time.time() - t0:.0f}초\n",
             "## 자동 선 vs 대조군 (지켜진 비율)\n",
             "| 선 | 방향 | 자동 선 | 대조군 | 차이 | 표본(자동/대조) | p |", "|---|---|---|---|---|---|---|"]
    for r in tests.itertuples():
        lines.append(f"| {r.type} | {r.kind} | {pct(r.real)} | {pct(r.control)} | {r.diff_pp:+.1f}%p | "
                     f"{r.n_real}/{r.n_ctrl} | {r.p:.3g} |")
    lines += ["\n## 별점별 (자동 선)\n", "| 선 | 별 | 지켜진 비율 | 95% 구간 | 표본 |", "|---|---|---|---|---|"]
    for r in by_star.itertuples():
        lines.append(f"| {r.type} | {'★' * int(r.stars)} | {pct(r.respect)} | {pct(r.ci_lo)}~{pct(r.ci_hi)} | {r.bounce + r.breaks} |")
    lines += ["\n## 후보 순위별 (자동 선)\n", "| 선 | 순위 | 지켜진 비율 | 95% 구간 | 표본 |", "|---|---|---|---|---|"]
    for r in by_rank.itertuples():
        lines.append(f"| {r.type} | {r.rank} | {pct(r.respect)} | {pct(r.ci_lo)}~{pct(r.ci_hi)} | {r.bounce + r.breaks} |")
    lines += ["\n## 시장별\n", "| 시장 | 구분 | 지켜진 비율 | 표본 |", "|---|---|---|---|"]
    for r in by_mkt.itertuples():
        lines.append(f"| {r.market} | {r.group} | {pct(r.respect)} | {r.bounce + r.breaks} |")
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

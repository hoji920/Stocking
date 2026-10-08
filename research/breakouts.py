"""선이 '깨진 뒤' 그 방향으로 계속 갔나? (backtest_lines 의 2단계)

질문: 자동 선이 대조군보다 잘 깨진다면, 깨진 뒤 그 방향으로 이어지는가(추세 지속) 아니면 되돌아오는가?
- 깨짐 = 종가가 선 너머로 0.5 ATR 이상 (backtest_lines 와 같은 정의). 지지선이 깨지면 하락 방향, 저항선이 깨지면 상승 방향.
- 깨진 봉 종가에서 h봉 뒤 수익률을 '깨진 방향'으로 부호를 맞춘다 (+면 이어짐, -면 되돌림).
- 같은 깨짐을 여러 평가 시점에서 중복으로 세지 않도록 (종목, 깨진 봉, 선 종류, 방향) 당 1개만 쓴다.
- 비교 대상
    대조군 선이 깨졌을 때 (거리만 섞은 근거 없는 선)
    아무 날 (같은 종목들에서 무작위 날 진입, 같은 방향) — 시장 자체의 흐름(미국 대형주는 대체로 우상향)

실행: python -m research.breakouts   (먼저 python -m research.backtest_lines)
결과: research/results/breakouts.md, breakouts.csv
"""
from __future__ import annotations
import json
import math

import numpy as np
import pandas as pd

from research import backtest_lines as b
from backend import analysis

HORIZONS = (5, 10, 20)


def load():
    real = pd.read_csv(b.OUT / "lines_real.csv", dtype={"symbol": str, "date": str})
    ctrl = pd.read_csv(b.OUT / "lines_control.csv", dtype={"symbol": str, "date": str})
    arrays = {}
    for s in real.symbol.unique():
        df = analysis.to_frame(json.loads((b.DATA / f"{s}.json").read_text()))
        arrays[s] = (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(),
                     analysis.atr(df).to_numpy())
    return real, ctrl, arrays


def break_events(lines: pd.DataFrame, arrays) -> pd.DataFrame:
    rows = []
    for r in lines.itertuples():
        h, l, c, atr = arrays[r.symbol]
        v0 = c[r.t] + r.dist * r.atr
        outcome, j = b.simulate_at(h, l, c, r.t, v0, r.slope, r.kind, r.atr)
        if outcome != "break" or j + max(HORIZONS) >= len(c):
            continue
        direction = -1 if r.kind == "support" else 1       # 깨진 방향
        ev = {"symbol": r.symbol, "j": j, "type": r.type, "kind": r.kind, "dir": direction}
        for hz in HORIZONS:
            ret = c[j + hz] / c[j] - 1
            ev[f"r{hz}"] = direction * ret * 100                             # %, 깨진 방향 기준
            ev[f"a{hz}"] = direction * (c[j + hz] - c[j]) / atr[j]           # ATR 단위 (종목 변동성 차이 제거)
        rows.append(ev)
    df = pd.DataFrame(rows)
    return df.drop_duplicates(["symbol", "j", "type", "kind"])


def random_days(arrays, n_per_symbol: int = 400, seed: int = 11) -> pd.DataFrame:
    """아무 날 진입 기준선: 같은 방향(상승/하락)으로 들고 있었으면 얼마였나."""
    rng = np.random.default_rng(seed)
    rows = []
    for s, (h, l, c, atr) in arrays.items():
        idx = rng.integers(300, len(c) - max(HORIZONS) - 1, n_per_symbol)
        for j in idx:
            for direction, kind in ((-1, "support"), (1, "resistance")):
                ev = {"symbol": s, "j": int(j), "kind": kind, "dir": direction}
                for hz in HORIZONS:
                    ev[f"r{hz}"] = direction * (c[j + hz] / c[j] - 1) * 100
                    ev[f"a{hz}"] = direction * (c[j + hz] - c[j]) / atr[j]
                rows.append(ev)
    return pd.DataFrame(rows)


def welch_p(x: pd.Series, y: pd.Series) -> float:
    x, y = x.dropna(), y.dropna()
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    se = math.sqrt(x.var(ddof=1) / len(x) + y.var(ddof=1) / len(y))
    if se == 0:
        return float("nan")
    z = (x.mean() - y.mean()) / se
    return math.erfc(abs(z) / math.sqrt(2))


def main() -> None:
    real, ctrl, arrays = load()
    ev_real = break_events(real, arrays)
    ev_ctrl = break_events(ctrl, arrays)
    base = random_days(arrays)
    ev_real.assign(group="자동 선").to_csv(b.OUT / "breakouts.csv", index=False)

    lines = ["# 선이 깨진 뒤 그 방향으로 이어졌나\n",
             f"- 깨짐 이벤트 (중복 제거): 자동 선 {len(ev_real)}개, 대조군 {len(ev_ctrl)}개 · 아무 날 기준 {len(base)}개",
             "- 값은 '깨진 방향' 기준 수익률. +면 이어짐, -면 되돌림. 지지선 깨짐 = 하락 방향, 저항선 깨짐 = 상승 방향",
             "- 이어진 비율 = 깨진 방향으로 움직인 경우의 비율\n"]
    for hz in HORIZONS:
        lines += [f"\n## {hz}봉 뒤\n",
                  "| 선 | 깨진 방향 | 자동 선 평균 | 대조군 평균 | 아무 날 평균 | 자동−대조 p | 자동 선 이어진 비율 | 대조군 | 아무 날 | 표본 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for (typ, kind), g in ev_real.groupby(["type", "kind"]):
            c = ev_ctrl[(ev_ctrl.type == typ) & (ev_ctrl.kind == kind)]
            bs = base[base.kind == kind]
            col, acol = f"r{hz}", f"a{hz}"
            lines.append(
                f"| {typ} | {'하락(지지 깨짐)' if kind == 'support' else '상승(저항 깨짐)'} | "
                f"{g[col].mean():+.2f}% | {c[col].mean():+.2f}% | {bs[col].mean():+.2f}% | {welch_p(g[acol], c[acol]):.3g} | "
                f"{(g[col] > 0).mean() * 100:.1f}% | {(c[col] > 0).mean() * 100:.1f}% | {(bs[col] > 0).mean() * 100:.1f}% | "
                f"{len(g)}/{len(c)} |")
    # 시장별 (20봉)
    lines += ["\n## 시장별 (20봉, 모든 선 종류 합침)\n", "| 시장 | 깨진 방향 | 자동 선 | 대조군 | 아무 날 | 표본 |", "|---|---|---|---|---|---|"]
    mkt = lambda d: d.assign(m=d.symbol.str[0].str.isdigit().map({True: "KR", False: "US"}))
    er, ec, bs = mkt(ev_real), mkt(ev_ctrl), mkt(base)
    for (m, kind), g in er.groupby(["m", "kind"]):
        c = ec[(ec.m == m) & (ec.kind == kind)]
        bb = bs[(bs.m == m) & (bs.kind == kind)]
        lines.append(f"| {m} | {'하락' if kind == 'support' else '상승'} | {g.r20.mean():+.2f}% | {c.r20.mean():+.2f}% | "
                     f"{bb.r20.mean():+.2f}% | {len(g)}/{len(c)} |")
    (b.OUT / "breakouts.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

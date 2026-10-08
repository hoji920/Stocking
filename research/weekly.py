"""주봉으로 그은 선은 일봉으로 그은 선보다 잘 지켜지나?

- 시점 t 마다 t 까지의 일봉 1000개(약 4년)를 주봉(~200개)으로 묶어 앱과 같은 알고리즘으로 선을 긋는다.
- 선을 일봉 축으로 옮겨(기울기는 주봉 1개 = 일봉 5개로 환산) backtest_lines 와 같은 기준으로 판정.
- 비교: 같은 시점 범위의 일봉 선(lines_real.csv), 그리고 각각의 대조군(거리만 섞은 선).
- 주봉 선은 현재가에서 먼 경우가 많아 기다리는 기간 20봉 / 60봉 두 가지로 본다.

실행: python -m research.weekly   (먼저 python -m research.backtest_lines)
결과: research/results/weekly.md
"""
from __future__ import annotations
import math
import random
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from research import backtest_lines as b
from backend import analysis, bars

DAILY_LOOKBACK = 1000
DAYS_PER_WEEK = 5
HORIZONS = (20, 60)


def _weekly_lines(sub_daily: pd.DataFrame) -> list[dict]:
    """일봉 sub(마지막 봉 = t) → 주봉으로 그은 선들. v0 = t 시점 값, slope = 일봉 1개당."""
    wk = analysis.to_frame(bars.aggregate_days(sub_daily.to_dict("records"), "1w"))
    if len(wk) < 70:
        return []
    # 마지막 주봉의 시각 = 이번 주 첫 거래일. 그날부터 t 까지 일봉 몇 개 지났나 (선 값을 t 로 옮기기 위해)
    k0 = len(sub_daily) - 1 - sub_daily["time"].tolist().index(wk["time"].iloc[-1])
    lines = []
    lv = analysis.find_levels(wk)
    for kind in ("support", "resistance"):
        for rank, l in enumerate(lv[kind], 1):
            lines.append({"type": "level", "kind": kind, "rank": rank, "touches": l["touches"],
                          "v0": l["price"], "slope": 0.0})
    cands = analysis.trendline_candidates(wk)
    for kind in ("support", "resistance"):
        for c in cands[kind]:
            per_day = c["slope_pct"] / 100 * c["price"] / DAYS_PER_WEEK
            lines.append({"type": "trend", "kind": kind, "rank": c["rank"], "touches": c["touches"],
                          "v0": c["price"] + per_day * k0, "slope": per_day})
    ch = analysis.find_channel(wk, cands["support"][:1] + cands["resistance"][:1])
    if ch:
        base = ch["base"]
        times = wk["time"].tolist()
        span = times.index(base[1]["time"]) - times.index(base[0]["time"])
        per_day = ((base[1]["value"] - base[0]["value"]) / span if span else 0.0) / DAYS_PER_WEEK
        lines.append({"type": "channel", "kind": ch["other_kind"], "rank": 1, "touches": 0,
                      "v0": ch["other_price"] + per_day * k0, "slope": per_day})
    return lines


def eval_symbol(args) -> list[dict]:
    symbol, candles, horizon = args
    b.HORIZON = horizon                       # 하위 프로세스에서도 같은 값을 쓰도록 여기서 설정
    df = analysis.to_frame(candles)
    atr_s = analysis.atr(df).to_numpy()
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    rows = []
    for t in range(DAILY_LOOKBACK, len(df) - horizon - b.FOLLOW, b.STEP):
        a = float(atr_s[t])
        if not a or math.isnan(a):
            continue
        sub = df.iloc[t - DAILY_LOOKBACK + 1: t + 1].reset_index(drop=True)
        for ln in _weekly_lines(sub):
            dist = (ln["v0"] - close[t]) / a
            if (ln["kind"] == "support" and dist >= 0) or (ln["kind"] == "resistance" and dist <= 0):
                continue
            rows.append({**ln, "symbol": symbol, "t": t, "atr": a, "dist": dist,
                         "outcome": b.simulate(high, low, close, t, ln["v0"], ln["slope"], ln["kind"], a)})
    return rows


def controls(real: pd.DataFrame, arrays, seed: int = 7) -> pd.DataFrame:
    rng = random.Random(seed)
    ctrl = real.copy()
    for _, idx in real.groupby(["type", "kind"]).groups.items():
        d = list(real.loc[idx, "dist"])
        rng.shuffle(d)
        ctrl.loc[idx, "dist"] = d
    ctrl["outcome"] = [b.simulate(*arrays[r.symbol], r.t, arrays[r.symbol][2][r.t] + r.dist * r.atr, r.slope, r.kind, r.atr)
                       for r in ctrl.itertuples()]
    return ctrl


def resim(df: pd.DataFrame, arrays) -> pd.Series:
    return pd.Series([b.simulate(*arrays[r.symbol], r.t, arrays[r.symbol][2][r.t] + r.dist * r.atr, r.slope, r.kind, r.atr)
                      for r in df.itertuples()], index=df.index)


def stat(s: pd.Series) -> tuple[float, int, int]:
    bn, br = int((s == "bounce").sum()), int((s == "break").sum())
    touched = int(s.isin(["bounce", "break", "unresolved"]).sum())
    return (bn / (bn + br) if bn + br else float("nan"), bn + br, touched)


def main() -> None:
    data = b.fetch_all()
    arrays = {}
    for s, c in data.items():
        df = analysis.to_frame(c)
        arrays[s] = (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())

    daily = pd.read_csv(b.OUT / "lines_real.csv", dtype={"symbol": str, "date": str})
    daily = daily[daily.t >= DAILY_LOOKBACK]          # 같은 시점 범위로 맞춤
    daily_ctrl = controls(daily, arrays, seed=3)

    out = ["# 주봉으로 그은 선 vs 일봉으로 그은 선\n",
           f"- 같은 시점 범위(일봉 {DAILY_LOOKBACK}번째 이후), 같은 판정 기준(닿음 0.25 / 튕김 1.0 / 깨짐 0.5 ATR, 일봉 기준)",
           "- 대조군: 각 선마다 같은 시점·기울기에 현재가와의 거리만 섞은 선\n"]
    for horizon in HORIZONS:
        b.HORIZON = horizon
        with ProcessPoolExecutor() as ex:
            parts = list(ex.map(eval_symbol, [(s, c, horizon) for s, c in data.items()]))
        weekly = pd.DataFrame([r for p in parts for r in p])
        weekly_ctrl = controls(weekly, arrays, seed=5)
        d_out, dc_out = resim(daily, arrays), resim(daily_ctrl, arrays)
        weekly.to_csv(b.OUT / f"lines_weekly_h{horizon}.csv", index=False)

        out += [f"\n## 선에 닿기를 {horizon}봉까지 기다릴 때\n",
                "| 선 | 방향 | 주봉 선 | 주봉 대조군 | 차이 (p) | 일봉 선 | 일봉 대조군 | 차이 (p) | 표본 주봉/일봉 | 닿은 비율 주봉/일봉 |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for (typ, kind), idx in weekly.groupby(["type", "kind"]).groups.items():
            w, wc = stat(weekly.loc[idx, "outcome"]), stat(weekly_ctrl.loc[idx, "outcome"])
            didx = daily[(daily.type == typ) & (daily.kind == kind)].index
            d, dc = stat(d_out[didx]), stat(dc_out[didx])
            pw = b.two_prop_p(round(w[0] * w[1]), w[1], round(wc[0] * wc[1]), wc[1])
            pd_ = b.two_prop_p(round(d[0] * d[1]), d[1], round(dc[0] * dc[1]), dc[1])
            out.append(
                f"| {typ} | {kind} | {w[0] * 100:.1f}% | {wc[0] * 100:.1f}% | {(w[0] - wc[0]) * 100:+.1f}%p ({pw:.2g}) | "
                f"{d[0] * 100:.1f}% | {dc[0] * 100:.1f}% | {(d[0] - dc[0]) * 100:+.1f}%p ({pd_:.2g}) | {w[1]}/{d[1]} | "
                f"{w[2] / len(idx) * 100:.0f}%/{d[2] / max(len(didx), 1) * 100:.0f}% |")
        print(f"[h={horizon}] 주봉 선 {len(weekly)}개")
    (b.OUT / "weekly.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

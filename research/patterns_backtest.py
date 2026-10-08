"""차트 패턴(이중 바닥·역헤드앤숄더·상승 삼각수렴·상승 깃발형·컵앤핸들) 돌파 후 실제로 더 올랐나?

- 종목: 탐색 40 + 확증 40 = 80 (research.backtest_lines.US/KR + research.confirm.HOLDOUT), 약 8년 일봉
- 이벤트: backend.patterns.events (봉 k 까지의 데이터만 사용, 돌파한 날)
- 수익: 돌파일 종가 → h봉 뒤 종가. '초과수익' = 그 수익 − 그 종목의 같은 h봉 평균 수익 (원래 많이 오른 종목 효과 제거)
- 대조군: ① 아무 날(=0 기준) ② 단순 돌파: 직전 20일 최고가를 처음 넘은 날 (패턴 모양 없이 '돌파'만)
- 유의성: 월 묶음 부트스트랩 2000회 + Holm 보정 (주 가설: 패턴 5개 × 20봉 초과수익 > 0)

실행: python -m research.patterns_backtest
결과: research/results/patterns.md
"""
from __future__ import annotations
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from backend import analysis, patterns
from research import backtest_lines as b
from research import confirm, methods

HORIZONS = (5, 10, 20, 60)
N_BOOT = 2000


def load_all() -> dict[str, list[dict]]:
    data = b.fetch_all()
    data.update(confirm.fetch(confirm.HOLDOUT))
    return data


def symbol_events(args) -> tuple[list[dict], dict]:
    symbol, candles = args
    df = analysis.to_frame(candles)
    c, h = df["close"].to_numpy(), df["high"].to_numpy()
    n = len(c)
    fwd = {hz: np.full(n, np.nan) for hz in HORIZONS}
    for hz in HORIZONS:
        fwd[hz][: n - hz] = (c[hz:] / c[:-hz] - 1) * 100
    base = {hz: float(np.nanmean(fwd[hz][60:])) for hz in HORIZONS}            # 그 종목 평균
    base_win = {hz: float(np.nanmean(fwd[hz][60:] > 0)) for hz in HORIZONS}
    month = df["time"].str[:7].to_numpy()
    rows = []

    def add(k, kind, note, group):
        if k + max(HORIZONS) >= n:
            return
        row = {"symbol": symbol, "k": k, "month": month[k], "type": kind, "note": note, "group": group}
        for hz in HORIZONS:
            row[f"r{hz}"] = fwd[hz][k]
            row[f"x{hz}"] = fwd[hz][k] - base[hz]          # 초과수익
            row[f"w{hz}"] = float(fwd[hz][k] > 0) - base_win[hz]
        rows.append(row)

    for k, kind, note in patterns.events(df):
        add(k, kind, note, "pattern")
    # 대조군: 직전 20일 최고가를 처음(직전 5일 안에 없던) 넘은 날
    prior_hi = pd.Series(h).shift().rolling(20).max().to_numpy()
    brk = c > prior_hi
    for k in range(60, n):
        if brk[k] and not brk[k - 5: k].any():
            add(k, "plain_breakout", "", "control")
    return rows, base


def boot_mean(df: pd.DataFrame, col: str, rng) -> tuple[float, float, float, float]:
    """평균, 95% 구간, 양측 p (월 묶음 부트스트랩)."""
    g = df.groupby("month")[col].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = rng.integers(0, len(g), (N_BOOT, len(g)))
    means = s[idx].sum(1) / np.maximum(n[idx].sum(1), 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(df[col].mean()), float(lo), float(hi), methods._boot_p(means)


def boot_diff(a: pd.DataFrame, c: pd.DataFrame, col: str, rng) -> tuple[float, float, float, float]:
    months = sorted(set(a.month) | set(c.month))
    ga = a.groupby("month")[col].agg(["sum", "count"]).reindex(months, fill_value=0)
    gc = c.groupby("month")[col].agg(["sum", "count"]).reindex(months, fill_value=0)
    idx = rng.integers(0, len(months), (N_BOOT, len(months)))
    d = (ga["sum"].to_numpy()[idx].sum(1) / np.maximum(ga["count"].to_numpy()[idx].sum(1), 1)
         - gc["sum"].to_numpy()[idx].sum(1) / np.maximum(gc["count"].to_numpy()[idx].sum(1), 1))
    lo, hi = np.percentile(d, [2.5, 97.5])
    return float(a[col].mean() - c[col].mean()), float(lo), float(hi), methods._boot_p(d)


def main() -> None:
    data = load_all()
    with ProcessPoolExecutor() as ex:
        parts = list(ex.map(symbol_events, data.items()))
    ev = pd.DataFrame([r for rows, _ in parts for r in rows])
    ev.to_csv(b.OUT / "pattern_events.csv", index=False)
    pat, ctrl = ev[ev.group == "pattern"], ev[ev.group == "control"]
    rng = np.random.default_rng(0)

    rows = []
    for kind in list(patterns.CATALOG) + ["ALL"]:
        g = pat if kind == "ALL" else pat[pat.type == kind]
        if len(g) < 20:
            continue
        r = {"type": kind, "n": len(g), "n_vol": int((g.note == "거래량 동반").sum())}
        for hz in HORIZONS:
            m, lo, hi, p = boot_mean(g, f"x{hz}", rng)
            r.update({f"x{hz}": m, f"x{hz}_lo": lo, f"x{hz}_hi": hi, f"p{hz}": p,
                      f"raw{hz}": float(g[f"r{hz}"].mean()), f"win{hz}": float((g[f"r{hz}"] > 0).mean())})
        d, dlo, dhi, dp = boot_diff(g, ctrl, "x20", rng)                 # 단순 돌파 대비
        r.update({"vs_plain": d, "vs_plain_lo": dlo, "vs_plain_hi": dhi, "vs_plain_p": dp})
        gv, gn = g[g.note == "거래량 동반"], g[g.note == "거래량 부족"]
        if len(gv) >= 10 and len(gn) >= 10:
            vd, vlo, vhi, vp = boot_diff(gv, gn, "x20", rng)
            r.update({"vol_diff": vd, "vol_lo": vlo, "vol_hi": vhi, "vol_p": vp,
                      "x20_vol": float(gv.x20.mean()), "x20_novol": float(gn.x20.mean())})
        rows.append(r)
    res = pd.DataFrame(rows)
    main_idx = res.index[res.type != "ALL"]
    res.loc[main_idx, "p20_holm"] = methods.holm(res.loc[main_idx, "p20"].tolist())
    res.loc[main_idx, "vs_plain_holm"] = methods.holm(res.loc[main_idx, "vs_plain_p"].tolist())
    if "vol_p" in res:
        ok = res.index[(res.type != "ALL") & res.vol_p.notna()]
        res.loc[ok, "vol_holm"] = methods.holm(res.loc[ok, "vol_p"].tolist())
    res.to_csv(b.OUT / "patterns.csv", index=False)

    cm = {hz: boot_mean(ctrl, f"x{hz}", rng) for hz in HORIZONS}
    name = lambda t: "패턴 전체" if t == "ALL" else patterns.CATALOG[t]["name"]
    f2 = lambda v: "-" if pd.isna(v) else f"{v:+.2f}%"
    pv = lambda v: "-" if pd.isna(v) else (f"{v:.3g}" + (" ✓" if v < 0.05 else ""))
    out = ["# 차트 패턴 돌파 후 실제로 더 올랐나\n",
           f"- {len(data)}종목(탐색 40 + 확증 40), 약 8년 일봉. 패턴 돌파 {len(pat):,}건, 단순 돌파(대조군) {len(ctrl):,}건",
           "- **초과수익** = 돌파일 종가 → h봉 뒤 수익 − 그 종목의 같은 기간 평균 수익. 0 이면 '아무 날 산 것과 같음'",
           "- 95% 구간·p: 월 묶음 부트스트랩 2000회. Holm 보정은 패턴 5개 기준. ✓ = 보정 후 p<0.05\n",
           "## ① 돌파 후 초과수익 (아무 날 대비)\n",
           "| 패턴 | 건수 (거래량 동반) | 5봉 | 10봉 | 20봉 초과수익 | 20봉 95% 구간 | Holm p | 20봉 뒤 오른 비율 | 60봉 (95% 구간) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        out.append(f"| {name(r.type)} | {r.n:,} ({r.n_vol:,}) | {f2(r.x5)} | {f2(r.x10)} | {f2(r.x20)} | "
                   f"{r.x20_lo:+.2f} ~ {r.x20_hi:+.2f} | {pv(getattr(r, 'p20_holm', np.nan))} | {r.win20 * 100:.0f}% | "
                   f"{f2(r.x60)} ({r.x60_lo:+.2f} ~ {r.x60_hi:+.2f}) |")
    out.append(f"| (대조군) 단순 20일 신고가 돌파 | {len(ctrl):,} | {f2(cm[5][0])} | {f2(cm[10][0])} | {f2(cm[20][0])} | "
               f"{cm[20][1]:+.2f} ~ {cm[20][2]:+.2f} | {pv(cm[20][3])} | {(ctrl.r20 > 0).mean() * 100:.0f}% | "
               f"{f2(cm[60][0])} ({cm[60][1]:+.2f} ~ {cm[60][2]:+.2f}) |")
    out += ["\n## ② 패턴 모양이 '그냥 돌파'보다 나은가 (20봉 초과수익 차이)\n",
            "| 패턴 | 패턴 − 단순 돌파 | 95% 구간 | Holm p |", "|---|---|---|---|"]
    for r in res[res.type != "ALL"].itertuples():
        out.append(f"| {name(r.type)} | {r.vs_plain:+.2f}%p | {r.vs_plain_lo:+.2f} ~ {r.vs_plain_hi:+.2f} | {pv(r.vs_plain_holm)} |")
    if "vol_diff" in res:
        out += ["\n## ③ 거래량 동반 돌파가 더 나은가 (20봉 초과수익)\n",
                "| 패턴 | 거래량 동반 | 거래량 부족 | 차이 | 95% 구간 | Holm p |", "|---|---|---|---|---|---|"]
        for r in res[res.type != "ALL"].itertuples():
            if pd.isna(getattr(r, "vol_diff", np.nan)):
                out.append(f"| {name(r.type)} | 표본 부족 | | | | |")
                continue
            out.append(f"| {name(r.type)} | {f2(r.x20_vol)} | {f2(r.x20_novol)} | {r.vol_diff:+.2f}%p | "
                       f"{r.vol_lo:+.2f} ~ {r.vol_hi:+.2f} | {pv(getattr(r, 'vol_holm', np.nan))} |")
    (b.OUT / "patterns.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

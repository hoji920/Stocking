"""여러 '선 긋는 방식'을 같은 틀로 비교 (지지/저항으로서 쓸모가 있나).

방식 (모두 시점 t 까지의 데이터만 사용)
- auto_level / auto_trend / auto_channel : 앱의 자동 선 (backend.analysis)
- volume_profile : 최근 120봉 거래량을 가격대(50칸)에 쌓은 뒤, 거래가 몰린 봉우리 가격
- round_minor / round_major : 딱 떨어지는 가격. 작은 단위 ≈ 가격의 2%, 큰 단위 = 작은 단위 × 5
- prior_60 / prior_252 : 직전 60봉 / 52주 최고가·최저가 (전고점·전저점)
- sma20 / sma50 / sma200 : 이동평균선 (매일 움직이는 선)
- pivot_month : 전월 고·저·종가로 계산한 P, S1, S2, R1, R2
- fib : 최근 120봉 고점·저점 사이 38.2 / 50 / 61.8% 되돌림

판정 (backtest_lines 와 동일)
- 20봉 안에 0.25 ATR 이내로 닿으면 → 이후 20봉 동안 1 ATR 튕김(지켜짐) vs 종가 0.5 ATR 돌파(깨짐)
- 깨짐이면 깨진 봉 종가에서 20봉 뒤 수익률을 깨진 방향으로 (이어짐 +)

대조군: 각 방식·방향 안에서 '현재가와의 거리(ATR)'만 섞은 선. 시점·모양(기울기, 이동평균의 움직임)은 그대로.
유의성: 월 단위 묶음 부트스트랩(같은 달은 통째로 뽑음 → 시점 겹침·같은 날 여러 종목 동시 움직임 반영) + Holm 다중비교 보정.

실행: python -m research.methods
결과: research/results/all_methods.md, methods_lines.csv
"""
from __future__ import annotations
import math
import random
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from research import backtest_lines as b
from backend import analysis

STEP, HORIZON, FOLLOW = 10, 20, 20
TOUCH, BOUNCE, BREAK = 0.25, 1.0, 0.5
FWD = 20
N_BOOT = 2000


# ── 선 만들기 (시점 t, 데이터 0..t) ──
def _nice_step(price: float) -> float:
    raw = price * 0.02
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def lines_at(df: pd.DataFrame, t: int, ctx: dict) -> list[dict]:
    """각 선: {method, kind?, v0, slope, ma}. kind 는 나중에 현재가 대비로 정한다 (위=저항, 아래=지지)."""
    close = ctx["close"]
    c = close[t]
    out: list[dict] = []
    add = lambda m, v, slope=0.0, ma=0: out.append({"method": m, "v0": float(v), "slope": float(slope), "ma": ma})

    # 앱 자동 선 (backtest_lines 와 같은 400봉)
    sub = df.iloc[max(0, t - 399): t + 1].reset_index(drop=True)
    for ln in b._lines_at(sub):
        add({"level": "auto_level", "trend": "auto_trend", "channel": "auto_channel"}[ln["type"]], ln["v0"], ln["slope"])

    # 매물대
    lo_, hi_, vol = ctx["low"][t - 119: t + 1], ctx["high"][t - 119: t + 1], ctx["volume"][t - 119: t + 1]
    edges = np.linspace(lo_.min(), hi_.max(), 51)
    prof = np.zeros(50)
    for l, h, v in zip(lo_, hi_, vol):
        a_, z_ = np.searchsorted(edges, l, "right") - 1, np.searchsorted(edges, h, "left")
        a_, z_ = max(a_, 0), min(max(z_, a_ + 1), 50)
        prof[a_:z_] += v / (z_ - a_)
    mids = (edges[:-1] + edges[1:]) / 2
    peaks = [i for i in range(1, 49) if prof[i] >= prof[i - 1] and prof[i] >= prof[i + 1] and prof[i] > prof.mean()]
    below = sorted((mids[i] for i in peaks if mids[i] < c), reverse=True)[:2]
    above = sorted(mids[i] for i in peaks if mids[i] > c)[:2]
    for v in below + above:
        add("volume_profile", v)

    # 라운드 넘버
    step = _nice_step(c)
    for m, s in (("round_minor", step), ("round_major", step * 5)):
        add(m, math.floor(c / s) * s)
        add(m, math.ceil(c / s) * s)

    # 전고점 / 전저점 (오늘 제외)
    for m, n in (("prior_60", 60), ("prior_252", 252)):
        add(m, ctx["high"][t - n: t].max())
        add(m, ctx["low"][t - n: t].min())

    # 이동평균선
    for n in (20, 50, 200):
        v = ctx[f"sma{n}"][t]
        if not math.isnan(v):
            add(f"sma{n}", v, ma=n)

    # 월 피벗 (지난달)
    month = ctx["month"][t]
    prev = ctx["month_hlc"].get(ctx["prev_month"].get(month))
    if prev:
        H, L, C = prev
        P = (H + L + C) / 3
        for v in (P, 2 * P - L, 2 * P - H, P + (H - L), P - (H - L)):
            add("pivot_month", v)

    # 피보나치 되돌림 (최근 120봉)
    H, L = ctx["high"][t - 119: t + 1].max(), ctx["low"][t - 119: t + 1].min()
    for r in (0.382, 0.5, 0.618):
        add("fib", L + (H - L) * r)
    return out


def line_value(ln: dict, ctx: dict, t: int, k: int) -> float:
    if ln["ma"]:
        return ctx[f"sma{ln['ma']}"][t + k] + (ln["v0"] - ctx[f"sma{ln['ma']}"][t])
    return ln["v0"] + ln["slope"] * k


def simulate(ctx: dict, t: int, ln: dict, kind: str, a: float) -> tuple[str, int | None]:
    high, low, close = ctx["high"], ctx["low"], ctx["close"]
    n = len(close)
    sign = 1 if kind == "support" else -1
    for k in range(1, HORIZON + 1):
        i = t + k
        if i >= n:
            return "no_touch", None
        line = line_value(ln, ctx, t, k)
        if not (low[i] <= line + TOUCH * a if sign == 1 else high[i] >= line - TOUCH * a):
            continue
        for j in range(i, min(i + FOLLOW, n - 1) + 1):
            lj = line_value(ln, ctx, t, j - t)
            if sign * (close[j] - lj) <= -BREAK * a:
                return "break", j
            if j > i and sign * ((high[j] if sign == 1 else low[j]) - lj) >= BOUNCE * a:
                return "bounce", j
        return "unresolved", None
    return "no_touch", None


def make_ctx(candles: list[dict]) -> tuple[pd.DataFrame, dict]:
    df = analysis.to_frame(candles)
    ctx = {k: df[k].to_numpy() for k in ("high", "low", "close", "volume")}
    for n in (20, 50, 200):
        ctx[f"sma{n}"] = df["close"].rolling(n).mean().to_numpy()
    ctx["atr"] = analysis.atr(df).to_numpy()
    ctx["month"] = df["time"].str[:7].to_numpy()
    g = df.groupby(df["time"].str[:7])
    ctx["month_hlc"] = {m: (x["high"].max(), x["low"].min(), x["close"].iloc[-1]) for m, x in g}
    months = sorted(ctx["month_hlc"])
    ctx["prev_month"] = {m: months[i - 1] for i, m in enumerate(months) if i}
    ctx["dates"] = df["time"].to_numpy()
    return df, ctx


def outcome_row(ctx, t, ln, kind, a) -> dict:
    res, j = simulate(ctx, t, ln, kind, a)
    row = {"outcome": res, "j": j, "fwd": float("nan")}
    if res == "break" and j + FWD < len(ctx["close"]):
        d = -1 if kind == "support" else 1
        row["fwd"] = d * (ctx["close"][j + FWD] / ctx["close"][j] - 1) * 100
    return row


def eval_symbol(args) -> list[dict]:
    symbol, candles = args
    df, ctx = make_ctx(candles)
    rows = []
    for t in range(300, len(df) - HORIZON - FOLLOW - FWD, STEP):
        a = float(ctx["atr"][t])
        if not a or math.isnan(a):
            continue
        c = ctx["close"][t]
        for ln in lines_at(df, t, ctx):
            dist = (ln["v0"] - c) / a
            if abs(dist) < 1e-9:
                continue
            kind = "support" if dist < 0 else "resistance"
            rows.append({**ln, "kind": kind, "symbol": symbol, "t": t, "month": ctx["month"][t], "atr": a, "dist": dist,
                         **outcome_row(ctx, t, ln, kind, a)})
    return rows


def control_symbol(args) -> list[dict]:
    """대조군: 거리만 바꾼 같은 모양의 선."""
    symbol, candles, items = args
    _, ctx = make_ctx(candles)
    out = []
    for r in items:
        ln = {"v0": ctx["close"][r["t"]] + r["dist"] * r["atr"], "slope": r["slope"], "ma": r["ma"]}
        out.append({**r, **outcome_row(ctx, r["t"], ln, r["kind"], r["atr"])})
    return out


# ── 통계 ──
def boot_bounce(real: pd.DataFrame, ctrl: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float, float, float, float]:
    """지켜진 비율 차이 (자동−대조), 월 묶음 부트스트랩 95% 구간과 양측 p."""
    def per_month(df):
        g = df[df.outcome.isin(["bounce", "break"])].groupby("month")
        return g.apply(lambda x: pd.Series({"b": (x.outcome == "bounce").sum(), "n": len(x)}))
    pr, pc = per_month(real), per_month(ctrl)
    months = sorted(set(pr.index) | set(pc.index))
    pr, pc = pr.reindex(months, fill_value=0), pc.reindex(months, fill_value=0)
    rb, rn, cb, cn = pr.b.to_numpy(), pr.n.to_numpy(), pc.b.to_numpy(), pc.n.to_numpy()
    obs_r, obs_c = rb.sum() / rn.sum(), cb.sum() / cn.sum()
    idx = rng.integers(0, len(months), (N_BOOT, len(months)))
    diffs = rb[idx].sum(1) / np.maximum(rn[idx].sum(1), 1) - cb[idx].sum(1) / np.maximum(cn[idx].sum(1), 1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return obs_r, obs_c, lo, hi, _boot_p(diffs)


def boot_fwd(real: pd.DataFrame, ctrl: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float, float, float, float]:
    """깨진 뒤 20봉 수익률(깨진 방향) 평균 차이."""
    def dedup(df):
        return df[df.outcome == "break"].dropna(subset=["fwd"]).drop_duplicates(["symbol", "j", "kind"])
    r, c = dedup(real), dedup(ctrl)
    months = sorted(set(r.month) | set(c.month))
    agg = lambda df: df.groupby("month").fwd.agg(["sum", "count"]).reindex(months, fill_value=0)
    ar, ac = agg(r), agg(c)
    rs, rn, cs, cn = ar["sum"].to_numpy(), ar["count"].to_numpy(), ac["sum"].to_numpy(), ac["count"].to_numpy()
    idx = rng.integers(0, len(months), (N_BOOT, len(months)))
    diffs = rs[idx].sum(1) / np.maximum(rn[idx].sum(1), 1) - cs[idx].sum(1) / np.maximum(cn[idx].sum(1), 1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return r.fwd.mean(), c.fwd.mean(), lo, hi, _boot_p(diffs), len(r), len(c)


def _boot_p(diffs: np.ndarray) -> float:
    """양측 부트스트랩 p. 2000번 중 한 번도 반대쪽이 안 나오면 0 이 아니라 '1/2000 미만' → 하한 1/N."""
    return min(1.0, max(2 * min((diffs <= 0).mean(), (diffs >= 0).mean()), 1 / len(diffs)))


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj = [0.0] * len(ps)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def main() -> None:
    data = b.fetch_all()
    with ProcessPoolExecutor() as ex:
        parts = list(ex.map(eval_symbol, data.items()))
    real = pd.DataFrame([r for p in parts for r in p])
    print(f"[real] 선 {len(real)}개")

    # 대조군: (방식, 방향) 안에서 거리 섞기
    rnd = random.Random(7)
    ctrl_dist = real["dist"].copy()
    for _, idx in real.groupby(["method", "kind"]).groups.items():
        d = list(real.loc[idx, "dist"])
        rnd.shuffle(d)
        ctrl_dist.loc[idx] = d
    shuffled = real.assign(dist=ctrl_dist)
    jobs = [(s, data[s], g.drop(columns=["outcome", "j", "fwd"]).to_dict("records")) for s, g in shuffled.groupby("symbol")]
    with ProcessPoolExecutor() as ex:
        cparts = list(ex.map(control_symbol, jobs))
    ctrl = pd.DataFrame([r for p in cparts for r in p])
    print(f"[ctrl] 선 {len(ctrl)}개")
    real.to_csv(b.OUT / "methods_lines.csv", index=False)

    rng = np.random.default_rng(0)
    rows = []
    for (m, kind), g in real.groupby(["method", "kind"]):
        c = ctrl[(ctrl.method == m) & (ctrl.kind == kind)]
        n_res = int(g.outcome.isin(["bounce", "break"]).sum())
        if n_res < 100:
            continue
        rr, cr, lo, hi, p = boot_bounce(g, c, rng)
        fr, fc, flo, fhi, fp, fn, fcn = boot_fwd(g, c, rng)
        touch = g.outcome.isin(["bounce", "break", "unresolved"]).mean()
        rows.append({"method": m, "kind": kind, "n": n_res, "touch": touch, "real": rr, "ctrl": cr,
                     "diff": rr - cr, "lo": lo, "hi": hi, "p": p,
                     "fwd_real": fr, "fwd_ctrl": fc, "fwd_diff": fr - fc, "flo": flo, "fhi": fhi, "fp": fp, "fn": fn})
    res = pd.DataFrame(rows)
    res["p_holm"] = holm(res.p.tolist())
    res["fp_holm"] = holm(res.fp.tolist())
    res = res.sort_values(["diff"], ascending=False)
    res.to_csv(b.OUT / "all_methods.csv", index=False)

    NAMES = {"auto_level": "자동 수평선", "auto_trend": "자동 추세선", "auto_channel": "자동 채널",
             "volume_profile": "매물대", "round_minor": "라운드 넘버(작은)", "round_major": "라운드 넘버(큰)",
             "prior_60": "전고점·전저점 60봉", "prior_252": "52주 고가·저가", "sma20": "20일선", "sma50": "50일선",
             "sma200": "200일선", "pivot_month": "월 피벗", "fib": "피보나치"}
    pct = lambda x: f"{x * 100:.1f}%"
    star = lambda p: " ✓" if p < 0.05 else ""
    out = ["# 선 긋는 방식 전체 비교\n",
           f"- 40종목(미국 30, 국내 10) 약 8년 일봉, 평가 시점 10봉 간격, 선 {len(real):,}개",
           "- **지켜진 비율**: 0.25 ATR 이내로 닿은 뒤 1 ATR 튕김(지켜짐) vs 종가 0.5 ATR 돌파(깨짐)",
           "- **대조군**: 같은 방식·방향 안에서 현재가와의 거리만 섞은 선 (모양은 그대로)",
           "- **95% 구간·p**: 월 단위 묶음 부트스트랩 2000회. **Holm p**: 비교 개수만큼 보정한 값. ✓ = 보정 후에도 p<0.05\n",
           "## ① 닿으면 튕기나 (지켜진 비율, 자동−대조 차이 순)\n",
           "| 방식 | 방향 | 표본 | 닿은 비율 | 방식 | 대조군 | 차이 | 95% 구간 | Holm p |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        out.append(f"| {NAMES[r.method]} | {'지지' if r.kind == 'support' else '저항'} | {r.n:,} | {pct(r.touch)} | "
                   f"{pct(r.real)} | {pct(r.ctrl)} | {r.diff * 100:+.1f}%p | {r.lo * 100:+.1f} ~ {r.hi * 100:+.1f} | "
                   f"{r.p_holm:.3g}{star(r.p_holm)} |")
    out += ["\n## ② 깨지면 그 방향으로 이어지나 (깨진 뒤 20봉 수익률, 깨진 방향 기준 +=이어짐)\n",
            "| 방식 | 깨진 방향 | 깨짐 표본 | 방식 | 대조군 | 차이 | 95% 구간 | Holm p |", "|---|---|---|---|---|---|---|---|"]
    for r in res.sort_values("fwd_diff", ascending=False).itertuples():
        out.append(f"| {NAMES[r.method]} | {'아래로(지지 깨짐)' if r.kind == 'support' else '위로(저항 깨짐)'} | {r.fn:,} | "
                   f"{r.fwd_real:+.2f}% | {r.fwd_ctrl:+.2f}% | {r.fwd_diff:+.2f}%p | {r.flo:+.2f} ~ {r.fhi:+.2f} | "
                   f"{r.fp_holm:.3g}{star(r.fp_holm)} |")
    (b.OUT / "all_methods.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

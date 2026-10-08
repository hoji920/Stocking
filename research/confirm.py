"""확증 검증: methods.py 에서 '단서'로 보인 가설만, 한 번도 안 쓴 종목으로 다시 확인.

탐색(methods.py)에서 26개를 비교하다 보면 우연히 좋아 보이는 게 생긴다.
그래서 가설을 미리 3개로 정해두고, 새 종목 40개(미국)로만 검정한다 (Holm 보정은 3개 기준).

  H1  20일선 지지   : 대조군보다 잘 지켜진다 (탐색 +3.2%p)
  H2  50일선 지지   : 대조군보다 잘 지켜진다 (탐색 +2.8%p)
  H3  자동 추세선 지지 : 대조군보다 덜 지켜진다 (탐색 -3.9%p)

실행: python -m research.confirm
결과: research/results/confirm.md
"""
from __future__ import annotations
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from research import backtest_lines as b
from research import methods as m

HOLDOUT = ["IBM", "GE", "CAT", "MMM", "HON", "LMT", "RTX", "DE", "UPS", "FDX", "NKE", "SBUX", "MCD", "LOW",
           "TGT", "BKNG", "GS", "MS", "BAC", "WFC", "C", "AXP", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT",
           "DHR", "AMGN", "GILD", "CVX", "COP", "SLB", "NEE", "DUK", "SO", "T", "VZ", "CMCSA"]
HYPOTHESES = [("sma20", "support", "+", "20일선 지지가 더 잘 지켜진다"),
              ("sma50", "support", "+", "50일선 지지가 더 잘 지켜진다"),
              ("auto_trend", "support", "-", "자동 추세선 지지가 덜 지켜진다")]


def fetch(symbols: list[str], pages: int = 10) -> dict[str, list[dict]]:
    assert not set(symbols) & set(b.US + b.KR), "확증 종목이 탐색 종목과 겹치면 안 된다"
    b.DATA.mkdir(parents=True, exist_ok=True)
    from backend.config import get_settings
    from backend.toss_client import TossClient
    client, out = None, {}
    for s in symbols:
        path = b.DATA / f"{s}.json"
        if path.exists() and time.time() - path.stat().st_mtime < 86400:
            out[s] = json.loads(path.read_text())
            continue
        client = client or TossClient(get_settings())
        out[s] = client.daily_candles(s, pages)
        path.write_text(json.dumps(out[s]))
    return out


def main() -> None:
    data = fetch(HOLDOUT)
    with ProcessPoolExecutor() as ex:
        parts = list(ex.map(m.eval_symbol, data.items()))
    real = pd.DataFrame([r for p in parts for r in p])
    real = real[real.method.isin({h[0] for h in HYPOTHESES})].reset_index(drop=True)

    rnd = random.Random(7)
    dist = real["dist"].copy()
    for _, idx in real.groupby(["method", "kind"]).groups.items():
        d = list(real.loc[idx, "dist"])
        rnd.shuffle(d)
        dist.loc[idx] = d
    jobs = [(s, data[s], g.drop(columns=["outcome", "j", "fwd"]).to_dict("records"))
            for s, g in real.assign(dist=dist).groupby("symbol")]
    with ProcessPoolExecutor() as ex:
        ctrl = pd.DataFrame([r for p in ex.map(m.control_symbol, jobs) for r in p])

    rng = np.random.default_rng(1)
    rows = []
    for method, kind, sign, text in HYPOTHESES:
        g, c = real[(real.method == method) & (real.kind == kind)], ctrl[(ctrl.method == method) & (ctrl.kind == kind)]
        rr, cr, lo, hi, p = m.boot_bounce(g, c, rng)
        rows.append({"h": text, "sign": sign, "n": int(g.outcome.isin(["bounce", "break"]).sum()),
                     "real": rr, "ctrl": cr, "diff": rr - cr, "lo": lo, "hi": hi, "p": p})
    adj = m.holm([r["p"] for r in rows])
    out = ["# 확증 검증 (탐색에 안 쓴 미국 40종목)\n",
           f"- 종목: {', '.join(HOLDOUT)}",
           "- 같은 판정 기준·대조군·월 묶음 부트스트랩 2000회. Holm 보정은 가설 3개 기준\n",
           "| 가설 | 표본 | 해당 선 | 대조군 | 차이 | 95% 구간 | Holm p | 결론 |", "|---|---|---|---|---|---|---|---|"]
    for r, pa in zip(rows, adj):
        right_way = (r["diff"] > 0) == (r["sign"] == "+")
        verdict = "확인됨" if pa < 0.05 and right_way else ("반대로 나옴" if pa < 0.05 else "확인 안 됨")
        out.append(f"| {r['h']} | {r['n']:,} | {r['real'] * 100:.1f}% | {r['ctrl'] * 100:.1f}% | {r['diff'] * 100:+.1f}%p | "
                   f"{r['lo'] * 100:+.1f} ~ {r['hi'] * 100:+.1f} | {pa:.3g} | {verdict} |")
    (b.OUT / "confirm.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

"""backtest_lines 결과가 판정 기준(ATR 배수)에 따라 달라지는지 확인.
lines_real.csv / lines_control.csv 의 선을 그대로 두고 판정만 다시 한다.

실행: python -m research.sensitivity
"""
from __future__ import annotations
import json

import pandas as pd

from research import backtest_lines as b
from backend import analysis

SETTINGS = [  # (이름, 닿음, 튕김, 깨짐)
    ("기본 0.25/1.0/0.5", 0.25, 1.0, 0.5),
    ("대칭 0.25/1.0/1.0", 0.25, 1.0, 1.0),
    ("촘촘 0.10/0.5/0.5", 0.10, 0.5, 0.5),
    ("크게 0.25/2.0/1.0", 0.25, 2.0, 1.0),
]


def resim(df: pd.DataFrame, arrays) -> pd.Series:
    out = []
    for r in df.itertuples():
        h, l, c = arrays[r.symbol]
        v0 = c[r.t] + r.dist * r.atr
        out.append(b.simulate(h, l, c, r.t, v0, r.slope, r.kind, r.atr))
    return pd.Series(out, index=df.index)


def respect(s: pd.Series) -> tuple[float, int]:
    bn, br = int((s == "bounce").sum()), int((s == "break").sum())
    return (bn / (bn + br) if bn + br else float("nan"), bn + br)


def main() -> None:
    # 국내 종목코드 앞자리 0 이 숫자로 읽히면 사라지니 문자열로
    real = pd.read_csv(b.OUT / "lines_real.csv", dtype={"symbol": str, "date": str})
    ctrl = pd.read_csv(b.OUT / "lines_control.csv", dtype={"symbol": str, "date": str})
    arrays = {}
    for s in real.symbol.unique():
        df = analysis.to_frame(json.loads((b.DATA / f"{s}.json").read_text()))
        arrays[s] = (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())

    lines = ["# 판정 기준 민감도\n", "| 기준 | 선 | 방향 | 자동 선 | 대조군 | 차이 | p |", "|---|---|---|---|---|---|---|"]
    for name, touch, bounce, brk in SETTINGS:
        b.TOUCH, b.BOUNCE, b.BREAK = touch, bounce, brk
        ro, co = resim(real, arrays), resim(ctrl, arrays)
        for (typ, kind), idx in real.groupby(["type", "kind"]).groups.items():
            cidx = ctrl[(ctrl.type == typ) & (ctrl.kind == kind)].index
            (rr, rn), (cr, cn) = respect(ro[idx]), respect(co[cidx])
            p = b.two_prop_p(round(rr * rn), rn, round(cr * cn), cn)
            lines.append(f"| {name} | {typ} | {kind} | {rr * 100:.1f}% | {cr * 100:.1f}% | {(rr - cr) * 100:+.1f}%p | {p:.3g} |")

    # 기본 기준에서: 닿은 횟수 / 거리별
    b.TOUCH, b.BOUNCE, b.BREAK = 0.25, 1.0, 0.5
    real["outcome"] = resim(real, arrays)
    real["touch_bin"] = pd.cut(real.touches, [-1, 0, 2, 3, 4, 99], labels=["0(채널)", "2", "3", "4", "5+"])
    real["dist_bin"] = pd.cut(real.dist.abs(), [0, 1, 2, 4, 8, 999], labels=["<1", "1-2", "2-4", "4-8", "8+"])
    for col, title in [("touch_bin", "닿은 횟수별 (자동 선)"), ("dist_bin", "현재가와 거리(ATR)별 (자동 선)")]:
        lines += [f"\n## {title}\n", "| 선 | 구간 | 지켜진 비율 | 표본 |", "|---|---|---|---|"]
        for (typ, binv), g in real.groupby(["type", col], observed=True):
            r, n = respect(g.outcome)
            if n:
                lines.append(f"| {typ} | {binv} | {r * 100:.1f}% | {n} |")
    (b.OUT / "sensitivity.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

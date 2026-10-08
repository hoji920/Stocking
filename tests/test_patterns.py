import numpy as np
import pandas as pd

from backend import patterns


def _frame(closes, vols=None):
    t = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    vols = vols if vols is not None else [1e6] * len(closes)
    return pd.DataFrame([{"time": t[i].date().isoformat(), "open": c, "high": c + 0.5, "low": c - 0.5,
                          "close": c, "volume": vols[i]} for i, c in enumerate(closes)])


def _seg(a, b, n):
    return list(np.linspace(a, b, n, endpoint=False))


def test_double_bottom_detected_on_neckline_break_and_not_before():
    # 하락 130→100, 반등 →112, 재하락 →100.5, 넥라인(112) 돌파 →118
    closes = [130.0] * 20 + _seg(130, 100, 40) + _seg(100, 112, 12) + _seg(112, 100.5, 12) + _seg(100.5, 118, 20) + [118] * 5
    df = _frame(closes)
    ev = [e for e in patterns.events(df) if e[1] == "pat_db"]
    assert len(ev) == 1
    k = ev[0][0]
    assert df.close[k] > 112 >= df.close[k - 1]           # 넥라인을 처음 넘은 그날
    # 미래 정보 없음: 돌파 전날까지만 잘라서 보면 돌파 이벤트가 없어야 한다
    assert not [e for e in patterns.events(df.iloc[:k]) if e[1] == "pat_db"]


def test_bull_flag_with_volume():
    # 이벤트는 60번째 봉부터 찾으니 앞에 평평한 구간을 충분히
    closes = [100.0] * 70 + _seg(100, 130, 8) + [130, 129, 128.5, 128, 127.5, 127.8, 127.2, 126.8, 126.5, 126.2] + [131, 133, 134]
    vols = [1e6] * 70 + [3e6] * 8 + [0.6e6] * 10 + [3e6, 2e6, 2e6]
    df = _frame(closes, vols)
    ev = [e for e in patterns.events(df) if e[1] == "pat_flag"]
    assert ev and ev[0][2] == "거래량 동반"


def test_current_reports_forming_pattern_with_drawable_lines():
    closes = [130.0] * 20 + _seg(130, 100, 40) + _seg(100, 112, 12) + _seg(112, 100.5, 12) + _seg(100.5, 108, 8)
    cur = patterns.current(_frame(closes), lambda p: f"{p:.2f}")
    db = [p for p in cur if p["type"] == "pat_db"]
    assert db and db[0]["status"] == "형성 중" and db[0]["distance_pct"] > 0
    assert all(len(ln["points"]) >= 2 for ln in db[0]["lines"])

// 보조지표 목록. 사용자가 "+ 지표"에서 골라 넣는다.
// overlay = 가격 차트 위에 겹침, pane = 아래 별도 칸
// calc(candles, params) → { lines: [{ label, color, data: number|null[] , type?: "histogram" }], bands?: [{ price, label }] }

const closeOf = (cs) => cs.map((c) => c.close);

function smaArr(v, n) {
  const out = Array(v.length).fill(null);
  let sum = 0;
  for (let i = 0; i < v.length; i++) {
    sum += v[i];
    if (i >= n) sum -= v[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

function emaArr(v, n) {
  const out = Array(v.length).fill(null);
  const k = 2 / (n + 1);
  let prev = null;
  for (let i = 0; i < v.length; i++) {
    if (v[i] == null) continue;
    if (prev == null) {
      // 첫 값은 앞 n개 단순평균으로 시작
      const start = v.slice(0, i + 1).filter((x) => x != null);
      if (start.length < n) continue;
      prev = start.slice(-n).reduce((a, b) => a + b, 0) / n;
    } else prev = v[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function wilder(v, n) {          // RSI·ATR 에 쓰는 Wilder 평활
  const out = Array(v.length).fill(null);
  let prev = null;
  for (let i = 1; i < v.length; i++) {
    if (i < n) continue;
    prev = prev == null ? v.slice(1, n + 1).reduce((a, b) => a + b, 0) / n : (prev * (n - 1) + v[i]) / n;
    out[i] = prev;
  }
  return out;
}

function stdArr(v, n, mean) {
  return v.map((_, i) => {
    if (mean[i] == null) return null;
    const seg = v.slice(i - n + 1, i + 1);
    return Math.sqrt(seg.reduce((a, x) => a + (x - mean[i]) ** 2, 0) / n);
  });
}

export const INDICATORS = {
  sma: {
    name: "이동평균선 (SMA)", type: "overlay", params: { period: 20 },
    desc: "최근 N일 종가의 단순 평균. 가격이 선 위에 있으면 상승 흐름, 아래면 하락 흐름으로 많이 봐요. 20일=한 달, 60일=석 달, 120일=반년.",
    calc: (cs, p) => ({ lines: [{ label: `SMA ${p.period}`, data: smaArr(closeOf(cs), p.period) }] }),
  },
  ema: {
    name: "지수이동평균 (EMA)", type: "overlay", params: { period: 20 },
    desc: "최근 가격에 더 큰 비중을 둔 평균. SMA보다 방향 전환에 빨리 반응해요.",
    calc: (cs, p) => ({ lines: [{ label: `EMA ${p.period}`, data: emaArr(closeOf(cs), p.period) }] }),
  },
  bb: {
    name: "볼린저밴드", type: "overlay", params: { period: 20, mult: 2 },
    desc: "평균선 위아래로 변동폭만큼 띠를 그려요. 가격 대부분이 띠 안에서 움직이고, 띠가 좁아지면 곧 크게 움직일 수 있다는 신호로 봐요.",
    calc: (cs, p) => {
      const c = closeOf(cs), mid = smaArr(c, p.period), sd = stdArr(c, p.period, mid);
      return { lines: [
        { label: "상단", data: mid.map((m, i) => m == null ? null : m + p.mult * sd[i]) },
        { label: "중심", data: mid, dashed: true },
        { label: "하단", data: mid.map((m, i) => m == null ? null : m - p.mult * sd[i]) },
      ] };
    },
  },
  rsi: {
    name: "RSI", type: "pane", params: { period: 14 },
    desc: "최근 오른 힘과 내린 힘의 비율(0~100). 70 이상은 단기 과열, 30 이하는 단기 과매도로 많이 봐요.",
    calc: (cs, p) => {
      const c = closeOf(cs);
      const d = c.map((x, i) => (i ? x - c[i - 1] : 0));
      const g = wilder(d.map((x) => Math.max(x, 0)), p.period);
      const l = wilder(d.map((x) => Math.max(-x, 0)), p.period);
      return { lines: [{ label: `RSI ${p.period}`, data: g.map((x, i) => x == null ? null : l[i] === 0 ? 100 : 100 - 100 / (1 + x / l[i])) }],
               bands: [{ price: 70, label: "과열" }, { price: 30, label: "과매도" }] };
    },
  },
  macd: {
    name: "MACD", type: "pane", params: { fast: 12, slow: 26, signal: 9 },
    desc: "단기 평균과 장기 평균의 차이. MACD선이 시그널선을 위로 뚫으면 상승 힘이 세지는 것으로, 아래로 뚫으면 약해지는 것으로 많이 봐요. 막대는 두 선의 차이예요.",
    calc: (cs, p) => {
      const c = closeOf(cs), f = emaArr(c, p.fast), s = emaArr(c, p.slow);
      const macd = f.map((x, i) => (x == null || s[i] == null ? null : x - s[i]));
      const sig = emaArr(macd, p.signal);
      return { lines: [
        { label: "차이", type: "histogram", data: macd.map((m, i) => (m == null || sig[i] == null ? null : m - sig[i])) },
        { label: "MACD", data: macd },
        { label: "시그널", data: sig },
      ], bands: [{ price: 0, label: "" }] };
    },
  },
  stoch: {
    name: "스토캐스틱", type: "pane", params: { k: 14, d: 3 },
    desc: "최근 N일 최고·최저 사이에서 지금 가격이 어디쯤인지(0~100). 80 이상은 고점 근처, 20 이하는 저점 근처예요.",
    calc: (cs, p) => {
      const k = cs.map((_, i) => {
        if (i < p.k - 1) return null;
        const seg = cs.slice(i - p.k + 1, i + 1);
        const hi = Math.max(...seg.map((c) => c.high)), lo = Math.min(...seg.map((c) => c.low));
        return hi === lo ? 50 : ((cs[i].close - lo) / (hi - lo)) * 100;
      });
      const valid = k.map((x) => x ?? 0);
      const dline = smaArr(valid, p.d).map((x, i) => (i < p.k + p.d - 2 ? null : x));
      return { lines: [{ label: "%K", data: k }, { label: "%D", data: dline }],
               bands: [{ price: 80, label: "" }, { price: 20, label: "" }] };
    },
  },
  atr: {
    name: "ATR (변동성)", type: "pane", params: { period: 14 },
    desc: "하루에 평균적으로 얼마나 움직이는지(가격 단위). 값이 클수록 출렁임이 큰 구간이에요. 손절 폭을 정할 때 참고하기도 해요.",
    calc: (cs, p) => {
      const tr = cs.map((c, i) => (i ? Math.max(c.high - c.low, Math.abs(c.high - cs[i - 1].close), Math.abs(c.low - cs[i - 1].close)) : c.high - c.low));
      return { lines: [{ label: `ATR ${p.period}`, data: wilder(tr, p.period) }] };
    },
  },
  obv: {
    name: "OBV (거래량 흐름)", type: "pane", params: {},
    desc: "오른 날 거래량은 더하고 내린 날 거래량은 빼서 누적해요. 가격은 그대로인데 OBV가 오르면 매수세가 쌓이는 것으로 보기도 해요.",
    calc: (cs) => {
      let acc = 0;
      return { lines: [{ label: "OBV", data: cs.map((c, i) => (acc += i ? Math.sign(c.close - cs[i - 1].close) * c.volume : 0)) }] };
    },
  },
};

export const PARAM_LABELS = { period: "기간", mult: "배수", fast: "단기", slow: "장기", signal: "시그널", k: "%K 기간", d: "%D 기간" };
// 지지(초록)·저항(주황)·상승(빨강)·하락(파랑)과 헷갈리지 않는 색만: 보라, 하늘, 라벤더, 분홍, 회색, 남색, 자주
export const PALETTE = ["#be4bdb", "#66d9e8", "#e599f7", "#f783ac", "#adb5bd", "#748ffc", "#da77f2"];

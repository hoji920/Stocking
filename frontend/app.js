import { INDICATORS, PALETTE, PARAM_LABELS } from "./indicators.js";

const LW = LightweightCharts;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (sel) => document.querySelector(sel);

// 차트에 겹쳐 그리는 분석 선들. "+ 추가" 메뉴에서 켜고 끈다. (보조지표는 indicators.js)
const LAYERS = {
  levels: { name: "지지/저항선", params: { count: 1 }, paramLabel: { count: "위아래 개수" },
    desc: "여러 번 하락이 멈춘 가격(지지)과 상승이 막힌 가격(저항). 가장 가까운 선만 진하게 보여요." },
  trend: { name: "자동 추세선", desc: "저점끼리 이은 상승 추세선, 고점끼리 이은 하락 추세선. 비스듬한 지지/저항이에요." },
  channel: { name: "추세 채널", desc: "추세선과, 그 반대편 끝에 평행하게 그은 선으로 만든 통로. 천장·바닥에서 막히거나 튕길 거라고 보는 사람이 많지만, 과거 검증에선 무작위로 그은 선과 차이가 없었어요." },
  avg: { name: "내 평단", desc: "토스 계좌에 보유 중인 종목이면 내 매수 평균가를 흰색 점선으로 보여줘요." },
  drawings: { name: "내가 그은 선", desc: "✏️/― 버튼으로 직접 그은 선. 관심종목이면 닿을 때 알림이 와요." },
  volume: { name: "거래량", desc: "그날 거래된 주식 수. 큰 움직임에 거래량이 같이 터지면 신뢰도가 높다고 봐요." },
  news: { name: "뉴스 마커", desc: "뉴스가 나온 날에 점을 찍어요. 빨강=호재, 파랑=악재, 회색=중립." },
  patterns: { name: "차트 패턴", desc: "이중 바닥·역헤드앤숄더·상승 삼각수렴·상승 깃발형·컵앤핸들 모양을 찾아 노란 선으로 그려요. 실제로 맞는지는 '차트 패턴' 탭의 검증 숫자를 같이 보세요." },
  signals: { name: "매매 신호", desc: "골든크로스·추세선 돌파·신고가 같은 신호가 난 날에 화살표를 찍어요. 장 마감 종가로 확정된 것만. 종류는 오른쪽 '매매 신호 설정'에서 골라요." },
};
// 차트에 기본으로 표시할 신호 (MACD·거래량은 자주 나와서 기본은 끔)
const DEFAULT_SIG_SHOW = ["gc", "dc", "gc_long", "dc_long", "rsi_os_exit", "rsi_ob_exit", "high52", "low52", "tl_up", "tl_down", "ch_up", "ch_down",
  "pat_db", "pat_ihs", "pat_asc", "pat_flag", "pat_cup"];
const DEFAULT_LAYERS = { levels: { count: 1 }, trend: {}, avg: {}, drawings: {}, volume: {}, patterns: {} };

const store = {
  load(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장 못 해도 동작엔 지장 없음 */ }
  },
};
const saveIndicators = () => store.save("stocking.indicators", state.indicators);
const saveLayers = () => store.save("stocking.layers.v2", state.layers);

const state = {
  data: null, news: [], watchlist: [], watchSummary: {}, drawings: [], holdings: [], tab: "holdings",
  priceLines: [], trendSeries: [], indSeries: [], panes: [],
  indicators: store.load("stocking.indicators", []),
  layers: store.load("stocking.layers.v2", DEFAULT_LAYERS),   // { 켜진 레이어: 파라미터 }
  vis: {}, focus: null,                                        // 자동 선: 보이기 덮어쓰기, 지금 고른 선
  sigShow: store.load("stocking.sigShow", DEFAULT_SIG_SHOW),   // 차트에 표시할 신호 종류 (브라우저별)
  sigCatalog: {}, sigAlert: [],                                // 알림 받을 종류는 서버 설정 (알림은 서버가 보내니까)
  drawMode: null, pending: null,
};
const on = (layer) => layer in state.layers;

// ── 차트 생성 ──
const baseOptions = () => ({
  layout: { background: { color: "transparent" }, textColor: css("--muted") },
  grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
  rightPriceScale: { borderColor: css("--line"), minimumWidth: 80 },
  timeScale: { borderColor: css("--line") },
  crosshair: { mode: LW.CrosshairMode.Normal },
  localization: { locale: "ko-KR" },
  autoSize: true,
});

const chart = LW.createChart($("#chart"), baseOptions());
const candles = chart.addCandlestickSeries({
  upColor: css("--up"), downColor: css("--down"), borderVisible: false,
  wickUpColor: css("--up"), wickDownColor: css("--down"),
  // 현재가 선: 기본(1px 촘촘한 점선)은 잘 안 보여서 굵은 긴 대시. 색은 마지막 봉 색(빨강/파랑)을 따라감
  // → 흰색 짧은 대시인 '내 평단' 선과 구분
  priceLineWidth: 2, priceLineStyle: LW.LineStyle.LargeDashed,
});
const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
candles.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } });
chart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && state.panes.forEach((p) => p.chart.timeScale().setVisibleLogicalRange(r)));
window.__app = { chart, state };   // 콘솔 디버깅용

// ── 포맷 / DOM ──
const fmtIn = (p, cur) => cur === "KRW" ? `${Math.round(p).toLocaleString("ko-KR")}원`
  : cur === "PT" ? p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })   // 지수 포인트
  : cur === "PCT" ? `${p.toFixed(3)}%`                                                                  // 금리
  : `$${p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmt = (p) => fmtIn(p, state.data?.currency);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => (k === "class" ? (node.className = v) : node.setAttribute(k, v)));
  children.forEach((c) => node.append(c));
  return node;
}

function banner(text, kind = "") {
  const b = $("#banner");
  b.hidden = !text;
  b.className = kind;
  b.textContent = text || "";
}

const toPoints = (data) => state.data.candles.map((c, i) => (data[i] == null || Number.isNaN(data[i]) ? { time: c.time } : { time: c.time, value: data[i] }));

// ── 자동으로 그은 선 (지지/저항 · 추세선 후보 · 채널) ──
// 가독성 원칙: 가격축 라벨은 현재가 + 가장 가까운 지지/저항 1개씩 + 평단 + 지금 고른 선만.
// 나머지 선은 라벨 없이 얇고 흐리게. 이름은 범례·오른쪽 목록에서.
// (별점 신뢰도는 뺐다: 백테스트에서 별이 많은 선이 더 잘 지켜지지 않았음 — research/results/summary.md)
const faded = (hex, strong) => hex + (strong ? "" : "8c");
const kindColor = (k) => css(k === "support" ? "--support" : "--resistance");
const CHANNEL_COLOR = "#74c0fc";
const PATTERN_COLOR = "#ffd43b";

// 화면에 그릴 수 있는 자동 선 전체 목록. visible 기본값: 각 레이어의 1등만
function autoItems() {
  const d = state.data;
  if (!d) return [];
  const items = [];
  const count = state.layers.levels?.count ?? 1;
  for (const kind of ["resistance", "support"]) {
    d.levels[kind].forEach((lv, i) => items.push({
      id: `lv-${kind}-${lv.price}`, group: "level", layer: "levels", kind, rank: i + 1,
      name: kind === "support" ? "지지선" : "저항선", why: lv.why, now: lv.price, price: lv.price,
      touch_points: lv.touch_points, defaultVisible: i < count, nearest: i === 0,
    }));
  }
  for (const kind of ["resistance", "support"]) {
    (d.trend_candidates?.[kind] || []).forEach((tl) => items.push({
      id: tl.id, group: "trend", layer: "trend", kind, rank: tl.rank, name: tl.label, why: tl.why,
      now: tl.price, points: tl.points, touch_points: tl.touch_points, defaultVisible: tl.rank === 1,
    }));
  }
  if (d.channel) {
    const ch = d.channel;
    items.push({
      id: "channel", group: "channel", layer: "channel", kind: ch.base_kind, rank: 1, name: ch.label,
      why: `${ch.why}. 지금 채널 안 ${ch.position_pct.toFixed(0)}% 위치 (0%=바닥, 100%=천장)`,
      now: ch.base_kind === "support" ? ch.lower : ch.upper, channel: ch, touch_points: ch.touch_points, defaultVisible: true,
    });
  }
  return items;
}

const isVisible = (it) => on(it.layer) && (state.vis[it.id] ?? it.defaultVisible);

function renderLevels() {
  state.priceLines.forEach((l) => candles.removePriceLine(l));
  state.priceLines = [];
  if (!state.data) return;
  for (const it of autoItems().filter((x) => x.group === "level" && isVisible(x))) {
    const focused = state.focus === it.id;
    const label = focused || it.nearest;
    state.priceLines.push(candles.createPriceLine({
      price: it.price,
      // 반투명: 현재가·캔들이 선 위에서 또렷하게 보이도록 (가장 가까운 선 ~65%, 나머지 ~35%, 고른 선만 불투명)
      color: kindColor(it.kind) + (focused ? "" : it.nearest ? "a6" : "59"),
      lineWidth: focused ? 4 : it.nearest ? 3 : 1,
      lineStyle: focused || it.nearest ? LW.LineStyle.Solid : LW.LineStyle.Dashed,
      axisLabelVisible: label,
      axisLabelColor: kindColor(it.kind),          // 가격 라벨은 진하게 그대로
      axisLabelTextColor: "#111",
      title: label ? (it.kind === "support" ? "지지" : "저항") : "",
    }));
  }
  // 보유 중이면 내 평단
  const held = heldOf(state.data.symbol);
  if (held && on("avg")) state.priceLines.push(candles.createPriceLine({
    // 흰색 점선 (라이트 모드에선 글자색을 따라 검정 계열 → 배경에 묻히지 않게)
    price: held.avg_price, color: css("--text"), lineWidth: 2, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true,
    title: `내 평단 ${held.pl_rate >= 0 ? "+" : ""}${held.pl_rate.toFixed(1)}%`,
  }));
  // 내가 그은 수평선
  if (on("drawings")) state.drawings.filter((d) => d.type === "horizontal").forEach((d) => state.priceLines.push(candles.createPriceLine({
    price: d.p1.price, color: css("--accent"), lineWidth: 2, lineStyle: LW.LineStyle.Solid, axisLabelVisible: true, title: "내 선",
  })));
}

// ── 추세선 (자동 + 내가 그은 것) ──
// 내가 그은 선 → [{ label, points, now }]. 채널은 기준선 + 평행선 두 줄. (서버 analysis.drawing_values 와 같은 계산)
function drawingLines(d) {
  const times = state.data.candles.map((c) => c.time);
  if (d.type === "horizontal") return [{ label: "수평선", points: null, now: d.p1.price }];
  const i1 = times.indexOf(d.p1.time), i2 = times.indexOf(d.p2.time);
  if (i1 < 0 || i2 < 0 || i1 === i2) return [];
  const slope = (d.p2.price - d.p1.price) / (i2 - i1);
  const last = times.length - 1;
  const seg = (offset) => [{ time: times[i1], value: d.p1.price + offset }, { time: times[last], value: d.p1.price + offset + slope * (last - i1) }];
  if (d.type === "trend") return [{ label: "추세선", points: seg(0), now: seg(0)[1].value }];
  const i3 = times.indexOf(d.p3?.time);
  const offset = i3 < 0 ? 0 : d.p3.price - (d.p1.price + slope * (i3 - i1));
  return [{ label: "채널 기준선", points: seg(0), now: seg(0)[1].value },
          { label: "채널 평행선", points: seg(offset), now: seg(offset)[1].value }];
}

function renderTrendlines() {
  state.trendSeries.forEach((s) => chart.removeSeries(s));
  state.trendSeries = [];
  if (!state.data) return;
  const line = (points, color, { width = 2, style = LW.LineStyle.Solid, title = "" } = {}) => {
    const s = chart.addLineSeries({ color, lineWidth: width, lineStyle: style, priceLineVisible: false,
      lastValueVisible: !!title, title, crosshairMarkerVisible: false });
    s.setData(points);
    state.trendSeries.push(s);
    return s;
  };
  const items = autoItems();
  const shownTrendIds = new Set();
  for (const it of items.filter((x) => x.group === "trend" && isVisible(x))) {
    const focused = state.focus === it.id;
    line(it.points, faded(kindColor(it.kind), focused || it.rank === 1), {
      width: focused ? 3 : it.rank === 1 ? 2 : 1, style: focused ? LW.LineStyle.Solid : LW.LineStyle.LargeDashed,
      title: focused ? it.name : "",
    });
    shownTrendIds.add(it.id);
  }
  const chItem = items.find((x) => x.group === "channel");
  if (chItem && isVisible(chItem)) {
    const ch = chItem.channel, focused = state.focus === "channel";
    const baseShown = shownTrendIds.has(`auto-${ch.base_kind}`);
    const color = baseShown ? kindColor(ch.base_kind) : CHANNEL_COLOR;
    // 기준 추세선이 이미 그려져 있으면 평행선만 같은 색 점선으로 → 어느 선의 짝인지 한눈에
    if (!baseShown) line(ch.base, color, { width: focused ? 3 : 2 });
    line(ch.other, color, { width: focused ? 3 : 2, style: LW.LineStyle.Dotted, title: focused ? "평행선" : "" });
  }
  // 차트 패턴 (노랑: 지표·지지저항 색과 안 겹침). 고른 패턴만 굵게, 아무것도 안 골랐으면 전부 보통
  if (on("patterns") && isDaily()) {
    for (const p of state.data.patterns || []) {
      if (state.patFocus && state.patFocus !== p.id) continue;
      for (const ln of p.lines) {
        const isBreak = /넥라인|저항선|테두리|윗선/.test(ln.label);
        line(ln.points, PATTERN_COLOR + (state.patFocus ? "" : "cc"), {
          width: state.patFocus ? 3 : 2, style: isBreak ? LW.LineStyle.Dashed : LW.LineStyle.Solid,
          title: isBreak && state.patFocus ? `${p.name} 돌파선` : "" });
      }
    }
  }
  // 고른 선이 실제로 닿은 지점 (근거)
  const f = items.find((x) => x.id === state.focus);
  if (f?.touch_points?.length && isVisible(f)) {
    const seen = new Set();
    const pts = f.touch_points.filter((p) => !seen.has(p.time) && seen.add(p.time))
      .sort((a, b) => (a.time < b.time ? -1 : 1));
    const dots = chart.addLineSeries({ color: f.group === "channel" ? CHANNEL_COLOR : kindColor(f.kind), lineVisible: false,
      pointMarkersVisible: true, pointMarkersRadius: 5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    dots.setData(pts);
    state.trendSeries.push(dots);
  }
  if (!on("drawings") || !isDaily()) return renderLegend();      // 비스듬한 선은 날짜로 저장돼서 일봉에서만
  state.drawings.filter((d) => d.type !== "horizontal").forEach((d) =>
    drawingLines(d).forEach((ln, i) =>
      line(ln.points, css("--accent"), { style: i ? LW.LineStyle.Dotted : LW.LineStyle.Solid })));
  renderLegend();
}

// 차트 왼쪽 위 범례: 지금 차트에 보이는 선과 보조지표 이름·값 (가격축 라벨 대신)
function renderLegend(param) {
  const box = $("#legend");
  if (!state.data) return box.replaceChildren();
  const rows = [];
  for (const it of autoItems().filter(isVisible)) {
    if (it.group === "level" && !it.nearest && state.focus !== it.id) continue;    // 범례도 핵심만
    const color = it.group === "channel" ? CHANNEL_COLOR : kindColor(it.kind);
    const row = el("span", { class: `lg${state.focus === it.id ? " on" : ""}`, title: it.why },
      el("i", { style: `background:${color}` }), `${it.name}${it.rank > 1 ? ` 후보${it.rank}` : ""} `,
      `${fmt(it.now)}`);
    row.addEventListener("click", () => setFocus(it.id));
    rows.push(row);
  }
  const seen = new Set();
  for (const e of state.indLive || []) {
    if (e.def.type !== "overlay" || seen.has(e.ind)) continue;
    seen.add(e.ind);
    const vals = state.indLive.filter((x) => x.ind === e.ind).map((x) => {
      const v = param?.seriesData?.get(x.series)?.value ?? x.series.data().at(-1)?.value;
      return v == null ? "-" : fmt(v);
    });
    rows.push(el("span", { class: "lg", title: e.def.desc },
      el("i", { style: `background:${e.ind.colors?.[0] || "var(--muted)"}` }), `${labelOf(e.ind)} `,
      el("span", { class: "v" }, vals.join(" / "))));
  }
  box.replaceChildren(...rows);
}
chart.subscribeCrosshairMove((p) => renderLegend(p.time ? p : undefined));

function setFocus(id) {
  state.focus = state.focus === id ? null : id;
  if (state.focus) state.vis[state.focus] = true;     // 고르면 보이게
  renderLevels();
  renderTrendlines();
  renderAutoLines();
}

// ── 보조지표 ──
function clearIndicators() {
  state.indSeries.forEach((s) => chart.removeSeries(s));
  state.indSeries = [];
  state.panes.forEach((p) => { p.chart.remove(); p.div.remove(); });
  state.panes = [];
  state.indLive = [];
}

// 실시간 체결로 마지막 봉이 바뀌면 지표의 마지막 값만 다시 계산해 덮어쓴다 (전체 다시 그리기 X)
let indTimer = null;
function refreshIndicatorsLive() {
  if (indTimer || !state.indLive?.length) return;
  indTimer = setTimeout(() => {                 // 체결이 몰려도 0.25초에 한 번
    indTimer = null;
    const cs = state.data.candles, i = cs.length - 1;
    const outs = new Map();
    for (const e of state.indLive) {
      if (!outs.has(e.ind)) outs.set(e.ind, e.def.calc(cs, e.ind.params));
      const v = outs.get(e.ind).lines[e.lineIdx].data[i];
      if (v == null || Number.isNaN(v)) continue;
      const pt = { time: cs[i].time, value: v };
      if (e.hist) pt.color = (v >= 0 ? css("--up") : css("--down")) + "99";
      e.series.update(pt);
    }
  }, 250);
}

function renderIndicators() {
  clearIndicators();
  renderIndicatorChips();
  if (!state.data) return;
  state.indLive = [];
  let colorIdx = 0;
  const nextColor = () => PALETTE[colorIdx++ % PALETTE.length];
  for (const ind of state.indicators) {
    const def = INDICATORS[ind.key];
    if (!def) continue;
    const out = def.calc(state.data.candles, ind.params);
    ind.colors = [];
    let target = chart;
    let first = null;
    if (def.type === "pane") {
      const div = el("div", { class: "pane" }, el("span", { class: "pane-label" }, labelOf(ind)));
      $("#panes").append(div);
      target = LW.createChart(div, { ...baseOptions(), timeScale: { borderColor: css("--line"), visible: false } });
      state.panes.push({ chart: target, div });
    }
    for (const [li, ln] of out.lines.entries()) {
      // 사용자가 고른 색(ind.color)이 있으면 첫 줄에, 볼린저밴드처럼 같은 계열 선들(상단·중심·하단)엔 전부
      const auto = nextColor();
      const color = ind.color && (li === 0 || ind.key === "bb") ? ind.color : auto;
      ind.colors.push(color);
      // 차트 위 지표는 가격축 라벨 대신 범례로 (가격축이 복잡해지지 않게)
      const common = { priceLineVisible: false, lastValueVisible: def.type === "pane", title: "" };
      const s = ln.type === "histogram"
        ? target.addHistogramSeries({ ...common })
        : target.addLineSeries({ ...common, color, lineWidth: 2, lineStyle: ln.dashed ? LW.LineStyle.Dashed : LW.LineStyle.Solid, crosshairMarkerVisible: false });
      const pts = toPoints(ln.data);
      if (ln.type === "histogram") pts.forEach((p) => p.value != null && (p.color = (p.value >= 0 ? css("--up") : css("--down")) + "99"));
      s.setData(pts);
      if (def.type === "overlay") state.indSeries.push(s);
      state.indLive.push({ ind, def, lineIdx: out.lines.indexOf(ln), series: s, hist: ln.type === "histogram" });
      first ??= s;
    }
    (out.bands || []).forEach((b) => first.createPriceLine({ price: b.price, color: css("--muted"), lineStyle: LW.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: b.label }));
  }
  const r = chart.timeScale().getVisibleLogicalRange();
  if (r) state.panes.forEach((p) => p.chart.timeScale().setVisibleLogicalRange(r));
  renderIndicatorChips();
  renderLegend();          // 범례 색·이름도 새 지표 상태로
}

// <input type=color> 는 #rrggbb 만 받는다 (#abc, 투명도 붙은 값 정리)
function toHex(c) {
  if (/^#[0-9a-f]{3}$/i.test(c)) return "#" + [...c.slice(1)].map((x) => x + x).join("");
  return /^#[0-9a-f]{6}/i.test(c) ? c.slice(0, 7) : "#be4bdb";
}

function labelOf(ind) {
  const def = INDICATORS[ind.key];
  const ps = Object.values(ind.params);
  return `${def.name.split(" (")[0]}${ps.length ? ` (${ps.join(", ")})` : ""}`;
}

// 레이어 하나 켜고/끄고 → 해당 그림만 다시
function applyLayers() {
  saveLayers();
  volume.applyOptions({ visible: on("volume") });
  renderLevels();
  renderTrendlines();
  renderMarkers();
  if (state.data) { renderSide(); renderAutoLines(); }
  renderIndicatorChips();
  buildIndicatorMenu();
}

function toggleLayer(key) {
  if (on(key)) delete state.layers[key];
  else state.layers[key] = { ...(LAYERS[key].params || {}) };
  applyLayers();
}

function layerChips() {
  return Object.keys(LAYERS).filter(on).map((key) => {
    const def = LAYERS[key];
    const inputs = Object.entries(state.layers[key]).map(([k, v]) => {
      const input = el("input", { type: "number", min: "1", max: "3", value: String(v), title: def.paramLabel?.[k] || k });
      input.addEventListener("change", () => {
        const num = Math.round(Number(input.value));
        if (num >= 1 && num <= 3) { state.layers[key][k] = num; applyLayers(); }
      });
      return input;
    });
    const x = el("span", { class: "x", title: "빼기" }, "×");
    x.addEventListener("click", () => toggleLayer(key));
    return el("span", { class: "ind-chip layer", title: def.desc }, def.name, ...inputs, x);
  });
}

function renderIndicatorChips() {
  $("#ind-chips").replaceChildren(...layerChips(), ...state.indicators.map((ind) => {
    const def = INDICATORS[ind.key];
    const inputs = Object.entries(ind.params).map(([k, v]) => {
      const input = el("input", { type: "number", min: "1", max: "250", step: k === "mult" ? "0.5" : "1", value: String(v), title: PARAM_LABELS[k] || k });
      input.addEventListener("change", () => {
        const num = Number(input.value);
        if (!(num > 0)) return;
        ind.params[k] = num;
        saveIndicators();
        renderIndicators();
      });
      return input;
    });
    const x = el("span", { class: "x", title: "빼기" }, "×");
    x.addEventListener("click", () => {
      state.indicators = state.indicators.filter((i) => i !== ind);
      saveIndicators();
      renderIndicators();
      buildIndicatorMenu();
    });
    // 색 고르기: 칩의 색 막대를 누르면 색상 선택. 고르는 동안 바로 반영, 다 고르면 저장
    const pick = el("input", { type: "color", class: "sw-pick", title: "선 색 바꾸기", value: toHex(ind.colors?.[0] || PALETTE[0]) });
    pick.addEventListener("input", () => {
      state.indLive.filter((e) => e.ind === ind && !e.hist && (e.lineIdx === 0 || ind.key === "bb"))
        .forEach((e) => e.series.applyOptions({ color: pick.value }));
    });
    pick.addEventListener("change", () => {
      ind.color = pick.value;
      saveIndicators();
      renderIndicators();
    });
    return el("span", { class: "ind-chip", title: def.desc },
      pick, def.name.split(" (")[0], ...inputs, x);
  }));
}

function buildIndicatorMenu() {
  const menu = $("#ind-menu");
  const layerItems = Object.entries(LAYERS).map(([key, def]) => {
    const item = el("div", { class: `item${on(key) ? " on" : ""}` },
      el("b", {}, def.name), el("span", { class: "kind" }, on(key) ? "켜짐 · 누르면 끔" : "누르면 켬"),
      el("p", {}, def.desc));
    item.addEventListener("click", (e) => { e.stopPropagation(); toggleLayer(key); });   // 여러 개 연달아 켤 수 있게 메뉴 유지
    return item;
  });
  const indItems = Object.entries(INDICATORS).map(([key, def]) => {
    const count = state.indicators.filter((i) => i.key === key).length;
    const item = el("div", { class: `item${count ? " on" : ""}` },
      el("b", {}, def.name),
      el("span", { class: "kind" }, `${def.type === "overlay" ? "차트 위" : "아래 칸"}${count ? ` · ${count}개 사용 중` : ""}`),
      el("p", {}, def.desc));
    item.addEventListener("click", () => {
      state.indicators.push({ id: Date.now().toString(36), key, params: { ...def.params } });
      saveIndicators();
      renderIndicators();
      buildIndicatorMenu();
      menu.hidden = true;
    });
    return item;
  });
  menu.replaceChildren(
    el("div", { class: "sec" }, "가격대 분석 — 누를 때마다 켜기/끄기"), ...layerItems,
    el("div", { class: "sec" }, "보조지표 — 누르면 추가 (기간 다르게 여러 개 가능), 빼기는 칩의 ×"), ...indItems);
}
$("#add-ind").addEventListener("click", (e) => { e.stopPropagation(); $("#ind-menu").hidden = !$("#ind-menu").hidden; });
document.addEventListener("click", (e) => { if (!e.target.closest(".dropdown")) $("#ind-menu").hidden = true; });

// ── 선 긋기 ──
function setDrawMode(mode) {
  state.drawMode = state.drawMode === mode ? null : mode;
  state.pending = null;
  $("#chart").classList.toggle("drawing", !!state.drawMode);
  $("#draw-trend").classList.toggle("on", state.drawMode === "trend");
  $("#draw-hline").classList.toggle("on", state.drawMode === "hline");
  $("#draw-channel").classList.toggle("on", state.drawMode === "channel");
  banner({
    trend: "추세선 시작점을 클릭하세요 (Esc 취소)",
    hline: "선을 그을 가격을 클릭하세요 (Esc 취소)",
    channel: "채널 기준선 시작점을 클릭하세요 (1/3, Esc 취소)",
  }[state.drawMode] || (state.data?.demo ? demoText : ""));
}
const demoText = "데모 데이터예요 (실제 시세 아님). .env 에 토스 API 키를 넣으면 실제 시세로 바뀌어요.";

$("#draw-trend").addEventListener("click", () => setDrawMode("trend"));
$("#draw-hline").addEventListener("click", () => setDrawMode("hline"));
$("#draw-channel").addEventListener("click", () => setDrawMode("channel"));
document.addEventListener("keydown", (e) => e.key === "Escape" && state.drawMode && setDrawMode(null));

// chart.subscribeClick 은 빠른 연속 클릭을 더블클릭으로 묶어 삼켜서, DOM 클릭으로 직접 좌표 계산
$("#chart").addEventListener("click", (e) => {
  if (!state.drawMode || !state.data) return;
  const rect = $("#chart").getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  if (x > chart.timeScale().width()) return;          // 오른쪽 가격축 클릭은 무시
  const logical = chart.timeScale().coordinateToLogical(x);
  if (logical == null) return;
  const cs = state.data.candles;
  const idx = Math.max(0, Math.min(cs.length - 1, Math.round(logical)));
  const price = candles.coordinateToPrice(y);
  if (price == null) return;
  const pt = { time: cs[idx].time, price: Number(price.toFixed(4)) };
  const id = Date.now().toString(36);
  if (state.drawMode === "hline") {
    saveDrawings([...state.drawings, { id, type: "horizontal", p1: pt }]);
    return setDrawMode(null);
  }
  const pending = state.pending || [];
  if (pending.length === 0) {
    state.pending = [pt];
    return banner(state.drawMode === "channel" ? "기준선 끝점을 클릭하세요 (2/3)" : "끝점을 클릭하세요 (Esc 취소)");
  }
  if (pending.length === 1) {
    if (pending[0].time === pt.time) return;
    const [p1, p2] = [pending[0], pt].sort((a, b) => (a.time < b.time ? -1 : 1));
    if (state.drawMode === "trend") {
      saveDrawings([...state.drawings, { id, type: "trend", p1, p2 }]);
      return setDrawMode(null);
    }
    state.pending = [p1, p2];
    return banner("평행선이 지나갈 곳을 클릭하세요 — 반대편 고점(또는 저점) (3/3)");
  }
  const [p1, p2] = pending;
  saveDrawings([...state.drawings, { id, type: "channel", p1, p2, p3: pt }]);
  setDrawMode(null);
});

async function saveDrawings(items) {
  const symbol = state.data.symbol;
  const res = await fetch(`/api/drawings/${encodeURIComponent(symbol)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
  });
  if (!res.ok) return banner("선 저장 실패", "error");
  state.drawings = (await res.json()).items;
  renderDrawings();
}

function renderDrawings() {
  renderLevels();
  renderTrendlines();
  const list = $("#drawings");
  if (!state.drawings.length) {
    return list.replaceChildren(el("li", { class: "muted" }, "차트 위 ✏️/― 버튼으로 그을 수 있어요. 관심종목이면 닿을 때 알림이 와요."));
  }
  const last = state.data.candles.at(-1).close;
  list.replaceChildren(...state.drawings.map((d) => {
    const x = el("span", { class: "x", title: "지우기" }, "×");
    x.addEventListener("click", () => saveDrawings(state.drawings.filter((w) => w.id !== d.id)));
    const name = { trend: "추세선", horizontal: "수평선", channel: "채널" }[d.type];
    const where = drawingLines(d).map((ln) => `${fmt(ln.now)} (${((ln.now / last - 1) * 100).toFixed(1)}%)`).join(" / ") || "-";
    return el("li", {}, el("span", {}, `${name} · 오늘 ${where}`), x);
  }));
}

// ── 차트 마커 (뉴스 + 매매 신호) ──
function newsMarkers() {
  if (!on("news") || !state.news.length || !isDaily()) return [];
  const days = state.data.candles.map((c) => c.time);
  const color = { 호재: css("--up"), 악재: css("--down"), 중립: "#8b95a1" };
  const byDay = new Map();
  for (const n of state.news) {
    const day = days.find((d) => d >= n.date);          // 휴일 뉴스는 다음 거래일에
    if (!day) continue;
    (byDay.get(day) || byDay.set(day, []).get(day)).push(n);
  }
  state.newsByDay = byDay;          // 마우스 올렸을 때 설명 상자용
  // 글자는 기사 수만 (선과 겹쳐도 읽기 쉽게). 제목은 마우스를 올리면
  return [...byDay.entries()].map(([time, list]) => {
    const tone = list.some((n) => n.sentiment === "악재") ? "악재" : list.some((n) => n.sentiment === "호재") ? "호재" : "중립";
    return { time, position: "aboveBar", shape: "circle", color: color[tone], size: 0.6, text: list.length > 1 ? `${list.length}` : "" };
  });
}

const shownSignals = () => (state.data?.signals?.events || []).filter((e) => state.sigShow.includes(e.type));

function signalMarkers() {
  if (!on("signals") || !isDaily()) return [];
  // 같은 날 여러 신호는 한 마커로 묶는다 (상승 쪽은 봉 아래, 하락 쪽은 봉 위)
  const groups = new Map();
  for (const e of shownSignals()) {
    const dir = e.dir === "info" ? (e.up_candle ? "bull" : "bear") : e.dir;
    const k = `${e.time}|${dir}`;
    (groups.get(k) || groups.set(k, []).get(k)).push(e);
  }
  // 글자는 짧게: 신호 하나면 짧은 이름, 여러 개면 개수만. 자세한 건 마우스를 올리면 설명 상자에
  return [...groups.entries()].map(([k, list]) => {
    const [time, dir] = k.split("|");
    const bull = dir === "bull";
    return { time, position: bull ? "belowBar" : "aboveBar", shape: bull ? "arrowUp" : "arrowDown",
             color: bull ? css("--up") : css("--down"), size: 0.9, text: list.length > 1 ? `${list.length}` : list[0].short };
  });
}

function renderMarkers() {
  if (!state.data) return candles.setMarkers([]);
  const all = [...newsMarkers(), ...signalMarkers()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  candles.setMarkers(all);
}

// 마커가 있는 날에 마우스를 올리면: 그날 신호·뉴스를 풀어서 보여주는 작은 상자
const timeKey = (t) => (typeof t === "object" && t ? `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}` : t);
chart.subscribeCrosshairMove((p) => {
  const tip = $("#tip");
  if (!p.time || !p.point || !state.data || !isDaily()) return (tip.hidden = true);
  const day = timeKey(p.time);
  const sigs = on("signals") ? shownSignals().filter((e) => e.time === day) : [];
  const news = on("news") ? state.newsByDay?.get(day) || [] : [];
  if (!sigs.length && !news.length) return (tip.hidden = true);
  tip.replaceChildren(el("div", { class: "tip-day" }, day),
    ...sigs.map((e) => el("div", { class: `tip-sig ${e.dir}` }, `${e.dir === "bear" ? "▼" : "▲"} ${e.name}${e.note ? ` · ${e.note}` : ""}`)),
    ...(news.length ? [el("div", { class: "tip-news" }, `뉴스 ${news.length}건`),
      ...news.slice(0, 3).map((n) => el("div", { class: "tip-nt" }, `[${n.sentiment}] ${n.title}`))] : []));
  tip.hidden = false;
  const wrap = $(".chart-wrap").getBoundingClientRect();
  const x = Math.min(p.point.x + 14, wrap.width - tip.offsetWidth - 8);
  const y = Math.max(8, Math.min(p.point.y + 14, wrap.height - tip.offsetHeight - 8));
  tip.style.transform = `translate(${x}px, ${y}px)`;
});

// ── 차트 패턴 탭 ──
function evidenceText(ev) {
  if (!ev || ev.n == null) return "아직 검증 숫자가 없어요 (python -m research.patterns_backtest).";
  const r = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  const zero = ev.x20_lo <= 0 && ev.x20_hi >= 0;
  return `검증(80종목·약 8년, 돌파 ${Math.round(ev.n).toLocaleString()}건): 돌파 후 20봉 수익이 그 종목 평소보다 ${r(ev.x20)} `
    + `(95% 구간 ${r(ev.x20_lo)} ~ ${r(ev.x20_hi)})${zero ? " — 아무 날 산 것과 차이가 없었어요." : "."}`
    + (ev.x60 != null ? ` 60봉 뒤 ${r(ev.x60)}.` : "");
}

function renderPatterns() {
  const list = $("#pattern-list");
  if (!state.data) return list.replaceChildren();
  if (!isDaily()) return list.replaceChildren(el("li", { class: "muted" }, "차트 패턴은 '일' 봉에서 찾아요"));
  const pats = state.data.patterns || [];
  const evs = state.data.pattern_evidence || {};
  if (!pats.length) {
    return list.replaceChildren(el("li", { class: "muted" }, "지금 형성 중이거나 최근 10봉 안에 돌파한 패턴이 없어요. 과거 돌파는 '매매 신호' 탭에 있어요."));
  }
  list.replaceChildren(...pats.map((p) => {
    const focused = state.patFocus === p.id;
    const badge = el("span", { class: `pbadge ${p.status === "돌파" ? "brk" : "form"}` }, p.status);
    const vol = p.volume_confirmed == null ? "" : el("span", { class: `pbadge ${p.volume_confirmed ? "vol" : "novol"}` },
      p.volume_confirmed ? "거래량 동반" : "거래량 부족");
    const li = el("li", { class: `pat${focused ? " focus" : ""}` },
      el("b", {}, p.name, badge, vol, el("span", { class: "t" }, p.break_time || `${p.start}~`)),
      el("p", {}, p.why),
      el("p", { class: "muted" }, p.desc),
      el("p", { class: "ev" }, evidenceText(evs[p.type])));
    li.addEventListener("click", () => {
      state.patFocus = focused ? null : p.id;
      if (!on("patterns")) toggleLayer("patterns");
      renderTrendlines(); renderPatterns();
    });
    return li;
  }));
}

// ── 매매 신호 패널 ──
function statText(st) {
  if (!st || !st.n20) return "이 종목에선 과거 기록이 부족해요.";
  return `과거 ${st.count}번 · 20거래일 뒤 평균 ${st.avg20 >= 0 ? "+" : ""}${st.avg20.toFixed(1)}% · 오른 경우 ${st.up20}/${st.n20}`;
}

function renderSignals() {
  const list = $("#signals");
  const sig = state.data?.signals;
  if (!sig) {
    $("#sig-through").textContent = "";
    return list.replaceChildren(el("li", { class: "muted" }, "매매 신호는 장 마감 확정 일봉 기준이라 '일' 봉에서 보여요"));
  }
  $("#sig-through").textContent = sig.confirmed_through ? `${sig.confirmed_through.slice(5)} 종가까지 확정` : "";
  const items = shownSignals().slice(-10).reverse();
  if (!items.length) return list.replaceChildren(el("li", { class: "muted" }, "표시할 신호가 없어요 (설정에서 종류를 골라요)"));
  list.replaceChildren(...items.map((e) => {
    const cat = state.sigCatalog[e.type] || {};
    const isNew = e.time === sig.confirmed_through;
    const li = el("li", { class: e.dir },
      el("b", {}, e.name, isNew ? el("span", { class: "new" }, "최신") : "", el("span", { class: "t" }, e.time)),
      el("p", {}, `${e.note ? `${e.note}. ` : ""}${cat.desc || ""}`),
      el("p", { class: "stat" }, statText(sig.stats[e.type])));
    li.addEventListener("click", () => focusDate(e.time));
    return li;
  }));
}

async function loadSignalSettings() {
  const res = await fetch("/api/signals/settings");
  if (!res.ok) return;
  const body = await res.json();
  state.sigCatalog = body.catalog;
  state.sigAlert = body.alert_types;
  renderSignalSettings();
}

function renderSignalSettings() {
  const box = $("#sig-settings");
  const dirColor = { bull: "var(--up)", bear: "var(--down)", info: "#8b95a1" };
  const check = (checked, onChange) => {
    const cb = el("input", { type: "checkbox" });
    cb.checked = checked;
    cb.addEventListener("change", () => onChange(cb.checked));
    return cb;
  };
  const rows = Object.entries(state.sigCatalog).map(([id, cat]) => el("tr", { title: cat.desc },
    el("td", {}, el("span", { class: "dir", style: `background:${dirColor[cat.dir]}` }), cat.name),
    el("td", {}, check(state.sigShow.includes(id), (v) => {
      state.sigShow = v ? [...state.sigShow, id] : state.sigShow.filter((s) => s !== id);
      store.save("stocking.sigShow", state.sigShow);
      renderMarkers();
      renderSignals();
    })),
    el("td", {}, check(state.sigAlert.includes(id), async (v) => {
      const types = v ? [...state.sigAlert, id] : state.sigAlert.filter((s) => s !== id);
      const res = await fetch("/api/signals/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ alert_types: types }) });
      if (res.ok) state.sigAlert = (await res.json()).alert_types;
    }))));
  box.replaceChildren(
    el("p", { class: "muted hint" }, "빨강=상승 쪽, 파랑=하락 쪽 신호. 알림은 관심종목에서 장 마감 후 확정된 신호만 와요."),
    el("table", {}, el("tr", {}, el("th", {}, "신호"), el("th", {}, "차트"), el("th", {}, "알림")), ...rows));
}
$("#sig-settings-btn").addEventListener("click", () => { $("#sig-settings").hidden = !$("#sig-settings").hidden; });

// ── 보유종목 ──
const heldOf = (symbol) => state.holdings.find((h) => h.symbol === symbol);
const qty = (v) => v.toLocaleString("en-US", { maximumFractionDigits: 3 });   // 소수점 주식
const pct = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const money = (v, cur) => cur === "KRW" ? `${Math.round(v).toLocaleString("ko-KR")}원` : `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

async function loadHoldings() {
  const list = $("#holdings");
  const res = await fetch("/api/holdings");
  const body = await res.json();
  if (!res.ok) return list.replaceChildren(el("li", { class: "muted" }, body.detail || "불러오기 실패"));
  if (!body.enabled) return list.replaceChildren(el("li", { class: "muted" }, "토스 API 키가 있어야 보유종목을 불러와요."));
  state.holdings = body.items;
  state.acct = body.summary;
  state.usdKrw = body.usd_krw;
  renderHoldings();
  if (state.data) { renderLevels(); renderSide(); }
}

// 종목 로고 대신 이름 첫 글자 + 종목별 고정 색
const LOGO_COLORS = ["#3182f6", "#f04452", "#12b886", "#7950f2", "#fd7e14", "#15aabf", "#e64980", "#495057"];
function logo(symbol, name) {
  let h = 0;
  for (const ch of symbol) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return el("span", { class: "logo", style: `background:${LOGO_COLORS[h % LOGO_COLORS.length]}` }, (name || symbol).slice(0, 2));
}
const cls = (v) => (v >= 0 ? "up" : "down");
const krw = (v) => `${Math.round(v).toLocaleString("ko-KR")}원`;
const signed = (v, f) => `${v >= 0 ? "+" : "-"}${f(Math.abs(v))}`;
state.holdView = store.load("stocking.holdView", "value");      // 현재가 | 평가금
state.acctCur = store.load("stocking.acctCur", "krw");          // 원 | $
state.acctFolded = store.load("stocking.acctFolded", false);    // 계좌 요약 접기

function renderAcct() {
  const a = state.acct;
  if (!a) return $("#acct").replaceChildren();
  const k = state.acctCur;
  const fmtA = (v) => (k === "krw" ? krw(v) : `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`);
  const seg = el("span", { class: "seg" }, ...[["usd", "$"], ["krw", "원"]].map(([c, label]) => {
    const btn = el("button", { class: c === k ? "on" : "" }, label);
    btn.addEventListener("click", () => { state.acctCur = c; store.save("stocking.acctCur", c); renderAcct(); });
    return btn;
  }));
  // 접기: 금액을 가리고 한 줄만 (화면 공유할 때 등). 상태 기억
  const fold = el("button", { class: "fold", title: state.acctFolded ? "펼치기" : "접기" }, state.acctFolded ? "▸" : "▾");
  fold.addEventListener("click", () => {
    state.acctFolded = !state.acctFolded;
    store.save("stocking.acctFolded", state.acctFolded);
    renderAcct();
  });
  const head = el("div", { class: "row", style: "margin-top:0" }, el("span", { class: "acct-title" }, fold, "총 평가금"),
    state.acctFolded ? el("span", { class: "muted" }, "접힘") : seg);
  $("#acct").classList.toggle("folded", state.acctFolded);
  if (state.acctFolded) return $("#acct").replaceChildren(head);
  $("#acct").replaceChildren(
    head,
    el("div", { class: "big" }, fmtA(a.market_value[k])),
    el("div", { class: "row" }, el("span", {}, "총 손익"),
      el("span", { class: cls(a.profit_rate) }, `${signed(a.profit[k], fmtA)} (${pct(a.profit_rate)})`)),
    el("div", { class: "row" }, el("span", {}, "오늘"),
      el("span", { class: cls(a.daily_rate) }, `${signed(a.daily[k], fmtA)} (${pct(a.daily_rate)})`)));
}

function renderHoldings() {
  renderAcct();
  document.querySelectorAll("[data-hv]").forEach((b) => b.classList.toggle("on", b.dataset.hv === state.holdView));
  const list = $("#holdings");
  if (!state.holdings.length) return list.replaceChildren(el("li", { class: "muted" }, "보유 종목이 없어요"));
  list.replaceChildren(...state.holdings.map((h) => {
    // 토스처럼: 평가금 보기 = 원화 평가금 + 손익(원, %) / 현재가 보기 = 현재가 + 오늘 등락
    const right = state.holdView === "value"
      ? [el("span", { class: "amt" }, krw(h.market_value_krw)),
         el("span", { class: `sub r ${cls(h.pl_rate)}` }, `${signed(h.pl_amount_krw, krw)} (${Math.abs(h.pl_rate).toFixed(2)}%)`)]
      : [el("span", { class: "amt" }, money(h.last_price, h.currency)),
         el("span", { class: `sub r ${cls(h.daily_rate)}` }, `오늘 ${pct(h.daily_rate)}`)];
    const li = el("li", { class: `row2${h.symbol === state.data?.symbol ? " active" : ""}`, title: `평단 ${money(h.avg_price, h.currency)}` },
      logo(h.symbol, h.name), el("span", { class: "nm" }, h.name), right[0],
      el("span", { class: "sub" }, `${qty(h.quantity)}주`), right[1]);
    li.addEventListener("click", () => load(h.symbol));
    return li;
  }));
}
document.querySelectorAll("[data-hv]").forEach((b) => b.addEventListener("click", () => {
  state.holdView = b.dataset.hv;
  store.save("stocking.holdView", state.holdView);
  renderHoldings();
}));

$("#list-refresh").addEventListener("click", () => (state.tab === "watch" ? loadWatchSummary() : loadHoldings()));

// ── 왜 움직였지? (최근 뉴스로 오늘 등락 이유 찾기) ──
$("#why-btn").addEventListener("click", async () => {
  const sym = state.data?.symbol;
  if (!sym) return;
  setStockTab("overview");
  const box = $("#why-box");
  box.replaceChildren(el("div", { class: "card why" }, el("b", {}, "오늘 움직임 이유 찾는 중…"),
    el("p", {}, "최근 뉴스와 시장 전체 움직임을 보고 있어요 (몇 초 걸려요)")));
  const res = await fetch(`/api/why/${encodeURIComponent(sym)}`);
  const w = await res.json();
  if (state.data?.symbol !== sym) return;
  if (!res.ok) return box.replaceChildren(el("div", { class: "card why" }, el("b", {}, "이유를 찾지 못했어요"), el("p", {}, w.detail || "")));
  const mkt = w.market_change_pct != null ? ` · ${w.market_label} ${w.market_change_pct >= 0 ? "+" : ""}${w.market_change_pct.toFixed(2)}%` : "";
  const close = el("span", { class: "x", title: "닫기" }, "×");
  close.addEventListener("click", () => box.replaceChildren());
  box.replaceChildren(el("div", { class: `card why ${w.change_pct >= 0 ? "up-b" : "down-b"}` },
    el("b", {}, `오늘 ${w.change_pct >= 0 ? "+" : ""}${w.change_pct.toFixed(2)}%${mkt}`, close),
    w.underlying ? el("p", { class: "und" }, `기초자산: ${w.underlying.label} ${w.underlying.change_pct == null ? "-" : `${w.underlying.change_pct >= 0 ? "+" : ""}${w.underlying.change_pct.toFixed(2)}%`}`
      + ` · ${w.underlying.describe}${w.underlying.note ? ` · ${w.underlying.note}` : ""}`) : "",
    el("p", {}, w.reason),
    sourceLinks(w.sources, w.found ? "근거 기사" : "참고 기사"),
    el("p", { class: "muted hint" }, "주어진 기사 안에서만 이유를 찾아요. 기사로 설명이 안 되면 못 찾았다고 말해요.")));
});

// ── 오른쪽 아이콘 탭 (내 투자 / 관심 / 최근 본 / 알림) ──
const SIDE_TITLES = { holdings: "내 투자", watch: "관심종목", recent: "최근 본 종목", market: "시장 한눈에", alerts: "알림" };
function setTab(tab) {
  state.tab = tab;
  store.save("stocking.tab", tab);
  document.querySelectorAll(".rail-btn[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== tab));
  $("#side-title").textContent = SIDE_TITLES[tab];
  $("#hold-watch").hidden = tab !== "holdings";
  $("#list-refresh").hidden = !["holdings", "watch"].includes(tab);
  if (tab === "alerts") $("#alert-badge").hidden = true;
  if (tab === "recent") renderRecent();
  if (tab === "market") loadMarket();
  else updateLiveSubscription();
  setCollapsed(false);
}
document.querySelectorAll(".rail-btn[data-tab]").forEach((b) => b.addEventListener("click", () => {
  // 이미 열린 탭을 다시 누르면 패널 접기 (토스처럼)
  if (state.tab === b.dataset.tab && !$("#app").classList.contains("collapsed")) return setCollapsed(true);
  setTab(b.dataset.tab);
}));
const isPhone = () => matchMedia("(max-width: 700px)").matches;
function setCollapsed(c) {
  $("#app").classList.toggle("collapsed", c);
  $("#rail-collapse").textContent = c ? "«" : "»";
  // 폰에선 '차트'가 열린 탭처럼 보이게, 목록 탭 강조는 목록이 열렸을 때만
  $("#rail-chart").classList.toggle("on", c);
  document.querySelectorAll(".rail-btn[data-tab]").forEach((b) => b.classList.toggle("on", !c && b.dataset.tab === state.tab));
  if (!isPhone()) store.save("stocking.sideCollapsed", c);      // 폰에서 접은 상태는 PC 설정에 안 남김
}
$("#rail-collapse").addEventListener("click", () => setCollapsed(!$("#app").classList.contains("collapsed")));
$("#rail-chart").addEventListener("click", () => setCollapsed(true));

// ── 종목 정보 탭 (한눈에 / 자동 선 / 신호 / 뉴스 / 내 선) ──
function setStockTab(t) {
  state.stockTab = t;
  store.save("stocking.stockTab", t);
  document.querySelectorAll(".stab").forEach((b) => b.classList.toggle("on", b.dataset.st === t));
  document.querySelectorAll("[data-stpanel]").forEach((p) => (p.hidden = p.dataset.stpanel !== t));
}
document.querySelectorAll(".stab").forEach((b) => b.addEventListener("click", () => setStockTab(b.dataset.st)));
setStockTab(store.load("stocking.stockTab", "overview"));

// ── 시장 탭 (지수·선물·국채·원자재·환율·코인) ──
function sparkline(values, up) {
  const w = 64, h = 22, min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / span) * h}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "spark");
  const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  pl.setAttribute("points", pts);
  pl.setAttribute("fill", "none");
  pl.setAttribute("stroke", up ? css("--up") : css("--down"));
  pl.setAttribute("stroke-width", "1.5");
  svg.append(pl);
  return svg;
}

const MACRO_CUR = { pt: "PT", pct: "PCT", usd: "USD", krw: "KRW" };
let marketTimer = null, marketRenderQueued = false;
state.market = [];
state.marketTab = store.load("stocking.marketTab", "전체");

async function loadMarket() {
  const box = $("#market-list");
  if (!state.market.length) box.replaceChildren(el("p", { class: "muted" }, "불러오는 중…"));
  const res = await fetch("/api/macro");
  const body = await res.json();
  if (!res.ok) return box.replaceChildren(el("p", { class: "muted" }, body.detail || "불러오기 실패"));
  state.market = body.groups;
  renderMarket();
  updateLiveSubscription();                    // 실시간 ETF 를 토스 체결로 받기
  clearTimeout(marketTimer);
  marketTimer = setTimeout(() => state.tab === "market" && !$("#app").classList.contains("collapsed") && loadMarket(), 60000);
}

function marketRow(it) {
  if (it.error) return el("li", { class: "muted" }, `${it.name}: 데이터 없음`);
  const up = it.change >= 0;
  // 금리는 % 가 아니라 bp(0.01%p) 로: '10년 금리 +5bp'
  const chg = it.unit === "pct" ? `${up ? "+" : ""}${it.change_bp.toFixed(1)}bp` : pct(it.change_pct);
  const name = el("span", { class: "nm" }, it.name);
  const li = el("li", { class: `mk${it.symbol === state.data?.symbol ? " active" : ""}`,
                        title: `${it.name} (${it.symbol}) · ${it.live ? "토스 실시간" : `${it.date} 기준, 야후·몇 분 지연`}` },
    // 실시간 줄은 이름 앞 초록 점 (묶음 제목에 '토스 실시간'), 나머지는 표시 없음
    el("span", { class: "nmw" }, it.live ? el("span", { class: "rt-dot", title: "토스 실시간" }, "●") : "", name),
    sparkline(it.spark, up),
    el("span", { class: "amt" }, fmtIn(it.last, MACRO_CUR[it.unit])),
    el("span", { class: `chg ${cls(it.change)}` }, chg));
  li.addEventListener("click", () => load(it.symbol));
  return li;
}

function renderMarket() {
  const tabs = ["전체", ...state.market.map((g) => g.group)];
  if (!tabs.includes(state.marketTab)) state.marketTab = "전체";
  const chips = el("div", { class: "mk-tabs" }, ...tabs.map((t) => {
    const b = el("button", { class: t === state.marketTab ? "on" : "" }, t);
    b.addEventListener("click", () => { state.marketTab = t; store.save("stocking.marketTab", t); renderMarket(); });
    return b;
  }));
  const groups = state.market.filter((g) => state.marketTab === "전체" || g.group === state.marketTab);
  $("#market-list").replaceChildren(chips, ...groups.flatMap((g) => [
    el("div", { class: "mk-group" }, g.group, el("span", { class: g.live ? "rt" : "delay" }, g.live ? "토스 실시간" : "야후 · 지연")),
    el("ul", { class: "stock-list" }, ...g.items.map(marketRow)),
  ]));
}

const marketLiveSymbols = () => (state.tab === "market" ? state.market.filter((g) => g.live).flatMap((g) => g.items.map((i) => i.symbol)) : []);

// ── 최근 본 종목 ──
function rememberRecent(symbol, name) {
  const list = store.load("stocking.recent", []).filter((r) => r.symbol !== symbol);
  list.unshift({ symbol, name });
  store.save("stocking.recent", list.slice(0, 20));
  if (state.tab === "recent") renderRecent();
}
function renderRecent() {
  const items = store.load("stocking.recent", []);
  const list = $("#recent-list");
  if (!items.length) return list.replaceChildren(el("li", { class: "muted" }, "아직 본 종목이 없어요"));
  list.replaceChildren(...items.map((r) => {
    const h = heldOf(r.symbol), w = state.watchSummary[r.symbol];
    const price = h ? money(h.last_price, h.currency) : w && !w.error ? money(w.price, w.currency) : "";
    const li = el("li", { class: `row2${r.symbol === state.data?.symbol ? " active" : ""}` },
      logo(r.symbol, r.name), el("span", { class: "nm" }, r.name), el("span", { class: "amt" }, price),
      el("span", { class: "sub" }, r.symbol + (h ? " · 보유" : "") + (state.watchlist.includes(r.symbol) ? " · 관심" : "")),
      el("span", { class: "sub r" }, ""));
    li.addEventListener("click", () => load(r.symbol));
    return li;
  }));
}
$("#hold-watch").addEventListener("click", async () => {
  const add = state.holdings.map((h) => h.symbol).filter((s) => !state.watchlist.includes(s));
  if (!add.length) return toast({ type: "info", title: "이미 다 들어있어요", body: "보유종목이 모두 관심종목이에요." });
  await saveWatchlist([...state.watchlist, ...add]);
  toast({ type: "info", title: `관심종목 ${add.length}개 추가`, body: `${add.join(", ")} — 이제 지지/저항 알림이 와요.` });
});

// ── 검색 자동완성 ──
let suggestTimer = null, suggestSel = -1, suggestItems = [];

function renderSuggest() {
  const box = $("#suggest");
  box.hidden = !suggestItems.length;
  box.replaceChildren(...suggestItems.map((s, i) => {
    const li = el("li", { class: i === suggestSel ? "sel" : "" }, el("span", {}, s.name), el("span", { class: "sym" }, `${s.symbol} · ${s.market}`));
    li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(s); });
    return li;
  }));
}

function pick(s) {
  suggestItems = [];
  renderSuggest();
  load(s.symbol);
  $("#symbol").blur();
}

$("#symbol").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  const q = $("#symbol").value.trim();
  if (!q || q.includes(",")) { suggestItems = []; return renderSuggest(); }
  suggestTimer = setTimeout(async () => {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`);
    if (!res.ok || $("#symbol").value.trim() !== q) return;
    suggestItems = (await res.json()).items;
    suggestSel = suggestItems.length ? 0 : -1;
    renderSuggest();
  }, 150);
});
$("#symbol").addEventListener("keydown", (e) => {
  if (!suggestItems.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    suggestSel = (suggestSel + (e.key === "ArrowDown" ? 1 : -1) + suggestItems.length) % suggestItems.length;
    renderSuggest();
  } else if (e.key === "Escape") { suggestItems = []; renderSuggest(); }
});
$("#symbol").addEventListener("blur", () => setTimeout(() => { suggestItems = []; renderSuggest(); }, 100));

async function submitSearch() {
  const q = $("#symbol").value.trim();
  if (!q) return;
  if (q.includes(",")) {                       // 여러 개 붙여넣기 → 관심종목에 추가
    const body = await (await fetch(`/api/resolve?q=${encodeURIComponent(q)}`)).json();
    const add = body.items.map((s) => s.symbol).filter((s) => !state.watchlist.includes(s));
    if (add.length) await saveWatchlist([...state.watchlist, ...add]);
    toast({ type: "info", title: `관심종목 ${add.length}개 추가`,
      body: (body.items.map((s) => `${s.name}(${s.symbol})`).join(", ") || "없음")
        + (body.missing.length ? ` · 못 찾음: ${body.missing.join(", ")}` : "") });
    $("#symbol").value = "";
    return;
  }
  if (suggestItems.length && suggestSel >= 0) return pick(suggestItems[suggestSel]);
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=1`);
  const hit = res.ok ? (await res.json()).items[0] : null;
  load(hit ? hit.symbol : q);
}

// ── 사이드 패널 ──
function renderSide() {
  const d = state.data;
  const cards = [...d.insights];
  const held = heldOf(d.symbol);
  if (held) {
    const near = d.levels.support[0];
    cards.unshift({
      kind: "holding",
      title: `내 평단 ${money(held.avg_price, held.currency)} · ${pct(held.pl_rate)}`,
      body: `${qty(held.quantity)}주 보유, 평가금액 ${money(held.market_value, held.currency)}.`
        + (near ? ` 가장 가까운 지지선(${fmt(near.price)})은 평단 대비 ${pct((near.price / held.avg_price - 1) * 100)} 위치예요.` : ""),
    });
  }
  // 차트에 꺼둔 레이어의 설명 카드는 숨긴다 (추세/RSI 요약은 항상)
  const layerOf = { support: "levels", resistance: "levels", alert: "levels", trendline: "trend", channel: "channel", holding: "avg" };
  const visible = cards.filter((c) => !layerOf[c.kind] || on(layerOf[c.kind]));
  $("#insights").replaceChildren(...visible.map((i) =>
    el("div", { class: `card ${i.kind}` }, el("b", {}, i.title), el("p", {}, i.body))));
}

// ── 오른쪽 '자동으로 그은 선' 목록: 후보 보기 · 근거 보기 · 내 선으로 쓰기 ──
const AUTO_GROUPS = [
  ["level", "수평 지지/저항선", "levels"],
  ["trend", "추세선 (후보 중 고르기)", "trend"],
  ["channel", "추세 채널", "channel"],
];

function renderAutoLines() {
  const box = $("#auto-lines");
  if (!state.data) return box.replaceChildren();
  const items = autoItems();
  const last = state.data.candles.at(-1).close;
  const sections = [];
  for (const [group, title, layer] of AUTO_GROUPS) {
    const list = items.filter((x) => x.group === group);
    const head = el("div", { class: "al-head" }, el("span", {}, title));
    if (!on(layer)) {
      const btn = el("button", { class: "ghost small" }, "차트에 켜기");
      btn.addEventListener("click", () => toggleLayer(layer));
      head.append(btn);
      sections.push(head);
      continue;
    }
    sections.push(head);
    if (!list.length) { sections.push(el("p", { class: "muted hint" }, "뚜렷한 선을 못 찾았어요")); continue; }
    for (const it of list) {
      const shown = isVisible(it), focused = state.focus === it.id;
      const color = it.group === "channel" ? CHANNEL_COLOR : kindColor(it.kind);
      const eye = el("button", { class: `ghost small eye${shown ? " on" : ""}`, title: shown ? "차트에서 숨기기" : "차트에 보이기" }, shown ? "보임" : "숨김");
      eye.addEventListener("click", (e) => {
        e.stopPropagation();
        state.vis[it.id] = !shown;
        if (shown && state.focus === it.id) state.focus = null;
        renderLevels(); renderTrendlines(); renderAutoLines();
      });
      const use = el("button", { class: "ghost small", title: "내가 그은 선으로 저장 → 관심종목이면 닿을 때 알림" }, "이 선 쓰기");
      use.addEventListener("click", (e) => { e.stopPropagation(); adopt(it); });
      const dist = ((it.now / last - 1) * 100);
      const row = el("li", { class: `al${focused ? " focus" : ""}${shown ? "" : " off"}` },
        el("div", { class: "al-main" },
          el("i", { style: `background:${color}` }),
          el("span", { class: "nm" }, it.name, it.rank > 1 ? el("span", { class: "rk" }, `후보${it.rank}`) : ""),
          el("span", { class: "px" }, `${fmt(it.now)} ${dist >= 0 ? "+" : ""}${dist.toFixed(1)}%`)),
        focused ? el("p", { class: "why" }, `차트의 점들이 이 선이 닿은 곳이에요. ${it.why}`) : "",
        el("div", { class: "al-act" }, eye, use));
      row.addEventListener("click", () => setFocus(it.id));
      sections.push(row);
    }
  }
  box.replaceChildren(el("ul", {}, ...sections.map((s) => (s.tagName === "LI" ? s : el("li", { class: "al-sec" }, s)))));
}

async function adopt(it) {
  const d = state.data;
  const lastTime = d.candles.at(-1).time;
  const id = Date.now().toString(36);
  let drawing;
  if (it.group === "level") {
    drawing = { id, type: "horizontal", p1: { time: String(lastTime), price: it.price } };
  } else if (!isDaily()) {
    return toast({ type: "info", title: "일봉에서 쓸 수 있어요", body: "비스듬한 선은 날짜 기준으로 저장돼서 '일' 봉에서 '이 선 쓰기'를 눌러주세요." });
  } else if (it.group === "trend") {
    drawing = { id, type: "trend", p1: { time: it.points[0].time, price: it.points[0].value }, p2: { time: it.points[1].time, price: it.points[1].value } };
  } else {
    const ch = it.channel;
    drawing = { id, type: "channel", p1: { time: ch.base[0].time, price: ch.base[0].value },
      p2: { time: ch.base[1].time, price: ch.base[1].value }, p3: { time: ch.other[0].time, price: ch.other[0].value } };
  }
  if (!on("drawings")) toggleLayer("drawings");
  await saveDrawings([...state.drawings, drawing]);
  const watched = state.watchlist.includes(d.symbol);
  toast({ type: "info", title: "내 선에 추가했어요", body: watched ? "이 선에 닿거나 넘으면 알림이 와요." : "관심종목(☆)에 넣으면 이 선에 닿을 때 알림이 와요." });
}

function renderNews(payload) {
  const box = $("#news-summary");
  box.replaceChildren();
  if (!payload.source_enabled) {
    const key = state.data.market === "KR" ? "네이버 검색 API 키(NAVER_CLIENT_ID/SECRET)" : "FINNHUB_API_KEY";
    box.append(el("p", { class: "muted" }, `.env 에 ${key}를 넣으면 뉴스가 나와요.`));
  }
  if (payload.summary) {
    box.append(el("b", {}, `전반적 분위기: ${payload.summary.tone}`),
      el("ol", {}, ...payload.summary.lines.map((l) => el("li", {}, l))));
  } else if (payload.items.length && !payload.summary_enabled) {
    box.append(el("p", { class: "muted" }, "OPENAI_API_KEY 를 넣으면 3줄 요약과 호재/악재 태그가 붙어요."));
  }
  $("#news").replaceChildren(...payload.items.map((n) => {
    const li = el("li", {},
      el("span", { class: `tag ${n.sentiment}` }, n.sentiment),
      el("a", { href: n.url, target: "_blank", rel: "noopener noreferrer" }, n.title),
      el("div", { class: "meta" }, `${n.date} · ${n.source}`));
    li.addEventListener("click", (e) => { if (e.target.tagName !== "A") focusDate(n.date); });
    return li;
  }));
  if (!payload.items.length && payload.source_enabled) $("#news").append(el("li", { class: "muted" }, "최근 뉴스가 없어요"));
}

function focusDate(date) {
  const days = state.data.candles.map((c) => c.time);
  const idx = days.findIndex((d) => d >= date);
  if (idx < 0) return;
  chart.timeScale().setVisibleLogicalRange({ from: idx - 30, to: idx + 15 });
}

// ── 로드 ──
// 봉 단위. 토스 API 는 1분·일봉만 주고 나머지는 서버가 묶어서 만든다
const INTERVALS = [
  ["1m", "1분"], ["3m", "3분"], ["5m", "5분"], ["15m", "15분"], ["30m", "30분"], ["60m", "1시간"],
  ["1d", "일"], ["1w", "주"], ["1M", "월"], ["1y", "년"],
];
state.interval = store.load("stocking.interval", "1d");
const isDaily = () => state.interval === "1d";

function renderIntervalBar() {
  $("#intervals").replaceChildren(...INTERVALS.map(([iv, label], i) => {
    const b = el("button", { class: `iv${iv === state.interval ? " on" : ""}${i === 6 ? " sep" : ""}` }, label);
    b.addEventListener("click", () => {
      if (iv === state.interval) return;
      state.interval = iv;
      store.save("stocking.interval", iv);
      renderIntervalBar();
      if (state.data) loadChart(state.data.symbol);
    });
    return b;
  }));
}

function renderPrice(price) {
  const d = state.data;
  const chg = (price / d.prev_close - 1) * 100;
  const prev = state.lastShown;
  state.lastShown = price;
  const box = $("#price");
  box.replaceChildren(fmt(price),
    el("span", { class: `chg ${chg >= 0 ? "up" : "down"}` }, `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`));
  if (prev != null && prev !== price) {           // 토스처럼 바뀔 때 깜빡임
    box.classList.remove("flash-up", "flash-down");
    void box.offsetWidth;
    box.classList.add(price > prev ? "flash-up" : "flash-down");
  }
}

// 차트만 다시 (봉 단위 바꿀 때). 뉴스는 그대로 둔다
async function loadChart(symbol) {
  banner("불러오는 중...");
  const res = await fetch(`/api/chart/${encodeURIComponent(symbol)}?interval=${state.interval}`);
  const d = await res.json();
  if (!res.ok) return banner(d.detail || "불러오기 실패", "error");
  if (state.data && state.data.symbol !== symbol && state.loading !== symbol) return;
  state.data = d;
  state.lastShown = null;
  state.vis = {};
  state.focus = null;
  state.patFocus = null;
  banner(d.demo ? demoText : "");

  chart.applyOptions({ timeScale: { timeVisible: d.intraday, secondsVisible: false } });
  state.panes.forEach((p) => p.chart.applyOptions({ timeScale: { timeVisible: d.intraday } }));
  candles.applyOptions({ priceFormat: d.currency === "KRW" ? { type: "price", precision: 0, minMove: 1 } : { type: "price", precision: 2, minMove: 0.01 } });
  // lightweight-charts 는 넘긴 객체의 time 을 자기 형식으로 바꿔버려서, 원본(날짜 문자열 비교에 씀) 대신 복사본을 준다
  candles.setData(d.candles.map((c) => ({ ...c })));
  volume.setData(d.candles.map((c) => ({ time: c.time, value: c.volume, color: (c.close >= c.open ? css("--up") : css("--down")) + "55" })));
  renderPrice(d.candles.at(-1).close);
  renderSide();
  renderIndicators();
  renderDrawings();
  renderMarkers();
  renderSignals();
  renderAutoLines();
  renderPatterns();
  $("#daily-only").hidden = isDaily();
  // 지수·선물·금리(야후)는 관심종목/이유찾기 대상이 아니고 토스 실시간도 없음
  $("#watch-toggle").hidden = $("#why-btn").hidden = $("#live-dot").hidden = !!d.macro;
  ["#draw-trend", "#draw-hline", "#draw-channel"].forEach((id) => ($(id).disabled = !isDaily()));
  // autoSize 가 첫 레이아웃 후에 폭을 잡기 때문에 한 프레임 뒤에 범위를 지정해야 안 찌그러진다
  requestAnimationFrame(() => setTimeout(() =>
    chart.timeScale().setVisibleLogicalRange({ from: d.candles.length - 150, to: d.candles.length + 3 }), 50));
}

async function load(symbol) {
  symbol = symbol.trim().toUpperCase();
  if (!symbol) return;
  if (state.drawMode) setDrawMode(null);
  $("#symbol").value = symbol;
  history.replaceState(null, "", `?s=${symbol}`);
  state.loading = symbol;
  if (symbol !== state.data?.symbol) $("#why-box").replaceChildren();   // 이전 종목의 '왜 움직였지?' 결과 지우기
  const dres = await fetch(`/api/drawings/${encodeURIComponent(symbol)}`);
  state.drawings = dres.ok ? (await dres.json()).items : [];
  state.news = [];
  await loadChart(symbol);
  if (state.data?.symbol !== symbol) return;
  $("#name").textContent = `${state.data.name} (${symbol})`;
  rememberRecent(symbol, state.data.name);
  if (isPhone()) setCollapsed(true);          // 폰: 목록에서 종목을 고르면 차트로 돌아감
  renderWatchlist();
  renderHoldings();
  updateLiveSubscription();

  $("#news").replaceChildren(el("li", { class: "muted" }, "뉴스 불러오는 중..."));
  $("#news-summary").replaceChildren();
  const nres = await fetch(`/api/news/${encodeURIComponent(symbol)}`);
  if (state.data?.symbol !== symbol) return;               // 그 사이 다른 종목 눌렀으면 무시
  if (!nres.ok) return $("#news").replaceChildren(el("li", { class: "muted" }, "뉴스를 불러오지 못했어요"));
  const payload = await nres.json();
  state.news = payload.items;
  renderNews(payload);
  renderMarkers();
}

// ── 관심종목 ──
async function saveWatchlist(symbols) {
  const res = await fetch("/api/watchlist", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbols }) });
  state.watchlist = (await res.json()).symbols;
  renderWatchlist();
  loadWatchSummary();
  updateLiveSubscription();
}

let summaryReq = 0;
async function loadWatchSummary() {
  const req = ++summaryReq;
  const res = await fetch("/api/watchlist/summary");
  if (!res.ok || req !== summaryReq) return;
  state.watchSummary = Object.fromEntries((await res.json()).items.map((i) => [i.symbol, i]));
  renderWatchlist();
}

function renderWatchlist() {
  const cur = state.data?.symbol;
  $("#watch-count").textContent = state.watchlist.length || "";
  const list = $("#watch-list");
  if (!state.watchlist.length) {
    list.replaceChildren(el("li", { class: "muted" }, "아직 관심종목이 없어요"));
  } else list.replaceChildren(...state.watchlist.map((s) => {
    const info = state.watchSummary?.[s];
    const ok = info && !info.error;
    const x = el("span", { class: "x", title: "관심종목에서 빼기" }, "×");
    x.addEventListener("click", (e) => { e.stopPropagation(); saveWatchlist(state.watchlist.filter((w) => w !== s)); });
    const dist = ok ? [
      info.support_pct != null ? `지지 ${info.support_pct.toFixed(1)}%` : null,
      info.resistance_pct != null ? `저항 +${info.resistance_pct.toFixed(1)}%` : null,
    ].filter(Boolean).join(" · ") : "";
    const li = el("li", { class: `row2${s === cur ? " active" : ""}` },
      logo(s, info?.name), el("span", { class: "nm" }, info?.name || s),
      el("span", { class: "amt" }, ok ? money(info.price, info.currency) : info?.error ? "불러오기 실패" : "…", x),
      el("span", { class: "sub" }, `${s}${dist ? ` · ${dist}` : ""}`),
      el("span", { class: `sub r ${ok ? cls(info.change_pct) : ""}` }, ok ? pct(info.change_pct) : ""));
    li.addEventListener("click", () => load(s));
    return li;
  }));
  const starred = state.watchlist.includes(cur);
  $("#watch-toggle").className = `ghost${starred ? " on" : ""}`;
  $("#watch-toggle").textContent = starred ? "★ 관심종목" : "☆ 관심종목";
}

$("#watch-toggle").addEventListener("click", () => {
  const s = state.data?.symbol;
  if (!s) return;
  saveWatchlist(state.watchlist.includes(s) ? state.watchlist.filter((w) => w !== s) : [...state.watchlist, s]);
});

// ── 알림 ──
const timeOf = (iso) => iso.slice(5, 16).replace("T", " ");

// 급등락 알림 등에 붙는 근거 기사 링크 (클릭해도 종목 이동은 안 함)
function sourceLinks(sources, label = "근거 기사") {
  if (!sources?.length) return "";
  return el("div", { class: "srcs" }, el("span", { class: "muted" }, `${label} `),
    ...sources.map((s, i) => {
      const a = el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", title: `${s.date} · ${s.source}` }, `[${i + 1}] ${s.title}`);
      a.addEventListener("click", (e) => e.stopPropagation());
      return a;
    }));
}

function alertItem(ev) {
  const li = el("li", { class: `ev-${ev.type}` },
    el("b", {}, ev.title, el("span", { class: "t" }, timeOf(ev.at))),
    el("p", {}, ev.body), sourceLinks(ev.sources, ev.found === false ? "참고 기사" : "근거 기사"));
  li.addEventListener("click", () => load(ev.symbol));
  return li;
}

function toast(ev) {
  const card = el("div", { class: `card ev-${ev.type}` }, el("b", {}, ev.title), el("p", {}, ev.body),
    sourceLinks(ev.sources, ev.found === false ? "참고 기사" : "근거 기사"));
  card.addEventListener("click", () => { if (ev.symbol) load(ev.symbol); card.remove(); });
  $("#toasts").prepend(card);
  setTimeout(() => card.remove(), 12000);
  if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
    const n = new Notification(ev.title, { body: ev.body, tag: ev.key });
    n.onclick = () => { window.focus(); load(ev.symbol); };
  }
}

function onAlert(ev) {
  $("#alerts").querySelector(".muted")?.remove();
  $("#alerts").prepend(alertItem(ev));
  if (state.tab !== "alerts" || $("#app").classList.contains("collapsed")) $("#alert-badge").hidden = false;
  toast(ev);
  if (ev.symbol === state.data?.symbol) $("#chart").animate([{ outline: "2px solid var(--resistance)" }, { outline: "none" }], 1500);
}

async function initAlerts() {
  const status = await (await fetch("/api/status")).json();
  const a = status.alert;
  $("#alert-status").textContent = status.toss
    ? `관심종목을 ${a.poll_sec}초마다 확인해요. 지지/저항선·추세선·내가 그은 선까지 ${a.near_pct}% 이내로 오거나 넘으면, `
      + "그리고 장 마감 후 매매 신호가 확정되면 알려줘요."
      + (status.telegram ? " 텔레그램 전송 켜짐." : "")
    : "토스 API 키가 있어야 알림이 동작해요.";
  const items = (await (await fetch("/api/alerts?limit=30")).json()).items;
  $("#alerts").replaceChildren(...(items.length ? items.map(alertItem) : [el("li", { class: "muted" }, "아직 알림이 없어요")]));

  const es = new EventSource("/api/alerts/stream");
  es.onmessage = (m) => onAlert(JSON.parse(m.data));

  const btn = $("#notify-btn");
  if (!("Notification" in window) || Notification.permission === "granted") btn.hidden = true;
  btn.addEventListener("click", async () => { if ((await Notification.requestPermission()) === "granted") btn.hidden = true; });
  $("#check-btn").addEventListener("click", async () => {
    const res = await fetch("/api/alerts/check", { method: "POST" });
    const body = await res.json();
    if (!res.ok) return banner(body.detail, "error");
    if (!body.new.length) toast({ type: "info", title: "새 알림 없음", body: "관심종목 모두 선 근처가 아니거나, 오늘 이미 알린 선이에요.", key: "none" });
  });
}

// ── 실시간 시세 (서버가 토스 WebSocket 을 중계한 SSE) ──
let liveSource = null, liveKey = "", listRenderQueued = false;

function updateLiveSubscription() {
  if (!state.toss) return;
  const cur = state.data?.macro ? null : state.data?.symbol;      // 지표(야후)는 토스 실시간이 없음
  const symbols = [...new Set([cur, ...state.watchlist, ...state.holdings.map((h) => h.symbol), ...marketLiveSymbols()].filter(Boolean))].slice(0, 50);
  const key = symbols.slice().sort().join(",");
  if (key === liveKey) return;
  liveKey = key;
  liveSource?.close();
  if (!symbols.length) return;
  liveSource = new EventSource(`/api/live?symbols=${encodeURIComponent(symbols.join(","))}`);
  liveSource.onmessage = (m) => Object.entries(JSON.parse(m.data)).forEach(([s, tick]) => onTick(s, tick));
  liveSource.onopen = () => $("#live-dot").classList.add("on");
  liveSource.onerror = () => $("#live-dot").classList.remove("on");
}

const marketTz = (market) => (market === "US" ? "America/New_York" : "Asia/Seoul");
const dayIn = (tz, epochSec) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date(epochSec * 1000));
const mondayOf = (day) => {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
};
const samePeriod = (a, b, iv) => (iv === "1w" ? mondayOf(a) === mondayOf(b) : iv === "1M" ? a.slice(0, 7) === b.slice(0, 7) : iv === "1y" ? a.slice(0, 4) === b.slice(0, 4) : a === b);
const MINUTES = { "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "60m": 60 };

// 체결 하나로 차트 마지막 봉을 갱신하거나 새 봉을 연다
function updateLastBar(price, tsIso) {
  const d = state.data;
  const bars = d.candles, last = bars.at(-1);
  const epoch = Math.floor(Date.parse(tsIso) / 1000);
  let time, same;
  if (d.intraday) {
    const step = MINUTES[d.interval] * 60, t = epoch + 9 * 3600;   // 서버와 같은 한국 시간 축
    time = t - (t % step);
    if (time < last.time) return;
    same = time === last.time;
  } else {
    time = dayIn(marketTz(d.market), epoch);
    if (time < last.time) return;
    same = samePeriod(last.time, time, d.interval);
  }
  if (same) {
    last.high = Math.max(last.high, price);
    last.low = Math.min(last.low, price);
    last.close = price;
    candles.update({ ...last });
  } else {
    const bar = { time, open: price, high: price, low: price, close: price, volume: 0 };
    bars.push(bar);
    candles.update({ ...bar });
    volume.update({ time, value: 0 });
  }
  refreshIndicatorsLive();
}

function onTick(symbol, tick) {
  if (symbol === state.data?.symbol) {
    renderPrice(tick.price);
    updateLastBar(tick.price, tick.ts);
  }
  const w = state.watchSummary[symbol];
  if (w && !w.error) {
    w.prev ??= w.price / (1 + w.change_pct / 100);
    w.price = tick.price;
    w.change_pct = (tick.price / w.prev - 1) * 100;
  }
  // 시장 탭의 실시간 ETF
  for (const g of state.market) {
    if (!g.live) continue;
    const it = g.items.find((i) => i.symbol === symbol && !i.error);
    if (!it) continue;
    it.last = tick.price;
    it.change = tick.price - it.prev;
    it.change_pct = (tick.price / it.prev - 1) * 100;
    if (!marketRenderQueued && state.tab === "market") {
      marketRenderQueued = true;
      requestAnimationFrame(() => { marketRenderQueued = false; renderMarket(); });
    }
  }
  const h = heldOf(symbol);
  if (h) {
    const fx = h.currency === "USD" ? state.usdKrw || 0 : 1;
    h.last_price = tick.price;
    h.market_value = h.quantity * tick.price;
    h.market_value_krw = h.market_value * fx;
    h.pl_amount_krw = (tick.price - h.avg_price) * h.quantity * fx;
    h.pl_rate = (tick.price / h.avg_price - 1) * 100;
  }
  if ((w || h) && !listRenderQueued) {          // 목록은 한 프레임에 한 번만 다시 그림
    listRenderQueued = true;
    requestAnimationFrame(() => { listRenderQueued = false; renderWatchlist(); renderHoldings(); });
  }
}

// ── 시작 ──
$("#search").addEventListener("submit", (e) => { e.preventDefault(); submitSearch(); });
buildIndicatorMenu();
renderIndicatorChips();
volume.applyOptions({ visible: on("volume") });
(async () => {
  state.watchlist = (await (await fetch("/api/watchlist")).json()).symbols;
  renderWatchlist();
  initAlerts();
  loadSignalSettings();
  state.toss = (await (await fetch("/api/status")).json()).toss;
  renderIntervalBar();
  await loadHoldings();
  setTab(store.load("stocking.tab", state.holdings.length ? "holdings" : "watch"));
  setCollapsed(isPhone() ? true : store.load("stocking.sideCollapsed", false));   // 폰은 차트부터
  loadWatchSummary();
  setInterval(loadWatchSummary, 60000);    // 실시간이 못 주는 등락률 기준값·지지/저항 거리 보정
  load(new URLSearchParams(location.search).get("s") || state.holdings[0]?.symbol || state.watchlist[0] || "AAPL");
})();

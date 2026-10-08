"""지지/저항선 알림.

관심종목의 현재가를 주기적으로 조회해서
- 근접: 선까지 near_pct% 이내로 다가옴
- 돌파/이탈: 직전 조회가와 이번 조회가 사이에 선을 건넘
이면 이벤트를 만든다. 같은 종목·같은 선·같은 종류 알림은 하루 한 번만.

전달: 브라우저(SSE) + 텔레그램(선택).
"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import date, datetime
from pathlib import Path

import httpx

from backend.config import Settings

# (선 종류, 건넌 방향) → (이벤트 타입, 제목 꼬리, 본문). {side}=선 이름(지지선/상승 추세선/내 선 ...)
_LABELS = {
    ("resistance", "up"): ("breakout", "돌파", "{name} {side} {lv}을 뚫고 올라갔어요."),
    ("support", "down"): ("breakdown", "이탈", "{name} {side} {lv} 아래로 내려갔어요."),
    ("support", "up"): ("reclaim", "회복", "{name} {side} {lv} 위로 다시 올라왔어요."),
    ("resistance", "down"): ("reject", "아래 복귀", "{name} {side} {lv} 아래로 다시 내려왔어요."),
}
_HISTORY = {"support": " 과거 {t}번 반등했던 가격대예요.", "resistance": " 과거 {t}번 막혔던 가격대예요."}


def subject(name: str) -> str:
    """이름 + 주격조사. 마지막 글자가 한글이면 받침 따라 이/가, 아니면 '이(가)'."""
    last = name[-1:]
    if "가" <= last <= "힣":
        return name + ("이" if (ord(last) - 0xAC00) % 28 else "가")
    return name + "이(가)"


def detect(symbol: str, name: str, prev: float | None, price: float,
           levels: dict, near_pct: float, fmt) -> list[dict]:
    """순수 함수: 직전가·현재가·선 목록 → 이벤트 목록 (쿨다운 전)."""
    events = []
    for kind in ("support", "resistance"):
        for lv in levels.get(kind, []):
            p = lv["price"]
            crossed = None
            if prev is not None:
                if prev < p <= price:
                    crossed = "up"
                elif prev > p >= price:
                    crossed = "down"
            side = lv.get("label") or ("지지선" if kind == "support" else "저항선")
            if crossed:
                etype, tail, body = _LABELS[(kind, crossed)]
            elif abs(price / p - 1) * 100 <= near_pct:
                etype, tail = "near", "근접"
                body = f"{{name}} {{side}} {{lv}}까지 {abs(price / p - 1) * 100:.1f}% 남았어요."
            else:
                continue
            if lv.get("touches"):
                body += _HISTORY[kind]
            events.append({
                "key": f"{symbol}:{etype}:{lv.get('id') or p}",
                "type": etype,
                "kind": kind,
                "symbol": symbol,
                "name": name,
                "title": f"{symbol} {side} {tail}",
                "body": body.format(name=subject(name), side=side, lv=fmt(p), t=lv.get("touches"))
                        + f" 현재가 {fmt(price)}",
                "level": p,
                "price": price,
            })
    return events


class Store:
    """data/*.json 에 관심종목·알림 기록 저장."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.watch_path = root / "watchlist.json"
        self.log_path = root / "alerts.json"
        self.drawings_path = root / "drawings.json"
        self.settings_path = root / "settings.json"

    def _read(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return default

    def _write(self, path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")

    def watchlist(self) -> list[str]:
        # 저장된 게 없으면(무료 서버는 재시작 때 파일이 지워짐) 환경변수 DEFAULT_WATCHLIST="MSTR,BE,INTC" 로 시작
        default = [s.strip().upper() for s in os.getenv("DEFAULT_WATCHLIST", "AAPL,NVDA,TSLA,MSFT").split(",") if s.strip()]
        return self._read(self.watch_path, default)

    def set_watchlist(self, symbols: list[str]) -> None:
        self._write(self.watch_path, symbols)

    def drawings(self, symbol: str) -> list[dict]:
        return self._read(self.drawings_path, {}).get(symbol, [])

    def set_drawings(self, symbol: str, drawings: list[dict]) -> None:
        all_ = self._read(self.drawings_path, {})
        all_[symbol] = drawings
        self._write(self.drawings_path, {k: v for k, v in all_.items() if v})

    def settings(self) -> dict:
        return self._read(self.settings_path, {})

    def update_settings(self, **values) -> dict:
        merged = {**self.settings(), **values}
        self._write(self.settings_path, merged)
        return merged

    def alerted(self, key: str) -> bool:
        return any(a.get("key") == key for a in self.alerts())

    def alerts(self) -> list[dict]:
        return self._read(self.log_path, [])

    def add_alert(self, event: dict) -> None:
        self._write(self.log_path, ([event] + self.alerts())[:200])


class Monitor:
    def __init__(self, settings: Settings, store: Store, load_levels, fetch_prices, formatter, load_signals=None,
                 check_move=None):
        """load_levels(symbol) -> (name, currency, levels) / fetch_prices(symbols) -> {symbol: price}
        load_signals(symbol) -> [알림 이벤트] : 가장 최근 확정 봉에서 새로 난 매매 신호 (key 포함)."""
        self.settings = settings
        self.store = store
        self.load_levels = load_levels
        self.load_signals = load_signals
        self.check_move = check_move      # check_move(symbol, price) -> [급등락 알림] (이유 찾기 포함, 느릴 수 있음)
        self.fetch_prices = fetch_prices
        self.formatter = formatter
        self.last_price: dict[str, float] = {}
        self.fired: set[str] = set()
        self.fired_day = date.today()
        self.subscribers: set[asyncio.Queue] = set()
        self.last_run: str | None = None
        self.last_error: str | None = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    async def run_forever(self) -> None:
        await asyncio.sleep(5)      # 서버 재시작 후 열려있던 브라우저가 재연결할 시간
        while True:
            try:
                await self.tick()
                self.last_error = None
            except Exception as error:          # 네트워크 오류 등으로 루프가 죽지 않게
                self.last_error = f"{type(error).__name__}: {error}"
                print(f"[alerts] {self.last_error}")
            await asyncio.sleep(self.settings.alert_poll_sec)

    async def tick(self) -> list[dict]:
        symbols = self.store.watchlist()
        if not symbols:
            return []
        if date.today() != self.fired_day:
            self.fired.clear()
            self.fired_day = date.today()

        prices = await asyncio.to_thread(self.fetch_prices, symbols)
        new_events = []
        for symbol in symbols:
            # 확정 매매 신호: key 에 봉 날짜가 들어 있어서, 재시작해도 알림 기록에 있으면 다시 안 보낸다
            if self.load_signals:
                try:
                    for ev in await asyncio.to_thread(self.load_signals, symbol):
                        if ev["key"] in self.fired or self.store.alerted(ev["key"]):
                            continue
                        self.fired.add(ev["key"])
                        ev["at"] = datetime.now().isoformat(timespec="seconds")
                        new_events.append(ev)
                except Exception as error:
                    print(f"[alerts] {symbol} 신호 계산 실패: {error}")
            price = prices.get(symbol)
            if price is None:
                continue
            # 급등락: 이미 알린 단계면 이유 찾기(LLM)를 다시 부르지 않도록 seen 을 넘긴다
            if self.check_move:
                seen = lambda k: k in self.fired or self.store.alerted(k)
                try:
                    for ev in await asyncio.to_thread(self.check_move, symbol, price, seen):
                        self.fired.add(ev["key"])
                        ev["at"] = datetime.now().isoformat(timespec="seconds")
                        new_events.append(ev)
                except Exception as error:
                    print(f"[alerts] {symbol} 급등락 확인 실패: {error}")
            try:
                name, currency, levels = await asyncio.to_thread(self.load_levels, symbol)
            except Exception as error:      # 한 종목 실패가 나머지 알림을 막지 않게
                print(f"[alerts] {symbol} 선 계산 실패: {error}")
                continue
            events = detect(symbol, name, self.last_price.get(symbol), price, levels,
                            self.settings.alert_near_pct, self.formatter(currency))
            self.last_price[symbol] = price
            for ev in events:
                if ev["key"] in self.fired:
                    continue
                self.fired.add(ev["key"])
                ev["at"] = datetime.now().isoformat(timespec="seconds")
                new_events.append(ev)

        for ev in new_events:
            self.store.add_alert(ev)
            for q in list(self.subscribers):
                if not q.full():
                    q.put_nowait(ev)
            links = "".join(f"\n- {s['title']}: {s['url']}" for s in ev.get("sources", []))
            await asyncio.to_thread(send_telegram, self.settings, f"[{ev['title']}]\n{ev['body']}{links}")
        self.last_run = datetime.now().isoformat(timespec="seconds")
        return new_events


def send_telegram(settings: Settings, text: str) -> None:
    if not settings.telegram_enabled:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=10.0,
        )
    except httpx.HTTPError as error:
        print(f"[alerts] 텔레그램 전송 실패: {type(error).__name__}")

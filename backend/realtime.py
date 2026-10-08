"""토스 실시간 체결 WebSocket → 브라우저(SSE) 중계.

토스 규칙 (asyncapi 명세):
- wss://openapi-ws.tossinvest.com/ws/v1, handshake 에 Bearer 토큰. 허용 IP 는 REST 와 동일
- 계정당 연결 2개, 연결당 구독 100건, 선언 5회/초
- 구독은 '선언형': JSON 배열 하나가 곧 전체 구독. 바꿀 땐 전체를 다시 보낸다
- 180초간 클라이언트 송신이 없으면 끊음 → 60초마다 텍스트 'PING'
- 시세는 유실될 수 있음(LOSSY). 최신값만 의미 있음

그래서 서버가 연결 하나만 유지하고, 브라우저들이 보고 싶은 종목의 합집합을 선언한다.
체결이 몰려도 화면이 버벅이지 않게 종목별 최신값만 0.3초마다 묶어서 보낸다.
"""
from __future__ import annotations
import asyncio
import itertools
import json
import random

from backend.config import market_of

WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
MAX_CODES = 100
FLUSH_SEC = 0.3
PING_SEC = 60


class Hub:
    def __init__(self, get_token):
        """get_token() -> access token (동기 함수, 스레드에서 호출)."""
        self.get_token = get_token
        self.subs: dict[int, tuple[set[str], asyncio.Queue]] = {}
        self._ids = itertools.count(1)
        self.pending: dict[str, dict] = {}        # 아직 안 보낸 종목별 최신 체결
        self.latest: dict[str, dict] = {}          # 종목별 마지막 체결 (새 구독자에게 바로 보여줄 값)
        self.changed = asyncio.Event()
        self.connected = False
        self.last_error: str | None = None
        self.rejected: dict[str, str] = {}

    # ── 구독자 (브라우저 SSE 연결 하나 = 구독자 하나) ──
    def add(self, symbols: set[str]) -> tuple[int, asyncio.Queue]:
        sid = next(self._ids)
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subs[sid] = (symbols, q)
        self.changed.set()
        snapshot = {s: self.latest[s] for s in symbols if s in self.latest}
        if snapshot:
            q.put_nowait(snapshot)
        return sid, q

    def remove(self, sid: int) -> None:
        self.subs.pop(sid, None)
        self.changed.set()

    def desired(self) -> list[str]:
        wanted: list[str] = []
        for symbols, _ in self.subs.values():
            for s in sorted(symbols):
                if s not in wanted and s not in self.rejected:
                    wanted.append(s)
        return wanted[:MAX_CODES]

    def declaration(self) -> list[dict]:
        kr = [s for s in self.desired() if market_of(s) == "KR"]
        us = [s for s in self.desired() if market_of(s) == "US"]
        decl: list[dict] = []
        if kr:
            decl.append({"type": "trade:kr", "codes": kr})
        if us:
            decl.append({"type": "trade:us", "codes": us})
        return decl

    # ── 수신 처리 ──
    def on_frame(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        kind = msg.get("type")
        if kind == "message" and str(msg.get("topic", "")).startswith("trade:"):
            symbol = msg["topic"].split(":", 2)[2]
            d = msg["data"]
            tick = {"price": float(d["price"]), "volume": float(d["volume"]),
                    "ts": d["timestamp"], "currency": d.get("currency")}
            self.pending[symbol] = tick
            self.latest[symbol] = tick
        elif kind == "subscriptions":
            for r in msg.get("rejected", []):
                symbol = r["target"].split(":", 2)[-1]
                self.rejected[symbol] = r.get("code", "rejected")   # 같은 이유로 또 거부되니 다음 선언에서 뺀다
            if msg.get("rejected"):
                self.changed.set()
        elif kind == "error":
            self.last_error = f"{msg['error'].get('code')}: {msg['error'].get('message')}"
            if msg["error"].get("code") == "rate-limit-exceeded":
                self.changed.set()
            if msg["error"].get("code") == "server-shutdown":
                raise ConnectionError("server-shutdown")

    def flush(self) -> None:
        if not self.pending:
            return
        batch, self.pending = self.pending, {}
        for symbols, q in list(self.subs.values()):
            part = {s: t for s, t in batch.items() if s in symbols}
            if part and not q.full():
                q.put_nowait(part)

    # ── 연결 유지 ──
    async def run_forever(self) -> None:
        from websockets.asyncio.client import connect

        backoff = 1.0
        while True:
            if not self.subs:                       # 보는 사람이 없으면 연결 슬롯(계정당 2개)을 쓰지 않는다
                self.changed.clear()
                await self.changed.wait()
                continue
            try:
                token = await asyncio.to_thread(self.get_token)
                async with connect(WS_URL, additional_headers={"Authorization": f"Bearer {token}"},
                                   ping_interval=None, open_timeout=10) as ws:
                    self.connected, self.last_error, backoff = True, None, 1.0
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
                print(f"[realtime] 연결 끊김: {self.last_error}")
            finally:
                self.connected = False
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 30)

    async def _session(self, ws) -> None:
        declared = None

        async def declarer():
            nonlocal declared
            while True:
                decl = self.declaration()
                if decl != declared:
                    await ws.send(json.dumps(decl))
                    declared = decl
                    await asyncio.sleep(0.25)       # 선언 5회/초 제한
                self.changed.clear()
                await self.changed.wait()
                await asyncio.sleep(0.2)            # 탭 전환 등으로 연달아 바뀌면 한 번에

        async def pinger():
            while True:
                await asyncio.sleep(PING_SEC)
                await ws.send("PING")

        async def flusher():
            while True:
                await asyncio.sleep(FLUSH_SEC)
                self.flush()

        async def reader():
            async for raw in ws:
                self.on_frame(raw)
                if not self.subs:
                    await ws.send("[]")
                    return                          # 아무도 안 보면 연결 닫기

        tasks = [asyncio.create_task(t()) for t in (declarer, pinger, flusher, reader)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.exception():
                    raise t.exception()
        finally:
            for t in tasks:
                t.cancel()

"""토스증권 Open API 클라이언트 (조회 전용).

주의할 점 (공식 명세 기준):
- 토큰은 client 당 1개만 유효. 재발급하면 이전 토큰이 즉시 무효화된다.
  → 파일에 캐시해두고 만료 전까지 재사용한다. 서버 재시작해도 재발급 안 하도록.
- refresh token 없음. 만료되면 /oauth2/token 다시 호출.
- 성공 응답은 {"result": ...} envelope, 실패는 {"error": {...}}.
- 429 는 Retry-After 만큼 기다렸다 재시도.
- 주문 API 는 일부러 넣지 않았다. 필요해지면 별도 모듈 + 이중 확인으로 추가.
- 계좌는 accounts/holdings 조회만. 토스 앱의 '관심종목'은 Open API 에 없다.
"""
from __future__ import annotations
import json
import threading
import time
from datetime import datetime

import httpx

from backend.config import Settings

BASE_URL = "https://openapi.tossinvest.com"
_TOKEN_MARGIN_SEC = 60


class TossApiError(RuntimeError):
    def __init__(self, status: int, payload: dict | str):
        self.status = status
        self.payload = payload
        super().__init__(f"Toss API {status}: {payload}")


class TossClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http = httpx.Client(base_url=BASE_URL, timeout=10.0)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self._load_cached_token()

    # ── 토큰 ──
    def _load_cached_token(self) -> None:
        path = self.settings.token_cache_path
        if not path.exists():
            return
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("client_id") == self.settings.toss_client_id:
                self._token = cached["access_token"]
                self._expires_at = float(cached["expires_at"])
        except (ValueError, KeyError):
            pass

    def _issue_token(self) -> None:
        resp = self._http.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.toss_client_id,
                "client_secret": self.settings.toss_client_secret,
            },
        )
        if resp.status_code != 200:
            raise TossApiError(resp.status_code, _safe_json(resp))
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body["expires_in"])
        self.settings.token_cache_path.write_text(
            json.dumps({
                "client_id": self.settings.toss_client_id,
                "access_token": self._token,
                "expires_at": self._expires_at,
            }),
            encoding="utf-8",
        )

    def _get_token(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._token or time.time() > self._expires_at - _TOKEN_MARGIN_SEC:
                self._issue_token()
            return self._token  # type: ignore[return-value]

    # ── 공통 GET ──
    def _get(self, path: str, params: dict, headers: dict | None = None) -> object:
        refreshed = False
        for attempt in range(4):
            resp = self._http.get(
                path, params=params,
                headers={"Authorization": f"Bearer {self._get_token()}", **(headers or {})},
            )
            if resp.status_code == 401 and not refreshed:
                self._get_token(force=True)
                refreshed = True
                continue
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 1.0 + attempt))
                time.sleep(min(wait, 5.0))
                continue
            if resp.status_code != 200:
                raise TossApiError(resp.status_code, _safe_json(resp))
            return resp.json()["result"]
        raise TossApiError(429, "rate limit: 재시도 초과")

    # ── 시세 ──
    def stock_info(self, symbol: str) -> dict:
        result = self._get("/api/v1/stocks", {"symbols": symbol})
        if not result:
            raise TossApiError(404, f"종목 없음: {symbol}")
        return result[0]  # type: ignore[index]

    def listed_stocks(self, market: str) -> list[dict]:
        """거래소별 전체 종목 (일 1회 갱신 데이터). 이름 검색용."""
        return self._get("/api/v1/stocks/all", {"market": market})  # type: ignore[return-value]

    # ── 계좌 (조회만) ──
    def brokerage_account_seq(self) -> int | None:
        accounts = self._get("/api/v1/accounts", {})
        for acc in accounts:  # type: ignore[union-attr]
            if acc.get("accountType") == "BROKERAGE":
                return int(acc["accountSeq"])
        return None

    def usd_krw(self) -> float:
        """USD→KRW 매매기준율 (1분 주기 갱신). 보유종목을 원화로 보여줄 때만 쓴다."""
        r = self._get("/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"})
        return float(r["midRate"])  # type: ignore[index]

    def holdings(self, account_seq: int) -> dict:
        return self._get("/api/v1/holdings", {}, {"X-Tossinvest-Account": str(account_seq)})  # type: ignore[return-value]

    def prices(self, symbols: list[str]) -> dict[str, float]:
        """현재가 다건 조회 (최대 200개). 체결 없는 종목은 빠진다."""
        result = self._get("/api/v1/prices", {"symbols": ",".join(symbols[:200])})
        return {p["symbol"]: float(p["lastPrice"]) for p in result if p.get("lastPrice")}  # type: ignore[union-attr]

    def daily_candles(self, symbol: str, pages: int = 2) -> list[dict]:
        """일봉. 한 번에 최대 200개라 nextBefore 로 pages 만큼 이어 받는다."""
        return normalize_candles(self.raw_candles(symbol, "1d", pages))

    def minute_candles(self, symbol: str, pages: int = 2) -> list[dict]:
        """1분봉. time = 유닉스 초 (UTC)."""
        return normalize_minute_candles(self.raw_candles(symbol, "1m", pages))

    def raw_candles(self, symbol: str, interval: str, pages: int) -> list[dict]:
        """토스 캔들 API 가 주는 단위는 1m·1d 뿐. 나머지는 bars.py 에서 묶어 만든다."""
        candles: list[dict] = []
        before: str | None = None
        for _ in range(pages):
            params: dict = {"symbol": symbol, "interval": interval, "count": 200}
            if before:
                params["before"] = before  # httpx 가 '+' 를 %2B 로 인코딩해준다
            page = self._get("/api/v1/candles", params)
            candles.extend(page["candles"])  # type: ignore[index]
            before = page.get("nextBefore")  # type: ignore[union-attr]
            if not before:
                break
        return candles


def normalize_candles(raw: list[dict]) -> list[dict]:
    """토스 Candle(문자열 decimal) → 차트용 float dict, 날짜 오름차순·중복 제거."""
    by_date: dict[str, dict] = {}
    for c in raw:
        day = datetime.fromisoformat(c["timestamp"]).date().isoformat()
        by_date[day] = {
            "time": day,
            "open": float(c["openPrice"]),
            "high": float(c["highPrice"]),
            "low": float(c["lowPrice"]),
            "close": float(c["closePrice"]),
            "volume": float(c["volume"]),
        }
    return [by_date[d] for d in sorted(by_date)]


def normalize_minute_candles(raw: list[dict]) -> list[dict]:
    """1분봉 → time = 봉 '시작' 유닉스 초.

    명세엔 '봉 시작 시간'이라 돼 있지만 실제 응답은 봉이 끝나는 시각이다
    (2026-10-08 14:29:42 에 받은 진행 중 봉이 14:30:00). 실시간 체결을 같은 봉에 붙이려면 시작 시각이어야 해서 60초 당긴다.
    """
    by_ts: dict[int, dict] = {}
    for c in raw:
        ts = int(datetime.fromisoformat(c["timestamp"]).timestamp()) - 60
        by_ts[ts] = {
            "time": ts,
            "open": float(c["openPrice"]),
            "high": float(c["highPrice"]),
            "low": float(c["lowPrice"]),
            "close": float(c["closePrice"]),
            "volume": float(c["volume"]),
        }
    return [by_ts[t] for t in sorted(by_ts)]


def _safe_json(resp: httpx.Response) -> dict | str:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:300]

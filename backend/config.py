"""환경변수 설정. .env 는 프로젝트 루트에 둔다."""
from __future__ import annotations
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    toss_client_id: str
    toss_client_secret: str
    naver_client_id: str
    naver_client_secret: str
    finnhub_api_key: str
    openai_api_key: str
    openai_model: str
    token_cache_path: Path
    data_dir: Path
    alert_poll_sec: int
    alert_near_pct: float
    alert_move_pct: float
    telegram_bot_token: str
    telegram_chat_id: str
    app_password: str           # 이 PC 말고 다른 기기(노트북·폰)에서 접속할 때 필요한 비밀번호

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def finnhub_enabled(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def toss_enabled(self) -> bool:
        return bool(self.toss_client_id and self.toss_client_secret)

    @property
    def naver_enabled(self) -> bool:
        return bool(self.naver_client_id and self.naver_client_secret)

    @property
    def summary_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        toss_client_id=os.getenv("TOSS_CLIENT_ID", ""),
        toss_client_secret=os.getenv("TOSS_CLIENT_SECRET", ""),
        naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
        finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        # 서버(Render 등)에선 DATA_DIR 로 저장 위치를 바꿀 수 있게 (영구 디스크를 붙이면 거기로)
        token_cache_path=Path(os.getenv("DATA_DIR", ROOT / "data")) / ".token_cache.json" if os.getenv("DATA_DIR")
        else ROOT / ".token_cache.json",
        data_dir=Path(os.getenv("DATA_DIR", ROOT / "data")),
        alert_poll_sec=int(os.getenv("ALERT_POLL_SEC", "60")),
        alert_near_pct=float(os.getenv("ALERT_NEAR_PCT", "1.0")),
        alert_move_pct=float(os.getenv("ALERT_MOVE_PCT", "3.0")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        app_password=os.getenv("APP_PASSWORD", ""),
    )


def market_of(symbol: str) -> str:
    """KRX 종목은 숫자로 시작하는 6자리 (신규 코드는 0047P0 처럼 영문 섞임), 그 외는 미국 티커."""
    return "KR" if len(symbol) == 6 and symbol[0].isdigit() and symbol.isalnum() else "US"

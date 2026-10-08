import base64
from dataclasses import replace

from fastapi.testclient import TestClient

from backend import main


def _client(monkeypatch, password):
    s = replace(main.get_settings(), app_password=password, toss_client_id="", toss_client_secret="")
    monkeypatch.setattr(main, "get_settings", lambda: s)
    return TestClient(main.app)       # TestClient 의 접속 주소는 'testclient' → 이 PC(127.0.0.1)가 아닌 기기로 취급


def _basic(pw):
    return {"Authorization": "Basic " + base64.b64encode(f"me:{pw}".encode()).decode()}


def test_remote_needs_password(monkeypatch):
    c = _client(monkeypatch, "s3cret")
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers=_basic("wrong")).status_code == 401
    assert c.get("/api/status", headers=_basic("s3cret")).status_code == 200
    assert c.get("/healthz").status_code == 200          # 배포 상태 확인은 비밀번호 없이 (정보 없음)


def test_remote_blocked_when_no_password_set(monkeypatch):
    c = _client(monkeypatch, "")
    assert c.get("/api/status", headers=_basic("anything")).status_code == 403

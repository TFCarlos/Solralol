from __future__ import annotations

import requests

from app.services.lcu_service import LCUService


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_is_connected_refreshes_stale_lockfile_after_client_restarts(monkeypatch) -> None:
    service = LCUService()
    service.port = 1234
    service.auth_token = "old-token"
    service.session.headers["Authorization"] = "Basic old-token"
    urls: list[str] = []

    def get(url: str, **_kwargs):
        urls.append(url)
        if len(urls) == 1:
            raise requests.ConnectionError("old client process closed")
        return _Response(200)

    def refresh() -> bool:
        service.port = 5678
        service.auth_token = "new-token"
        return True

    monkeypatch.setattr(service.session, "get", get)
    monkeypatch.setattr(service, "refresh_connection", refresh)

    assert service.is_connected() is True
    assert urls == [
        "https://127.0.0.1:1234/lol-summoner/v1/current-summoner",
        "https://127.0.0.1:5678/lol-summoner/v1/current-summoner",
    ]


def test_is_connected_returns_false_when_client_is_closed(monkeypatch) -> None:
    service = LCUService()
    service.port = 1234
    service.auth_token = "old-token"
    monkeypatch.setattr(service.session, "get", lambda *_args, **_kwargs: _Response(503))
    monkeypatch.setattr(service, "refresh_connection", lambda: False)

    assert service.is_connected() is False


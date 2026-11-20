from __future__ import annotations

from backend.application import Application
from backend.saved_matches import _participant_sides
from app.services.riot_api_service import RiotApiError
import pytest


def test_lcu_team_mapping_uses_local_team_id_on_either_side():
    for local_team in (100, 200):
        source = [
            {"participantId": index + 1, "teamId": 100 if index < 5 else 200, "local": index == 0 if local_team == 100 else index == 5}
            for index in range(10)
        ]
        source[0 if local_team == 100 else 5]["teamId"] = local_team
        other_team = 200 if local_team == 100 else 100
        for player in source:
            if player["teamId"] == local_team:
                player["teamId"] = local_team
            else:
                player["teamId"] = other_team
        mapped, known = _participant_sides(source)
        assert known is True
        assert sum(player["side"] == "allied" for player in mapped) == 5
        assert sum(player["side"] == "enemy" for player in mapped) == 5
        assert mapped[0 if local_team == 100 else 5]["side"] == "allied"


def test_legacy_participants_without_local_identity_remain_unassigned():
    mapped, known = _participant_sides([{"teamId": 100}, {"teamId": 100}, {"teamId": 200}])
    assert known is False
    assert [player["side"] for player in mapped] == ["unknown", "unknown", "unknown"]


class _Settings:
    def __init__(self, key: str = ""): self.key = key
    def load(self): return {"riot_api_key": self.key} if self.key else {}


def _application(key: str = "test-key") -> Application:
    app = object.__new__(Application)
    app.settings = _Settings(key)
    app._riot_readiness = None
    import threading
    app._riot_readiness_guard = threading.Lock()
    return app


def test_riot_readiness_distinguishes_auth_permissions_rate_limit_and_network(monkeypatch):
    import backend.application as application

    class _Service:
        PLATFORM_BASE_URLS = {"euw1": "https://euw1.api.riotgames.com"}
        outcome = None
        calls = 0
        def __init__(self, *_args, **_kwargs): pass
        def _request(self, *_args):
            type(self).calls += 1
            if type(self).outcome is not None: raise type(self).outcome
            return {}

    monkeypatch.setattr(application, "RiotApiService", _Service)
    app = _application()
    for status, expected in ((401, "invalid"), (403, "forbidden"), (429, "rate_limited"), (None, "unavailable")):
        _Service.outcome = RiotApiError("safe test error", status, 35 if status == 429 else None)
        app._riot_readiness = None
        assert app._check_riot_readiness()["state"] == expected
    _Service.outcome = None
    app._riot_readiness = None
    first = app._check_riot_readiness()
    calls = _Service.calls
    assert first["state"] == "ready"
    assert app._check_riot_readiness() == first
    assert _Service.calls == calls


def test_missing_riot_key_is_reported_without_network_request(monkeypatch):
    import backend.application as application
    monkeypatch.setattr(application, "RiotApiService", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected request")))
    assert _application("")._check_riot_readiness()["state"] == "missing"


def test_saved_sync_requires_exactly_one_local_participant(monkeypatch):
    import backend.saved_matches as saved_matches

    class _Repository:
        def load_last_profile(self): return {"puuid": "private", "region": "euw1"}
        def load_saved_lcu_matches(self, _profile): return []
        def load(self, _profile): return {"matches": [{
            "stable_match_id": "EUW1_12345", "queue_id": 420, "participants": []
        }]}

    class _Tracker:
        def load_saved_sessions(self): return []

    monkeypatch.setattr(saved_matches, "_tracker", lambda: _Tracker())
    monkeypatch.setattr("backend.soloq_analyses.register_analysis", lambda *_args: {"status": "pending"})
    with pytest.raises(ValueError, match="participante local"):
        saved_matches._sync_saved_match("EUW1_12345", _Repository())


def test_champion_aliases_resolve_to_canonical_data_dragon_ids(monkeypatch, tmp_path):
    import backend.assets as assets

    monkeypatch.setattr(assets.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(assets, "_version", lambda: "16.1.1")
    resolved_paths = []
    monkeypatch.setattr(assets, "_data_url", lambda path, **_kwargs: resolved_paths.append(path.name if path else None) or "data:image/png;base64,test")
    monkeypatch.setattr(assets, "_cached_or_download", lambda _url, path: path)
    catalog = [
        {"id": "MonkeyKing", "key": "62", "name": "Wukong"},
        {"id": "Bard", "key": "432", "name": "Bard"},
        {"id": "Nunu", "key": "20", "name": "Nunu & Willump"},
        {"id": "KaiSa", "key": "145", "name": "Kai'Sa"},
        {"id": "Khazix", "key": "121", "name": "Kha'Zix"},
        {"id": "LeBlanc", "key": "7", "name": "LeBlanc"},
        {"id": "MissFortune", "key": "21", "name": "Miss Fortune"},
        {"id": "Belveth", "key": "200", "name": "Bel'Veth"},
        {"id": "Renata", "key": "888", "name": "Renata Glasc"},
    ]
    result = assets.resolve_home_assets(
        ["Wukong", "Bardo", "Nunu y Willump", "Nunu & Willump", "Kai'Sa", "Kha'Zix", "Leblanc", "Miss Fortune", "Bel'Veth", "Renata Glasc", "62", "432", "20", "145", "121", "7", "21", "200", "888"],
        None,
        catalog,
    )
    for champion_id in ("MonkeyKing", "Bard", "Nunu", "KaiSa", "Khazix", "LeBlanc", "MissFortune", "Belveth", "Renata"):
        assert f"{champion_id}.png" in resolved_paths
    assert set(result["champions"]) == {"MonkeyKing", "Bard", "Nunu", "KaiSa", "Khazix", "LeBlanc", "MissFortune", "Belveth", "Renata"}
    assert result["championAliases"]["Wukong"] == "MonkeyKing"
    assert result["championAliases"]["Bardo"] == "Bard"
    assert result["championAliases"]["Leblanc"] == "LeBlanc"
    for champion_key, champion_id in (("62", "MonkeyKing"), ("432", "Bard"), ("20", "Nunu"), ("145", "KaiSa"), ("121", "Khazix"), ("7", "LeBlanc"), ("21", "MissFortune"), ("200", "Belveth"), ("888", "Renata")):
        canonical = result["championAliases"][champion_key]
        assert canonical == champion_id
        assert result["champions"][canonical] == "data:image/png;base64,test"

"""Regression checks for Electron's Draft adapter without a live LCU client."""
from __future__ import annotations

from typing import Any

import pytest
import threading

from backend.draft import DraftRuntime
from backend.application import Application


class _Response:
    status_code = 200

    @staticmethod
    def json() -> str:
        return "ChampSelect"


class _Session:
    @staticmethod
    def get(*args: Any, **kwargs: Any) -> _Response:
        return _Response()


class _DisconnectedLCU:
    def is_connected(self) -> bool:
        return False


class _LiveLCU:
    port = 2999
    session = _Session()

    def is_connected(self) -> bool:
        return True

    def get_champ_select_session(self) -> dict[str, Any]:
        return {
            "localPlayerCellId": 0,
            "myTeam": [
                {"cellId": 0, "summonerName": "Player", "championId": 103, "assignedPosition": "middle"},
                {"cellId": 1, "championId": 0, "championPickIntent": 22},
            ],
            "theirTeam": [{"cellId": 5, "championId": 103, "assignedPosition": ""}],
            "actions": [[
                {"type": "pick", "championId": 103, "actorCellId": 0, "completed": True},
                {"type": "ban", "championId": 22, "actorCellId": 0, "isAllyAction": True},
                {"type": "ban", "championId": 103, "actorCellId": 5, "isAllyAction": False},
            ]],
        }


def _runtime(monkeypatch: pytest.MonkeyPatch) -> DraftRuntime:
    runtime = DraftRuntime(Application._load_champion_catalog())
    runtime.lcu = _DisconnectedLCU()
    runtime._analysis = lambda champion, role, enemies, allies, opposing: {
        "champion": champion, "role": role, "roleLabel": role, "profileAvailable": False,
        "variantStatus": "NO_LOCAL_DATA", "runes": [], "spells": [],
        "build": {"items": [], "boots": None}, "situational": [], "bans": [],
        "damage": {}, "powerCurve": {}, "matchups": [],
        "composition": {"allies": len([p for p in allies if p.get("champion")]),
                        "enemies": len([p for p in opposing if p.get("champion")]), "damageSamples": 0},
    }
    monkeypatch.setattr("backend.draft.resolve_meta_assets", lambda *args, **kwargs: {})
    runtime._rune_assets = lambda *args, **kwargs: None
    return runtime


def test_manual_draft_preserves_role_selection_and_empty_lcu_state(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    snapshot = runtime.snapshot({
        "champion": "Ahri", "role": "mid",
        "allies": [{"champion": "Ahri", "role": "mid", "locked": True}, {"champion": "Garen", "role": "top"}],
        "enemies": [{"champion": "Lux", "role": "mid"}],
        "manualBans": {"allies": ["Darius"], "enemies": ["Ashe"]},
    })
    assert snapshot["connection"] == "disconnected"
    assert snapshot["live"] is False
    assert snapshot["phase"] == "Disconnected"
    assert snapshot["allies"][0]["champion"] == "Ahri"
    assert snapshot["allies"][0]["role"] == "mid"
    assert snapshot["allies"][0]["locked"] is True
    assert snapshot["enemies"][0]["roleKnown"] is True
    assert snapshot["bans"] == {"allies": ["Darius"], "enemies": ["Ashe"]}
    assert snapshot["analysis"]["role"] == "mid"
    assert len(snapshot["allies"]) == len(snapshot["enemies"]) == 5


def test_real_local_repository_data_reaches_electron_draft_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = DraftRuntime(Application._load_champion_catalog())
    runtime.lcu = _DisconnectedLCU()
    monkeypatch.setattr("backend.draft.resolve_meta_assets", lambda *args, **kwargs: {})
    runtime._rune_assets = lambda *args, **kwargs: None
    snapshot = runtime.snapshot({"champion": "Ahri", "role": "mid", "allies": [{"champion": "Ahri", "role": "mid"}]})
    analysis = snapshot["analysis"]
    assert analysis["variantStatus"] == "AVAILABLE"
    assert len(analysis["runes"]) == 2
    assert len(analysis["builds"]) == 2
    assert analysis["spells"]
    assert analysis["build"]["items"]
    assert all(str(item["id"]).isdigit() for item in analysis["build"]["items"])


def test_application_dispatch_exposes_the_draft_snapshot_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    app = Application.__new__(Application)
    app._draft_lock = threading.RLock()
    app._draft_runtime = runtime
    app._storage_condition = threading.Condition(threading.RLock())
    app._storage_migration = {"state": "idle"}
    app._active_requests = 0
    response = app.dispatch("draft.snapshot", {"champion": "Ahri", "role": "mid"})
    assert response["rank"] == "emerald_plus"
    assert response["analysis"]["champion"] == "Ahri"


def test_live_draft_maps_picks_bans_and_marks_enemy_role_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    resolved_assets: list[str] = []
    monkeypatch.setattr("backend.draft.resolve_meta_assets", lambda champions, *args, **kwargs: (resolved_assets.extend(champions) or {}))
    runtime.lcu = _LiveLCU()
    runtime.analyzer.assign_likely_roles = lambda names: ["Top"] * len(names)
    snapshot = runtime.snapshot({"champion": "Ahri", "role": "mid"})
    assert snapshot["live"] is True
    assert snapshot["phase"] == "ChampSelect"
    assert snapshot["allies"][0]["champion"] == "Ahri"
    assert snapshot["allies"][0]["local"] is True
    assert snapshot["allies"][0]["locked"] is True
    assert snapshot["allies"][1]["intent"] == "Ashe"
    assert snapshot["enemies"][0]["champion"] == "Ahri"
    assert snapshot["enemies"][0]["roleKnown"] is False
    assert snapshot["bans"] == {"allies": ["Ashe"], "enemies": ["Ahri"]}
    assert "Ashe" in resolved_assets and "Ahri" in resolved_assets


def test_live_local_intent_owns_analysis_and_never_falls_back_to_manual_ahri(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    briar_id = next(champion_id for champion_id, name in runtime.by_id.items() if name == "Briar")
    session = {"localPlayerCellId": 0,
               "myTeam": [{"cellId": 0, "championId": 0, "championPickIntent": briar_id}],
               "theirTeam": [], "actions": []}
    runtime.lcu = _LiveLCU()
    runtime.lcu.get_champ_select_session = lambda: session
    analysis_champions = []
    runtime._analysis = lambda champion, role, enemies, allies, opposing: (analysis_champions.append(champion) or {
        "champion": champion, "role": role, "roleLabel": role, "profileAvailable": False,
        "variantStatus": "NO_LOCAL_DATA", "runes": [], "spells": [], "build": {}, "builds": [],
        "situational": [], "bans": [], "damage": {}, "powerCurve": {}, "matchups": [],
        "composition": {"allies": 1, "enemies": 0, "damageSamples": 0}})
    snapshot = runtime.snapshot({"champion": "Ahri", "role": "mid"},
                                {"connected": True, "phase": "ChampSelect", "session": session})
    assert snapshot["localChampion"] == "Briar"
    assert snapshot["analysis"]["champion"] == "Briar"
    assert analysis_champions == ["Briar"]
    session["actions"] = [[{"type": "pick", "championId": briar_id,
                            "actorCellId": 0, "completed": True}]]
    locked = runtime.snapshot({"champion": "Ahri", "role": "mid"},
                              {"connected": True, "phase": "ChampSelect", "session": session})
    assert locked["allies"][0]["locked"] is True
    assert locked["localChampion"] == "Briar"
    assert locked["analysis"]["champion"] == "Briar"


def test_live_draft_with_no_local_pick_does_not_show_any_champions_build(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    session = {"localPlayerCellId": 0,
               "myTeam": [{"cellId": 0, "championId": 0, "championPickIntent": 0}],
               "theirTeam": [], "actions": []}
    snapshot = runtime.snapshot({"champion": "Ahri", "role": "mid"},
                                {"connected": True, "phase": "ChampSelect", "session": session})
    assert snapshot["localChampion"] == ""
    assert snapshot["analysis"]["champion"] == ""
    assert snapshot["analysis"]["variantStatus"] == "NO_CHAMPION_SELECTED"


def test_draft_import_rejects_unavailable_selection_before_lcu_call(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(monkeypatch)
    with pytest.raises(ValueError, match="preparación"):
        runtime.import_selection({"kind": "all", "champion": "not-a-champion", "role": "mid", "pageIndex": 0})

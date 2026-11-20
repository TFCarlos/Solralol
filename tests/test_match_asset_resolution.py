"""Saved-match identifiers resolve through the shared, persistent asset cache."""
from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from backend import assets
from data_dragon import rune_icon_cache_path


PNG = b"\x89PNG\r\n\x1a\nfixture"


def test_match_build_uses_local_patch_or_cached_historical_version(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_item_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_version", lambda: "16.17.1")
    assert assets._version_for_patch("16.20.824.8524", tmp_path) == "16.20.1"

    (tmp_path / "versions.json").write_text(json.dumps(["16.20.1", "16.19.2", "16.19.1"]), encoding="utf-8")
    monkeypatch.setattr(assets.requests, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network request")))
    assert assets._version_for_patch("16.19.123.456", tmp_path) == "16.19.2"
    assert assets._version_for_patch("../../bad", tmp_path) == ""


def test_saved_match_items_runes_and_numeric_spells_use_patch_scoped_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "get_storage_manager", lambda: SimpleNamespace(ddragon_dir=tmp_path))
    monkeypatch.setattr(assets, "_item_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_version", lambda: "16.17.1")
    (tmp_path / "versions.json").write_text(json.dumps(["16.19.1"]), encoding="utf-8")
    monkeypatch.setattr(assets, "_rune_icons_by_id", lambda version: {"8005": "perk-images/Styles/Precision/PressTheAttack/PressTheAttack.png"})
    downloaded = []

    def download(url, path):
        downloaded.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return path

    monkeypatch.setattr(assets, "_cached_or_download", download)
    monkeypatch.setattr(assets, "_communitydragon_item_paths", lambda: (_ for _ in ()).throw(AssertionError("latest item fallback")))
    monkeypatch.setattr(assets, "_communitydragon_rune_paths", lambda: (_ for _ in ()).throw(AssertionError("latest rune fallback")))
    result = assets.resolve_meta_assets([], ["0", "1001", "2003", "3364"], [], [], ["8005", "999999"], ["4", "14", "999"], "16.19.500.42")

    assert "item:0" not in result
    assert all(result[f"item:{item}"] for item in ("1001", "2003", "3364"))
    assert result["rune:8005"] and result["rune:999999"] is None
    assert result["spell:4"] and result["spell:14"] and result["spell:999"] is None
    assert any(url.endswith("/16.19.1/img/spell/SummonerFlash.png") for url in downloaded)
    assert any(url.endswith("/16.19.1/img/spell/SummonerDot.png") for url in downloaded)
    assert all("/16.20.1/" not in url for url in downloaded)


def test_cached_match_assets_remain_available_without_network_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "get_storage_manager", lambda: SimpleNamespace(ddragon_dir=tmp_path))
    monkeypatch.setattr(assets, "_item_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_rune_icons_by_id", lambda version: {"8005": "perk-images/Styles/Precision/PressTheAttack/PressTheAttack.png"})
    for path in (tmp_path / "items" / "16.20.1" / "1001.png",
                 rune_icon_cache_path("16.20.1", "perk-images/Styles/Precision/PressTheAttack/PressTheAttack.png", tmp_path),
                 tmp_path / "spells" / "16.20.1" / "SummonerFlash.png"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
    monkeypatch.setattr(assets.requests, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network request")))
    result = assets.resolve_meta_assets([], ["1001"], [], [], ["8005"], ["4"], "16.20.824.8524")
    assert all(result.values())


def test_missing_icon_is_backed_off_without_repeated_downloads(tmp_path, monkeypatch):
    calls = []

    def unavailable(url, **_kwargs):
        calls.append(url)
        raise requests.HTTPError("fixture unavailable")

    monkeypatch.setattr(assets.requests, "get", unavailable)
    path = tmp_path / "items" / "16.20.1" / "9999.png"
    assert assets._cached_or_download("https://ddragon.leagueoflegends.com/cdn/16.20.1/img/item/9999.png", path) is None
    assert assets._cached_or_download("https://ddragon.leagueoflegends.com/cdn/16.20.1/img/item/9999.png", path) is None
    assert len(calls) == 1


def test_ability_request_does_not_replace_requested_summoner_spells(tmp_path, monkeypatch):
    data = tmp_path / "data"
    abilities = data / "champion_abilities"
    abilities.mkdir(parents=True)
    (abilities / "Ahri.json").write_text(json.dumps({"data": {"Ahri": {"spells": [{"image": {"full": "AhriQ.png"}}]}}}), encoding="utf-8")
    monkeypatch.setattr(assets, "DATA_DIR", data)
    monkeypatch.setattr(assets, "get_storage_manager", lambda: SimpleNamespace(ddragon_dir=tmp_path / "cache"))
    monkeypatch.setattr(assets, "_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_item_version", lambda: "16.20.1")

    def download(_url, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return path

    monkeypatch.setattr(assets, "_cached_or_download", download)
    result = assets.resolve_meta_assets([], [], [{"champion": "Ahri", "slot": "q"}],
                                        [{"id": "Ahri", "name": "Ahri", "key": "103"}], spells=["4"])
    assert result["ability:Ahri|q"] and result["spell:4"]

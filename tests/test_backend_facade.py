from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from backend.application import Application


def test_champion_analysis_uses_existing_local_repository() -> None:
    app = Application()

    assert len(app.dispatch("champions.list")) >= 150
    result = app.dispatch(
        "champions.analysis",
        {"champion": "Ahri", "lane": "mid", "rank": "emerald_plus"},
    )

    assert result["champion"] == "Ahri"
    assert result["rank"] == "emerald_plus"
    assert result["status"] == "AVAILABLE"
    assert isinstance(result["data"], dict)


@pytest.mark.parametrize(
    "params",
    [
        {"champion": "not-a-champion", "lane": "mid", "rank": "emerald_plus"},
        {"champion": "Ahri", "lane": "not-a-lane", "rank": "emerald_plus"},
        {"champion": "Ahri", "lane": "mid", "rank": "all"},
    ],
)
def test_analysis_rejects_invalid_identifiers(params: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Application().dispatch("champions.analysis", params)


def test_public_settings_never_return_credentials() -> None:
    result = Application().dispatch("settings.public")

    assert set(result) == {"riotApiKeyConfigured", "geminiApiKeyConfigured"}
    assert all(isinstance(value, bool) for value in result.values())


def test_bootstrap_unicode_contract_round_trips_as_utf8() -> None:
    result = Application().dispatch("app.bootstrap")
    analysis = next(feature for feature in result["features"] if feature["id"] == "analysis")
    assert analysis["label"] == "An\u00e1lisis local"
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    assert json.loads(encoded.decode("utf-8"))["features"] == result["features"]


def test_home_frontend_source_keeps_unicode_labels_and_svg_icons() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    shell = (root / "frontend/src/pages/App.tsx").read_text(encoding="utf-8")
    assert "Región no disponible" in home
    assert "Rendimiento por campeón" in home
    assert "Sincronizar" in home
    assert "Ã" not in home and "â" not in home and "�" not in home
    assert "<Icon className=\"nav-glyph\"" in shell
    assert "<WindowTitleBar" in shell


def test_sidebar_is_persisted_collapsible_and_responsive() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    shell = (root / "frontend/src/pages/App.tsx").read_text(encoding="utf-8")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert "localStorage.getItem('solralol.sidebarCollapsed')" in shell
    assert "setSidebarCollapsed((collapsed) => !collapsed)" in shell
    assert "aria-expanded={!sidebarCollapsed}" in shell
    assert "title={feature.label}" in shell
    assert "sidebar-toggle-label" in shell
    assert "SOLRALOL · DESKTOP" not in shell
    assert "sidebar-collapsed .rail" in styles
    assert "scrollbar-gutter:stable both-edges" in styles
    assert ".sidebar-toggle{width:100%" in styles
    assert "--sidebar-compact-control-size:36px" in styles
    assert "260ms cubic-bezier(.4,0,.2,1)" in styles
    assert ".sidebar-collapsed .nav-item{width:var(--sidebar-compact-control-size);height:var(--sidebar-compact-control-size)" in styles
    assert ".sidebar-collapsed .connection{width:var(--sidebar-compact-control-size);height:var(--sidebar-compact-control-size);flex:0 0 var(--sidebar-compact-control-size);grid-template-columns:1fr;grid-template-rows:1fr;place-items:center" in styles
    assert ".sidebar-collapsed .connection .status-dot,.sidebar-collapsed .connection-label{grid-area:1 / 1}" in styles
    assert "prefers-reduced-motion:reduce" in styles


def test_home_dashboard_keeps_match_history_height_independent_of_match_count() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert 'className="card home-card redesign-history-card"' in home
    assert 'className="redesign-match-list"' in home
    assert ".redesign-history-card{display:grid;grid-template-rows:auto minmax(0,1fr) auto" in styles
    assert "height:clamp(380px,48vh,540px)" in styles
    assert ".redesign-match-list{display:grid;grid-auto-rows:max-content" in styles
    assert "min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain" in styles
    assert "matches.slice(0, visible).map" in home
    assert "Cargar 25 partidas" in home
    assert "home.matches" in home and "home.match.detail" in home
    assert "@media(max-width:650px)" in styles and ".redesign-history-card{grid-row:auto;height:430px}" in styles


def test_home_assets_uses_canonical_ids_and_never_accepts_paths(monkeypatch, tmp_path) -> None:
    from pathlib import Path
    from backend import assets

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "items.json").write_text('{"version":"16.20.1"}', encoding="utf-8")
    (data_dir / "champion_catalog.json").write_text('{"version":"16.17.1"}', encoding="utf-8")
    cache = tmp_path / ".solralol" / "ddragon"
    (cache / "champions").mkdir(parents=True)
    (cache / "profileicons").mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n" + b"fixture"
    (cache / "champions" / "MonkeyKing.png").write_bytes(png)
    (cache / "profileicons" / "123.png").write_bytes(png)
    monkeypatch.setattr(assets, "DATA_DIR", data_dir)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(assets, "_cached_or_download", lambda *_args: None)
    assert assets._version() == "16.17.1"

    result = assets.resolve_home_assets(
        ["Wukong", "../items.json", "Ahri"], 123,
        [{"id": "MonkeyKing", "name": "Wukong"}, {"id": "Ahri", "name": "Ahri"}],
    )
    assert result["champions"]["MonkeyKing"].startswith("data:image/png;base64,")
    assert result["champions"]["Ahri"] is None
    assert set(result["champions"]) == {"MonkeyKing", "Ahri"}
    assert result["profileIcon"].startswith("data:image/png;base64,")


def test_home_assets_contract_maps_canonical_champion_keys(monkeypatch) -> None:
    import backend.application as application

    monkeypatch.setattr(
        application,
        "resolve_home_assets",
        lambda names, profile_id, _catalog: {"names": names, "profileIconId": profile_id},
    )
    result = Application().dispatch(
        "home.assets", {"champions": ["Briar", "Kayn", "Mordekaiser"], "profileIconId": 123}
    )
    assert result == {"names": ["Briar", "Kayn", "Mordekaiser"], "profileIconId": 123}
    with pytest.raises(ValueError):
        Application().dispatch("home.assets", {"champions": ["../private.png"] * 21})


def test_stdio_protocol_returns_structured_errors_and_successes() -> None:
    env = {**os.environ, "PYTHONUTF8": "1"}
    process = subprocess.run(
        [sys.executable, "-m", "backend.protocol"],
        input=(
            '{"protocol":1,"id":"ok","method":"app.bootstrap","params":{}}\n'
            '{"protocol":1,"id":"bad","method":"bad.method","params":{}}\n'
            'not json\n'
        ),
        text=True,
        capture_output=True,
        env=env,
        check=True,
        timeout=10,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]

    by_id = {item["id"]: item for item in responses}
    assert set(by_id) == {"ok", "bad", ""}
    assert by_id["ok"]["ok"] is True
    assert by_id["bad"]["error"]["code"] == "not_found"
    assert by_id[""]["error"]["code"] == "invalid_json"


def test_backend_facade_does_not_import_qt() -> None:
    assert not any(
        module.startswith(("PySide6", "PyQt5", "PyQt6"))
        for module in sys.modules
    )


def test_home_contract_uses_cached_history_and_excludes_account_identifiers(monkeypatch) -> None:
    profile = {
        "puuid": "private-puuid", "summonerId": "private-summoner",
        "gameName": "Invoker", "tagLine": "EUW", "summonerLevel": 40,
        "profileIconId": 1, "region": "EUW", "ranked": [], "collection": {},
    }
    match = {
        "stable_match_id": "EUW1_123", "game_id": "123", "result": "victory",
        "champion_name": "Ahri", "queue_id": "420", "started_at": "2026-10-18T12:00:00Z",
        "puuid": "private-puuid", "participants": [{"puuid": "another-private-id"}],
        "teammates": [{"puuid": "teammate-private-id", "name": "Streamer 1"}],
    }

    class Repository:
        def load_last_profile(self):
            return profile

        def load(self, _profile):
            return {"matches": [match], "last_sync": "2026-10-18T12:00:00Z"}

    monkeypatch.setattr("backend.application.HomeHistoryRepository", Repository)
    result = Application().dispatch("home.dashboard")

    assert result["profile"]["gameName"] == "Invoker"
    assert result["analytics"]["total"] == 1
    assert result["analytics"]["rolling_winrate"]["current_winrate"] == 100
    assert result["analytics"]["rolling_winrate"]["points"][0]["match_id"] == "EUW1_123"
    assert result["analytics"]["recent_performance"]["scope"] == "SoloQ (cola 420)"
    assert result["analytics"]["recent_performance"]["comparison_available"] is False
    assert result["analytics"]["champion_performance"] == []
    assert result["matches"][0]["champion_name"] == "Ahri"
    assert "puuid" not in result["profile"]
    assert "participants" not in result["matches"][0]
    assert "teammates" not in result["matches"][0]
    page = Application().dispatch("home.matches", {"offset": 1, "limit": 1})
    assert page["matches"] == []
    assert page["totalMatches"] == 1
    assert page["hasMore"] is False


def test_soloq_rolling_winrate_is_chronological_deduplicated_and_queue_scoped() -> None:
    from app.services.home_history_service import calculate_soloq_rolling_winrate

    matches = [
        {
            "stable_match_id": f"match-{index}",
            "game_id": str(index),
            "queue_id": 420,
            "started_at": f"2026-10-{index:02d}T12:00:00Z",
            "champion_name": "Briar",
            "result": "victory" if index <= 7 else "defeat",
        }
        for index in range(1, 12)
    ]
    matches.extend([
        {**matches[0], "champion_name": "Duplicate"},
        {**matches[0], "stable_match_id": "flex-match", "game_id": "flex-match", "queue_id": 440},
        {**matches[0], "stable_match_id": "aram-match", "game_id": "aram-match", "queue_id": 450},
    ])

    series = calculate_soloq_rolling_winrate(list(reversed(matches)))

    assert series["total_matches"] == 11
    assert series["points"][0]["match_id"] == "match-1"
    assert series["points"][0]["position"] == 1
    assert series["points"][8]["sample_size"] == 9
    assert series["points"][9]["sample_size"] == 10
    assert series["points"][9]["winrate"] == 70
    assert series["points"][10]["window_wins"] == 6
    assert series["points"][10]["window_losses"] == 4
    assert series["points"][10]["winrate"] == 60
    assert series["points"][10]["champion_name"] == "Briar"
    assert all(0 <= point["winrate"] <= 100 for point in series["points"])


def test_soloq_rolling_winrate_skips_incomplete_records_and_reports_empty_history() -> None:
    from app.services.home_history_service import calculate_soloq_rolling_winrate

    series = calculate_soloq_rolling_winrate([
        {"stable_match_id": "no-date", "queue_id": 420, "result": "victory"},
        {"stable_match_id": "no-result", "queue_id": 420, "started_at": "2026-10-18T12:00:00Z"},
        {"queue_id": 420, "result": "defeat", "started_at": "2026-10-18T12:00:00Z"},
        {"stable_match_id": "normal", "queue_id": 400, "started_at": "2026-10-18T12:00:00Z", "result": "victory"},
    ])

    assert series["points"] == []
    assert series["total_matches"] == 0
    assert series["overall_winrate"] is None
    assert series["incomplete_matches"] == 3


def test_soloq_rolling_winrate_uses_only_the_30_newest_ranked_matches() -> None:
    from datetime import datetime, timedelta

    from app.services.home_history_service import calculate_soloq_rolling_winrate

    start = datetime(2026, 9, 1, 12)
    matches = [
        {
            "stable_match_id": f"match-{index}",
            "queue_id": 420,
            "started_at": (start + timedelta(days=index - 1)).isoformat() + "Z",
            "result": "victory" if index <= 5 else "defeat",
        }
        for index in range(1, 36)
    ]
    series = calculate_soloq_rolling_winrate(matches)

    assert series["total_matches"] == 30
    assert series["points"][0]["match_id"] == "match-6"
    assert series["points"][-1]["match_id"] == "match-35"


def test_home_winrate_chart_falls_back_to_loaded_match_history() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    component = (root / "frontend/src/components/WinRateEvolution.tsx").read_text(encoding="utf-8")
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")

    assert "matches={data?.matches}" in home
    assert "buildSeriesFromMatches(matches)" in component
    assert "slice(-30)" in component


def test_home_starts_with_profile_and_has_no_redundant_intro_header() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8-sig")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8-sig")

    assert "PANEL PERSONAL" not in home
    assert "Tu actividad reciente y progreso en League of Legends." not in home
    assert home.index("<PlayerStatisticsCard") < home.index("<RankSummary")
    assert ".home-heading" not in styles


def test_home_activity_card_renders_hourly_daily_and_data_backed_insights() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert "function ActivityCard" in home
    assert "Array.from({ length: 24 }" in home
    assert "analytics?.busiest_hour" in home and "analytics?.busiest_day" in home
    assert ".redesign-hour-chart" in styles and ".redesign-weekdays" in styles

def test_home_frontend_renders_real_rolling_winrate_chart_without_requests_on_hover() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    component = (root / "frontend/src/components/WinRateEvolution.tsx").read_text(encoding="utf-8")
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    assert "Evoluci\u00f3n del Win Rate" in home
    assert "Win rate m\u00f3vil en partidas clasificatorias registradas" in home
    assert "Win rate m\u00f3vil:" in component
    assert "window_wins" in component and "window_losses" in component
    assert "onPointerEnter={() => setActivePosition(point.position)}" in component
    assert "window.solralol.request" not in component

def test_recent_performance_compares_latest_soloq_ten_to_previous_ten() -> None:
    from datetime import datetime, timedelta

    from app.services.home_history_service import analyze_recent_soloq_performance

    start = datetime(2026, 8, 1, 12)
    matches = []
    for index in range(20):
        old = index < 10
        matches.append({
            "stable_match_id": f"solo-{index}", "queue_id": 420,
            "started_at": (start + timedelta(days=index)).isoformat() + "Z",
            "result": "victory", "kills": 2 if old else 4, "deaths": 2,
            "assists": 2 if old else 4, "cs": 120 if old else 150,
            "duration_seconds": 1800, "vision_score": 20 if old else 30,
        })
    matches.extend([
        {**matches[0], "champion_name": "duplicate"},
        {**matches[0], "stable_match_id": "flex", "queue_id": 440, "started_at": "2026-09-01T12:00:00Z"},
    ])

    result = analyze_recent_soloq_performance(matches)

    assert result["recent_matches"] == result["previous_matches"] == 10
    assert result["comparison_available"] is True
    assert result["metrics"]["kda"]["previous"] == 2
    assert result["metrics"]["kda"]["current"] == 4
    assert result["metrics"]["kda"]["delta"] == 2
    assert result["metrics"]["cs_per_min"]["current"] == 5
    assert result["metrics"]["cs_per_min"]["delta"] == 1
    assert result["metrics"]["vision"]["current"] == 30
    assert result["metrics"]["vision"]["delta"] == 10
    assert result["trend"]["state"] == "improving"


def test_recent_performance_handles_zero_deaths_missing_vision_and_short_history() -> None:
    from datetime import datetime, timedelta

    from app.services.home_history_service import analyze_recent_soloq_performance

    start = datetime(2026, 8, 1, 12)
    matches = [
        {
            "stable_match_id": str(index), "queue_id": 420,
            "started_at": (start + timedelta(days=index)).isoformat() + "Z",
            "result": "victory", "kills": 2, "deaths": 0, "assists": 3,
            "cs": 100, "duration_seconds": 1200,
        }
        for index in range(19)
    ]
    result = analyze_recent_soloq_performance(matches)

    assert result["comparison_available"] is False
    assert result["recent_matches"] == 10 and result["previous_matches"] == 9
    assert result["metrics"]["kda"]["current"] is None
    assert result["metrics"]["kda"]["current_zero_deaths"] is True
    assert result["metrics"]["kda"]["delta"] is None
    assert result["metrics"]["vision"]["current"] is None
    assert result["metrics"]["cs_per_min"]["current"] == 5


def test_champion_performance_groups_canonical_ids_and_ranks_with_minimum_sample() -> None:
    from datetime import datetime, timedelta

    from app.services.home_history_service import aggregate_soloq_champion_performance

    start = datetime(2026, 8, 1, 12)
    matches = []
    for index in range(6):
        matches.append({
            "stable_match_id": f"ahri-{index}", "queue_id": 420,
            "started_at": (start + timedelta(days=index)).isoformat() + "Z",
            "result": "victory" if index < 5 else "defeat", "champion_id": 103,
            "kills": 4, "deaths": 2, "assists": 2,
        })
    for index in range(5):
        matches.append({
            "stable_match_id": f"briar-{index}", "queue_id": 420,
            "started_at": (start + timedelta(days=index + 10)).isoformat() + "Z",
            "result": "victory" if index < 4 else "defeat", "champion_id": 233,
            "kills": 2, "deaths": 2, "assists": 2,
        })
    matches.append({
        "stable_match_id": "kayn-1", "queue_id": 420,
        "started_at": (start + timedelta(days=20)).isoformat() + "Z",
        "result": "victory", "champion_id": 141,
        "kills": 9, "deaths": 0, "assists": 3,
    })
    catalog = [
        {"id": "Ahri", "key": "103", "name": "Ahri"},
        {"id": "Briar", "key": "233", "name": "Briar"},
        {"id": "Kayn", "key": "141", "name": "Kayn"},
    ]

    result = aggregate_soloq_champion_performance(matches, catalog)

    assert [row["champion_id"] for row in result] == ["Ahri", "Briar", "Kayn"]
    assert result[0]["matches"] == 6 and result[0]["winrate"] == 83.3
    assert result[0]["kda_ratio"] == 3
    assert result[1]["winrate"] == 80
    assert result[2]["sample_sufficient"] is False
    assert result[2]["kda_ratio"] is None


def test_home_performance_cards_use_existing_layout_and_assets_request() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    cards = (root / "frontend/src/components/HomePerformanceCards.tsx").read_text(encoding="utf-8")
    side = home[home.index('className="home-redesign-side"'):]
    assert side.index("<ChampionPerformance") < side.index("<RecentPerformanceCard")
    assert home.index('className="home-dashboard-tiles"') < home.index('className="home-redesign-side"')
    assert "ranked?.champions" in home
    assert "home.assets" in home and "champion.champion_id" in home
    assert "champion.winrate" in home and "champion.kda" in home
    assert "window.solralol.request" not in cards


def test_dashboard_sparklines_reuse_role_filtered_evolution_and_remove_redundant_analysis_panels() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    home = (root / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8")
    left = home[home.index('className="home-redesign-left"'):home.index('className="home-redesign-side"')]
    assert "<MiniSparkline" in home
    assert "performance_evolution_by_role?.[rankedRole]" in home
    assert "performance_score" in home
    assert "<PerformanceEvolutionCard" not in home
    assert "<WinLossComparisonCard" not in home and "<PerformanceInsightsCard" not in home
    assert left.index("<PlayerStatisticsCard") < left.index('className="home-dashboard-tiles"')
    assert left.count("className=\"card home-card") >= 3
    assert 'className="home-dashboard-tiles"' not in home[home.index('className="home-redesign-side"'):]
    assert "home-redesign-left{display:grid" in styles
    assert "player-stat-sparkline" in styles
    assert "home-dashboard-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in styles

def test_normalized_home_match_preserves_available_vision_score() -> None:
    from app.services.home_history_service import LCUHomeProvider

    match = LCUHomeProvider._normalize({
        "gameId": 1, "gameCreation": 1_780_000_000_000, "gameDuration": 1200,
        "queueId": 420,
        "participants": [{
            "participantId": 1, "puuid": "local-player", "championId": 233,
            "teamId": 100,
            "stats": {"win": True, "kills": 2, "deaths": 1, "assists": 3,
                       "minionsKilled": 100, "neutralMinionsKilled": 10,
                       "visionScore": 25},
        }],
    }, {"puuid": "local-player"})

    assert match is not None
    assert match["vision_score"] == 25


def test_home_assets_resolve_numeric_riot_champion_key_to_datadragon_id(monkeypatch, tmp_path) -> None:
    import backend.assets as assets

    legacy_icons = tmp_path / "champion_icons"
    legacy_icons.mkdir()
    (legacy_icons / "Briar.png").write_bytes(b"\x89PNG\r\n\x1a\nasset")
    monkeypatch.setattr(assets, "DATA_DIR", tmp_path)
    monkeypatch.setattr(assets, "_version", lambda: "16.17.1")
    monkeypatch.setattr(assets, "_cached_or_download", lambda _url, _path: None)

    resolved = assets.resolve_home_assets(["233"], None, [
        {"id": "Briar", "key": "233", "name": "Briar"},
    ])

    assert resolved["champions"]["Briar"].startswith("data:image/png;base64,")


def test_home_assets_resolve_numeric_key_to_canonical_champion(monkeypatch, tmp_path) -> None:
    import backend.assets as assets

    monkeypatch.setattr(assets, "DATA_DIR", tmp_path)
    monkeypatch.setattr(assets, "_version", lambda: "")

    resolved = assets.resolve_home_assets(["233"], None, [
        {"id": "Briar", "key": "233", "name": "Briar"},
    ])

    # A local/legacy cached icon may exist even with downloads disabled; the
    # public key must still be the catalog's canonical Data Dragon ID.
    assert set(resolved["champions"]) == {"Briar"}
    assert resolved["champions"]["Briar"] is None or resolved["champions"]["Briar"].startswith("data:image/png;base64,")


def test_collection_challenge_payload_preserves_rank_and_points_for_presentation() -> None:
    from app.services.home_history_service import LCUHomeProvider
    challenge = LCUHomeProvider._normalize_collection("challenges", {
        "overallChallengeLevel": "PLATINUM", "totalChallengeScore": 13075,
    })
    assert challenge == {"count": None, "points": 13075, "tier": "PLATINUM", "title": None}
    from pathlib import Path
    component = (Path(__file__).resolve().parents[1] / "frontend/src/pages/HomeDashboard.tsx").read_text(encoding="utf-8")
    assert "DESAF\u00cdOS Y T\u00cdTULO" in component and "MAESTR\u00cdAS DESTACADAS" in component
    assert "challenges.points" in component
    assert "challengeTier} \u00b7" not in component

def test_winrate_chart_tracks_its_container_without_stretching_or_backend_requests() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    component = (root / "frontend/src/components/WinRateEvolution.tsx").read_text(encoding="utf-8")
    styles = (root / "frontend/src/styles.css").read_text(encoding="utf-8")

    assert "new ResizeObserver" in component
    assert "observer.disconnect()" in component
    assert "viewBox={`0 0 ${size.width} ${size.height}`}" in component
    assert "size.width - PLOT.right" in component
    assert "size.height - PLOT.bottom" in component
    assert "width:min(100%,1080px);height:clamp(180px,15vw,240px)" in styles
    assert "height:clamp(175px,24vw,220px)" in styles
    assert "window.solralol.request" not in component

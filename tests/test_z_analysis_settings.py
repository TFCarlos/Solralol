from __future__ import annotations

import copy

import pytest

from backend import analysis_settings
from backend.battlescore_engine import calculate_match


def test_configuration_is_created_persisted_and_versioned(tmp_path, monkeypatch):
    target = tmp_path / "analysis_settings.json"
    monkeypatch.setattr(analysis_settings, "config_path", lambda: target)

    initial = analysis_settings.load_configuration()
    assert target.is_file()
    assert initial["general"]["initial_score"] == 5.0
    assert initial["analysis_limits"]["max_active_matches"] == 10

    draft = copy.deepcopy(initial)
    draft["rewards"]["kill"] = 0.45
    draft["penalties"]["death"] = 0.29
    draft["role_multipliers"]["JUNGLE"]["gold"] = 0.75
    saved = analysis_settings.save_configuration(draft)
    reloaded = analysis_settings.load_configuration()
    assert saved["configuration_version"] == initial["configuration_version"] + 1
    assert reloaded["rewards"]["kill"] == 0.45
    assert reloaded["penalties"]["death"] == 0.29
    assert reloaded["role_multipliers"]["JUNGLE"]["gold"] == 0.75
    assert target.with_suffix(".json.bak").is_file()


@pytest.mark.parametrize("mutate", [
    lambda config: config["rewards"].__setitem__("kill", float("nan")),
    lambda config: config["role_multipliers"]["MIDDLE"].__setitem__("kills", -1),
    lambda config: config["general"].__setitem__("minimum_score", 10),
    lambda config: config["recovery"].__setitem__("below_4_threshold", 2.5),
    lambda config: config["analysis_limits"].__setitem__("max_active_matches", 0),
])
def test_invalid_configuration_is_rejected(mutate):
    config = analysis_settings.default_configuration()
    config.pop("configuration_hash")
    mutate(config)
    with pytest.raises(ValueError):
        analysis_settings.validate_configuration(config)


def test_corrupt_configuration_recovers_from_backup_and_preserves_bad_file(tmp_path, monkeypatch):
    target = tmp_path / "analysis_settings.json"
    monkeypatch.setattr(analysis_settings, "config_path", lambda: target)
    baseline = analysis_settings.default_configuration()
    analysis_settings.save_configuration({key: value for key, value in baseline.items() if key != "configuration_hash"})
    backup = target.with_suffix(".json.bak")
    backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text("{broken", encoding="utf-8")

    recovered = analysis_settings.load_configuration()
    assert recovered["general"]["initial_score"] == 5.0
    assert target.is_file()
    assert list(tmp_path.glob("analysis_settings.json.corrupt.*"))


def test_engine_uses_custom_coefficients_role_multipliers_and_component_toggle():
    config = analysis_settings.default_configuration()
    config["rewards"]["kill"] = 0.40
    config["role_multipliers"]["MIDDLE"]["kills"] = 1.25
    config["enabled_components"]["first_blood"] = False
    result = calculate_match("configured", [
        {"participantId": 1, "role": "MIDDLE"}, {"participantId": 2, "role": "TOP"},
    ], [{"id": "kill-1", "timestamp": 30_000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 2}], [], 60,
        configuration=config)
    killer = next(row for row in result["participants"] if row["participantId"] == 1)
    assert killer["breakdown"]["kills"] == pytest.approx(0.5)
    assert result["configurationHash"]

    config["enabled_components"]["kills"] = False
    disabled = calculate_match("configured", [
        {"participantId": 1, "role": "MIDDLE"}, {"participantId": 2, "role": "TOP"},
    ], [{"id": "kill-1", "timestamp": 30_000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 2}], [], 60,
        configuration=config)
    killer_disabled = next(row for row in disabled["participants"] if row["participantId"] == 1)
    assert killer_disabled["breakdown"]["kills"] == 0
    assert killer_disabled["finalScore"] == pytest.approx(5.0)


def test_graph_preferences_do_not_change_canonical_scoring_resolution():
    config = analysis_settings.default_configuration()
    frames = [
        {"timestamp": 0, "participantId": 1, "gold": 0},
        {"timestamp": 30_000, "participantId": 1, "gold": 1000},
    ]
    config["visualization"]["sample_interval_ms"] = 60_000
    result = calculate_match("chart-only", [{"participantId": 1, "role": "TOP"}], [], frames, 60,
                             configuration=config)
    assert result["sampleIntervalMs"] == 10_000
    assert result["visualization"]["sample_interval_ms"] == 60_000


def test_custom_decay_gold_and_death_values_are_used_chronologically():
    config = analysis_settings.default_configuration()
    config["decay"]["grace_period_seconds"] = 120
    config["decay"]["normal_per_minute"] = 0.25
    config["rewards"]["gold_per_1000"] = 0.50
    config["penalties"]["death"] = 0.50
    config["role_multipliers"]["TOP"]["death"] = 1.0
    config["enabled_components"]["kills"] = False
    config["enabled_components"]["first_blood"] = False

    economy = calculate_match("gold-config", [{"participantId": 1, "role": "TOP"}], [], [
        {"timestamp": 0, "participantId": 1, "gold": 0},
        {"timestamp": 60_000, "participantId": 1, "gold": 1_000},
    ], 60, configuration=config)
    assert economy["participants"][0]["breakdown"]["gold"] == pytest.approx(0.45)
    assert economy["participants"][0]["finalScore"] == pytest.approx(5.45)

    death = calculate_match("death-config", [
        {"participantId": 1, "role": "TOP"}, {"participantId": 2, "role": "JUNGLE"},
    ], [{"id": "death-1", "timestamp": 180_000, "type": "CHAMPION_KILL", "killerId": 2, "victimId": 1}], [], 240,
        configuration=config)
    victim = next(row for row in death["participants"] if row["participantId"] == 1)
    assert victim["breakdown"]["time_decay"] == pytest.approx(-0.50)
    assert victim["breakdown"]["death_penalties"] == pytest.approx(-0.50)
    assert victim["finalScore"] == pytest.approx(4.00)


def test_unsupported_telemetry_provider_cannot_be_saved():
    config = analysis_settings.default_configuration()
    config.pop("configuration_hash")
    config["telemetry_sources"]["gold"]["fields"] = ["arbitrary.expression"]
    with pytest.raises(ValueError, match="fuentes de telemetría"):
        analysis_settings.validate_configuration(config)


def test_active_analyses_recalculate_from_saved_telemetry_and_store_config_audit(monkeypatch):
    from backend import soloq_analyses
    config = analysis_settings.default_configuration()
    config["rewards"]["gold_per_1000"] = 0.25
    # The candidate is a fully validated immutable batch snapshot.
    config = analysis_settings.validate_configuration({key: value for key, value in config.items() if key != "configuration_hash"})
    config["configuration_hash"] = analysis_settings._canonical_hash(config)
    record = {
        "match_id": "EUW1_123", "duration": 60, "timeline_available": True,
        "participants": [{"participantId": 1, "role": "TOP", "champion": "Garen"}],
        "events": [], "frames": [
            {"timestamp": 0, "participantId": 1, "gold": 0},
            {"timestamp": 60_000, "participantId": 1, "gold": 1_000},
        ], "battle_score": {"version": "battlescore_v2_7", "state": "partial"},
    }

    class Repository:
        saved = []
        def load_last_profile(self): return {"puuid": "fixture"}
        def load_saved_analyses(self, _profile): return [record]
        def load(self, _profile): return {"matches": []}
        def save_soloq_analysis(self, _profile, value): self.saved.append(copy.deepcopy(value))

    class Cache:
        data = {"timelines": {}}
        def get_timeline(self, _match_id): return None

    monkeypatch.setattr(soloq_analyses, "MatchHistoryCache", Cache)
    repository = Repository()
    progress = []
    outcome = soloq_analyses.recalculate_active_analyses(repository, config, lambda: True,
        lambda current, total, match_id, message: progress.append((current, total, match_id, message)))
    assert outcome == {"recalculated": 1, "skipped": 0}
    saved = repository.saved[-1]
    assert saved["battle_score"]["configurationHash"] == analysis_settings.engine_snapshot(config)["configuration_hash"]
    assert saved["battle_score"]["participants"][0]["breakdown"]["gold"] > 0
    assert saved["frames"] == record["frames"]
    assert len(progress) == 1


def test_configured_active_match_limit_is_used_by_analysis_registration(monkeypatch):
    from backend import soloq_analyses
    config = analysis_settings.default_configuration()
    config["analysis_limits"]["max_active_matches"] = 2
    monkeypatch.setattr(analysis_settings, "load_configuration", lambda: config)
    profile = {"puuid": "fixture", "region": "euw1"}

    class Repository:
        def load_last_profile(self): return profile
        def load(self, _profile): return {"matches": [{"stable_match_id": "EUW1_123", "game_id": "EUW1_123", "queue_id": 420}]}
        def load_saved_analyses(self, _profile): return [{"match_id": "EUW1_1"}, {"match_id": "EUW1_2"}]

    with pytest.raises(ValueError, match="límite de 2"):
        soloq_analyses.register_analysis(Repository(), "EUW1_123")


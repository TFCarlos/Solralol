from __future__ import annotations

from typing import Any

from app.services.game_calculator import (
    calculate_champion_total_stats,
    calculate_item_stats,
)
from data_dragon import get_champion_data


AWARD_LABELS = {
    "victory": "Victoria",
    "early": "Ha ganado el early",
    "mid": "Ha ganado el mid",
    "late": "Ha ganado el late",
    "full_ad": "Full AD",
    "full_ap": "Full AP",
    "armor": "Armadura",
    "mr": "Resistencia mágica",
    "health": "Vida extra",
    "crit": "Crítico",
    "life_steal": "Robo de vida",
    "antiheal": "Antiheal",
    "lethality": "Penetración de armadura",
    "full_lethality": "Full letalidad",
    "roamer": "Roamer",
}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _latest_point(
    session: dict[str, Any],
    player_key: str,
) -> dict[str, Any]:
    for snapshot in reversed(session.get("snapshots", [])):
        point = snapshot.get("players", {}).get(player_key)
        if isinstance(point, dict):
            return point
    return {}


def _point_at_or_before(
    session: dict[str, Any],
    player_key: str,
    seconds: float,
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for snapshot in session.get("snapshots", []):
        if _number(snapshot.get("time")) > seconds:
            break
        point = snapshot.get("players", {}).get(player_key)
        if isinstance(point, dict):
            selected = point
    return selected or _latest_point(session, player_key)


def _normalise_item_catalog(
    item_catalog: dict[str, Any],
) -> dict[str, Any]:
    items = item_catalog.get("items", item_catalog)
    return items if isinstance(items, dict) else {}


def _item_ids(point: dict[str, Any]) -> list[int]:
    values = point.get("items", [])
    if not isinstance(values, list):
        return []

    result = []
    for value in values:
        try:
            if isinstance(value, dict):
                value = value.get("itemID", value.get("id", 0))
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id > 0:
            result.append(item_id)
    return result


def calculate_post_stats(
    session: dict[str, Any],
    player_key: str,
    item_catalog: dict[str, Any],
    version: str,
) -> dict[str, float | bool]:
    """
    Calcula estadísticas finales POST desde el último snapshot:

    base del campeón + crecimiento por nivel + objetos finales.

    Las runas, buffs y pasivas temporales de jugadores que no son el
    local no se incluyen hasta contar con una fuente que los exponga.
    """
    player = session.get("players", {}).get(player_key, {})
    point = _latest_point(session, player_key)
    champion_name = str(
        player.get("champion_name", "Desconocido")
    )
    level = max(1, int(_number(point.get("level", 1))))
    items = _item_ids(point)

    item_player = {
        **player,
        "items": [{"itemID": item_id} for item_id in items],
    }
    item_stats = calculate_item_stats(
        item_player,
        _normalise_item_catalog(item_catalog),
    )

    champion_data = get_champion_data(champion_name, version)
    total = calculate_champion_total_stats(
        champion_data,
        level,
        item_stats,
    )

    total["level"] = level
    total["items"] = items
    total["champion_name"] = champion_name
    return total


def _is_winner(
    session: dict[str, Any],
    player_key: str,
) -> bool:
    player = session.get("players", {}).get(player_key, {})
    team = player.get("team")
    winning_team = session.get("winning_team")

    if winning_team:
        return team == winning_team

    final = session.get("final_scoreboard", {})
    if not isinstance(final, dict) or not final:
        return False

    totals: dict[str, float] = {}
    for key, score in final.items():
        team_key = session.get("players", {}).get(key, {}).get("team")
        if not team_key:
            continue
        totals[team_key] = totals.get(team_key, 0.0) + _number(
            score.get("kills", 0)
        )

    if len(totals) != 2:
        return False

    return totals.get(team, -1) == max(totals.values())


def _matchup_for_player(
    session: dict[str, Any],
    player_key: str,
) -> dict[str, Any]:
    for matchup in session.get("lane_matchups", {}).values():
        if matchup.get("ally_key") == player_key:
            return matchup
        if matchup.get("enemy_key") == player_key:
            return matchup
    return {}


def calculate_achievements(
    session: dict[str, Any],
    player_key: str,
    item_catalog: dict[str, Any],
    version: str = "16.17.1",
) -> list[str]:
    awards: list[str] = []

    if _is_winner(session, player_key):
        awards.append(AWARD_LABELS["victory"])

    matchup = _matchup_for_player(session, player_key)
    ally_key = matchup.get("ally_key")
    enemy_key = matchup.get("enemy_key")
    opponent_key = enemy_key if player_key == ally_key else ally_key

    if opponent_key:
        at_15 = _point_at_or_before(session, player_key, 900)
        opponent_at_15 = _point_at_or_before(
            session,
            opponent_key,
            900,
        )
        if _number(at_15.get("estimated_gold")) > _number(
            opponent_at_15.get("estimated_gold")
        ):
            awards.append(AWARD_LABELS["early"])

        at_30 = _point_at_or_before(session, player_key, 1800)
        opponent_at_30 = _point_at_or_before(
            session,
            opponent_key,
            1800,
        )
        if _number(at_30.get("estimated_gold")) > _number(
            opponent_at_30.get("estimated_gold")
        ):
            awards.append(AWARD_LABELS["mid"])

        latest = _latest_point(session, player_key)
        opponent_latest = _latest_point(session, opponent_key)
        if _number(latest.get("estimated_gold")) > _number(
            opponent_latest.get("estimated_gold")
        ):
            awards.append(AWARD_LABELS["late"])

    stats = calculate_post_stats(
        session,
        player_key,
        item_catalog,
        version,
    )

    if _number(stats.get("ad")) >= 300:
        awards.append(AWARD_LABELS["full_ad"])
    if _number(stats.get("ap")) >= 400:
        awards.append(AWARD_LABELS["full_ap"])
    if _number(stats.get("armor")) >= 150:
        awards.append(AWARD_LABELS["armor"])
    if _number(stats.get("mr")) >= 150:
        awards.append(AWARD_LABELS["mr"])

    player = session.get("players", {}).get(player_key, {})
    champion_data = get_champion_data(
        str(player.get("champion_name", "")),
        version,
    )
    base_hp = _number(
        champion_data.get("stats", {}).get("hp", 0)
    )
    if _number(stats.get("hp")) - base_hp >= 3000:
        awards.append(AWARD_LABELS["health"])

    crit = _number(stats.get("crit"))
    crit = crit * 100 if crit <= 1 else crit
    if crit >= 50:
        awards.append(AWARD_LABELS["crit"])

    life_steal = _number(stats.get("life_steal_percent"))
    life_steal = life_steal * 100 if life_steal <= 1 else life_steal
    if life_steal >= 25:
        awards.append(AWARD_LABELS["life_steal"])

    if bool(stats.get("grievous_wounds", False)):
        awards.append(AWARD_LABELS["antiheal"])

    if (
        _number(stats.get("lethality")) > 0
        or _number(stats.get("armor_pen_percent")) > 0
        or bool(stats.get("has_armor_penetration", False))
    ):
        awards.append(AWARD_LABELS["lethality"])

    if _number(stats.get("lethality")) >= 100:
        awards.append(AWARD_LABELS["full_lethality"])

    unique: list[str] = []
    for award in awards:
        if award not in unique:
            unique.append(award)
    return unique



def calculate_all_achievements(
    session: dict[str, Any],
    item_catalog: dict[str, Any],
    version: str = "16.17.1",
) -> dict[str, list[str]]:
    return {
        player_key: calculate_achievements(
            session,
            player_key,
            item_catalog,
            version,
        )
        for player_key in session.get("players", {})
    }


def attach_achievements(
    session: dict[str, Any],
    item_catalog: dict[str, Any],
    version: str = "16.17.1",
) -> dict[str, Any]:
    session["achievements"] = calculate_all_achievements(
        session,
        item_catalog,
        version,
    )
    return session


def build_postgame_payload(
    session: dict[str, Any],
    riot_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not riot_match:
        return session

    session["postgame"] = True
    session["final_sync"] = {
        "status": "synced",
        "source": "riot_match_v5",
        "synced_at": datetime.now(UTC).isoformat(),
    }
    session["riot_match"] = riot_match

    # Rellenar el campo "final" de cada jugador.
    final_scoreboard = session.get("final_scoreboard", {})
    for playerkey, player in session.get("players", {}).items():
        if isinstance(player, dict):
            player["final"] = final_scoreboard.get(playerkey, {})

    return session
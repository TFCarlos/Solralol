"""Métricas por jugador que alimentan los overlays de la partida en vivo.

Todo se calcula a partir del snapshot de la Live Client Data API, que es la
única fuente disponible durante la partida. La API no expone el oro real de los
jugadores, así que para todos (incluido el jugador local) se usa la misma
estimación que ya emplea ``LiveMatchTracker``: valor del inventario + 300 por
asesinato + 75 por asistencia + 20 por CS. Así el panel mide la build y no el
oro sin gastar, que baja al comprar.

El módulo no depende de Qt, de modo que puede probarse sin interfaz.
"""

from __future__ import annotations

from typing import Any

from app.services.game_calculator import get_inventory_value


ROLE_ORDER = (
    "TOP",
    "JUNGLE",
    "MIDDLE",
    "BOTTOM",
    "UTILITY",
)

ROLE_SHORT_LABELS = {
    "TOP": "TOP",
    "JUNGLE": "JGL",
    "MIDDLE": "MID",
    "BOTTOM": "ADC",
    "UTILITY": "SUP",
    "UNKNOWN": "?",
}

ROLE_ALIASES = {
    "TOP": "TOP",
    "JUNG": "JUNGLE",
    "JUNGLE": "JUNGLE",
    "MID": "MIDDLE",
    "MIDDLE": "MIDDLE",
    "BOT": "BOTTOM",
    "BOTTOM": "BOTTOM",
    "ADC": "BOTTOM",
    "APC": "BOTTOM",
    "UTILITY": "UTILITY",
    "SUP": "UTILITY",
    "SUPPORT": "UTILITY",
}

GOLD_PER_KILL = 300
GOLD_PER_ASSIST = 75
GOLD_PER_CS = 20

# Peso del nivel y de la participación en asesinatos al ordenar por fuerza.
# El criterio es el mismo que ya usa LiveRecommendationService: la inversión en
# objetos y el nivel dominan y el KDA solo ajusta de forma acotada.
LEVEL_GOLD_WEIGHT = 600
KDA_GOLD_WEIGHT = 150
KDA_GOLD_LIMIT = 2000


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def player_identity(player: dict) -> str:
    """Nombre estable de un jugador (Riot ID, invocador o campeón)."""
    if not isinstance(player, dict):
        return ""

    riot_id = str(player.get("riotId") or "").strip()
    if riot_id:
        return riot_id

    name = str(player.get("summonerName") or "").strip()
    if name:
        return name

    return str(player.get("championName") or "").strip()


def player_champion(player: dict) -> str:
    if not isinstance(player, dict):
        return ""

    return str(player.get("championName") or "")


def player_role(player: dict) -> str:
    """Rol del jugador según la posición informada o el hechizo Smite."""
    if not isinstance(player, dict):
        return "UNKNOWN"

    raw = str(
        player.get("position")
        or player.get("teamPosition")
        or player.get("individualPosition")
        or ""
    ).upper()
    role = ROLE_ALIASES.get(raw)

    if role:
        return role

    spells = player.get("summonerSpells", {})
    names: list[str] = []

    if isinstance(spells, dict):
        for value in spells.values():
            if isinstance(value, dict):
                names.append(str(value.get("displayName", "")).casefold())
            else:
                names.append(str(value).casefold())

    if any("smite" in name for name in names):
        return "JUNGLE"

    return "UNKNOWN"


def is_local_player(player: dict, local_player: dict) -> bool:
    """True cuando el jugador es el invocador local del snapshot."""
    if not isinstance(local_player, dict) or not local_player:
        return False

    if player is local_player:
        return True

    identity = player_identity(player)

    return bool(identity) and identity == player_identity(local_player)


def estimate_gold(
    player: dict,
    item_catalog: dict,
    current_gold: Any = None,
) -> int:
    """Oro de un jugador a partir del snapshot (build y lo ganado).

    La API local no expone el oro de los rivales, así que se estima sumando el
    valor del inventario a lo ganado por asesinatos, asistencias y granja. El
    jugador local usa exactamente el mismo criterio: el panel mide su build y no
    su oro sin gastar, que baja al comprar. ``current_gold`` se mantiene en la
    firma por compatibilidad, pero ya no interviene en el cálculo.
    """
    if not isinstance(player, dict):
        return 0

    inventory_value = get_inventory_value(player, item_catalog)

    scores = player.get("scores", {})
    if not isinstance(scores, dict):
        scores = {}

    return (
        inventory_value
        + _int(scores.get("kills")) * GOLD_PER_KILL
        + _int(scores.get("assists")) * GOLD_PER_ASSIST
        + _int(scores.get("creepScore")) * GOLD_PER_CS
    )


def kda_adjustment(player: dict) -> int:
    """Ajuste acotado por KDA, en oro equivalente."""
    scores = player.get("scores", {}) if isinstance(player, dict) else {}
    if not isinstance(scores, dict):
        scores = {}

    weighted = (
        _int(scores.get("kills"))
        + _int(scores.get("assists")) * 0.3
        - _int(scores.get("deaths"))
    )
    bonus = int(round(weighted * KDA_GOLD_WEIGHT))

    return max(-KDA_GOLD_LIMIT, min(KDA_GOLD_LIMIT, bonus))


def strength_score(
    player: dict,
    item_catalog: dict,
    current_gold: Any = None,
) -> int:
    """Proxy de fuerza comparable entre jugadores (en oro equivalente).

    ``current_gold`` se acepta por compatibilidad y se ignora: la fuerza se mide
    sobre la build y lo ganado, igual para todos los jugadores.
    """
    if not isinstance(player, dict):
        return 0

    level = max(0, _int(player.get("level")) - 1)

    return (
        estimate_gold(player, item_catalog)
        + level * LEVEL_GOLD_WEIGHT
        + kda_adjustment(player)
    )


def format_gold(value: Any) -> str:
    """Oro compacto: 900, 1.2K, 12.5K, 123K."""
    amount = _int(value)

    if abs(amount) >= 100_000:
        return f"{amount / 1000:.0f}K"

    if abs(amount) >= 1000:
        return f"{amount / 1000:.1f}K"

    return str(amount)


def format_delta(value: Any) -> str:
    """Diferencia con signo: +400, -1.2K, 0."""
    amount = _int(value)

    if amount == 0:
        return "0"

    sign = "+" if amount > 0 else "-"

    return f"{sign}{format_gold(abs(amount))}"


def _gold_entry(
    player: dict,
    item_catalog: dict,
) -> dict:
    """Resumen mínimo de un jugador para los overlays.

    El oro es el mismo cálculo para todos (valor de la build y lo ganado), así
    que el panel no cambia al comprar y la comparación por rol es homogénea.
    """
    return {
        "identity": player_identity(player),
        "champion": player_champion(player),
        "role": player_role(player),
        "team": str(player.get("team", "")),
        "gold": estimate_gold(player, item_catalog),
        "score": strength_score(player, item_catalog),
    }


def _team_players(
    snapshot: dict,
    item_catalog: dict,
) -> tuple[list[dict], list[dict]]:
    """Separa al equipo local de los rivales, ya resumidos."""
    local_player = snapshot.get("local_player", {})
    if not isinstance(local_player, dict):
        local_player = {}

    local_team = str(
        snapshot.get("local_team")
        or local_player.get("team")
        or ""
    )

    allies: list[dict] = []
    enemies: list[dict] = []

    for player in snapshot.get("all_players", []):
        if not isinstance(player, dict):
            continue

        entry = _gold_entry(player, item_catalog)

        if local_team:
            if entry["team"] == local_team:
                allies.append(entry)
            else:
                enemies.append(entry)
        elif is_local_player(player, local_player):
            # Sin equipo local identificado se usa el propio jugador local.
            allies.append(entry)
        else:
            enemies.append(entry)

    return allies, enemies


def _pop_role(
    players: list[dict],
    role: str,
    used: set[int],
) -> dict | None:
    """Primer jugador sin usar con ese rol (o None)."""
    for index, entry in enumerate(players):
        if index in used:
            continue
        if entry.get("role") == role:
            used.add(index)
            return entry

    return None


def _lane_row(
    role: str,
    ally_entry: dict | None,
    enemy_entry: dict | None,
) -> dict:
    """Línea del overlay de oro: aliado y rival del mismo rol."""
    ally_gold = int(ally_entry["gold"]) if ally_entry else 0
    enemy_gold = int(enemy_entry["gold"]) if enemy_entry else 0
    paired = ally_entry is not None and enemy_entry is not None

    return {
        "role": role,
        "ally": ally_entry,
        "enemy": enemy_entry,
        "delta": (ally_gold - enemy_gold) if paired else 0,
        "paired": paired,
    }


def build_gold_report(
    snapshot: dict,
    item_catalog: dict,
) -> dict:
    """Informe de oro para el overlay: totales y comparación por rol.

    Devuelve ``{"team": {...}, "lanes": [...]}`` donde cada línea enfrenta al
    jugador aliado de un rol con el rival del mismo rol (``None`` si falta).
    """
    empty = {
        "team": {"ally": 0, "enemy": 0, "delta": 0},
        "lanes": [],
    }

    if not isinstance(snapshot, dict):
        return empty

    allies, enemies = _team_players(snapshot, item_catalog)

    if not allies and not enemies:
        return empty

    ally_total = sum(entry["gold"] for entry in allies)
    enemy_total = sum(entry["gold"] for entry in enemies)

    lanes: list[dict] = []
    ally_used: set[int] = set()
    enemy_used: set[int] = set()

    for role in ROLE_ORDER:
        ally_entry = _pop_role(allies, role, ally_used)
        enemy_entry = _pop_role(enemies, role, enemy_used)

        if ally_entry is None and enemy_entry is None:
            continue

        lanes.append(_lane_row(role, ally_entry, enemy_entry))

    # Jugadores con rol desconocido o duplicado se añaden al final para no
    # perderlos en el resumen de equipo.
    for index, entry in enumerate(allies):
        if index not in ally_used:
            lanes.append(
                _lane_row(str(entry.get("role", "UNKNOWN")), entry, None)
            )

    for index, entry in enumerate(enemies):
        if index not in enemy_used:
            lanes.append(
                _lane_row(str(entry.get("role", "UNKNOWN")), None, entry)
            )

    return {
        "team": {
            "ally": ally_total,
            "enemy": enemy_total,
            "delta": ally_total - enemy_total,
        },
        "lanes": lanes,
    }


def build_rival_ranking(
    snapshot: dict,
    item_catalog: dict,
) -> dict:
    """Rival más fuerte y más débil del equipo enemigo."""
    if not isinstance(snapshot, dict):
        return {"strongest": None, "weakest": None}

    _, enemies = _team_players(snapshot, item_catalog)

    if not enemies:
        return {"strongest": None, "weakest": None}

    ranked = sorted(
        enemies,
        key=lambda entry: (
            -int(entry.get("score", 0)),
            str(entry.get("champion", "")),
        ),
    )

    return {
        "strongest": ranked[0],
        "weakest": ranked[-1] if len(ranked) > 1 else None,
    }

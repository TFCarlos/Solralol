"""Alertas del overlay en vivo: compras completas y objetivos inminentes.

El tracker compara el inventario de cada jugador entre snapshots consecutivos
(igual que ``LiveMatchTracker``) para detectar cuándo alguien completa un objeto
y avisa cuando falta un minuto para que aparezca Dragón, Grumos, Heraldo o
Barón. Los tiempos de aparición son los del parche 26.1 (temporada 2026).

Módulo sin Qt: devuelve listas de diccionarios listos para pintar.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.live_player_metrics_service import (
    player_champion,
    player_identity,
    player_role,
)


ALERT_LEAD_SECONDS = 60
PURCHASE_ALERT_SECONDS = 12
COMPLETED_ITEM_MIN_GOLD = 1000

# Temporada 2026 (parche 26.1): Dragón 5:00 y +5:00 por muerte, Grumos 8:00
# (una única vez, se retiran a las 14:45), Heraldo 15:00 (se retira a las
# 19:45) y Barón 20:00 y +6:00 por muerte. El Anciano aparece tras la cuarta
# alma de un equipo y vuelve cada 6:00.
OBJECTIVE_RULES = (
    {
        "key": "dragon",
        "name": "Dragón",
        "elder_name": "Anciano",
        "first_spawn": 300.0,
        "respawn": 300.0,
        "elder_respawn": 360.0,
        "despawn": None,
    },
    {
        "key": "voidgrubs",
        "name": "Grumos",
        "elder_name": None,
        "first_spawn": 480.0,
        "respawn": None,
        "elder_respawn": None,
        "despawn": 885.0,
    },
    {
        "key": "herald",
        "name": "Heraldo",
        "elder_name": None,
        "first_spawn": 900.0,
        "respawn": None,
        "elder_respawn": None,
        "despawn": 1185.0,
    },
    {
        "key": "baron",
        "name": "Barón",
        "elder_name": None,
        "first_spawn": 1200.0,
        "respawn": 360.0,
        "elder_respawn": None,
        "despawn": None,
    },
)

EVENT_TO_OBJECTIVE = {
    "dragonkill": "dragon",
    "baronkill": "baron",
    "heraldkill": "herald",
}

DRAGONS_FOR_ELDER = 4


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def format_clock(seconds: Any) -> str:
    """Cuenta atrás compacta: 0:47, 1:00."""
    total = max(0, int(round(_number(seconds))))
    minutes, remainder = divmod(total, 60)

    return f"{minutes}:{remainder:02d}"


def item_catalog_entry(item_id: Any, item_catalog: dict) -> dict:
    """Objeto del catálogo aceptando los dos formatos usados en la app."""
    items = item_catalog.get("items", item_catalog)
    if not isinstance(items, dict):
        return {}

    entry = items.get(str(item_id), items.get(item_id, {}))

    return entry if isinstance(entry, dict) else {}


def item_name(item_id: Any, item_catalog: dict) -> str:
    entry = item_catalog_entry(item_id, item_catalog)
    name = str(entry.get("name") or entry.get("name_es") or "")

    return name or f"Objeto {item_id}"


def item_total_gold(item_id: Any, item_catalog: dict) -> int:
    entry = item_catalog_entry(item_id, item_catalog)
    gold = entry.get("gold", {})

    if isinstance(gold, dict):
        return max(
            _int(gold.get("total", 0)),
            _int(gold.get("base", 0)),
            _int(gold.get("sell", 0)),
        )

    return _int(entry.get("price", 0))


def is_completed_item(item_id: Any, item_catalog: dict) -> bool:
    """True cuando el objeto es un objeto terminado (no un componente).

    Se exige que el objeto sea comprable, que valga al menos 1.000 de oro y
    que no sea un objeto evolucionable (``into`` vacío): así las compras de
    componentes, pociones, centinelas, objetos de misión o mascotas de jungla
    (que llegan solas, sin pasar por tienda) no generan avisos. La exclusión
    por ``tags`` de consumible/trinket se mantiene como red de seguridad.
    """
    entry = item_catalog_entry(item_id, item_catalog)

    if not entry:
        return False

    gold = entry.get("gold", {})
    if isinstance(gold, dict) and gold.get("purchasable") is False:
        return False

    if item_total_gold(item_id, item_catalog) < COMPLETED_ITEM_MIN_GOLD:
        return False

    tags = entry.get("tags") or []
    if isinstance(tags, list) and (
        "Consumable" in tags or "Trinket" in tags
    ):
        return False

    return not entry.get("into")



class OverlayAlertTracker:
    """Estado necesario para avisar de compras completas y de objetivos.

    Se alimenta con el mismo snapshot que el resto del panel en vivo y devuelve
    la lista de avisos activos (objetivos a punto de aparecer y compras
    recientes). El estado se reinicia solo cuando el reloj de la partida
    retrocede, es decir, al empezar otra partida.
    """

    MAX_FEED_ITEMS = 6
    URGENT_SECONDS = 15

    def __init__(
        self,
        item_catalog: dict,
        lead_seconds: int = ALERT_LEAD_SECONDS,
        purchase_seconds: int = PURCHASE_ALERT_SECONDS,
    ) -> None:
        self.item_catalog = (
            item_catalog if isinstance(item_catalog, dict) else {}
        )
        self.lead_seconds = max(0, min(int(lead_seconds), 300))
        self.purchase_seconds = max(1, int(purchase_seconds))
        self.reset()

    def reset(self) -> None:
        """Olvida la partida anterior."""
        self._known_items: dict[str, Counter] = {}
        self._purchases: list[dict] = []
        self._killed_at: dict[str, float] = {}
        self._seen_events: set[str] = set()
        self._dragon_teams: dict[str, int] = {}
        self._last_game_time = -1.0

    @property
    def elder_active(self) -> bool:
        """True cuando algún equipo ya tiene el alma de dragón."""
        return any(
            count >= DRAGONS_FOR_ELDER
            for count in self._dragon_teams.values()
        )

    def update(self, snapshot: dict) -> list[dict]:
        """Procesa un snapshot y devuelve los avisos activos."""
        if not isinstance(snapshot, dict):
            return self.active_alerts(self._last_game_time)

        game_time = _number(snapshot.get("game_time"))

        if game_time + 5 < self._last_game_time:
            # El reloj retrocede: es otra partida.
            self.reset()

        self._last_game_time = max(game_time, self._last_game_time)
        self._record_objective_events(snapshot)
        self._record_purchases(snapshot, game_time)
        self._drop_expired(game_time)

        return self.active_alerts(game_time)

    def active_alerts(self, game_time: float) -> list[dict]:
        """Objetivos a punto de aparecer y compras todavía recientes."""
        alerts: list[dict] = []

        for rule in OBJECTIVE_RULES:
            spawn_at = self._spawn_time(rule, game_time)

            if spawn_at is None:
                continue

            remaining = spawn_at - game_time

            if remaining <= 0 or remaining > self.lead_seconds:
                continue

            alerts.append(
                {
                    "kind": "objective",
                    "key": f"objective:{rule['key']}",
                    "name": self._objective_name(rule),
                    "remaining": remaining,
                    "spawn_at": spawn_at,
                    "urgent": remaining <= self.URGENT_SECONDS,
                }
            )

        alerts.sort(key=lambda alert: alert["remaining"])

        purchases = sorted(
            self._purchases,
            key=lambda alert: alert.get("time", 0.0),
            reverse=True,
        )

        return (alerts + purchases)[: self.MAX_FEED_ITEMS]

    def _objective_name(self, rule: dict) -> str:
        if (
            self.elder_active
            and rule.get("key") == "dragon"
            and rule.get("elder_name")
        ):
            return str(rule["elder_name"])

        return str(rule["name"])

    def _spawn_time(self, rule: dict, game_time: float) -> float | None:
        """Momento del próximo aviso de ese objetivo (o None si ya no vuelve)."""
        killed_at = self._killed_at.get(rule["key"])
        respawn = rule.get("respawn")

        if rule.get("key") == "dragon" and self.elder_active:
            respawn = rule.get("elder_respawn") or respawn

        if respawn is None:
            # Objetivo único (Grumos, Heraldo): si ya se capturó no vuelve.
            if killed_at is not None:
                return None
            spawn_at = float(rule["first_spawn"])
        else:
            spawn_at = (
                float(rule["first_spawn"])
                if killed_at is None
                else killed_at + float(respawn)
            )

        despawn = rule.get("despawn")

        if despawn is not None and game_time > float(despawn):
            return None

        return spawn_at

    def _record_objective_events(self, snapshot: dict) -> None:
        events = snapshot.get("game_events", [])

        if not isinstance(events, list):
            return

        for event in events:
            if not isinstance(event, dict):
                continue

            objective = EVENT_TO_OBJECTIVE.get(
                str(event.get("EventName", "")).casefold()
            )

            if not objective:
                continue

            time_value = _number(event.get("EventTime"))
            event_id = event.get("EventID", event.get("eventId"))

            if event_id is None:
                # Sin identificador estable no se puede deduplicar: solo se
                # actualiza el tiempo de muerte (operación idempotente).
                self._killed_at[objective] = max(
                    time_value,
                    self._killed_at.get(objective, -1.0),
                )
                continue

            event_key = f"{objective}:{event_id}"

            if event_key in self._seen_events:
                continue

            self._seen_events.add(event_key)
            self._killed_at[objective] = max(
                time_value,
                self._killed_at.get(objective, -1.0),
            )

            if objective == "dragon":
                team = self._team_from_killer(
                    snapshot,
                    str(event.get("KillerName", "")),
                )

                if team:
                    self._dragon_teams[team] = (
                        self._dragon_teams.get(team, 0) + 1
                    )

    @staticmethod
    def _team_from_killer(snapshot: dict, killer_name: str) -> str:
        target = killer_name.strip().casefold()

        if not target:
            return ""

        for player in snapshot.get("all_players", []):
            if not isinstance(player, dict):
                continue

            identity = player_identity(player).casefold()
            summoner = str(player.get("summonerName", "")).casefold()

            if target in {identity, summoner} or (
                identity and target in identity
            ):
                return str(player.get("team", ""))

        return ""

    def _record_purchases(self, snapshot: dict, game_time: float) -> None:
        """Detecta objetos nuevos por jugador comparando con el snapshot previo."""
        local_team = str(snapshot.get("local_team", ""))
        seen_keys: set[str] = set()

        for index, player in enumerate(snapshot.get("all_players", [])):
            if not isinstance(player, dict):
                continue

            identity = player_identity(player) or f"player-{index}"
            team = str(player.get("team", ""))
            player_key = f"{team}:{identity}".casefold()
            seen_keys.add(player_key)

            current = self._item_counts(player)
            previous = self._known_items.get(player_key)
            self._known_items[player_key] = current

            if previous is None:
                # Primera lectura: ese inventario ya estaba ahí.
                continue

            added = current - previous

            if not added:
                continue

            champion = player_champion(player)
            role = player_role(player)
            role_label = role if role != "UNKNOWN" else ""
            side = "ally" if local_team and team == local_team else "enemy"

            for item_id, amount in added.items():
                if not is_completed_item(item_id, self.item_catalog):
                    continue

                name = item_name(item_id, self.item_catalog)

                for _ in range(amount):
                    self._purchases.append(
                        {
                            "kind": "purchase",
                            "key": (
                                f"purchase:{game_time}:{player_key}:{item_id}"
                            ),
                            "champion": champion,
                            "role": role_label,
                            "side": side,
                            "item_id": item_id,
                            "item_name": name,
                            "time": game_time,
                            "expires_at": game_time + self.purchase_seconds,
                            "detail": " · ".join(
                                part
                                for part in (champion, role_label, name)
                                if part
                            ),
                        }
                    )

        for player_key in list(self._known_items):
            if player_key not in seen_keys:
                self._known_items.pop(player_key, None)

    @staticmethod
    def _item_counts(player: dict) -> Counter:
        counts: Counter = Counter()

        for item in player.get("items", []):
            item_id = _int(
                item.get("itemID", 0)
                if isinstance(item, dict)
                else item
            )

            if item_id > 0:
                counts[item_id] += 1

        return counts

    def _drop_expired(self, game_time: float) -> None:
        self._purchases = [
            alert
            for alert in self._purchases
            if _number(alert.get("expires_at")) > game_time
        ]


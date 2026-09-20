"""Barra lateral de la ventana de repaso post-partida.

Se usa dentro de ``PostgameReplayWindow`` y muestra, junto al vídeo, el
desglose de la partida: marcador de los diez jugadores, comparativa por
rol (gráfico de radar) y una timeline de revisión con los sucesos
clasificados y valorados.

Origen de los datos: **siempre la telemetría LOCAL** guardada por
``LiveMatchTracker`` (snapshots y eventos de la Live Client Data API).
La sincronización con la Riot API solo enriquece la sesión en disco: el
desglose se calcula con lo local, de modo que está disponible al
instante y no depende de que la partida se haya sincronizado. Cuando se
sincroniza, el botón «Re-desglosar» de la ventana vuelve a construir
esta barra con la sesión recargada de disco.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.recording_service import (
    format_duration,
    normalise_marker_kind,
)
from data_dragon import get_champion_icon_path, get_item_icon_path

# ---------------------------------------------------------------------------
# Tipos de suceso de la telemetría local
# ---------------------------------------------------------------------------

#: Etiqueta legible de cada tipo de suceso del tracker local.
EVENT_KIND_LABELS: dict[str, str] = {
    "kill": "Asesinato",
    "death": "Muerte",
    "assist": "Asistencia",
    "dragon": "Dragón",
    "baron": "Barón (Nashor)",
    "rift_herald": "Heraldo",
    "horde": "Grumos",
    "tower": "Torre",
    "inhibitor": "Inhibidor",
    "objective": "Objetivo",
    "item_purchase": "Compra de objeto",
    "item_removed": "Venta de objeto",
    "cs_milestone": "Hito de CS",
    "level_up": "Subida de nivel",
    "default": "Suceso",
}

#: Icono de cada tipo de suceso: espada para los asesinatos, calavera para
#: las muertes, castillo para las torres... así la revisión se lee de un
#: vistazo sin depender de la columna de texto.
EVENT_KIND_GLYPHS: dict[str, str] = {
    "kill": "⚔️",
    "death": "💀",
    "assist": "🤝",
    "dragon": "🐉",
    "baron": "👑",
    "rift_herald": "👁️",
    "horde": "🐛",
    "tower": "🏰",
    "inhibitor": "💠",
    "objective": "🎯",
    "item_purchase": "🛒",
    "item_removed": "🗑️",
    "cs_milestone": "🌾",
    "level_up": "⬆️",
    "default": "•",
}

#: Tipos de objetivo: siempre se muestran (son globales de partida).
OBJECTIVE_KINDS = (
    "dragon",
    "baron",
    "rift_herald",
    "horde",
    "tower",
    "inhibitor",
)

#: Traducción a la clave canónica de los nombres de objetivo que aparecen en
#: las sesiones guardadas: la telemetría local ya usa claves canónicas, pero
#: la Riot API escribe "Tower Building", "Baron Nashor"... y esas sesiones
#: quedaron en disco tal cual. Sin esta tabla la revisión no reconocía las
#: torres del rival (ni su valoración, ni su color, ni su icono).
OBJECTIVE_KEY_ALIASES: dict[str, str] = {
    "tower": "tower",
    "tower building": "tower",
    "turret": "tower",
    "torre": "tower",
    "inhibitor": "inhibitor",
    "inhibitor building": "inhibitor",
    "barracks": "inhibitor",
    "inhibidor": "inhibitor",
    "dragon": "dragon",
    "dragon kill": "dragon",
    "elder dragon": "dragon",
    "baron": "baron",
    "baron nashor": "baron",
    "nashor": "baron",
    "rift herald": "rift_herald",
    "riftherald": "rift_herald",
    "herald": "rift_herald",
    "heraldo": "rift_herald",
    "horde": "horde",
    "void grub": "horde",
    "voidgrub": "horde",
    "grubs": "horde",
    "grumos": "horde",
    "objective": "objective",
    "objetivo": "objective",
    "building": "objective",
    "edificio": "objective",
}

#: Valoración de cada suceso: glifo, color y descripción corta.
EVALUATION_STYLES: dict[int, dict[str, str]] = {
    1: {"glyph": "🟢", "color": "#4ade80", "label": "Buen intercambio"},
    0: {"glyph": "⚪", "color": "#9eb4d3", "label": "Neutro"},
    -1: {"glyph": "🔴", "color": "#f07d8a", "label": "Coste alto"},
}

#: Color de la barra lateral de cada tipo de suceso.
EVENT_KIND_COLORS: dict[str, str] = {
    "kill": "#4adea0",
    "death": "#f07d8a",
    "assist": "#57cafa",
    "dragon": "#fb923c",
    "baron": "#c084fc",
    "rift_herald": "#c3b1fc",
    "horde": "#a3e635",
    "tower": "#e9c875",
    "inhibitor": "#2dd4bf",
    "item_purchase": "#fbbf24",
    "item_removed": "#94a3b8",
    "cs_milestone": "#38bdf8",
    "level_up": "#34d399",
    "objective": "#a78bfa",
    "default": "#94a3b8",
}

ALLY_TEAMS = {"ORDER", "BLUE", "100", "1", "ALLY", "TEAM"}
ENEMY_TEAMS = {"CHAOS", "RED", "200", "2", "ENEMY"}

#: Orden canónico de roles para el marcador (TOP→JUNGLA→MEDIO→TIRADOR→APOYO).
ROLE_ORDER = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "UNKNOWN")

#: Etiqueta legible de cada rol (para identificar al dueño del suceso).
ROLE_LABELS_ES: dict[str, str] = {
    "TOP": "Cima",
    "JUNGLE": "Jungla",
    "MIDDLE": "Medio",
    "BOTTOM": "Tirador",
    "UTILITY": "Soporte",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def kind_label(kind: Any) -> str:
    """Etiqueta legible de un tipo de suceso (o el propio texto)."""
    text = str(kind or "")

    if not text:
        return EVENT_KIND_LABELS["default"]

    return EVENT_KIND_LABELS.get(
        text, text.replace("_", " ").capitalize()
    )


def normalise_objective_kind(value: Any) -> str:
    """Clave canónica de un objetivo (``"Tower Building"`` → ``"tower"``).

    Se usa con los datos de la Riot API y con las sesiones ya guardadas en
    disco, que pueden traer el nombre "humano" del objetivo en vez de la
    clave del tracker (``tower``, ``dragon``, ``rift_herald``...).
    """
    text = str(value or "").strip().casefold()

    if not text:
        return ""

    text = " ".join(text.replace("_", " ").replace("-", " ").split())

    return OBJECTIVE_KEY_ALIASES.get(text, text.replace(" ", "_"))


def kind_glyph(kind: Any) -> str:
    """Icono del tipo de suceso (espada, calavera, torre, dragón...)."""
    canonical = normalise_objective_kind(kind) or str(kind or "").strip().casefold()

    return EVENT_KIND_GLYPHS.get(canonical, EVENT_KIND_GLYPHS["default"])


def objective_side(session: dict[str, Any], event: dict[str, Any]) -> str:
    """Bando (``"ally"``/``"enemy"``) que consiguió un objetivo.

    El bando se busca, por este orden, en el campo ``team`` del suceso, en
    ``objective_team`` (lo que resolvió el tracker), en ``owner_team``
    (bando dueño del edificio: el objetivo es del bando contrario) y, si aún
    no aparece, en el equipo del jugador que lo remató o de cualquiera de sus
    asistentes: así se identifican las torres aunque el evento original no
    traiga bando.
    """
    for candidate in (event.get("team"), event.get("objective_team")):
        side = team_side(session, candidate)

        if side:
            return side

    # ``owner_team``: el edificio destruido era de ese bando → el objetivo es
    # del contrario.
    owner_side = team_side(session, event.get("owner_team"))

    if owner_side == "ally":
        return "enemy"

    if owner_side == "enemy":
        return "ally"

    players = session_players(session)
    owners = [event.get("killer_key"), event.get("player_key")]
    owners.extend(_assister_keys(event))

    for key in owners:
        metadata = players.get(str(key or ""))

        if not isinstance(metadata, dict):
            continue

        side = team_side(session, metadata.get("team"))

        if side:
            return side

    return ""


def objective_detail(
    kind: str,
    side: str,
    event: dict[str, Any],
) -> str:
    """Texto del objetivo con su bando ("Tu equipo consiguió Torre")."""
    base = kind_label(kind)

    if side == "ally":
        return f"Tu equipo consiguió {base}"

    if side == "enemy":
        return f"El rival consiguió {base}"

    stored = str(event.get("label") or "").strip()
    lowered = stored.casefold()

    if stored and "no identificado" not in lowered and "sin identificar" not in lowered:
        return stored

    return f"{base} · bando sin identificar"


def team_side(session: dict[str, Any], team: Any) -> str:
    """``"ally"``, ``"enemy"`` o ``""`` según el bando del suceso."""
    value = str(team or "").strip().upper()
    local_team = str(session.get("local_team") or "").strip().upper()

    if value and local_team:
        return "ally" if value == local_team else "enemy"

    if value in ALLY_TEAMS:
        return "ally"

    if value in ENEMY_TEAMS:
        return "enemy"

    return ""


def local_player_key(session: dict[str, Any]) -> str:
    return str(session.get("local_player_key") or "")


def session_players(session: dict[str, Any]) -> dict[str, Any]:
    players = session.get("players")

    return players if isinstance(players, dict) else {}


def latest_point(session: dict[str, Any], player_key: str) -> dict[str, Any]:
    """Último punto conocido del jugador (snapshot más reciente)."""
    snapshots = session.get("snapshots")

    if not isinstance(snapshots, list):
        return {}

    for snapshot in reversed(snapshots):
        if not isinstance(snapshot, dict):
            continue

        players = snapshot.get("players")

        if not isinstance(players, dict):
            continue

        point = players.get(player_key)

        if isinstance(point, dict) and point:
            return point

    return {}


def player_final_stats(
    session: dict[str, Any], player_key: str
) -> dict[str, Any]:
    """Estadísticas del jugador calculadas solo con la telemetría local.

    El resultado no cambia si la sesión está sincronizada con Riot: el
    desglose siempre sale de los snapshots locales, que existen desde el
    primer segundo de la partida.
    """
    players = session_players(session)
    player = players.get(player_key)
    player = player if isinstance(player, dict) else {}
    point = latest_point(session, player_key)
    final = session.get("final_scoreboard")

    if isinstance(final, dict) and isinstance(final.get(player_key), dict):
        # El marcador final local rellena los huecos del último snapshot;
        # nunca sustituye los valores ya observados.
        merged = dict(final[player_key])
        merged.update(point)
        point = merged

    kills = _int(point.get("kills"))
    deaths = _int(point.get("deaths"))
    assists = _int(point.get("assists"))
    cs = _int(point.get("cs"))
    gold = _int(point.get("estimated_gold"))
    level = _int(point.get("level"), 1)
    stats = point.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    vision = _int(stats.get("vision_score"))
    duration = _number(session.get("duration"))
    kda = (kills + assists) / deaths if deaths > 0 else float(kills + assists)

    return {
        "player_key": player_key,
        "champion": str(player.get("champion_name") or "Desconocido"),
        "riot_id": str(player.get("riot_id") or ""),
        "role": str(player.get("role") or "UNKNOWN"),
        "team": str(player.get("team") or ""),
        "win": player.get("win"),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "cs": cs,
        "gold": gold,
        "vision": vision,
        "level": level,
        "kda": kda,
        "cspm": cs / (duration / 60.0) if duration > 0 else 0.0,
        "gpm": gold / (duration / 60.0) if duration > 0 else 0.0,
        "duration": duration,
    }


def team_kills(session: dict[str, Any], side: str) -> int:
    """Asesinatos totales de un bando, según los snapshots locales."""
    total = 0

    for key, player in session_players(session).items():
        if not isinstance(player, dict):
            continue

        if team_side(session, player.get("team")) != side:
            continue

        total += player_final_stats(session, key)["kills"]

    return total


def ordered_player_keys(session: dict[str, Any]) -> list[str]:
    """Claves de jugador: primero el bando local, con el local delante."""
    local_key = local_player_key(session)
    bucket: dict[str, list[str]] = {"ally": [], "enemy": [], "": []}

    for key, player in session_players(session).items():
        if not isinstance(player, dict):
            continue

        bucket[team_side(session, player.get("team"))].append(key)

    for values in bucket.values():
        values.sort(
            key=lambda value: (
                value != local_key,
                str(
                    (session_players(session).get(value) or {}).get("role")
                    or ""
                ),
            )
        )

    return bucket["ally"] + bucket["enemy"] + bucket[""]


def matchup_partner(session: dict[str, Any], player_key: str) -> str:
    """Clave del rival directo del jugador según ``lane_matchups``."""
    matchups = session.get("lane_matchups")

    if not isinstance(matchups, dict):
        return ""

    for matchup in matchups.values():
        if not isinstance(matchup, dict):
            continue

        if matchup.get("ally_key") == player_key:
            return str(matchup.get("enemy_key") or "")

    return ""


# ---------------------------------------------------------------------------
# Timeline de revisión (siempre con los eventos locales)
# ---------------------------------------------------------------------------


def _objective_kind(event: dict[str, Any]) -> str:
    """Clave canónica del objetivo (traduce los nombres de Riot/antiguos)."""
    kind = normalise_objective_kind(
        event.get("objective") or event.get("objective_label") or ""
    )

    return kind or "objective"


def _assister_keys(event: dict[str, Any]) -> list[str]:
    values = event.get("assister_keys")

    if not isinstance(values, list):
        return []

    return [str(value) for value in values if str(value)]


def _evaluation_for(kind: str, side: str) -> int:
    if kind in OBJECTIVE_KINDS or kind == "objective":
        if side == "ally":
            return 1
        if side == "enemy":
            return -1
        return 0

    if kind == "kill":
        return 1 if side == "ally" else -1

    if kind == "death":
        return -1 if side == "ally" else 1

    if kind == "assist":
        if side == "ally":
            return 1
        if side == "enemy":
            return -1
        return 0

    return 0


def build_review_events(
    session: dict[str, Any],
    player_key: str | None = None,
) -> list[dict[str, Any]]:
    """Sucesos de la timeline de revisión, desde los eventos LOCALES.

    Se construyen siempre con ``session["events"]`` (telemetría de la Live
    Client Data API), nunca con los eventos oficiales de Riot: así el
    desglose existe aunque la partida no se haya sincronizado.

    Con ``player_key`` se devuelven solo los sucesos de ese jugador más los
    objetivos (que son globales). Con ``None`` se devuelven los de todos.
    """
    events = session.get("events")
    events = events if isinstance(events, list) else []
    wanted = "" if player_key is None else str(player_key)
    has_exact = any(
        str((event or {}).get("type") or "")
        in {"kill_exact", "death_exact", "assist_exact"}
        for event in events
        if isinstance(event, dict)
    )
    champions = {
        key: str((player or {}).get("champion_name") or "")
        for key, player in session_players(session).items()
        if isinstance(player, dict)
    }
    result: list[dict[str, Any]] = []

    for order, event in enumerate(events):
        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type") or "")
        owner = str(event.get("player_key") or "")
        side = team_side(session, event.get("team"))
        assisters = _assister_keys(event)
        kind = ""

        if event_type in {"kill_exact", "kill"}:
            if event_type == "kill" and has_exact:
                continue

            killer = str(event.get("killer_key") or owner)

            if not wanted or killer == wanted:
                kind = "kill"
            elif wanted in assisters:
                kind = "assist"
            else:
                continue

        elif event_type in {"death_exact", "death"}:
            if event_type == "death" and has_exact:
                continue

            victim = str(event.get("victim_key") or owner)

            if wanted and victim != wanted:
                continue

            kind = "death"

        elif event_type == "assist_exact":
            if wanted and wanted not in {owner, *assisters}:
                continue

            kind = "assist"

        elif event_type == "objective":
            kind = _objective_kind(event)
            # El bando del objetivo se resuelve aquí (no se da por hecho que
            # el evento lo traiga): es lo que permite saber si la torre la
            # tiró tu equipo o el rival.
            side = objective_side(session, event)

        elif event_type in {"item_purchase", "item_removed"}:
            if not wanted or owner != wanted:
                continue

            kind = event_type

        else:
            continue

        if not kind:
            continue

        label = str(event.get("label") or "").strip()
        is_objective = kind in OBJECTIVE_KINDS or kind == "objective"

        if is_objective:
            # El texto del objetivo se reconstruye con el bando resuelto: las
            # sesiones sincronizadas guardaron "Bando no identificado
            # consiguió Torre" aunque el suceso sí traía el equipo.
            detail = objective_detail(kind, side, event)
            row_label = kind_label(kind)
        else:
            detail = label or kind_label(kind)
            row_label = kind_label(kind)

        result.append(
            {
                "time": _number(event.get("time")),
                "order": _int(event.get("order"), order),
                "kind": kind,
                "label": row_label,
                "detail": detail,
                "glyph": kind_glyph(kind),
                "team": str(
                    event.get("team")
                    or event.get("objective_team")
                    or event.get("owner_team")
                    or ""
                ),
                "side": side,
                "role": str(event.get("role") or ""),
                "player_key": owner or None,
                "player_name": champions.get(owner, ""),
                "evaluation": _evaluation_for(kind, side),
                "feedback": review_feedback(kind, event, session),
            }
        )

    result.sort(key=lambda item: (item["time"], item["order"]))

    return result


def review_feedback(
    kind: str, event: dict[str, Any], session: dict[str, Any]
) -> str:
    """Explicación corta del suceso, construida con datos locales."""
    label = str(event.get("label") or "").strip()
    side = team_side(session, event.get("team"))

    if kind == "kill":
        return "Oro y presión de mapa a favor."
    if kind == "death":
        return "Revisa visión y posición antes de esa pelea."
    if kind == "assist":
        return "Participación en la pelea del equipo."
    if kind == "tower":
        return (
            "Torre derribada del rival."
            if side == "ally"
            else "Torre propia perdida."
        )
    if kind == "dragon":
        return (
            "Dragón para tu equipo."
            if side == "ally"
            else "Dragón para el rival."
        )
    if kind == "baron":
        return (
            "Barón (Nashor) para tu equipo."
            if side == "ally"
            else "Barón (Nashor) para el rival."
        )
    if kind == "rift_herald":
        return (
            "Heraldo para tu equipo."
            if side == "ally"
            else "Heraldo para el rival."
        )
    if kind == "inhibitor":
        return (
            "Inhibidor del rival destruido."
            if side == "ally"
            else "Inhibidor propio perdido."
        )
    if kind == "item_purchase":
        return f"Compra: {label}" if label else "Compra de objeto completada."
    if kind == "item_removed":
        return f"Vendido: {label}" if label else "Objeto vendido."

    return label or kind_label(kind)


def evaluation_style(value: Any) -> dict[str, str]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0

    return EVALUATION_STYLES.get(number, EVALUATION_STYLES[0])


# ---------------------------------------------------------------------------
# Gráfico de radar (pintado a mano con QPainter)
# ---------------------------------------------------------------------------


def radar_values(stats: dict[str, Any]) -> list[float]:
    """Valores normalizados (0-1) de las cinco métricas del radar."""
    duration = _number(stats.get("duration"))
    minutes = duration / 60.0 if duration > 0 else 0.0
    cspm = _number(stats.get("cspm"))
    gpm = _number(stats.get("gpm"))
    vision = _number(stats.get("vision"))
    kda = _number(stats.get("kda"))

    def ratio(value: float, ceiling: float) -> float:
        if ceiling <= 0:
            return 0.0

        return max(0.0, min(1.0, value / ceiling))

    return [
        ratio(cspm, 10.0),
        ratio(gpm, 600.0),
        ratio(vision, max(15.0, minutes)) if minutes else ratio(vision, 30.0),
        ratio(kda, 8.0),
        ratio(_number(stats.get("kills")) + _number(stats.get("assists")), 20.0),
    ]


class RadarChartWidget(QWidget):
    """Comparativa por radar entre el jugador elegido y su rival directo.

    Se dibuja con ``QPainter``, sin dependencias nuevas (ni pyqtgraph ni
    matplotlib), para mantener el proyecto tal y como está.
    """

    METRICS = ("CS/min", "Oro/min", "Visión", "KDA", "Participación")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("postgameRadar")
        self.setMinimumHeight(210)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.player_values: list[float] = [0.0] * len(self.METRICS)
        self.enemy_values: list[float] = [0.0] * len(self.METRICS)
        self.player_label = "Yo"
        self.enemy_label = "Rival"

    def set_data(
        self,
        player_values: list[float],
        enemy_values: list[float],
        player_label: str = "Yo",
        enemy_label: str = "Rival",
    ) -> None:
        self.player_values = [max(0.0, min(1.0, _number(v))) for v in player_values]
        self.enemy_values = [max(0.0, min(1.0, _number(v))) for v in enemy_values]
        self.player_label = str(player_label or "Yo")
        self.enemy_label = str(enemy_label or "Rival")
        self.update()

    def _polygon(self, values: list[float], radius: float, step: float) -> QPolygonF:
        points = [QPointF(0.0, 0.0)]

        for index in range(len(self.METRICS)):
            value = values[index] if index < len(values) else 0.0
            angle = -math.pi / 2 + index * step
            length = radius * max(0.0, min(1.0, value))
            points.append(
                QPointF(length * math.cos(angle), length * math.sin(angle))
            )

        points.append(points[1])

        return QPolygonF(points[1:])

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        height = self.height()
        side = min(width, height)

        if side < 90:
            return

        painter.translate(width / 2.0, height / 2.0 + 6)
        radius = side / 2.6
        count = len(self.METRICS)
        step = 2 * math.pi / count
        grid_pen = QPen(QColor(97, 148, 211, 90))
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for factor in (0.25, 0.5, 0.75, 1.0):
            painter.drawEllipse(QPointF(0.0, 0.0), radius * factor, radius * factor)

        for index in range(count):
            angle = -math.pi / 2 + index * step
            painter.drawLine(
                QPointF(0.0, 0.0),
                QPointF(radius * math.cos(angle), radius * math.sin(angle)),
            )

        painter.setPen(QPen(QColor(240, 125, 138), 2.0))
        painter.setBrush(QColor(240, 125, 138, 60))
        painter.drawPolygon(self._polygon(self.enemy_values, radius, step))

        painter.setPen(QPen(QColor(76, 175, 80), 2.0))
        painter.setBrush(QColor(76, 175, 80, 80))
        painter.drawPolygon(self._polygon(self.player_values, radius, step))

        painter.setPen(QColor(160, 186, 214))
        painter.setFont(QFont("Segoe UI", 8))

        for index, text in enumerate(self.METRICS):
            angle = -math.pi / 2 + index * step
            x = (radius + 20) * math.cos(angle)
            y = (radius + 20) * math.sin(angle)
            painter.drawText(QPointF(x - 24, y + 4), text)

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor(76, 175, 80))
        painter.drawText(QPointF(-radius, radius + 34), f"● {self.player_label}")
        painter.setPen(QColor(240, 125, 138))
        painter.drawText(QPointF(-radius, radius + 48), f"● {self.enemy_label}")


# ---------------------------------------------------------------------------
# Filas de la timeline de revisión
# ---------------------------------------------------------------------------


class EventRow(QFrame):
    """Una línea de la timeline: hora, tipo, detalle, valoración y aviso."""

    activated = Signal(float)

    def __init__(
        self, event: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("postgameEventRow")
        # Ojo: el atributo NO puede llamarse ``event``: QObject ya tiene
        # ``event()`` y sobrescribirlo rompe el reparto de eventos de Qt.
        self.data = event
        kind = str(event.get("kind") or "default")
        style = evaluation_style(event.get("evaluation"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        player_name = str(event.get("player_name") or "").strip()
        self.setToolTip(
            f"{format_duration(event.get('time'))} · {style['label']}"
            + (f" · {player_name}" if player_name else "")
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        accent = QFrame()
        accent.setObjectName("postgameEventAccent")
        accent.setFixedWidth(4)
        accent.setStyleSheet(
            f"background: {EVENT_KIND_COLORS.get(kind, '#94a3b8')};"
            "border-radius: 2px;"
        )
        layout.addWidget(accent)

        time_label = QLabel(format_duration(event.get("time")))
        time_label.setObjectName("postgameEventTime")
        time_label.setFixedWidth(44)
        layout.addWidget(time_label)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(
            f"{str(event.get('glyph') or kind_glyph(kind))} "
            f"{str(event.get('label') or kind_label(kind))}"
        )
        title.setObjectName("postgameEventTitle")
        title.setProperty("evaluation", str(event.get("evaluation", 0)))
        texts.addWidget(title)
        detail_text = str(event.get("detail") or "").strip()

        if detail_text and detail_text != str(event.get("label") or ""):
            detail = QLabel(detail_text)
            detail.setObjectName("postgameEventDetail")
            detail.setWordWrap(True)
            texts.addWidget(detail)

        feedback = str(event.get("feedback") or "").strip()

        if feedback:
            note = QLabel(feedback)
            note.setObjectName("postgameEventFeedback")
            note.setWordWrap(True)
            texts.addWidget(note)

        layout.addLayout(texts, 1)

        if player_name:
            # Dueño del suceso (su campeón y, si se conoce, su rol): así la
            # revisión identifica QUIÉN hizo cada cosa, no solo qué pasó.
            role = str(event.get("role") or "").strip().upper()
            owner = QLabel(
                player_name
                if role not in ROLE_LABELS_ES
                else f"{player_name} · {ROLE_LABELS_ES[role]}"
            )
            owner.setObjectName("postgameEventPlayer")
            owner.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(owner, 0)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(_number(self.data.get("time")))

        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Barra lateral completa
# ---------------------------------------------------------------------------


class PostgameSidebar(QWidget):
    """Desglose de la partida junto al vídeo del repaso.

    Pestañas: **Marcador** (los diez jugadores + radar del jugador elegido)
    y **Revisión** (timeline de sucesos valorados, clic para saltar el
    vídeo a ese momento). Todo se calcula con la telemetría local.
    """

    #: Se emite con el segundo de partida del suceso pulsado.
    event_activated = Signal(float)
    #: Se emite cada vez que la lista de sucesos de la revisión cambia
    #: (sesión, jugador o alcance distintos): la ventana de repaso la usa
    #: para repintar los indicadores de la barra de duración.
    events_changed = Signal()

    SCOPE_PLAYER = "player"
    SCOPE_ALL = "all"

    COLUMNS = ("Campeón", "K/D/A", "CS", "Oro", "Visión", "Resultado")

    def __init__(
        self,
        session: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("postgameSidebar")
        self.session: dict[str, Any] = session if isinstance(session, dict) else {}
        self.player_key: str = local_player_key(self.session)
        self.scope: str = self.SCOPE_PLAYER
        self.review_events: list[dict[str, Any]] = []
        self.event_rows: list[EventRow] = []
        self._build_ui()
        self.refresh()

    # -- construcción ---------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("postgameSidebarHeader")
        head_layout = QHBoxLayout(header)
        head_layout.setContentsMargins(12, 10, 12, 10)
        head_layout.setSpacing(8)
        title = QLabel("Desglose de la partida")
        title.setObjectName("postgameSidebarTitle")
        head_layout.addWidget(title)
        head_layout.addStretch(1)
        self.source_badge = QLabel("Telemetría LIVE")
        self.source_badge.setObjectName("postgameSidebarBadge")
        head_layout.addWidget(self.source_badge)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("postgameTabs")
        self.tabs.addTab(self._build_overview_tab(), "Marcador")
        self.tabs.addTab(self._build_review_tab(), "Revisión")
        root.addWidget(self.tabs, 1)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("postgameTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # Marcador MI EQUIPO vs EQUIPO ENEMIGO en dos columnas paralelas: cada
        # columna muestra sus 5 jugadores (o los que haya) con tarjetas
        # idénticas, para comparar de un vistazo.
        score_row = QFrame()
        score_row.setObjectName("postgameVsRow")
        score_row.setStyleSheet(
            "QFrame#postgameVsRow { "
            "border: 1px solid rgba(97,148,211,70); "
            "border-radius: 18px; "
            "background: rgba(10,20,36,205); "
            "padding: 10px 4px; }"
        )
        score_layout = QVBoxLayout(score_row)
        score_layout.setContentsMargins(6, 8, 6, 8)
        score_layout.setSpacing(6)

        # Encabezado con los totales de cada bando.
        self.team_header = QLabel("MI EQUIPO · VS · EQUIPO ENEMIGO")
        self.team_header.setObjectName("postgameVsTitle")
        self.team_header.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.team_header.setStyleSheet(
            "color:#d9ae4f; font-size:11px; font-weight:800; letter-spacing:2px;"
        )
        score_layout.addWidget(self.team_header)

        columns = QHBoxLayout()
        columns.setSpacing(8)
        columns.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.ally_column = QWidget()
        self.ally_column.setObjectName("postgameAllyColumn")
        self.ally_column.setStyleSheet(
            "QWidget#postgameAllyColumn { background: rgba(74,150,255,40); "
            "border-radius:10px; border:1px solid rgba(74,150,255,90); }"
        )
        ally_layout = QVBoxLayout(self.ally_column)
        ally_layout.setContentsMargins(6, 6, 6, 6)
        ally_layout.setSpacing(6)
        ally_layout.addStretch(1)
        columns.addWidget(self.ally_column, 1)

        self.enemy_column = QWidget()
        self.enemy_column.setObjectName("postgameEnemyColumn")
        self.enemy_column.setStyleSheet(
            "QWidget#postgameEnemyColumn { background: rgba(240,96,118,40); "
            "border-radius:10px; border:1px solid rgba(240,96,118,90); }"
        )
        enemy_layout = QVBoxLayout(self.enemy_column)
        enemy_layout.setContentsMargins(6, 6, 6, 6)
        enemy_layout.setSpacing(6)
        enemy_layout.addStretch(1)
        columns.addWidget(self.enemy_column, 1)

        score_layout.addLayout(columns, 1)
        layout.addWidget(score_row, 0, Qt.AlignmentFlag.AlignTop)

        # Radar comparativo debajo
        self.radar = RadarChartWidget()
        self.radar.setObjectName("postgameRadar")
        layout.addWidget(self.radar)

        # Fila resumen con KDA, CS/min, oro/min, visión, nivel del jugador
        self.stats_label = QLabel("Sin datos de la partida todavía.")
        self.stats_label.setObjectName("postgameStatsLine")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet(
            "QLabel#postgameStatsLine { color:#b9c8dc; font-size:11px; "
            "border-radius:8px; padding:4px 8px; "
            "background:rgba(14,26,44,190); }"
        )
        layout.addWidget(self.stats_label)

        return page

    def _build_review_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("postgameTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.player_combo = QComboBox()
        self.player_combo.setObjectName("postgamePlayerCombo")
        self.player_combo.currentIndexChanged.connect(
            self._on_player_combo_changed
        )
        filters.addWidget(self.player_combo, 1)

        self.scope_group = QButtonGroup(page)
        self.scope_group.setExclusive(True)
        self.scope_buttons: dict[str, QPushButton] = {}

        for scope, text in (
            (self.SCOPE_PLAYER, "Solo el jugador"),
            (self.SCOPE_ALL, "Todos"),
        ):
            button = QPushButton(text)
            button.setObjectName("postgameScopeButton")
            button.setCheckable(True)
            button.setChecked(scope == self.scope)
            button.clicked.connect(
                lambda checked=False, value=scope: self.set_scope(value)
            )
            self.scope_group.addButton(button)
            self.scope_buttons[scope] = button
            filters.addWidget(button)

        layout.addLayout(filters)

        self.review_scroll = QScrollArea()
        self.review_scroll.setObjectName("postgameReviewScroll")
        self.review_scroll.setWidgetResizable(True)
        self.review_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.review_container = QWidget()
        self.review_container.setObjectName("postgameReviewContent")
        self.review_layout = QVBoxLayout(self.review_container)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(6)
        self.review_layout.addStretch(1)
        self.review_scroll.setWidget(self.review_container)
        layout.addWidget(self.review_scroll, 1)

        self.review_empty = QLabel(
            "No hay sucesos locales registrados para este filtro.\n"
            "El desglose se construye con la telemetría de la API local."
        )
        self.review_empty.setObjectName("postgameReviewEmpty")
        self.review_empty.setWordWrap(True)
        layout.addWidget(self.review_empty)

        return page

    # -- estado ---------------------------------------------------------

    def set_session(self, session: dict[str, Any] | None) -> None:
        """Cambia la sesión mostrada (la del vídeo o la partida guardada)."""
        self.session = session if isinstance(session, dict) else {}
        self.player_key = local_player_key(self.session)
        self.refresh()

    def set_player(self, player_key: str) -> None:
        key = str(player_key or "")

        if not key or key == self.player_key:
            return

        self.player_key = key
        self._sync_player_combo()
        self._refresh_stats()
        self._rebuild_timeline()

    def set_scope(self, scope: str) -> None:
        value = (
            self.SCOPE_ALL
            if str(scope) == self.SCOPE_ALL
            else self.SCOPE_PLAYER
        )

        if value == self.scope:
            self._sync_scope_buttons()
            return

        self.scope = value
        self._sync_scope_buttons()
        self._rebuild_timeline()

    def refresh(self) -> None:
        """Reconstruye marcador, combo de jugadores, radar y timeline."""
        self._refresh_source_badge()
        self._fill_scoreboard()
        self._fill_player_combo()
        self._refresh_stats()
        self._rebuild_timeline()

    # -- pintado de datos ----------------------------------------------

    def _refresh_source_badge(self) -> None:
        final_sync = self.session.get("final_sync")
        status = ""
        message = ""

        if isinstance(final_sync, dict):
            status = str(final_sync.get("status") or "")
            message = str(final_sync.get("message") or "")

        if status == "synced":
            text = "Desglose local · Riot sincronizado"
        elif status in {"pending", "failed", "not_found", "live_only"}:
            text = "Desglose local (sin Riot)"
        else:
            text = "Telemetría LIVE"

        self.source_badge.setText(text)
        self.source_badge.setProperty("state", status or "live")
        self.source_badge.setToolTip(
            message or "El desglose se calcula con la telemetría local."
        )
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)

    def _fill_scoreboard(self) -> None:
        # Marcador "MI EQUIPO vs EQUIPO ENEMIGO" en dos columnas paralelas:
        # imagen, KDA, CS, oro, visión y build de cada jugador, con el jugador
        # local primero y ordenados por rol (TOP→JUNGLA→MEDIO→TIRADOR→APOYO).
        players = session_players(self.session)
        version = str(self.session.get("game_version") or "").strip()
        dd_version = ""

        try:
            dd_version = str(self._assets_version() or "").strip()
        except Exception:
            pass

        version = version or dd_version or "15.16.1"

        local_key = local_player_key(self.session)
        by_side = {"ally": [], "enemy": [], "": []}

        for key, player in players.items():
            if not isinstance(player, dict):
                continue

            side = team_side(self.session, player.get("team"))
            by_side.setdefault(side, []).append(key)

        for values in by_side.values():
            values.sort(
                key=lambda value: (
                    value != local_key,
                    ROLE_ORDER.index(
                        str(
                            (players.get(value) or {}).get("role") or "UNKNOWN"
                        ).upper()
                    ) if str(
                        (players.get(value) or {}).get("role") or "UNKNOWN"
                    ).upper() in ROLE_ORDER else len(ROLE_ORDER),
                )
            )

        # Empareja por rol: la fila i de cada columna es el mismo rol cuando
        # es posible, para comparar cara a cara.
        ally_keys = by_side.get("ally", [])
        enemy_keys = by_side.get("enemy", [])
        unknown_keys = by_side.get("", [])
        max_rows = max(len(ally_keys), len(enemy_keys), len(unknown_keys), 0)

        def fill_column(keys: list[str], layout: Any) -> None:
            # Solo se quitan las tarjetas previas: el espaciador final queda
            # para que las nuevas se apilen desde arriba.
            for index in reversed(range(layout.count())):
                entry = layout.itemAt(index)
                widget = entry.widget() if entry is not None else None

                if widget is not None and widget.objectName() == "postgamePlayerCard":
                    layout.takeAt(index)
                    widget.setParent(None)
                    widget.deleteLater()

            for key in keys:
                player = players.get(key)

                if not isinstance(player, dict):
                    continue

                card = self._create_player_card(
                    key, player, version, key == local_key
                )
                layout.insertWidget(max(0, layout.count() - 1), card)

        ally_layout = self.ally_column.layout()
        enemy_layout = self.enemy_column.layout()

        if ally_layout is not None:
            padded = list(ally_keys) + [None] * max(0, max_rows - len(ally_keys))
            fill_column([key for key in padded if key], ally_layout)

        if enemy_layout is not None:
            padded = list(enemy_keys) + [None] * max(0, max_rows - len(enemy_keys))
            fill_column([key for key in padded if key], enemy_layout)

        # Los jugadores sin bando conocido van a la columna con menos filas.
        if unknown_keys:
            target = (
                ally_layout
                if len(ally_keys) <= len(enemy_keys)
                else enemy_layout
            )

            if target is not None:
                fill_column(unknown_keys, target)

        # Encabezado con los totales de cada bando (asesinatos de equipo).
        try:
            self.team_header.setText(
                "MI EQUIPO "
                f"({team_kills(self.session, 'ally')})  ·  VS  ·  "
                f"EQUIPO ENEMIGO ({team_kills(self.session, 'enemy')})"
            )
        except Exception:
            pass

    def _catalog(self) -> dict[str, Any]:
        """Catálogo de objetos (para el build), tomado del window padre."""
        try:
            window = self.window()
        except (RuntimeError, AttributeError):
            return {}

        value = getattr(window, "item_catalog", None)

        return value if isinstance(value, dict) else {}

    def _assets_version(self) -> str:
        """Versión de Data Dragon para los iconos (nunca sale a la red)."""
        value = str(self.session.get("game_version") or "").strip()

        return value or DEFAULT_DD_VERSION

    def _create_player_card(
        self,
        key: str,
        player: dict,
        version: str,
        is_local: bool = False,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("postgamePlayerCard")
        card.setMinimumWidth(132)
        side = team_side(self.session, player.get("team"))
        accent = "#4a96ff" if side == "ally" else "#f06076"
        card.setStyleSheet(
            "QFrame#postgamePlayerCard { "
            f"border: 1px solid {accent}; "
            "border-radius: 10px; "
            "background: rgba(12, 22, 40, 215); }"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        champion_name = str(player.get("champion_name") or "").strip()
        role = str(player.get("role") or "").upper()
        stats = player_final_stats(self.session, key)

        header = QHBoxLayout()
        header.setSpacing(6)

        icon = QLabel()
        icon.setObjectName("postgameChampionIcon")
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = _champion_icon(champion_name, version, 36)

        if not pixmap.isNull():
            icon.setPixmap(pixmap)
        else:
            icon.setText(champion_name[:2].upper())
            icon.setStyleSheet(
                "color:#eef4ff; font-size:13px; font-weight:800; "
                "background:rgba(40,58,85,220); border-radius:6px;"
            )

        icon.setToolTip(champion_name or "Campeón")
        header.addWidget(icon)

        texts = QVBoxLayout()
        texts.setSpacing(1)

        name = QLabel(champion_name or "Desconocido")
        name.setObjectName("postgameChampionName")
        name.setStyleSheet(
            "color:#eef4ff; font-size:11px; font-weight:800; border:none;"
        )
        name.setToolTip(champion_name or "")
        texts.addWidget(name)

        badge = QLabel(
            ROLE_LABELS_ES.get(role, role or "—")
            + (" · TÚ" if is_local else "")
        )
        badge.setObjectName("postgameRoleBadge")
        badge.setStyleSheet(
            "color:#d9ae4f; font-size:9px; font-weight:800; border:none;"
        )
        badge.setToolTip("Tu jugador" if is_local else (role or "Rol"))
        texts.addWidget(badge)

        header.addLayout(texts, 1)
        layout.addLayout(header)

        kda = QLabel(
            f"{stats['kills']} / {stats['deaths']} / {stats['assists']}"
        )
        kda.setObjectName("postgameStatKda")
        kda.setStyleSheet(
            "color:#eef4ff; font-size:12px; font-weight:800; border:none;"
        )
        kda.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        kda.setToolTip(
            f"KDA {stats['kda']:.2f} · asesinatos / muertes / asistencias"
        )
        layout.addWidget(kda)

        numbers = QHBoxLayout()
        numbers.setSpacing(4)

        for caption, value, tooltip, object_name, colour in (
            (
                "CS",
                str(stats["cs"]),
                f"{stats['cspm']:.1f} CS/min",
                "postgameStatCs",
                "#38bdf8",
            ),
            (
                "ORO",
                _format_gold(stats["gold"]),
                f"{stats['gpm']:.0f} oro/min",
                "postgameStatGold",
                "#d9ae4f",
            ),
            (
                "VIS",
                str(stats["vision"]),
                "Puntuación de visión",
                "postgameStatVision",
                "#7ee7a6",
            ),
        ):
            block = QVBoxLayout()
            block.setSpacing(0)
            label = QLabel(caption)
            label.setObjectName("postgameStatCaption")
            label.setStyleSheet(
                "color:#8fa2bd; font-size:9px; font-weight:700; border:none;"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            amount = QLabel(value)
            amount.setObjectName(object_name)
            amount.setStyleSheet(
                f"color:{colour}; font-size:12px; font-weight:800; border:none;"
            )
            amount.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            amount.setToolTip(tooltip)
            block.addWidget(label)
            block.addWidget(amount)
            numbers.addLayout(block)

        layout.addLayout(numbers)

        build = QHBoxLayout()
        build.setSpacing(2)
        build.setContentsMargins(0, 0, 0, 0)
        catalog = self._catalog()

        for item_id in player_build_items(self.session, key):
            slot = QLabel()
            slot.setObjectName("postgameItemIcon")
            slot.setFixedSize(20, 20)
            slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item_pixmap = _item_icon(item_id, catalog, version, 18)

            if not item_pixmap.isNull():
                slot.setPixmap(item_pixmap)

            slot.setToolTip(_item_name(item_id, catalog))
            build.addWidget(slot)

        if build.count():
            layout.addLayout(build)

        layout.addStretch(1)

        return card


    def _fill_player_combo(self) -> None:
        self.player_combo.blockSignals(True)
        self.player_combo.clear()
        keys = ordered_player_keys(self.session)

        for key in keys:
            stats = player_final_stats(self.session, key)
            name = stats["champion"] or str(key)
            tag = " (yo)" if key == local_player_key(self.session) else ""
            self.player_combo.addItem(f"{name}{tag}", key)

        self.player_combo.blockSignals(False)
        self._sync_player_combo()

    def _sync_player_combo(self) -> None:
        index = self.player_combo.findData(self.player_key)

        if index < 0:
            return

        self.player_combo.blockSignals(True)
        self.player_combo.setCurrentIndex(index)
        self.player_combo.blockSignals(False)

    def _sync_scope_buttons(self) -> None:
        for scope, button in self.scope_buttons.items():
            button.blockSignals(True)
            button.setChecked(scope == self.scope)
            button.blockSignals(False)

    def _partner_by_role(self, role: Any) -> str:
        """Jugador del mismo rol en el bando contrario.

        Sirve para el radar: si el jugador elegido es del equipo rival, su
        pareja es el jugador aliado de ese mismo rol.
        """
        wanted = str(role or "").upper()
        players = session_players(self.session)
        own = players.get(self.player_key)
        own = own if isinstance(own, dict) else {}
        side = team_side(self.session, own.get("team"))
        target = "ally" if side == "enemy" else "enemy"

        for key in ordered_player_keys(self.session):
            if key == self.player_key:
                continue

            player = players.get(key)
            player = player if isinstance(player, dict) else {}

            if team_side(self.session, player.get("team")) != target:
                continue

            if str(player.get("role") or "").upper() == wanted:
                return key

        return ""

    def _refresh_stats(self) -> None:
        # Radar y resumen del jugador SELECCIONADO (por defecto, el local).
        key = self.player_key or local_player_key(self.session)
        stats = player_final_stats(self.session, key)
        partner = matchup_partner(self.session, key) or self._partner_by_role(
            stats.get("role")
        )
        rival = player_final_stats(self.session, partner) if partner else {}

        self.radar.set_data(
            radar_values(stats),
            radar_values(rival) if rival else [0.0] * 5,
            stats["champion"],
            str(rival.get("champion") or "Rival"),
        )

        allies_kills = team_kills(self.session, "ally")
        participation = stats["kills"] + stats["assists"]
        share = (
            f"{participation / allies_kills * 100:.0f}%"
            if allies_kills > 0
            else "—"
        )

        self.stats_label.setText(
            f"{stats['champion']} · "
            f"KDA {stats['kda']:.2f} · "
            f"{stats['cspm']:.1f} CS/min · "
            f"{stats['gpm']:.0f} oro/min · "
            f"Visión {stats['vision']} · "
            f"Nivel {stats['level']} · "
            f"Participación {share}"
        )

    def summary_text(self) -> str:
        """Resumen de la timeline actual (para la cabecera o los tests)."""
        counts: dict[str, int] = {}

        for event in self.review_events:
            kind = str(event.get("kind") or "")
            counts[kind] = counts.get(kind, 0) + 1

        order = (
            "kill",
            "death",
            "assist",
            "dragon",
            "baron",
            "rift_herald",
            "tower",
            "inhibitor",
            "item_purchase",
        )
        parts = [
            f"{counts[kind]} {kind_label(kind).lower()}"
            for kind in order
            if counts.get(kind)
        ]

        return " · ".join(parts)

    def _rebuild_timeline(self) -> None:
        wanted = None if self.scope == self.SCOPE_ALL else self.player_key
        self.review_events = build_review_events(self.session, wanted)

        for row in self.event_rows:
            row.setParent(None)
            row.deleteLater()

        self.event_rows = []

        for event in self.review_events:
            row = EventRow(event, self.review_container)
            row.activated.connect(self.event_activated.emit)
            self.review_layout.insertWidget(
                max(0, self.review_layout.count() - 1), row
            )
            self.event_rows.append(row)

        has_events = bool(self.review_events)
        self.review_scroll.setVisible(has_events)
        self.review_empty.setVisible(not has_events)
        self.tabs.setTabText(1, f"Revisión ({len(self.review_events)})")
        try:
            self.events_changed.emit()
        except RuntimeError:
            pass

    #: Tipos de suceso que aparecen como indicadores en la barra de duración.
    MARKER_KINDS = {
        "kill",
        "death",
        "assist",
        "dragon",
        "baron",
        "rift_herald",
        "herald",
        "horde",
        "tower",
        "inhibitor",
        "objective",
    }

    def review_markers(self, game_time_offset: float = 0.0) -> list[dict[str, Any]]:
        """Indicadores de la barra de duración según el filtro actual.

        Devuelve los sucesos de ``review_events`` (jugador/alcance elegidos)
        convertidos al formato de la barra: momento desplazado a tiempo de
        vídeo, tipo canónico, etiqueta, detalle y equipo.
        """
        markers: list[dict[str, Any]] = []

        try:
            offset = float(game_time_offset or 0.0)
        except (TypeError, ValueError):
            offset = 0.0

        for order, event in enumerate(self.review_events or []):
            if not isinstance(event, dict):
                continue

            kind = normalise_marker_kind(str(event.get("kind") or ""))

            if kind not in self.MARKER_KINDS:
                continue

            try:
                moment = max(0.0, _number(event.get("time")) - offset)
            except (TypeError, ValueError):
                moment = 0.0

            label = str(event.get("label") or kind_label(kind))
            detail = str(event.get("detail") or label)
            owner = str(event.get("player_name") or "").strip()

            if owner and owner.casefold() not in detail.casefold():
                detail = f"{detail} · {owner}"

            markers.append(
                {
                    "time": round(moment, 1),
                    "kind": kind,
                    "label": label,
                    "detail": detail,
                    "glyph": str(event.get("glyph") or kind_glyph(kind)),
                    "team": str(
                        event.get("team")
                        or event.get("objective_team")
                        or event.get("owner_team")
                        or ""
                    ),
                    "order": _int(event.get("order"), order),
                }
            )

        markers.sort(key=lambda marker: (marker["time"], marker["order"]))

        return markers

    # -- interacción ----------------------------------------------------

    def _on_player_combo_changed(self, index: int) -> None:
        key = self.player_combo.itemData(index)
        if key:
            self.set_player(str(key))


def _key(player: dict) -> str:
    """Clave interna de jugador (para lookup en session_players)."""
    if not isinstance(player, dict):
        return ""
    for candidate in ("player_key", "summonerName", "riotId", "championName"):
        value = player.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


#: Versión de Data Dragon usada si la sesión no declara la suya.
DEFAULT_DD_VERSION = "15.16.1"


def _champion_icon(champion_name: str, version: str, size: int) -> QPixmap:
    """Retrato del campeón desde la caché local (no descarga aquí)."""
    if not champion_name:
        return QPixmap()

    try:
        path = get_champion_icon_path(champion_name, version, download=False)
    except (OSError, ValueError):
        path = None

    return _scaled_local_pixmap(path, size)


def _item_icon(
    item_id: Any,
    catalog: dict[str, Any],
    version: str,
    size: int,
) -> QPixmap:
    """Icono de objeto desde la caché local (no descarga aquí)."""
    try:
        path = get_item_icon_path(item_id, catalog, version, download=False)
    except (OSError, ValueError):
        path = None

    return _scaled_local_pixmap(path, size)


def _scaled_local_pixmap(path: Any, size: int) -> QPixmap:
    if path is None:
        return QPixmap()

    pixmap = QPixmap(str(path))

    if pixmap.isNull():
        return QPixmap()

    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _format_gold(value: Any) -> str:
    """Oro abreviado: 12.5k a partir de mil, número exacto por debajo."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = 0

    if number >= 1000:
        return f"{number / 1000:.1f}k".replace(".", ",")

    return str(number)


def _item_name(item_id: Any, catalog: dict[str, Any]) -> str:
    data = catalog

    if isinstance(data, dict) and isinstance(data.get("items"), dict):
        data = data["items"]

    entry = data.get(str(item_id)) if isinstance(data, dict) else None

    if isinstance(entry, dict):
        name = str(entry.get("name") or "").strip()

        if name:
            return name

    return f"Objeto {item_id}"


def _item_ids(values: Any) -> list[int]:
    """IDs de objeto a partir de una lista o de un mapa por hueco."""
    if isinstance(values, dict):
        values = [values[key] for key in sorted(values, key=lambda value: str(value))]

    if not isinstance(values, list):
        return []

    result: list[int] = []

    for value in values:
        if isinstance(value, dict):
            value = value.get("itemID") or value.get("itemId") or value.get("id")

        try:
            number = int(value)
        except (TypeError, ValueError):
            continue

        if number > 0:
            result.append(number)

    return result


def player_build_items(session: dict[str, Any], player_key: str) -> list[int]:
    """Objetos del jugador: marcador final (Riot) y, si no, último snapshot."""
    final = session.get("final_scoreboard")

    if isinstance(final, dict):
        entry = final.get(player_key)

        if isinstance(entry, dict):
            ids = _item_ids(entry.get("items"))

            if ids:
                return ids

    return _item_ids(latest_point(session, player_key).get("items"))

"""Tarjeta visual de un jugador en la pestaña «Partida en vivo».

Resume el estado de un jugador (campeón, KDA, granja, oro en objetos, runas
con su icono oficial, estadísticas estimadas e inventario) sobre un fondo
teñido con el color de su equipo.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services.game_calculator import (
    calculate_estimated_enemy_stats,
    calculate_item_stats,
    get_inventory_value,
    normalize_live_stats,
)
from app.ui.inventory import create_item_slots, get_player_role
from data_dragon import (
    get_champion_data,
    get_champion_icon_path,
    get_rune_icon_path,
)


CARD_HEIGHT = 292
CHIP_LIMIT = 6
CHIP_COLUMNS = 3
CHIP_ROWS = 2
CHIP_ROW_HEIGHT = 22
CHIP_ROW_SPACING = 5
CHIP_MARGIN = 6
INVENTORY_SLOT_SIZE = 32
INVENTORY_SLOT_SPACING = 6
PIXMAP_CACHE_LIMIT = 192
MAX_EQUIPPED_ITEMS = 6

_PIXMAP_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()

ROLE_LABELS = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLA",
    "MIDDLE": "MID",
    "BOTTOM": "BOT",
    "UTILITY": "SUPPORT",
}

RUNE_TREE_COLORS = {
    "precision": "#e6a23c",
    "domination": "#e05b63",
    "sorcery": "#55a9ff",
    "resolve": "#55c98b",
    "inspiration": "#8ed6d9",
}

CHIP_COLORS = {
    "hp": "#7ee787",
    "ad": "#ffab73",
    "ap": "#8ab4ff",
    "armor": "#ffd479",
    "mr": "#c79bff",
    "crit": "#ffd479",
    "lethality": "#ffab73",
    "pen": "#8ab4ff",
    "lifesteal": "#7ee787",
    "grievous": "#ff8080",
    "more": "#a9bad2",
}

CHIP_TAGS = {
    "hp": "VIDA",
    "ad": "AD",
    "ap": "AP",
    "armor": "ARM",
    "mr": "MR",
    "crit": "CRIT",
    "lethality": "LET",
    "pen": "PEN ARM",
    "lifesteal": "ROBO DE VIDA",
    "grievous": "HERIDAS GRAVES",
}

CHIP_TOOLTIPS = {
    "hp": "Vida máxima estimada con nivel, runas y objetos",
    "ad": "Daño de ataque estimado",
    "ap": "Poder de habilidad estimado",
    "armor": "Armadura estimada",
    "mr": "Resistencia mágica estimada",
    "crit": "Probabilidad de crítico estimada",
    "lethality": "Letalidad estimada",
    "pen": "Penetración de armadura estimada",
    "lifesteal": "Robo de vida estimado",
    "grievous": "Lleva objetos con heridas graves",
    "more": "Hay más estadísticas calculadas para este jugador",
}

TEAM_THEMES = {
    "ORDER": {
        "top": QColor(17, 46, 79, 242),
        "bottom": QColor(7, 15, 27, 242),
        "accent": QColor(74, 150, 255),
    },
    "CHAOS": {
        "top": QColor(60, 23, 37, 242),
        "bottom": QColor(20, 9, 17, 242),
        "accent": QColor(240, 96, 118),
    },
    "DEFAULT": {
        "top": QColor(21, 33, 54, 242),
        "bottom": QColor(9, 15, 26, 242),
        "accent": QColor(140, 165, 200),
    },
}

LOCAL_ACCENT = QColor(217, 174, 79)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _with_alpha(color: QColor, alpha: int) -> QColor:
    faded = QColor(color)
    faded.setAlpha(alpha)
    return faded


def _scaled_cached_pixmap(
    key: tuple,
    path,
    size: int,
) -> QPixmap:
    """Escala una imagen ya descargada y la guarda en una caché corta."""
    cached = _PIXMAP_CACHE.get(key)

    if cached is not None:
        _PIXMAP_CACHE.move_to_end(key)
        return cached

    if path is None:
        return QPixmap()

    pixmap = QPixmap(str(path))

    if pixmap.isNull():
        return QPixmap()

    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    _PIXMAP_CACHE[key] = scaled

    while len(_PIXMAP_CACHE) > PIXMAP_CACHE_LIMIT:
        _PIXMAP_CACHE.popitem(last=False)

    return scaled


def champion_pixmap(
    champion_name: str,
    version: str,
    size: int,
) -> QPixmap:
    """Retrato del campeón (se descarga solo la primera vez)."""
    if not champion_name:
        return QPixmap()

    return _scaled_cached_pixmap(
        ("champion", champion_name, size),
        get_champion_icon_path(champion_name, version),
        size,
    )


def rune_pixmap(
    rune_name: str,
    version: str,
    size: int,
) -> QPixmap:
    """Icono oficial de una runa usando únicamente la caché local."""
    if not rune_name:
        return QPixmap()

    return _scaled_cached_pixmap(
        ("rune", rune_name, size),
        get_rune_icon_path(rune_name, version, download=False),
        size,
    )


def build_stat_chips(
    stats: dict,
    estimated: bool,
) -> list[tuple[str, str, str]]:
    """Convierte las estadísticas en fichas (tipo, texto, ayuda)."""
    prefix = "≈" if estimated else ""
    entries: list[tuple[str, str]] = []

    def add(kind: str, value_text: str) -> None:
        entries.append((kind, f"{prefix}{value_text}"))

    if _number(stats.get("hp")) > 0:
        add("hp", f"{_int(stats['hp'])}")

    if _number(stats.get("ad")) > 0:
        add("ad", f"{_int(stats['ad'])}")

    if _number(stats.get("ap")) > 0:
        add("ap", f"{_int(stats['ap'])}")

    if _number(stats.get("armor")) > 0:
        add("armor", f"{_int(stats['armor'])}")

    if _number(stats.get("mr")) > 0:
        add("mr", f"{_int(stats['mr'])}")

    crit = _number(stats.get("crit"))
    if crit > 0:
        crit = crit * 100 if crit <= 1 else crit
        add("crit", f"{_int(crit)}%")

    if _number(stats.get("lethality")) > 0:
        add("lethality", f"{_int(stats['lethality'])}")

    penetration = _number(stats.get("armor_pen_percent"))
    if penetration > 0:
        penetration = (
            penetration * 100 if penetration <= 1 else penetration
        )
        add("pen", f"{_int(penetration)}%")

    life_steal = _number(stats.get("life_steal_percent"))
    if life_steal > 0:
        life_steal = (
            life_steal * 100 if life_steal <= 1 else life_steal
        )
        add("lifesteal", f"{_int(life_steal)}%")

    if stats.get("grievous_wounds"):
        add("grievous", "")

    chips = [
        (kind, f"{CHIP_TAGS[kind]} {text}".strip(), CHIP_TOOLTIPS[kind])
        for kind, text in entries
    ]

    if len(chips) > CHIP_LIMIT:
        hidden = chips[CHIP_LIMIT - 1:]
        chips = chips[: CHIP_LIMIT - 1]
        chips.append(
            (
                "more",
                f"+{len(hidden)}",
                ", ".join(text for _, text, _ in hidden),
            )
        )

    return chips


def create_divider() -> QFrame:
    """Línea fina de separación entre bloques de la tarjeta."""
    divider = QFrame()
    divider.setObjectName("cardDivider")
    divider.setFixedHeight(1)
    return divider


def format_gold(value) -> str:
    """Formatea el oro con separador de millares español."""
    return f"{int(value or 0):,}".replace(",", ".") + " g"


class ChampionCard(QFrame):
    """Tarjeta visual individual de un jugador."""

    def __init__(
        self,
        player: dict,
        is_local_player: bool,
        item_catalog: dict,
        version: str,
        game_time: float,
        local_live_stats: dict | None,
    ) -> None:
        super().__init__()

        self.player = player
        self.is_local_player = is_local_player
        self.item_catalog = item_catalog
        self.version = version
        self.game_time = game_time
        self.local_live_stats = local_live_stats
        self.team = str(
            player.get("team", "")
        ).upper()
        self.role = get_player_role(player)

        self.setObjectName(
            "playerCardMe"
            if is_local_player
            else "playerCard"
        )

        # Propiedad usada por la hoja de estilos para teñir los acentos.
        self.setProperty(
            "team",
            "chaos" if self.team == "CHAOS" else "order",
        )

        self.setFixedHeight(CARD_HEIGHT)
        self.setMinimumWidth(240)

        self.build_ui()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(5)

        layout.addLayout(self.create_header())
        layout.addWidget(create_divider())
        layout.addLayout(self.create_stats_row())
        layout.addWidget(create_divider())
        layout.addWidget(self.create_rune_strip())
        layout.addWidget(self.create_stat_chips())
        layout.addWidget(create_divider())
        layout.addWidget(self.create_inventory_block())
        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Cabecera: retrato, nombre, jugador, rol y chapas
    # ------------------------------------------------------------------
    def create_header(self) -> QHBoxLayout:
        champion_name = str(
            self.player.get("championName")
            or "Desconocido"
        )
        riot_id = str(
            self.player.get("riotId")
            or self.player.get("summonerName")
            or "Desconocido"
        )
        level = _int(self.player.get("level"))

        header = QHBoxLayout()
        header.setSpacing(10)

        header.addWidget(
            self.create_champion_icon(champion_name),
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        names = QVBoxLayout()
        names.setSpacing(2)
        names.setContentsMargins(0, 1, 0, 0)

        champion_label = QLabel(champion_name)
        champion_label.setObjectName("cardChampionName")
        champion_label.setWordWrap(False)
        names.addWidget(champion_label)

        meta = QHBoxLayout()
        meta.setSpacing(6)

        player_label = QLabel(riot_id)
        player_label.setObjectName("cardPlayerId")
        player_label.setWordWrap(False)
        meta.addWidget(player_label)

        role_label = ROLE_LABELS.get(self.role)
        if role_label:
            role_chip = QLabel(role_label)
            role_chip.setObjectName("cardRoleChip")
            meta.addWidget(role_chip)

        meta.addStretch(1)
        names.addLayout(meta)

        header.addLayout(names, 1)

        badges = QVBoxLayout()
        badges.setSpacing(4)

        level_badge = QLabel(f"NV {level}")
        level_badge.setObjectName("cardLevelBadge")
        level_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        level_badge.setToolTip(f"Nivel {level}")
        badges.addWidget(
            level_badge,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        if self.is_local_player:
            me_badge = QLabel("TÚ")
            me_badge.setObjectName("cardMeBadge")
            me_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            me_badge.setToolTip("Es tu jugador")
            badges.addWidget(
                me_badge,
                0,
                Qt.AlignmentFlag.AlignRight,
            )
        else:
            badges.addStretch(1)

        header.addLayout(badges)
        return header

    def create_champion_icon(self, champion_name: str) -> QLabel:
        icon = QLabel()
        icon.setObjectName("cardChampionIcon")
        icon.setFixedSize(50, 50)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setToolTip(champion_name)

        pixmap = champion_pixmap(champion_name, self.version, 44)

        if pixmap.isNull():
            icon.setText(champion_name[:2].upper())
        else:
            icon.setPixmap(pixmap)

        return icon

    # ------------------------------------------------------------------
    # KDA, granja y oro en objetos
    # ------------------------------------------------------------------
    def create_stats_row(self) -> QHBoxLayout:
        scores = self.player.get("scores", {})

        if not isinstance(scores, dict):
            scores = {}

        kills = _int(scores.get("kills"))
        deaths = _int(scores.get("deaths"))
        assists = _int(scores.get("assists"))
        cs = _int(scores.get("creepScore"))
        cs_per_minute = cs / max(self.game_time / 60, 0.01)
        build_value = get_inventory_value(
            self.player,
            self.item_catalog,
        )

        kda_html = (
            f"<span style='color:#66d98a'>{kills}</span>"
            "<span style='color:#5d7290'> / </span>"
            f"<span style='color:#f0736f'>{deaths}</span>"
            "<span style='color:#5d7290'> / </span>"
            f"<span style='color:#5cb6ef'>{assists}</span>"
        )

        cs_html = (
            f"{cs}"
            "<span style='color:#8fa2bd;font-size:9px'> "
            f"{cs_per_minute:.1f}/min</span>"
        )

        row = QHBoxLayout()
        row.setSpacing(6)

        row.addWidget(
            self.create_stat_block(
                "KDA",
                kda_html,
                "Asesinatos / muertes / asistencias",
            ),
            1,
        )
        row.addWidget(
            self.create_stat_block(
                "CS",
                cs_html,
                f"{cs} súbditos · {cs_per_minute:.1f} por minuto",
            ),
            1,
        )
        row.addWidget(
            self.create_stat_block(
                "ORO",
                format_gold(build_value),
                "Valor de los objetos equipados",
            ),
            1,
        )

        return row

    def create_stat_block(
        self,
        caption: str,
        value_html: str,
        tooltip: str,
    ) -> QFrame:
        block = QFrame()
        block.setObjectName("cardStat")
        block.setFixedHeight(38)
        block.setToolTip(tooltip)

        layout = QVBoxLayout(block)
        layout.setContentsMargins(8, 3, 8, 4)
        layout.setSpacing(0)

        caption_label = QLabel(caption)
        caption_label.setObjectName("cardStatLabel")
        layout.addWidget(caption_label)

        value_label = QLabel(value_html)
        value_label.setObjectName("cardStatValue")
        value_label.setTextFormat(Qt.TextFormat.RichText)
        value_label.setWordWrap(False)
        layout.addWidget(value_label)

        return block

    def resolve_stats(self) -> tuple[dict, bool]:
        """Estadísticas del jugador y si son estimadas o medidas en vivo."""
        if (
            self.is_local_player
            and self.local_live_stats is not None
        ):
            stats = normalize_live_stats(self.local_live_stats)
            item_stats = calculate_item_stats(
                self.player,
                self.item_catalog,
            )
            stats["grievous_wounds"] = item_stats.get(
                "grievous_wounds",
                False,
            )
            return stats, False

        champion_data = get_champion_data(
            str(self.player.get("championName", "")),
            self.version,
        )

        return (
            calculate_estimated_enemy_stats(
                self.player,
                champion_data,
                self.item_catalog,
            ),
            True,
        )

    # ------------------------------------------------------------------
    # Runas: piedra angular y árboles con sus iconos
    # ------------------------------------------------------------------
    def create_rune_strip(self) -> QFrame:
        runes = self.player.get("runes", {})

        if not isinstance(runes, dict):
            runes = {}

        keystone = runes.get("keystone", {})
        primary = runes.get("primaryRuneTree", {})
        secondary = runes.get("secondaryRuneTree", {})

        keystone_name = str(
            keystone.get("displayName")
            if isinstance(keystone, dict)
            else ""
        ).strip()
        primary_name = str(
            primary.get("displayName")
            if isinstance(primary, dict)
            else ""
        ).strip()
        secondary_name = str(
            secondary.get("displayName")
            if isinstance(secondary, dict)
            else ""
        ).strip()

        primary_color = RUNE_TREE_COLORS.get(
            primary_name.casefold(),
            "#b696eb",
        )

        strip = QFrame()
        strip.setObjectName("cardRunes")
        strip.setFixedHeight(30)
        strip.setToolTip(
            "Runas: "
            f"{keystone_name or 'sin datos'} · "
            f"{primary_name or 'árbol desconocido'} / "
            f"{secondary_name or 'árbol desconocido'}"
        )

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(7)

        layout.addWidget(
            self.create_rune_icon(
                keystone_name,
                24,
                "cardRuneIcon",
                keystone_name or "Runa desconocida",
                "✦",
            )
        )

        keystone_label = QLabel(
            keystone_name or "Runas sin datos"
        )
        keystone_label.setObjectName("cardRuneKeystone")
        keystone_label.setStyleSheet(
            f"color: {primary_color};"
        )
        keystone_label.setWordWrap(False)
        layout.addWidget(keystone_label)
        layout.addStretch(1)

        if primary_name:
            layout.addWidget(
                self.create_rune_icon(
                    primary_name,
                    18,
                    "cardRuneTreeIcon",
                    f"Árbol principal · {primary_name}",
                    "◆",
                )
            )

        if secondary_name:
            separator = QLabel("›")
            separator.setObjectName("cardRuneSeparator")
            layout.addWidget(separator)
            layout.addWidget(
                self.create_rune_icon(
                    secondary_name,
                    18,
                    "cardRuneTreeIcon",
                    f"Árbol secundario · {secondary_name}",
                    "◆",
                )
            )

        return strip

    def create_rune_icon(
        self,
        rune_name: str,
        size: int,
        object_name: str,
        tooltip: str,
        placeholder: str,
    ) -> QLabel:
        icon = QLabel()
        icon.setObjectName(object_name)
        icon.setFixedSize(size, size)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if tooltip:
            icon.setToolTip(tooltip)

        pixmap = rune_pixmap(rune_name, self.version, size - 4)

        if pixmap.isNull():
            icon.setText(placeholder)
        else:
            icon.setPixmap(pixmap)

        return icon

    # ------------------------------------------------------------------
    # Estadísticas estimadas en fichas de color
    # ------------------------------------------------------------------
    def create_stat_chips(self) -> QFrame:
        stats, estimated = self.resolve_stats()
        chips = build_stat_chips(stats, estimated)

        frame = QFrame()
        frame.setObjectName("cardChips")
        # Se reservan siempre dos filas: así las secciones de todas las
        # tarjetas de la fila quedan a la misma altura.
        frame.setMinimumHeight(
            CHIP_ROWS * CHIP_ROW_HEIGHT
            + (CHIP_ROWS - 1) * CHIP_ROW_SPACING
            + 2 * CHIP_MARGIN
        )
        frame.setToolTip(
            "Estadísticas estimadas con el nivel, los objetos y las runas"
            if estimated
            else "Estadísticas medidas en vivo por el cliente"
        )

        grid = QGridLayout(frame)
        grid.setContentsMargins(
            CHIP_MARGIN,
            CHIP_MARGIN,
            CHIP_MARGIN,
            CHIP_MARGIN,
        )
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(CHIP_ROW_SPACING)

        for column in range(CHIP_COLUMNS):
            grid.setColumnStretch(column, 1)

        if not chips:
            empty = QLabel("Sin estadísticas calculadas")
            empty.setObjectName("cardChipsEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(empty, 0, 0, 1, CHIP_COLUMNS)
            return frame

        total = len(chips)

        for index, (kind, text, tooltip) in enumerate(chips):
            column = index % CHIP_COLUMNS
            row = index // CHIP_COLUMNS

            # Una ficha sola en su fila se centra para no dejar un hueco
            # descolgado a la derecha.
            if (
                index == total - 1
                and column == 0
                and (row > 0 or total == 1)
            ):
                column = CHIP_COLUMNS // 2

            chip = QLabel(text)
            chip.setObjectName("cardChip")
            chip.setProperty("kind", kind)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setToolTip(tooltip)
            chip.setFixedHeight(CHIP_ROW_HEIGHT)
            grid.addWidget(chip, row, column)

        return frame

    # ------------------------------------------------------------------
    # Inventario
    # ------------------------------------------------------------------
    def create_inventory_block(self) -> QWidget:
        block = QWidget()
        block.setObjectName("cardInventory")

        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        title = QLabel("INVENTARIO")
        title.setObjectName("cardInventoryTitle")
        header.addWidget(title)
        header.addStretch(1)

        count = self.count_equipped_items()
        count_label = QLabel(
            "1 objeto" if count == 1 else f"{count} objetos"
        )
        count_label.setObjectName("cardInventoryCount")
        header.addWidget(count_label)

        layout.addLayout(header)

        inventory = create_item_slots(
            player=self.player,
            item_catalog=self.item_catalog,
            version=self.version,
            size=INVENTORY_SLOT_SIZE,
            spacing=INVENTORY_SLOT_SPACING,
        )

        if inventory is not None:
            layout.addWidget(inventory)

        return block

    def count_equipped_items(self) -> int:
        """Objetos equipados (sin trinket ni huecos vacíos)."""
        count = 0

        for item in self.player.get("items", []):
            if not isinstance(item, dict):
                continue

            try:
                slot = int(item.get("slot", -1))
            except (TypeError, ValueError):
                continue

            if 0 <= slot < MAX_EQUIPPED_ITEMS and item.get("itemID"):
                count += 1

        return count

    # ------------------------------------------------------------------
    # Fondo de la tarjeta con el color del equipo
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme = TEAM_THEMES.get(self.team, TEAM_THEMES["DEFAULT"])
        accent = theme["accent"]

        area = self.rect().adjusted(1, 1, -1, -1)

        path = QPainterPath()
        path.addRoundedRect(area, 12, 12)
        painter.setClipPath(path)

        base = QLinearGradient(0, 0, 0, self.height())
        base.setColorAt(0.0, theme["top"])
        base.setColorAt(0.55, _with_alpha(theme["top"], 205))
        base.setColorAt(1.0, theme["bottom"])
        painter.fillRect(self.rect(), base)

        glow = QRadialGradient(
            self.width() * 0.92,
            self.height() * 0.03,
            max(self.width(), self.height()) * 0.95,
        )
        glow.setColorAt(0.0, _with_alpha(accent, 50))
        glow.setColorAt(0.45, _with_alpha(accent, 14))
        glow.setColorAt(1.0, _with_alpha(accent, 0))
        painter.fillRect(self.rect(), glow)

        bar = QLinearGradient(0, 0, 0, self.height())
        bar.setColorAt(0.0, _with_alpha(accent, 235))
        bar.setColorAt(1.0, _with_alpha(accent, 80))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bar)
        painter.drawRoundedRect(
            QRect(area.left(), area.top() + 9, 3, area.height() - 18),
            1.5,
            1.5,
        )

        border_color = (
            LOCAL_ACCENT
            if self.is_local_player
            else accent
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(border_color, 190), 1))
        painter.drawRoundedRect(area, 12, 12)

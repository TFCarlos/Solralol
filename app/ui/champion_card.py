"""Tarjeta visual de un jugador en la pestaña «Partida en vivo».

Resume el estado de un jugador (campeón, KDA, granja, oro en objetos, runas
con su icono oficial, estadísticas estimadas e inventario) sobre un fondo
teñido con el color de su equipo.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.game_calculator import (
    calculate_estimated_enemy_stats,
    calculate_item_stats,
    normalize_live_stats,
)
from app.ui.icono_pixmap import IconoPixmap
from app.ui.inventory import create_item_icon, get_player_role
from app.ui.sistema_visual import PALETA
from app.ui.tema import actualizar_estilo, color_con_alfa
from data_dragon import (
    get_champion_data,
    get_champion_icon_path,
    get_rune_icon_path,
    resolver_icono_hechizo_invocador,
)

CARD_MIN_HEIGHT = 270
CARD_MAX_HEIGHT = 560
CHIP_LIMIT = 6
CHIP_COLUMNS = 2
CHIP_ROWS = 3
CHIP_ROW_HEIGHT = 26
CHIP_ROW_SPACING = 5
CHIP_MARGIN = 6
INVENTORY_SLOT_SIZE = 28
INVENTORY_SLOT_SPACING = 2
PIXMAP_CACHE_LIMIT = 192
MAX_EQUIPPED_ITEMS = 6

_PIXMAP_CACHE: OrderedDict[tuple[Any, ...], QPixmap] = OrderedDict()
_LOGGER = logging.getLogger(__name__)


class EtiquetaElidida(QLabel):
    """Muestra el texto completo en tooltip y lo elide al ancho disponible."""

    def __init__(self, texto: str, parent: QWidget | None = None) -> None:
        """Inicializa una etiqueta flexible para identificadores largos."""
        super().__init__(parent)
        self._texto_completo = texto
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setWordWrap(False)
        self.setToolTip(texto)
        self.setAccessibleName(texto)
        self._actualizar_texto()

    def resizeEvent(self, event: Any) -> None:
        """Actualiza el texto visible cuando cambia el ancho de la etiqueta."""
        super().resizeEvent(event)
        self._actualizar_texto()

    def _actualizar_texto(self) -> None:
        """Recorta visualmente el identificador sin perder su valor original."""
        visible = self.fontMetrics().elidedText(
            self._texto_completo,
            Qt.TextElideMode.ElideRight,
            max(0, self.contentsRect().width()),
        )
        if self.text() != visible:
            self.setText(visible)

    def establecer_texto(self, texto: str) -> None:
        """Actualiza el valor y tooltip de la etiqueta elidida.

        Args:
            texto: Contenido completo que se conservará para tooltip y elisión.
        Returns:
            None.
        """
        self._texto_completo = texto
        self.setToolTip(texto)
        self.setAccessibleName(texto)
        self._actualizar_texto()


ROLE_LABELS = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLA",
    "MIDDLE": "MID",
    "BOTTOM": "BOT",
    "UTILITY": "SUPPORT",
}

RUNE_TREE_COLORS = {
    "precision": PALETA["oro_suave"],
    "domination": PALETA["desventaja"],
    "sorcery": PALETA["teal"],
    "resolve": PALETA["ventaja"],
    "inspiration": PALETA["teal"],
}

CHIP_COLORS = {
    "hp": PALETA["ventaja"],
    "ad": PALETA["oro_suave"],
    "ap": PALETA["teal"],
    "armor": PALETA["oro_suave"],
    "mr": PALETA["magenta"],
    "crit": PALETA["oro_suave"],
    "lethality": PALETA["oro_suave"],
    "pen": PALETA["teal"],
    "lifesteal": PALETA["ventaja"],
    "grievous": PALETA["desventaja"],
    "more": PALETA["texto"],
}

CHIP_TAGS = {
    "hp": "VIDA",
    "ad": "AD",
    "ap": "AP",
    "armor": "ARM",
    "mr": "MR",
    "crit": "CRIT",
    "lethality": "LET",
    "pen": "PEN",
    "lifesteal": "ROBO",
    "grievous": "HERIDAS",
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
        "top": color_con_alfa("borde", 242),
        "bottom": color_con_alfa("base", 242),
        "accent": color_con_alfa("teal", 255),
    },
    "CHAOS": {
        "top": color_con_alfa("elevada", 242),
        "bottom": color_con_alfa("base", 242),
        "accent": color_con_alfa("desventaja", 255),
    },
    "DEFAULT": {
        "top": color_con_alfa("elevada", 242),
        "bottom": color_con_alfa("base", 242),
        "accent": color_con_alfa("teal", 255),
    },
}

LOCAL_ACCENT = color_con_alfa("oro_suave", 255)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _int_opcional(valor: object) -> int | None:
    """Convierte un valor observado en entero sin convertir ausencias en cero."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _with_alpha(color: QColor, alpha: int) -> QColor:
    faded = QColor(color)
    faded.setAlpha(alpha)
    return faded


def _cached_source_pixmap(key: tuple[Any, ...], path: Path | None) -> QPixmap:
    """Carga una fuente local y la conserva en una caché corta.

    Args:
        key: Identidad estable del recurso.
        path: Ruta local del pixmap.
    Returns:
        Pixmap fuente sin escalar o vacío si el recurso no se puede leer.
    """
    cached = _PIXMAP_CACHE.get(key)

    if cached is not None:
        _PIXMAP_CACHE.move_to_end(key)
        return cached

    if path is None:
        return QPixmap()

    pixmap = QPixmap(str(path))

    if pixmap.isNull():
        return QPixmap()

    _PIXMAP_CACHE[key] = pixmap

    while len(_PIXMAP_CACHE) > PIXMAP_CACHE_LIMIT:
        _PIXMAP_CACHE.popitem(last=False)

    return pixmap


def champion_pixmap(
    champion_name: str,
    version: str,
) -> QPixmap:
    """Devuelve el pixmap fuente del campeón desde la caché local.

    Args:
        champion_name: Nombre del campeón.
        version: Versión de Data Dragon.
    Returns:
        Pixmap fuente o vacío si no hay recurso disponible.
    """
    if not champion_name:
        return QPixmap()

    return _cached_source_pixmap(
        ("champion", version, champion_name),
        get_champion_icon_path(champion_name, version),
    )


def rune_pixmap(
    rune_name: str,
    version: str,
) -> QPixmap:
    """Devuelve el pixmap fuente de una runa desde la caché local.

    Args:
        rune_name: Nombre observado de la runa.
        version: Versión de Data Dragon.
    Returns:
        Pixmap fuente o vacío si no hay recurso disponible.
    """
    if not rune_name:
        return QPixmap()

    return _cached_source_pixmap(
        ("rune", version, rune_name),
        get_rune_icon_path(rune_name, version, download=False),
    )


def spell_pixmap(spell_name: object, version: str) -> QPixmap:
    """Devuelve la fuente local resuelta para un hechizo observado.

    Args:
        spell_name: Registro LIVE, nombre o identificador del hechizo.
        version: Versión de Data Dragon.
    Returns:
        Pixmap fuente o vacío si no hay recurso disponible.
    """
    resolucion = resolver_icono_hechizo_invocador(spell_name, version, download=False)
    if resolucion.estado != "resuelto" or resolucion.ruta is None:
        return QPixmap()
    return _cached_source_pixmap(
        ("spell", version, resolucion.identificador_normalizado), resolucion.ruta
    )


def build_stat_chips(
    stats: dict,
    estimated: bool,
) -> list[tuple[str, str, str]]:
    """Devuelve tipo, valor y ayuda sin repetir la etiqueta de cada metrica.

    Args:
        stats: Valores normalizados de combate.
        estimated: Indica si los valores se estimaron.
    Returns:
        Fichas con el tipo, el valor y el texto de ayuda.
    """
    prefix = "\u2248" if estimated else ""
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
        penetration = penetration * 100 if penetration <= 1 else penetration
        add("pen", f"{_int(penetration)}%")
    life_steal = _number(stats.get("life_steal_percent"))
    if life_steal > 0:
        life_steal = life_steal * 100 if life_steal <= 1 else life_steal
        add("lifesteal", f"{_int(life_steal)}%")
    if stats.get("grievous_wounds"):
        add("grievous", "")

    chips = [(kind, text, CHIP_TOOLTIPS[kind]) for kind, text in entries]
    if len(chips) > CHIP_LIMIT:
        hidden = chips[CHIP_LIMIT - 1 :]
        chips = chips[: CHIP_LIMIT - 1]
        chips.append(
            (
                "more",
                f"+{len(hidden)}",
                ", ".join(
                    f"{CHIP_TAGS[kind]} {text}".strip() for kind, text, _ in hidden
                ),
            )
        )
    return chips


def create_divider() -> QFrame:
    """Crea una linea fina entre las secciones de la tarjeta.

    Args:
        None.
    Returns:
        Separador visual de un pixel.
    """
    divider = QFrame()
    divider.setObjectName("cardDivider")
    divider.setFixedHeight(1)
    return divider


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
        """Construye una tarjeta responsiva a partir del estado LIVE.

        Args:
            player: Participante y datos de inventario, runas y marcador.
            is_local_player: Indica si se trata del jugador de este cliente.
            item_catalog: Catálogo local de objetos.
            version: Versión de recursos de Data Dragon.
            game_time: Tiempo de partida en segundos.
            local_live_stats: Estadísticas activas del jugador local.
        Returns:
            None.
        """
        super().__init__()

        self.player = player
        self.is_local_player = is_local_player
        self.item_catalog = item_catalog
        self.version = version
        self.game_time = game_time
        self.local_live_stats = local_live_stats
        self.team = str(player.get("team", "")).upper()
        self.role = get_player_role(player)

        self.setObjectName("playerCardMe" if is_local_player else "playerCard")

        # Propiedad usada por la hoja de estilos para teñir los acentos.
        self.setProperty(
            "team",
            "chaos" if self.team == "CHAOS" else "order",
        )

        self.setMinimumHeight(CARD_MIN_HEIGHT)
        self.setMaximumHeight(CARD_MAX_HEIGHT)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._loadout_signature: tuple[Any, ...] | None = None
        self._inventory_item_keys: list[tuple[Any, ...] | None] = [None] * 7
        self._icon_sizes = (44, 26, 20, 26)
        self._inventory_slot_size = 26

        self.build_ui()
        self._actualizar_tamano_iconos()

    def resizeEvent(self, event: Any) -> None:
        """Adapta los iconos cuando cambia el tamaño de la tarjeta.

        Args:
            event: Evento Qt con la geometría nueva.
        Returns:
            None.
        """
        super().resizeEvent(event)
        self._actualizar_tamano_iconos()

    def build_ui(self) -> None:
        """Construye una sola vez las secciones semánticas de la tarjeta.

        Args:
            None.
        Returns:
            None.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 10, 11, 10)
        layout.setSpacing(5)
        self.header_layout = self.create_header()
        layout.addLayout(self.header_layout, 2)
        layout.addWidget(create_divider(), 0)
        self.loadout_widget = self.create_rune_strip()
        layout.addWidget(self.loadout_widget, 1)
        self.stats_widget = self.create_stat_chips()
        layout.addWidget(self.stats_widget, 2)
        self._actualizar_estadisticas()
        layout.addWidget(create_divider(), 0)
        self.inventory_widget = self.create_inventory_block()
        layout.addWidget(self.inventory_widget, 1)

    @classmethod
    def _limpiar_layout(cls, layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
        """Elimina recursivamente widgets y diseños hijos de un layout."""
        while layout.count():
            elemento = layout.takeAt(0)
            widget = elemento.widget()
            sublayout = elemento.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif sublayout is not None:
                cls._limpiar_layout(sublayout)

    def actualizar_datos(
        self,
        player: dict,
        game_time: float,
        local_live_stats: dict | None,
    ) -> None:
        """Refresca la misma tarjeta sin reemplazar su jerarquía de widgets.

        Args:
            player: Datos LIVE actualizados del participante.
            game_time: Tiempo de partida en segundos.
            local_live_stats: Estadísticas precisas del jugador local, si existen.
        Returns:
            None.
        """
        self.setUpdatesEnabled(False)
        try:
            self.player = player
            self.game_time = game_time
            self.local_live_stats = local_live_stats
            self.team = str(player.get("team", "")).upper()
            self.role = get_player_role(player)
            self.setProperty("team", "chaos" if self.team == "CHAOS" else "order")
            self._actualizar_cabecera()
            self._actualizar_loadout()
            self._actualizar_estadisticas()
            self._actualizar_inventario()
        finally:
            self.setUpdatesEnabled(True)
        self.update()

    # ------------------------------------------------------------------
    # Cabecera: retrato, nombre, jugador, rol y chapas
    # ------------------------------------------------------------------
    def create_header(self) -> QHBoxLayout:
        """Crea una cabecera estable con nivel y KDA agrupados.

        Args:
            None.
        Returns:
            Disposici?n de identidad y estado del participante.
        """
        header = QHBoxLayout()
        header.setSpacing(7)
        champion_name = str(self.player.get("championName") or "Desconocido")
        self.champion_icon = self.create_champion_icon(champion_name)
        self.champion_icon.setFixedSize(self._icon_sizes[0], self._icon_sizes[0])
        header.addWidget(self.champion_icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.setContentsMargins(0, 0, 0, 0)
        self.champion_label = EtiquetaElidida(champion_name)
        self.champion_label.setObjectName("cardChampionName")
        names.addWidget(self.champion_label)
        self.player_label = EtiquetaElidida("")
        self.player_label.setObjectName("cardPlayerId")
        names.addWidget(self.player_label)
        role_row = QHBoxLayout()
        role_row.setContentsMargins(0, 0, 0, 0)
        role_row.setSpacing(4)
        self.role_label = QLabel()
        self.role_label.setObjectName("cardRoleChip")
        role_row.addWidget(self.role_label, 0, Qt.AlignmentFlag.AlignLeft)
        role_row.addStretch(1)
        names.addLayout(role_row)
        header.addLayout(names, 1)
        estado = QVBoxLayout()
        estado.setSpacing(2)
        self.level_label = QLabel()
        self.level_label.setObjectName("cardLevelBadge")
        self.level_label.setProperty("nivel", "live_badge")
        self.level_label.setProperty("densidad", "compacta")
        self.level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kda_label = QLabel()
        self.kda_label.setObjectName("cardKDA")
        self.kda_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        alinear_estado = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        estado.addWidget(self.level_label, 0, alinear_estado)
        estado.addWidget(self.kda_label, 0, alinear_estado)
        self.me_label = QLabel("TÚ")
        self.me_label.setObjectName("cardMeBadge")
        self.me_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        if self.is_local_player:
            estado.addWidget(self.me_label, 0, alinear_estado)
        header.addLayout(estado)
        header.setStretch(1, 1)
        self._actualizar_cabecera()
        return header

    def _actualizar_cabecera(self) -> None:
        """Refresca identidad, nivel y KDA sin sustituir sus widgets.

        Args:
            None.
        Returns:
            None.
        """
        champion_name = str(self.player.get("championName") or "Desconocido")
        riot_id = str(
            self.player.get("riotId")
            or self.player.get("summonerName")
            or "Desconocido"
        )
        self.champion_label.establecer_texto(champion_name)
        self.champion_icon.setToolTip(champion_name)
        self.player_label.establecer_texto(riot_id)
        self.role_label.setText(ROLE_LABELS.get(self.role, ""))
        level = _int_opcional(self.player.get("level"))
        if level is None and self.is_local_player and self.local_live_stats:
            level = _int_opcional(self.local_live_stats.get("level"))
        self.level_label.setText(f"NV {level}" if level is not None else "NV \u2014")
        self.level_label.setToolTip(
            f"Nivel {level}" if level is not None else "Nivel no disponible"
        )
        scores = self.player.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        values = [
            _int_opcional(scores.get(key)) for key in ("kills", "deaths", "assists")
        ]
        self.kda_label.setText(
            " / ".join(
                str(value) if value is not None else "\u2014" for value in values
            )
        )
        self.kda_label.setToolTip("Asesinatos / muertes / asistencias")

    def _actualizar_tamano_iconos(self) -> None:
        """Ajusta retratos e iconos por tramos de tamaño lógico.

        Args:
            None.
        Returns:
            None.
        """
        ancho = self.width()
        alto = self.height()
        if ancho >= 360 and alto >= 430:
            tamano = (56, 32, 24, 32)
        elif ancho >= 285 and alto >= 330:
            tamano = (50, 29, 22, 29)
        else:
            tamano = (44, 26, 20, 24)
        if tamano == self._icon_sizes:
            return
        self._icon_sizes = tamano
        densidad = "compacta"
        if ancho >= 360 and alto >= 430:
            densidad = "amplia"
        elif ancho >= 285 and alto >= 330:
            densidad = "estandar"
        if self.level_label.property("densidad") != densidad:
            self.level_label.setProperty("densidad", densidad)
            actualizar_estilo(self.level_label)
        retrato, _hechizo, _menor, inventario = tamano
        self.champion_icon.setFixedSize(retrato, retrato)
        self._actualizar_loadout()
        self._actualizar_inventario(inventario)

    def create_champion_icon(self, champion_name: str) -> IconoPixmap:
        """Crea el retrato local del campeón con tamaño compacto.

        Args:
            champion_name: Nombre de campeón informado por la partida.
        Returns:
            Etiqueta que conserva el icono y su tooltip.
        """
        icon = IconoPixmap()
        icon.setObjectName("cardChampionIcon")
        icon.setFixedSize(self._icon_sizes[0], self._icon_sizes[0])
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setToolTip(champion_name)

        pixmap = champion_pixmap(champion_name, self.version)

        if pixmap.isNull():
            icon.setText(champion_name[:2].upper())
        else:
            icon.establecer_pixmap_fuente(pixmap)

        return icon

    # ------------------------------------------------------------------
    # Runas: piedra angular y árboles con sus iconos
    # ------------------------------------------------------------------
    def create_rune_strip(self) -> QFrame:
        """Crea una fila compartida para hechizos y runas observados.

        Args:
            None.
        Returns:
            Contenedor estable del equipamiento de invocador.
        """
        strip = QFrame()
        strip.setObjectName("cardLoadout")
        strip.setMinimumHeight(38)
        strip.setMaximumHeight(48)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self._loadout_layout = layout
        self._actualizar_loadout()
        return strip

    def _obtener_datos_runas(self) -> list[tuple[str, str, str]]:
        """Extrae la piedra angular y runas generales del jugador observado.

        Args:
            None.
        Returns:
            Lista de nombre, descripci?n disponible y tipo visual de cada runa.
        """
        runes = self.player.get("runes", {})
        if not isinstance(runes, dict):
            return []
        resultado: list[tuple[str, str, str]] = []
        clave = runes.get("keystone")
        if isinstance(clave, dict):
            nombre = str(clave.get("displayName") or clave.get("name") or "").strip()
            if nombre:
                resultado.append(
                    (nombre, str(clave.get("rawDescription") or ""), "clave")
                )
        general = runes.get("generalRunes", [])
        if isinstance(general, list):
            for entrada in general:
                if not isinstance(entrada, dict):
                    continue
                nombre = str(
                    entrada.get("displayName") or entrada.get("name") or ""
                ).strip()
                if nombre and all(
                    nombre.casefold() != actual[0].casefold() for actual in resultado
                ):
                    resultado.append(
                        (nombre, str(entrada.get("rawDescription") or ""), "runa")
                    )
        if len(resultado) <= 1:
            for clave_dato, tipo in (
                ("primaryRuneTree", "\u00e1rbol principal"),
                ("secondaryRuneTree", "\u00e1rbol secundario"),
            ):
                entrada = runes.get(clave_dato, {})
                nombre = (
                    str(entrada.get("displayName") or "").strip()
                    if isinstance(entrada, dict)
                    else ""
                )
                if nombre and all(
                    nombre.casefold() != actual[0].casefold() for actual in resultado
                ):
                    resultado.append(
                        (nombre, str(entrada.get("rawDescription") or ""), tipo)
                    )
        return resultado[:6]

    def _actualizar_loadout(self) -> None:
        """Refresca iconos solo cuando cambian los hechizos o runas del jugador.

        Args:
            None.
        Returns:
            None.
        """
        spells = self.player.get("summonerSpells", {})
        spells = spells if isinstance(spells, dict) else {}
        hechizos = tuple(
            spells.get(clave) for clave in ("summonerSpellOne", "summonerSpellTwo")
        )
        resoluciones = tuple(
            resolver_icono_hechizo_invocador(hechizo, self.version, download=False)
            for hechizo in hechizos
        )
        runas = self._obtener_datos_runas()
        firma = (
            tuple(repr(hechizo) for hechizo in hechizos)
            + tuple(resolucion.estado for resolucion in resoluciones)
            + tuple((nombre, tipo) for nombre, _descripcion, tipo in runas)
            + (tuple(self._icon_sizes[:3]),)
        )
        if firma == self._loadout_signature:
            return
        self._limpiar_layout(self._loadout_layout)
        self._loadout_signature = firma
        _retrato, tamano_hechizo, tamano_runa, _inventario = self._icon_sizes
        for indice, (hechizo, resolucion) in enumerate(
            zip(hechizos, resoluciones), start=1
        ):
            icono = IconoPixmap()
            icono.setObjectName("cardSpellIcon")
            icono.setFixedSize(tamano_hechizo, tamano_hechizo)
            nombre = ""
            if isinstance(hechizo, dict):
                nombre = str(
                    hechizo.get("displayName") or hechizo.get("name") or ""
                ).strip()
            elif hechizo is not None:
                nombre = str(hechizo).strip()
            pixmap = spell_pixmap(hechizo, self.version)
            destino = icono.contentsRect().size()
            if pixmap.isNull():
                icono.setProperty("missing", True)
                icono.setText("—" if resolucion.estado == "sin_datos" else "?")
                icono.setToolTip(
                    "Hechizo no informado por Live Client Data"
                    if resolucion.estado == "sin_datos"
                    else f"{nombre or resolucion.identificador_crudo} · recurso no disponible"
                )
            else:
                icono.setProperty("missing", False)
                icono.establecer_pixmap_fuente(pixmap)
                icono.setToolTip(
                    nombre or resolucion.identificador_normalizado or "Hechizo"
                )
            existe = bool(resolucion.ruta and resolucion.ruta.exists())
            visible = icono.pixmap()
            escala = max(1.0, icono.devicePixelRatioF())
            visible_logico = (
                (round(visible.width() / escala), round(visible.height() / escala))
                if not visible.isNull()
                else None
            )
            render_ok = bool(
                visible_logico
                and visible_logico[0] <= destino.width()
                and visible_logico[1] <= destino.height()
            )
            diagnostico = resolucion.estado
            if resolucion.estado == "resuelto" and pixmap.isNull():
                diagnostico = "pixmap_invalido"
            elif resolucion.estado == "resuelto":
                diagnostico = "render_ok" if render_ok else "render_fuera_de_area"
            nivel_log = (
                logging.INFO
                if resolucion.estado == "sin_datos"
                else logging.WARNING
                if pixmap.isNull()
                else logging.DEBUG
            )
            _LOGGER.log(
                nivel_log,
                "Hechizo LIVE campeon=%s ranura=%s raw=%r normalizado=%s estado=%s diagnostico=%s ruta=%s existe=%s pixmap_nulo=%s fuente=%s destino=%s visible=%s render_ok=%s",
                self.player.get("championName", "Desconocido"),
                indice,
                hechizo,
                resolucion.identificador_normalizado,
                resolucion.estado,
                diagnostico,
                resolucion.ruta,
                existe,
                pixmap.isNull(),
                pixmap.size().toTuple() if not pixmap.isNull() else None,
                destino.toTuple(),
                visible_logico,
                render_ok,
            )
            self._loadout_layout.addWidget(
                icono, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            if indice == 2:
                self._loadout_layout.addSpacing(7)
        separador = QFrame()
        separador.setObjectName("cardLoadoutDivider")
        separador.setFixedSize(1, max(24, tamano_hechizo - 2))
        self._loadout_layout.addWidget(separador, 0, Qt.AlignmentFlag.AlignVCenter)
        self._loadout_layout.addSpacing(7)
        if runas:
            for nombre, _descripcion, tipo in runas:
                tamano = tamano_hechizo if tipo == "clave" else tamano_runa
                icono = self.create_rune_icon(
                    nombre,
                    tamano,
                    "cardRuneKeystoneIcon" if tipo == "clave" else "cardRuneIcon",
                    nombre,
                )
                self._loadout_layout.addWidget(
                    icono,
                    0,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
        else:
            sin_runas = QLabel("RUNAS \u2014")
            sin_runas.setObjectName("cardLoadoutEmpty")
            sin_runas.setToolTip("No hay datos de runas para este jugador")
            self._loadout_layout.addWidget(sin_runas)
        self._loadout_layout.addStretch(1)

    def create_rune_icon(
        self,
        rune_name: str,
        size: int,
        object_name: str,
        tooltip: str,
    ) -> IconoPixmap:
        """Crea un icono de runa con su identidad accesible por tooltip.

        Args:
            rune_name: Nombre observado de la runa.
            size: Tamaño lógico cuadrado del icono.
            object_name: Nombre Qt que identifica el tipo de runa.
            tooltip: Identidad completa mostrada al pasar el cursor.
        Returns:
            Etiqueta de icono lista para el layout de carga.
        """
        icon = IconoPixmap()
        icon.setObjectName(object_name)
        icon.setFixedSize(size, size)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if tooltip:
            icon.setToolTip(tooltip)

        pixmap = rune_pixmap(rune_name, self.version)

        if pixmap.isNull():
            icon.setText("?")
            icon.setToolTip(f"{tooltip} · icono no disponible")
        else:
            icon.establecer_pixmap_fuente(pixmap)

        return icon

    # ------------------------------------------------------------------
    # Estadísticas estimadas en fichas de color
    # ------------------------------------------------------------------
    def create_stat_chips(self) -> QFrame:
        """Crea un bloque compacto y estable para estad\u00edsticas de combate.

        Args:
            tamano: Tamaño lógico cuadrado para las ranuras, si cambia.
        Returns:
            Contenedor \u00fanico con dos filas de m\u00e9tricas seleccionadas.
        """
        frame = QFrame()
        frame.setObjectName("cardCombatStats")
        frame.setMinimumHeight(68)
        frame.setMaximumHeight(180)
        grid = QGridLayout(frame)
        grid.setContentsMargins(7, 5, 7, 5)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(4)
        self._stat_labels: list[QLabel] = []
        self._stat_grid = grid
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        for indice in range(6):
            valor = QLabel()
            valor.setObjectName("cardCombatValue")
            valor.setTextFormat(Qt.TextFormat.RichText)
            valor.setWordWrap(False)
            valor.setMinimumWidth(0)
            valor.setMinimumHeight(20)
            valor.setToolTip("Estad\u00edstica de combate")
            grid.addWidget(valor, indice // 3, indice % 3)
            grid.setColumnStretch(indice % 3, 1)
            self._stat_labels.append(valor)
        return frame

    def _actualizar_estadisticas(self) -> None:
        """Pinta las m\u00e9tricas defensivas prioritarias y el ataque relevante.

        Args:
            None.
        Returns:
            None.
        """
        stats, estimated = self.resolve_stats()
        chips = build_stat_chips(stats, estimated)
        por_tipo = {kind: (texto, tooltip) for kind, texto, tooltip in chips}
        if not por_tipo:
            por_tipo["more"] = ("DATOS —", "Estadísticas no disponibles")
            orden = ["more"]
        else:
            orden = []
        ofensivas = [kind for kind in ("ad", "ap") if kind in por_tipo]
        orden.extend(
            kind for kind in ("hp", *ofensivas, "armor", "mr") if kind in por_tipo
        )
        orden.extend(kind for kind in por_tipo if kind not in orden)
        for indice, etiqueta in enumerate(self._stat_labels):
            if indice >= len(orden):
                etiqueta.clear()
                etiqueta.setToolTip("Estad\u00edstica no disponible")
                continue
            kind = orden[indice]
            texto, tooltip = por_tipo[kind]
            if kind == "more":
                etiqueta.setText(
                    f"<span style='color:{PALETA['secundario']}'>{texto}</span>"
                )
            else:
                valor = texto.replace("\u2248", "")
                prefijo = "\u2248" if texto.startswith("\u2248") else ""
                etiqueta.setText(
                    f"<span style='color:{PALETA['secundario']}'>{CHIP_TAGS[kind]} </span>"
                    f"<span style='color:{PALETA['texto']};font-weight:700'>{prefijo}{valor}</span>"
                )
            etiqueta.setToolTip(tooltip)
        self.stats_widget.setToolTip(
            "Estad\u00edsticas estimadas con nivel y objetos"
            if estimated
            else "Estad\u00edsticas observadas en vivo por el cliente"
        )

    def resolve_stats(self) -> tuple[dict, bool]:
        """Devuelve estad\u00edsticas del jugador y si son estimadas o medidas.

        Args:
            None.
        Returns:
            Estad\u00edsticas normalizadas y un indicador de estimaci?n.
        """
        if self.is_local_player and self.local_live_stats is not None:
            stats = normalize_live_stats(self.local_live_stats)
            item_stats = calculate_item_stats(self.player, self.item_catalog)
            stats["grievous_wounds"] = item_stats.get("grievous_wounds", False)
            return stats, False
        champion_data = get_champion_data(
            str(self.player.get("championName", "")), self.version
        )
        return calculate_estimated_enemy_stats(
            self.player, champion_data, self.item_catalog
        ), True

    def create_inventory_block(self) -> QWidget:
        """Crea siete huecos compactos con sus etiquetas de estado.

        Args:
            None.
        Returns:
            Bloque estable de inventario, seis objetos y un talism\u00e1n.
        """
        block = QWidget()
        block.setObjectName("cardInventory")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        header = QHBoxLayout()
        header.setSpacing(4)
        title = QLabel("INVENTARIO")
        title.setObjectName("cardInventoryTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.inventory_count_label = QLabel()
        self.inventory_count_label.setObjectName("cardInventoryCount")
        header.addWidget(self.inventory_count_label)
        layout.addLayout(header)
        self.inventory_slots_layout = QHBoxLayout()
        self.inventory_slots_layout.setContentsMargins(0, 0, 0, 0)
        self.inventory_slots_layout.setSpacing(INVENTORY_SLOT_SPACING)
        self._inventory_slot_size = self._icon_sizes[3]
        self.inventory_slot_labels = []
        for slot in range(7):
            etiqueta = create_item_icon(
                None,
                self.item_catalog,
                self.version,
                size=self._inventory_slot_size,
                object_name="itemSlot" if slot < 6 else "trinketSlot",
            )
            self.inventory_slots_layout.addWidget(etiqueta)
            self.inventory_slot_labels.append(etiqueta)
        self.inventory_slots_layout.addStretch(1)
        layout.addLayout(self.inventory_slots_layout)
        self._actualizar_inventario()
        return block

    def _actualizar_inventario(self, tamano: int | None = None) -> None:
        """Actualiza los huecos LIVE y su tamaño lógico solicitado.

        Args:
            tamano: Tamaño cuadrado de los huecos, si se ha actualizado.
        Returns:
            None.
        """
        tamano = tamano or self._icon_sizes[3]
        self._inventory_slot_size = tamano
        elementos = self.player.get("items")
        disponible = isinstance(elementos, list)
        items: dict[int, dict] = {}
        if disponible:
            for item in elementos:
                if not isinstance(item, dict):
                    continue
                try:
                    ranura = int(item.get("slot", -1))
                except (TypeError, ValueError):
                    continue
                items[ranura] = item
        for slot, etiqueta in enumerate(self.inventory_slot_labels):
            item = items.get(slot)
            item_id = item.get("itemID") if isinstance(item, dict) else None
            if isinstance(item, dict):
                try:
                    cantidad = int(item.get("count", 1) or 1)
                except (TypeError, ValueError):
                    cantidad = 1
            else:
                cantidad = 0
            clave = (
                tamano,
                str(item_id or ""),
                str(item.get("displayName") or "") if isinstance(item, dict) else "",
                cantidad,
            )
            if clave == self._inventory_item_keys[slot]:
                continue
            self._inventory_item_keys[slot] = clave
            temporal = create_item_icon(
                item,
                self.item_catalog,
                self.version,
                size=tamano,
                object_name="itemSlot" if slot < 6 else "trinketSlot",
            )
            etiqueta.setObjectName(temporal.objectName())
            etiqueta.setFixedSize(tamano, tamano)
            etiqueta.establecer_pixmap_fuente(
                temporal.obtener_pixmap_fuente()
                if isinstance(temporal, IconoPixmap)
                else temporal.pixmap()
            )
            etiqueta.setText(temporal.text())
            etiqueta.setToolTip(temporal.toolTip())
            temporal.deleteLater()
        count = self.count_equipped_items()
        self.inventory_count_label.setText(
            ("1 objeto" if count == 1 else f"{count} objetos")
            if disponible
            else "Sin datos"
        )
        self.inventory_count_label.setToolTip(
            "Inventario informado por Live Client Data"
            if disponible
            else "El cliente no inform\u00f3 el inventario de este jugador"
        )

    def count_equipped_items(self) -> int:
        """Objetos equipados (sin trinket ni huecos vacíos)."""
        count = 0

        elementos = self.player.get("items", [])
        if not isinstance(elementos, list):
            return count

        for item in elementos:
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

        border_color = LOCAL_ACCENT if self.is_local_player else accent
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(border_color, 190), 1))
        painter.drawRoundedRect(area, 12, 12)

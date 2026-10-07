from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from app.services.live_player_metrics_service import player_role
from app.ui.icono_pixmap import IconoPixmap
from data_dragon import get_item_icon_path

BOOT_IDS = {
    1001,
    3005,
    3006,
    3020,
    3047,
    3111,
    3158,
    3172,
    3175,
}

LAST_KNOWN_BOOTS: dict[str, dict] = {}

# Ayuda de los huecos de misión cuando todavía no hay objeto que mostrar.
QUEST_EMPTY_TOOLTIPS = {
    "bootsQuestSlot": "Botas no publicadas por Live Client Data",
    "pinkWardQuestSlot": "Role Quest: Control Wards",
}


class RejillaInventario(QWidget):
    """Distribuye los huecos del inventario en filas según el ancho disponible."""

    def __init__(
        self,
        iconos: list[QLabel],
        tamano: int,
        separacion: int,
        parent: QWidget | None = None,
    ) -> None:
        """Crea la rejilla con iconos de tamaño uniforme y espaciado fijo."""
        super().__init__(parent)
        self._iconos = iconos
        self._tamano = tamano
        self._separacion = separacion
        self._columnas = 0
        self.setObjectName("inventoryContainer")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._rejilla = QGridLayout(self)
        self._rejilla.setContentsMargins(0, 0, 0, 0)
        self._rejilla.setHorizontalSpacing(separacion)
        self._rejilla.setVerticalSpacing(separacion)
        self._redistribuir(max(1, len(iconos)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recoloca los iconos en filas cuando cambia el ancho de la tarjeta."""
        super().resizeEvent(event)
        columnas = max(
            1,
            min(
                len(self._iconos),
                (self.width() + self._separacion) // (self._tamano + self._separacion),
            ),
        )
        self._redistribuir(columnas)

    def _redistribuir(self, columnas: int) -> None:
        """Coloca cada icono en una celda sin cambiar su orden ni tamaño."""
        if columnas == self._columnas and self._rejilla.count() == len(self._iconos):
            return
        while self._rejilla.count():
            self._rejilla.takeAt(0)
        self._columnas = columnas
        for indice, icono in enumerate(self._iconos):
            fila, columna = divmod(indice, columnas)
            self._rejilla.addWidget(icono, fila, columna)
        filas = (len(self._iconos) + columnas - 1) // columnas
        alto = filas * self._tamano + max(0, filas - 1) * self._separacion
        self.setMinimumHeight(alto)
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        """Devuelve el alto de filas actual sin fijar un ancho mínimo."""
        columnas = max(1, self._columnas)
        filas = (len(self._iconos) + columnas - 1) // columnas
        alto = filas * self._tamano + max(0, filas - 1) * self._separacion
        return QSize(0, alto)

    def minimumSizeHint(self) -> QSize:
        """Permite envolver iconos sin forzar el ancho de una fila completa."""
        return QSize(0, self._tamano)


def get_player_role(player: dict) -> str:
    """Rol del jugador (misma lógica que el servicio de métricas en vivo)."""
    return player_role(player)


def is_boots(item: dict | None) -> bool:
    if not item:
        return False

    try:
        item_id = int(item.get("itemID", 0))
    except (TypeError, ValueError):
        item_id = 0

    if item_id in BOOT_IDS:
        return True

    name = str(item.get("displayName", "")).lower()

    return any(
        word in name
        for word in (
            "boots",
            "greaves",
            "shoes",
            "treads",
            "zephyr",
            "spellslinger",
        )
    )


def find_boots(
    player: dict,
) -> tuple[int | None, dict | None]:
    player_id = (
        player.get("riotId")
        or player.get("summonerName")
        or player.get("championName")
        or "unknown"
    )

    for item in player.get("items", []):
        if not isinstance(item, dict):
            continue

        if not is_boots(item):
            continue

        try:
            slot = int(item.get("slot", -1))
        except (TypeError, ValueError):
            slot = -1

        LAST_KNOWN_BOOTS[player_id] = item
        return slot, item

    return None, LAST_KNOWN_BOOTS.get(player_id)


def create_item_icon(
    item: dict | None,
    item_catalog: dict,
    version: str,
    size: int = 30,
    object_name: str = "itemSlot",
) -> QLabel:
    """Crea un icono de objeto o un hueco vacío con dimensiones uniformes.

    Args:
        item: Objeto LIVE o None si la ranura está vacía.
        item_catalog: Catálogo local de objetos.
        version: Versión de Data Dragon para resolver el recurso.
        size: Tamaño lógico cuadrado del icono.
        object_name: Nombre Qt para distinguir ranuras y trinket.
    Returns:
        Etiqueta lista para añadirse a un layout.
    """
    icon = IconoPixmap()
    icon.setObjectName(object_name)
    icon.setFixedSize(size, size)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

    if item is None:
        icon.setObjectName("emptyItemSlot")
        icon.setToolTip("Hueco vacío")
        return icon

    item_id = item.get("itemID")

    if not item_id:
        icon.setObjectName("emptyItemSlot")
        icon.setToolTip("Hueco vacío")
        return icon

    icon_path = get_item_icon_path(
        item_id,
        item_catalog,
        version,
    )

    if icon_path is not None and icon_path.exists():
        pixmap = QPixmap(str(icon_path))

        if not pixmap.isNull():
            icon.establecer_pixmap_fuente(pixmap)

    name = item.get(
        "displayName",
        f"Objeto {item_id}",
    )
    count = item.get("count", 1)

    icon.setToolTip(f"{name} ×{count}" if count > 1 else name)

    return icon


def create_item_slots(
    player: dict,
    item_catalog: dict,
    version: str,
    size: int = 30,
    spacing: int = 6,
) -> QWidget:
    """Crea los huecos de inventario y los adapta al ancho disponible."""
    elementos = player.get("items", [])
    if not isinstance(elementos, list):
        elementos = []

    items = {
        int(item.get("slot", -1)): item for item in elementos if isinstance(item, dict)
    }

    role = get_player_role(player)
    boots_slot = None
    boots_item = None

    if role == "BOTTOM":
        boots_slot, boots_item = find_boots(player)

    slots: list[tuple[str, dict | None]] = []

    for slot in range(6):
        item = items.get(slot)

        # Las botas del tirador se muestran en su hueco de misión.
        if role == "BOTTOM" and slot == boots_slot:
            item = None

        slots.append(("itemSlot", item))

    slots.append(("trinketSlot", items.get(6)))

    if role == "BOTTOM":
        slots.append(("bootsQuestSlot", boots_item))
    elif role == "UTILITY":
        slots.append(("pinkWardQuestSlot", items.get(7) or items.get(8)))

    iconos: list[QLabel] = []
    for object_name, item in slots:
        icon = create_item_icon(
            item=item,
            item_catalog=item_catalog,
            version=version,
            size=size,
            object_name=object_name,
        )

        quest_tip = QUEST_EMPTY_TOOLTIPS.get(object_name)

        if quest_tip is not None:
            icon.setToolTip(item.get("displayName") if item else quest_tip)

        iconos.append(icon)

    return RejillaInventario(iconos, size, spacing)

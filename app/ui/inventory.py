from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from data_dragon import get_item_icon_path

from app.services.live_player_metrics_service import player_role


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

    name = str(
        item.get("displayName", "")
    ).lower()

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
    icon = QLabel()
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
            icon.setPixmap(
                pixmap.scaled(
                    size - 2,
                    size - 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    name = item.get(
        "displayName",
        f"Objeto {item_id}",
    )
    count = item.get("count", 1)

    icon.setToolTip(
        f"{name} ×{count}"
        if count > 1
        else name
    )

    return icon


def create_item_slots(
    player: dict,
    item_catalog: dict,
    version: str,
    size: int = 30,
    spacing: int = 6,
) -> QWidget:
    """Fila única de inventario: 6 objetos, trinket y hueco de misión.

    Todos los huecos van en la misma fila, repartidos a lo ancho de la
    tarjeta. La rejilla de dos filas anterior reservaba la última columna
    para el trinket y empujaba el sexto objeto a una segunda fila, que
    quedaba descolgado abajo a la izquierda.
    """
    container = QWidget()
    container.setObjectName("inventoryContainer")
    container.setFixedHeight(size)

    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(spacing)
    layout.setVerticalSpacing(0)

    items = {
        int(item.get("slot", -1)): item
        for item in player.get("items", [])
        if isinstance(item, dict)
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

    for column, (object_name, item) in enumerate(slots):
        icon = create_item_icon(
            item=item,
            item_catalog=item_catalog,
            version=version,
            size=size,
            object_name=object_name,
        )

        quest_tip = QUEST_EMPTY_TOOLTIPS.get(object_name)

        if quest_tip is not None:
            icon.setToolTip(
                item.get("displayName") if item else quest_tip
            )

        layout.addWidget(icon, 0, column)
        layout.setColumnStretch(column, 1)

    return container

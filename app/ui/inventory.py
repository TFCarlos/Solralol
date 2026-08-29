from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

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


def get_player_role(player: dict) -> str:
    position = str(
        player.get("position", "")
    ).upper()

    aliases = {
        "ADC": "BOTTOM",
        "APC": "BOTTOM",
        "MID": "MIDDLE",
        "SUP": "UTILITY",
        "SUPPORT": "UTILITY",
        "JUNG": "JUNGLE",
    }

    position = aliases.get(position, position)

    if position in {
        "TOP",
        "JUNGLE",
        "MIDDLE",
        "BOTTOM",
        "UTILITY",
    }:
        return position

    spells = player.get(
        "summonerSpells",
        {},
    )

    spell_names = (
        str(
            spells.get(
                "summonerSpellOne",
                {},
            ).get("displayName", "")
        ).lower(),
        str(
            spells.get(
                "summonerSpellTwo",
                {},
            ).get("displayName", "")
        ).lower(),
    )

    if any("smite" in name for name in spell_names):
        return "JUNGLE"

    return "UNKNOWN"


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
) -> QWidget:
    container = QWidget()
    container.setObjectName("inventoryContainer")
    container.setFixedHeight(size * 2 + 8)

    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(4)
    layout.setVerticalSpacing(4)

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

    for slot in range(6):
        item = items.get(slot)

        if role == "BOTTOM" and slot == boots_slot:
            item = None

        icon = create_item_icon(
            item=item,
            item_catalog=item_catalog,
            version=version,
            size=size,
            object_name="itemSlot",
        )

        layout.addWidget(
            icon,
            slot // 3,
            slot % 3,
        )

    trinket_icon = create_item_icon(
        item=items.get(6),
        item_catalog=item_catalog,
        version=version,
        size=size,
        object_name="trinketSlot",
    )
    layout.addWidget(trinket_icon, 0, 3)

    if role == "BOTTOM":
        boots_icon = create_item_icon(
            item=boots_item,
            item_catalog=item_catalog,
            version=version,
            size=size,
            object_name="bootsQuestSlot",
        )
        boots_icon.setToolTip(
            boots_item.get("displayName")
            if boots_item
            else "Botas no publicadas por Live Client Data"
        )
        layout.addWidget(boots_icon, 1, 3)

    elif role == "UTILITY":
        ward_item = items.get(7) or items.get(8)
        ward_icon = create_item_icon(
            item=ward_item,
            item_catalog=item_catalog,
            version=version,
            size=size,
            object_name="pinkWardQuestSlot",
        )
        ward_icon.setToolTip(
            ward_item.get("displayName")
            if ward_item
            else "Role Quest: Control Wards"
        )
        layout.addWidget(ward_icon, 1, 3)

    return container

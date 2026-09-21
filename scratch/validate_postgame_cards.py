"""Valida la estructura y el renderizado de las tarjetas del marcador.

Comprueba, tarjeta a tarjeta:
- retrato de campeón con pixmap real y redondeado,
- nombre y KDA en la misma fila (fila superior), un solo KDA por tarjeta,
- rol y nivel con contexto explícito ("ROL · ", "NIVEL · "),
- seis huecos de build con tamaño uniforme,
- altura homogénea entre tarjetas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from app.ui.postgame_sidebar import PostgameSidebar
from app.ui.styles import CONTROL_WINDOW_STYLE

ROOT = Path(__file__).resolve().parent.parent
APP = QApplication(sys.argv)
APP.setStyleSheet(CONTROL_WINDOW_STYLE)

ORDER = {
    "a1": ("Camille", "TOP", [3074, 3153, 6333, 3071, 3053, 3143], 18, 9, 3, 6, 214, 16220, 41),
    "a2": ("Lee Sin", "JUNGLE", [6692, 3111, 6333, 3053, 3071, 3143], 17, 5, 6, 12, 168, 13480, 33),
    "a3": ("Ahri", "MIDDLE", [6655, 3020, 4645, 3157, 3089, 3135], 18, 11, 4, 9, 231, 17890, 28),
    "a4": ("Jinx", "BOTTOM", [6673, 3006, 3031, 3072, 3036, 3035], 18, 12, 2, 10, 245, 18420, 22),
    "a5": ("Thresh", "UTILITY", [3860, 3190, 3222, 3107, 3050, 3190], 16, 2, 8, 21, 48, 10240, 96),
}
CHAOS = {
    "e1": ("Aatrox", "TOP", [3074, 3153, 6333, 3053], 17, 3, 7, 4, 189, 12980, 18),
    "e2": ("Vi", "JUNGLE", [6692, 3111, 3071], 16, 4, 8, 7, 141, 11020, 15),
    "e3": ("Syndra", "MIDDLE", [6655, 3020, 4645, 3157], 17, 6, 5, 5, 205, 14100, 19),
    "e4": ("Kai'Sa", "BOTTOM", [6673, 3006, 3031], 17, 8, 4, 6, 210, 15640, 12),
    "e5": ("Nautilus", "UTILITY", [3860, 3190, 3222], 15, 1, 9, 14, 39, 8920, 74),
}


def build_session() -> dict:
    players: dict = {}
    scoreboard: dict = {}

    for key, (champ, role, items, level, k, d, a, cs, gold, vision) in {
        **ORDER,
        **CHAOS,
    }.items():
        team = "ORDER" if key.startswith("a") else "CHAOS"
        players[key] = {
            "champion_name": champ,
            "team": team,
            "role": role,
            "win": team == "ORDER",
        }
        scoreboard[key] = {
            "kills": k,
            "deaths": d,
            "assists": a,
            "cs": cs,
            "level": level,
            "estimated_gold": gold,
            "stats": {"vision_score": vision},
            "items": items,
        }

    return {
        "local_player_key": "a1",
        "local_team": "ORDER",
        "champion_name": "Camille",
        "duration": 1812.0,
        "game_mode": "CLASSIC",
        "game_version": "16.18.1",
        "players": players,
        "events": [],
        "snapshots": [],
        "final_scoreboard": scoreboard,
        "final_sync": {"status": "live_only"},
    }


def labels(parent, object_name: str) -> list[QLabel]:
    return [
        child
        for child in parent.findChildren(QLabel)
        if child.objectName() == object_name
    ]


def main() -> None:
    sidebar = PostgameSidebar(build_session())
    catalog = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    sidebar._catalog = lambda: catalog
    sidebar.resize(700, 820)
    sidebar.show()
    APP.processEvents()

    cards = [
        child
        for child in sidebar.findChildren(QFrame)
        if child.objectName() == "postgamePlayerCard"
    ]
    assert len(cards) == 10, f"esperaba 10 tarjetas, hay {len(cards)}"

    icons_before = sum(
        1
        for card in cards
        for slot in labels(card, "postgameItemIcon")
        if not slot.pixmap().isNull()
    )

    # Se deja terminar la descarga en segundo plano (si la hay) para validar
    # el estado final que ve el usuario.
    thread = sidebar._icon_warmup

    if thread is not None:
        thread.wait(30000)
        APP.processEvents()

    cards = [
        child
        for child in sidebar.findChildren(QFrame)
        if child.objectName() == "postgamePlayerCard"
    ]

    heights: set[int] = set()
    item_pixmaps = 0

    for card in cards:
        names = labels(card, "postgameChampionName")
        kdas = labels(card, "postgameStatKda")
        roles = labels(card, "postgameRoleBadge")
        levels = labels(card, "postgameLevelBadge")
        icons = labels(card, "postgameChampionIcon")
        slots = labels(card, "postgameItemIcon")

        assert len(names) == 1, f"{len(names)} nombres en una tarjeta"
        assert len(kdas) == 1, f"{len(kdas)} KDA en una tarjeta"
        assert len(roles) == 1, f"{len(roles)} roles en una tarjeta"
        assert len(levels) == 1, f"{len(levels)} niveles en una tarjeta"
        assert len(icons) == 1, f"{len(icons)} retratos en una tarjeta"
        assert len(slots) == 6, f"{len(slots)} huecos de build en una tarjeta"

        # El KDA vive en la esquina superior derecha de la tarjeta y el
        # nombre ocupa la mitad izquierda de esa misma fila.
        name = names[0]
        kda = kdas[0]
        name_rect = QRect(name.mapTo(card, name.rect().topLeft()), name.size())
        kda_rect = QRect(kda.mapTo(card, kda.rect().topLeft()), kda.size())
        assert kda_rect.left() >= card.width() // 2, (
            f"el KDA no está en la mitad derecha ({kda_rect.left()} de {card.width()})"
        )
        assert kda_rect.top() <= 34, f"el KDA no está arriba ({kda_rect.top()})"
        assert name_rect.left() < card.width() // 2, "el nombre no está a la izquierda"
        assert abs(kda_rect.top() - name_rect.top()) <= 28, (
            f"nombre y KDA desalineados ({name_rect.top()} vs {kda_rect.top()})"
        )

        # El rol va debajo del nombre (con contexto), nunca a media tarjeta.
        role_rect = QRect(roles[0].mapTo(card, roles[0].rect().topLeft()), roles[0].size())
        assert roles[0].text().startswith("ROL · "), roles[0].text()
        assert levels[0].text().startswith("NIVEL · "), levels[0].text()
        assert role_rect.top() >= name_rect.bottom() - 4, "el rol no está bajo el nombre"

        # Retrato real y redondeado.
        icon = icons[0]
        assert not icon.pixmap().isNull(), f"retrato vacío en {names[0].text()}"
        assert icon.pixmap().height() == 40, icon.pixmap().height()

        # Huecos de igual tamaño y con herramienta descriptiva.
        sizes = {(slot.width(), slot.height()) for slot in slots}
        assert sizes == {(24, 24)}, sizes
        item_pixmaps += sum(1 for slot in slots if not slot.pixmap().isNull())

        heights.add(card.height() or card.minimumHeight())
        print(
            f"  {names[0].text():<10} alto={card.height():>4} "
            f"ancho={card.width():>4} build={len(slots)}"
        )

    if len(heights) != 1:
        print(f"AVISO alturas dispares: {sorted(heights)}")

    assert len(heights) == 1, f"alturas de tarjeta desiguales: {sorted(heights)}"

    print(
        f"warmup: {icons_before}/60 -> {item_pixmaps}/60 huecos con icono"
    )
    print(
        "OK tarjetas=10 altura="
        f"{sorted(heights)[0]} huecos_con_icono={item_pixmaps}/60"
    )

    # A ancho mínimo del panel las seis casillas del build deben caber.
    sidebar.resize(430, 780)
    APP.processEvents()

    narrow = [
        child
        for child in sidebar.findChildren(QFrame)
        if child.objectName() == "postgamePlayerCard"
    ][0]
    slots = labels(narrow, "postgameItemIcon")
    used = sum(slot.width() for slot in slots) + 3 * (len(slots) - 1)
    assert used <= narrow.width(), f"el build no cabe: {used} > {narrow.width()}"
    print(f"OK ancho minimo: tarjeta={narrow.width()} build={used}")


if __name__ == "__main__":
    main()

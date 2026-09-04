from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.services.synergy_recommendation_service import SynergyRecommendationService


class _ClickableFrame(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.installEventFilter(self)

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            self.clicked.emit()
            return True
        return super().eventFilter(watched, event)

    def childEvent(self, event: QEvent) -> None:
        super().childEvent(event)
        child = event.child()
        if isinstance(child, QWidget):
            child.installEventFilter(self)


class RecommendationPanel(QFrame):
    """Vista LIVE de estilos, builds y contramedidas para el campeón local."""

    THREATS = {
        "curacion": (("curación", "curacion", "healing", "life steal", "robo de vida"), "Curación"),
        "armadura": (("armadura", "armor"), "Armadura"),
        "resistencia_magica": (("resistencia mágica", "resistencia magica", "magic resist"), "Resistencia mágica"),
        "critico": (("crítico", "critico", "critical"), "Crítico"),
        "vida": (("vida", "health", "vitalidad"), "Vida"),
    }
    COUNTERS = {
        "curacion": ("grievous wounds", "heridas graves", "anti-curación", "antiheal"),
        "armadura": ("armor penetration", "penetración de armadura", "penetracion de armadura", "letalidad", "lethality"),
        "resistencia_magica": ("magic penetration", "penetración mágica", "penetracion magica", "magic pen"),
        "critico": ("armor", "armadura"),
        "vida": ("% current health", "% de la vida", "max health"),
    }
    PRIMARY_STYLES = {
        "Akali": "assassin_ap", "Alistar": "tank", "Amumu": "tank", "Anivia": "control_ap",
        "Annie": "burst_ap", "Aphelios": "crit_ad", "Blitzcrank": "tank", "Briar": "bruiser_ad",
        "Darius": "bruiser_ad", "Diana": "assassin_ap", "DrMundo": "tank", "Ekko": "assassin_ap",
        "Ezreal": "poke_ad", "Gnar": "bruiser_ad", "Hwei": "control_ap", "Irelia": "on_hit",
        "Lissandra": "control_ap", "Lucian": "crit_ad", "Lulu": "utility", "Lux": "burst_ap",
        "Malphite": "tank", "Malzahar": "control_ap", "Maokai": "tank", "Milio": "utility",
        "Mordekaiser": "bruiser_ap", "Morgana": "control_ap", "Nasus": "split_push", "Pantheon": "bruiser_ad",
        "Poppy": "tank", "Qiyana": "assassin_lethality", "Rammus": "tank", "Rengar": "assassin_lethality",
        "Rumble": "bruiser_ap", "Seraphine": "utility", "Swain": "bruiser_ap", "Sylas": "bruiser_ap",
        "Syndra": "burst_ap", "Taric": "utility", "Teemo": "poke_ap", "Thresh": "utility",
        "TwistedFate": "poke_ap", "Twitch": "crit_ad", "Urgot": "bruiser_ad", "Varus": "poke_ad",
        "Volibear": "bruiser_ad", "Warwick": "bruiser_ad", "Xayah": "crit_ad", "Xerath": "poke_ap",
        "Yasuo": "crit_ad", "Yunara": "crit_ad", "Zoe": "burst_ap",
    }
    ARCHETYPE_ORDER = [
        "bruiser_ad", "tank", "on_hit", "crit_ad", "assassin_lethality",
        "bruiser_ap", "assassin_ap", "control_ap", "burst_ap", "poke_ad",
        "poke_ap", "split_push", "utility",
    ]
    ITEM_REASONS = {
        "3009": "Aporta velocidad de movimiento y velocidad de ataque para alcanzar objetivos y mantener el DPS de tu campeón.",
        "3047": "Reduce el daño de ataques básicos; es la bota defensiva correcta contra una composición con mucho daño AD.",
        "3111": "Aporta resistencia mágica y tenacidad; es especialmente buena contra Lux porque reduce el impacto de su daño mágico y de su control de masas.",
        "3020": "Aporta penetración mágica para que las habilidades AP atraviesen las resistencias enemigas.",
        "3078": "Combina daño, vida y velocidad de movimiento; potencia los intercambios prolongados y permite mantenerse pegado al objetivo.",
        "3033": "Reduce la curación recibida por los enemigos y aporta penetración de armadura; es la respuesta directa a composiciones con mucho healing.",
        "3071": "Aplica reducción de armadura y aumenta el daño físico sostenido contra frontlines resistentes.",
        "3036": "Aporta penetración de armadura para que el daño AD siga siendo relevante contra campeones con mucha armadura.",
        "6692": "Aporta letalidad y daño explosivo para eliminar objetivos frágiles antes de que puedan responder.",
        "3065": "Aporta resistencia mágica y vida para sobrevivir contra daño mágico prolongado.",
        "3047": "Reduce el daño de ataques básicos, por eso es una respuesta eficiente contra carries AD.",
        "3111": "Aporta resistencia mágica y tenacidad para aguantar burst y control mágico.",
        "3157": "Permite esquivar temporalmente el daño de una entrada enemiga y esperar la siguiente ventana.",
        "3089": "Multiplica el poder de habilidad y convierte las ventanas de burst en eliminaciones más fiables.",
        "3116": "Aporta vida y ralentización para mantener el objetivo dentro del rango de daño y ganar peleas largas.",
        "3748": "Aporta vida y daño en área para limpiar oleadas y resistir en peleas prolongadas o split push.",
        "3053": "Aporta vida y daño, y su escudo permite sobrevivir al siguiente intercambio antes de continuar atacando.",
        "3153": "Aporta daño contra vida y robo de vida; mejora los duelos largos contra campeones resistentes.",
        "3091": "Aporta velocidad de ataque y resistencia mágica, equilibrando DPS y supervivencia contra daño AP.",
        "3142": "Aporta letalidad y movilidad para llegar a objetivos frágiles antes de que puedan reaccionar.",
        "6694": "Aporta penetración de armadura para que el burst AD no se quede corto contra objetivos con defensa física.",
        "3107": "Protege a un aliado con curación y estadísticas de utilidad; se compra cuando la victoria depende de mantener vivo al carry.",
        "3190": "Convierte oro en un escudo de área para negar burst durante el engage enemigo.",
    }
    CHOICE_REASONS = {
        ("Briar", "bruiser_ad", "3078"): "Se elige antes que una defensa pura porque Briar necesita llegar al objetivo y mantener el daño durante su primera pelea; da daño, vida y movilidad en una sola compra.",
        ("Briar", "bruiser_ad", "3071"): "Se elige después de Fuerza de Trinidad porque Briar ya tiene daño y movilidad: ahora necesita reducir armadura y ganar vida para seguir pegada a bruisers y tanques.",
        ("Briar", "bruiser_ad", "3053"): "Se elige como tercera compra porque el escudo cubre la ventana en la que Briar entra en frenesí y convierte su daño en una pelea que puede sobrevivir.",
        ("Briar", "tank", "3068"): "Se elige porque este arquetipo cambia el plan de Briar: prioriza aguantar dentro del equipo enemigo y el daño de área de esta pasiva, no el burst de una build AD pura.",
        ("Briar", "tank", "3111"): "Se elige frente a Botas blindadas cuando el problema principal es Lux, no los ataques básicos: la tenacidad reduce su control y la resistencia mágica reduce su burst.",
    }
    CROWD_CONTROL_ENEMIES = {"Lux", "Morgana", "Lissandra", "Leona", "Nautilus", "Thresh", "Milio", "Seraphine", "Amumu", "Morgana"}
    EXCLUSIVE_ITEMS = {
        "3036": {"3071"},
        "3071": {"3036"},
    }
    EXCLUSIVE_GROUP_LABELS = {
        "boots": "botas",
        "lifeline": "objetos de salvavidas",
        "hydra": "objetos Hydra",
        "tear": "objetos de Lágrima",
        "spellblade": "objetos de Hoja encantada",
        "last_whisper": "objetos de penetración de armadura",
    }
    EXCLUSIVE_NAME_GROUPS = {
        "spellblade": ("fuerza de trinidad", "guantelete de hielo", "sable de hechicero", "lich bane"),
        "last_whisper": ("lord dominik", "recuerdos de lord dominik", "mortal reminder", "recordatorio letal", "cuchilla negra"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.assets = None
        self.item_catalog: dict[str, Any] = {}
        self.profiles: dict[str, Any] = self._load_profiles()
        self.active_champion = ""
        self.active_style = ""
        self._last_session: dict[str, Any] = {}
        self.route_view = False
        self.current_threats: list[tuple[str, str]] = []
        self.synergy = SynergyRecommendationService()
        self.setObjectName("recommendationPanel")
        self._build_ui()

    def configure(self, assets: Any, item_catalog: dict[str, Any]) -> None:
        self.assets = assets
        self.item_catalog = item_catalog or {}

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName("recommendationHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        self.title = QLabel("RECOMENDACIONES LIVE")
        self.title.setObjectName("recommendationTitle")
        header_layout.addWidget(self.title)
        self.style_label = QLabel("Analizando campeón y enfrentamiento…")
        self.style_label.setObjectName("recommendationStyle")
        header_layout.addWidget(self.style_label)
        self.gold_label = QLabel("Oro disponible: detectando…")
        self.gold_label.setObjectName("recommendationGold")
        header_layout.addWidget(self.gold_label)
        self.summary = QLabel()
        self.summary.setObjectName("recommendationNote")
        self.summary.setWordWrap(True)
        header_layout.addWidget(self.summary)
        layout.addWidget(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def update_recommendations(self, session: dict[str, Any]) -> None:
        self._clear()
        self._last_session = session
        champion = self._local_champion(session)
        profile = self._profile_for(champion)
        styles = profile.get("styles", [])
        enemy_items = self._enemy_items(session)
        threats = self._detect_threats(enemy_items)
        self.current_threats = threats
        default_style = self._adaptive_style(profile, threats)
        if champion != self.active_champion or self.active_style not in styles:
            self.active_champion = champion
            self.active_style = str(profile.get("recommendation") or default_style or (styles[0] if styles else ""))
        self.title.setText(f"RECOMENDACIONES LIVE · {champion.upper()}")
        self.style_label.setText(f"Recomendado: {self._style_label(default_style)}  ·  Activo: {self._style_label(self.active_style)}")
        available_gold = self._available_gold(self._local_state())
        self.gold_label.setText(f"Oro disponible: {available_gold:,}" if available_gold is not None else "Oro disponible: no detectado")
        if self.route_view:
            build = self.profiles.get("archetypes", {}).get(self.active_style, {})
            self._render_route_detail(self.active_style, build, threats)
            return
        self.summary.setText(self._summary(profile, threats, enemy_items))
        if not enemy_items:
            self._message("Esperando inventarios enemigos publicados por League…")
        ordered_styles = [self.active_style] + [style_key for style_key in styles if style_key != self.active_style]
        for style_key in ordered_styles:
            build = self.profiles.get("archetypes", {}).get(style_key, {})
            self.content_layout.addWidget(self._build_card(style_key, build, threats))
        self.content_layout.addWidget(self._situational_card(threats))
        self.content_layout.addStretch(1)

    def _build_card(self, style_key: str, build: dict[str, Any], threats: list[tuple[str, str]]) -> QWidget:
        card = _ClickableFrame()
        card.setObjectName("recommendationBuildCard")
        card.clicked.connect(lambda: self._show_route_detail(style_key, build, threats))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = QHBoxLayout()
        label = QLabel(build.get("label", "Build adaptable"))
        label.setObjectName("recommendationBuildTitle")
        heading.addWidget(label)
        heading.addStretch(1)
        badge = QLabel("RUTA")
        badge.setObjectName("recommendationBadge")
        heading.addWidget(badge)
        layout.addLayout(heading)
        items = build.get("core", [])
        item_names = [self._catalog().get(str(item_id), {}).get("name", str(item_id)) for item_id in items]
        core = QLabel("  →  ".join(item_names))
        core.setObjectName("recommendationItems")
        core.setWordWrap(True)
        layout.addWidget(core)
        situational = [self._catalog().get(str(item_id), {}).get("name", str(item_id)) for item_id in build.get("situational", [])]
        reason = QLabel(f"{self._build_reason(build, threats)} Situacionales: {', '.join(situational)}.")
        reason.setObjectName("recommendationReason")
        reason.setWordWrap(True)
        layout.addWidget(reason)
        return card

    def _show_route_detail(self, style_key: str, build: dict[str, Any], threats: list[tuple[str, str]]) -> None:
        self.active_style = style_key
        self.route_view = True
        self.style_label.setText(f"Arquetipo activo: {self._style_label(style_key)}")
        self._render_route_detail(style_key, build, threats)

    def _render_route_detail(self, style_key: str, build: dict[str, Any], threats: list[tuple[str, str]]) -> None:
        self._clear()
        self.content_layout.addWidget(self._player_header())
        self.content_layout.addWidget(self._inventory_widget())
        back = QPushButton("← Volver a rutas")
        back.setObjectName("recommendationBackButton")
        back.clicked.connect(self._show_route_list)
        self.content_layout.addWidget(back)

        title = QLabel(f"RUTA · {build.get('label', 'Build adaptable')}")
        title.setObjectName("recommendationRouteTitle")
        self.content_layout.addWidget(title)
        intro = QLabel(self._route_reason(style_key, build, threats))
        intro.setObjectName("recommendationReason")
        intro.setWordWrap(True)
        self.content_layout.addWidget(intro)

        next_item, path = self._next_purchase(build)
        self.content_layout.addWidget(self._next_purchase_card(next_item, path, threats))

        section = QLabel("ORDEN RECOMENDADO")
        section.setObjectName("recommendationBuildTitle")
        self.content_layout.addWidget(section)
        owned = self._owned_items()
        excluded = [
            f"{self._catalog().get(str(item_id), {}).get('name', str(item_id))} (incompatible con {self._incompatibility_name(str(item_id), owned)})"
            for item_id in build.get("core", [])
            if str(item_id) not in owned and not self._is_purchase_compatible(str(item_id), owned)
        ]
        if excluded:
            note = QLabel(f"No se recomiendan: {', '.join(excluded)}. Son incompatibles con tu inventario actual.")
            note.setObjectName("recommendationCompatibilityNote")
            note.setWordWrap(True)
            self.content_layout.addWidget(note)
        purchase_position = 1
        for item_id in build.get("core", []):
            if not self._is_purchase_compatible(str(item_id), owned):
                continue
            self.content_layout.addWidget(self._item_recommendation(item_id, purchase_position, threats, False, style_key))
            purchase_position += 1

        situational_title = QLabel("SITUACIONALES")
        situational_title.setObjectName("recommendationBuildTitle")
        self.content_layout.addWidget(situational_title)
        for position, item_id in enumerate(build.get("situational", []), 1):
            self.content_layout.addWidget(self._item_recommendation(item_id, position, threats, True, style_key))
        self.content_layout.addStretch(1)

    def _player_header(self) -> QWidget:
        state = self._local_state()
        player = self._last_session.get("players", {}).get(self._last_session.get("local_player_key"), {})
        champion = self.active_champion or self._local_champion(self._last_session)
        level = int(state.get("level", player.get("level", 0)) or 0)
        live_stats = state.get("live_stats", {})
        if not isinstance(live_stats, dict):
            live_stats = {}
        health = live_stats.get("maxHealth", live_stats.get("maxhealth", "--"))
        gold = self._available_gold(state)
        header = QFrame()
        header.setObjectName("recommendationPlayerHeader")
        outer = QHBoxLayout(header)
        outer.setContentsMargins(12, 10, 12, 10)
        portrait = QLabel()
        portrait.setObjectName("recommendationPortrait")
        portrait.setFixedSize(58, 58)
        if self.assets is not None:
            self.assets.set_label_image(portrait, self.assets.champion_url(champion), f"recommendation-champion:{champion}:58", 58)
        outer.addWidget(portrait)
        identity = QVBoxLayout()
        name = QLabel(f"{champion}  ·  NIVEL {level}")
        name.setObjectName("recommendationPlayerName")
        identity.addWidget(name)
        identity.addWidget(QLabel(f"VIDA  {health}     TIEMPO  {self._game_time()}"))
        outer.addLayout(identity, 1)
        economy = QLabel(f"ORO\n{gold:,}" if gold is not None else "ORO\n--")
        economy.setObjectName("recommendationPlayerGold")
        outer.addWidget(economy)
        outer.addWidget(self._spell_rune_summary(player))
        return header

    def _spell_rune_summary(self, player: dict[str, Any]) -> QLabel:
        spells = player.get("summoner_spells", player.get("summonerSpells", {}))
        spell_names = [str(value.get("displayName", "?")) for value in spells.values() if isinstance(value, dict)] if isinstance(spells, dict) else []
        runes = player.get("runes", {})
        keystone = ""
        if isinstance(runes, dict):
            keystone = str(runes.get("keystone", {}).get("displayName", ""))
        label = QLabel(f"HECHIZOS\n{' · '.join(spell_names) or '--'}\n\nRUNAS\n{keystone or '--'}")
        label.setObjectName("recommendationPlayerMeta")
        return label

    def _game_time(self) -> str:
        seconds = int(float(self._last_session.get("duration", 0) or 0))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _inventory_widget(self) -> QWidget:
        state = self._local_state()
        items = [self._item_id(value) for value in state.get("items", [])]
        items = [value for value in items if value]
        panel = QFrame()
        panel.setObjectName("recommendationInventory")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 9, 12, 9)
        title = QLabel(f"TU INVENTARIO  ·  {len(items)}/6 OBJETOS")
        title.setObjectName("recommendationSectionTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(7)
        for index, item_id in enumerate(items[:6]):
            icon = QLabel()
            icon.setObjectName("recommendationInventoryIcon")
            icon.setFixedSize(46, 46)
            if self.assets is not None:
                self.assets.set_label_image(icon, self.assets.item_url(int(item_id)), f"recommendation-inventory:{item_id}:46", 46)
            grid.addWidget(icon, 0, index)
        if not items:
            empty = QLabel("Inventario todavía vacío")
            empty.setObjectName("recommendationMuted")
            grid.addWidget(empty, 0, 0)
        grid.setColumnStretch(6, 1)
        layout.addLayout(grid)
        return panel

    def _next_purchase_card(self, item: dict[str, Any], path: list[str], threats: list[tuple[str, str]]) -> QWidget:
        card = QFrame()
        card.setObjectName("recommendationNextPurchase")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        icon = QLabel()
        icon.setObjectName("recommendationLargeIcon")
        icon.setFixedSize(58, 58)
        if item and self.assets is not None:
            self.assets.set_label_image(icon, self.assets.item_url(int(item["id"])), f"recommendation-next:{item['id']}:58", 58)
        layout.addWidget(icon)
        details = QVBoxLayout()
        title = QLabel("SIGUIENTE COMPRA RECOMENDADA")
        title.setObjectName("recommendationBuildTitle")
        details.addWidget(title)
        text = QLabel(self._purchase_text(item, path))
        text.setObjectName("recommendationReason")
        text.setWordWrap(True)
        details.addWidget(text)
        layout.addLayout(details, 1)
        return card

    def _route_reason(self, style_key: str, build: dict[str, Any], threats: list[tuple[str, str]]) -> str:
        matchup = self._matchup_text()
        reason = self._build_reason(build, threats)
        return f"ARQUETIPO: {self._style_label(style_key)}. {reason} {matchup}"

    def _show_route_list(self) -> None:
        self.route_view = False
        self.update_recommendations(self._last_session)

    def _matchup_text(self) -> str:
        enemies = sorted({str(player.get("champion_name", "enemigo")) for player in self._last_session.get("players", {}).values() if isinstance(player, dict) and player.get("side") == "enemy"})
        return f"Matchup detectado: {', '.join(enemies)}." if enemies else "Aún no hay campeones enemigos identificados."

    def _next_purchase(self, build: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        state = self._local_state()
        owned = self._owned_items()
        for target_id in build.get("core", []):
            if str(target_id) not in owned and self._is_purchase_compatible(str(target_id), owned):
                path = self._component_path(str(target_id), owned)
                gold = self._available_gold(state)
                next_id = path[0]
                if gold is not None:
                    affordable = [
                        candidate
                        for candidate in path
                        if self._item_cost(candidate) <= gold
                    ]
                    if affordable:
                        next_id = affordable[-1]
                return {"id": next_id, **self._catalog().get(next_id, {})}, path
        return {}, []

    def _owned_items(self) -> set[str]:
        return {self._item_id(item) for item in self._local_state().get("items", []) if self._item_id(item)}

    def _is_purchase_compatible(self, item_id: str, owned: set[str]) -> bool:
        if item_id in owned:
            return False
        if self.EXCLUSIVE_ITEMS.get(item_id, set()) & owned:
            return False
        item_groups = self._item_groups(item_id)
        if not item_groups:
            return True
        return not any(
            group in self._item_groups(owned_item)
            for owned_item in owned
            for group in item_groups
        )

    def _item_groups(self, item_id: str) -> set[str]:
        item = self._catalog().get(str(item_id), {})
        if not isinstance(item, dict):
            return set()
        name = str(item.get("name", "")).casefold()
        text = self._text(item)
        tags = {str(tag).casefold() for tag in item.get("tags", [])}
        groups: set[str] = set()
        if "boots" in tags or "botas" in name or "grebas" in name or "tabi" in name:
            groups.add("boots")
        if "hidra" in name or "hydra" in name:
            groups.add("hydra")
        if "salvavidas" in text or "lifeline" in text or any(term in name for term in ("sterak", "malmortius", "arcoescudo")):
            groups.add("lifeline")
        if any(term in name for term in ("manamune", "muramana", "abrazo del serafín", "seraph's embrace")):
            groups.add("tear")
        for group, terms in self.EXCLUSIVE_NAME_GROUPS.items():
            if any(term in name for term in terms):
                groups.add(group)
        return groups

    def _incompatibility_name(self, item_id: str, owned: set[str]) -> str:
        item = self._catalog().get(str(item_id), {})
        groups = self._item_groups(item_id)
        for owned_item in owned:
            if self.EXCLUSIVE_ITEMS.get(item_id, set()) and owned_item in self.EXCLUSIVE_ITEMS[item_id]:
                return self._catalog().get(owned_item, {}).get("name", owned_item)
            if groups & self._item_groups(owned_item):
                return self._catalog().get(owned_item, {}).get("name", owned_item)
        return "otro objeto exclusivo"

    def _component_path(self, item_id: str, owned: set[str]) -> list[str]:
        item = self._catalog().get(item_id, {})
        components = [self._item_id(value) for value in item.get("from", [])] if isinstance(item, dict) else []
        for component in components:
            if component not in owned:
                return self._component_path(component, owned) + [item_id]
        return [item_id]

    def _purchase_text(self, item: dict[str, Any], path: list[str]) -> str:
        if not item:
            return "El núcleo de la ruta ya está completo; elige un situacional según las amenazas."
        state = self._local_state()
        gold = self._available_gold(state)
        cost = int(item.get("gold", {}).get("total", 0) or 0)
        path_names = " → ".join(self._catalog().get(key, {}).get("name", key) for key in path)
        gold_text = str(gold) if gold is not None else "no disponible"
        affordable = "Puedes comprarlo ahora." if gold is not None and gold >= cost else (f"Te faltan {cost - gold} de oro para este componente." if gold is not None else "Espera a recibir el oro LIVE para confirmar la compra.")
        return f"Compra ahora {item.get('name', 'el siguiente componente')} ({cost} oro). {self._item_explanation(item, self.active_style, self.current_threats, False)} Oro disponible: {gold_text}. {affordable} Path completo: {path_names}."

    @staticmethod
    def _available_gold(state: dict[str, Any]) -> int | None:
        for key in ("current_gold", "currentGold", "goldCurrent"):
            value = state.get(key)
            if value is not None:
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    pass
        return None

    def _item_cost(self, item_id: str) -> int:
        item = self._catalog().get(str(item_id), {})
        gold = item.get("gold", {}) if isinstance(item, dict) else {}
        if isinstance(gold, dict):
            try:
                return int(gold.get("total", gold.get("base", 0)) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def _local_state(self) -> dict[str, Any]:
        local_key = self._last_session.get("local_player_key")
        players = self._last_session.get("players", {})
        latest = {}
        for snapshot in self._last_session.get("snapshots", []):
            latest = snapshot.get("players", {}).get(local_key, latest)
        return latest or players.get(local_key, {}) or {}

    def _item_recommendation(self, item_id: Any, position: int, threats: list[tuple[str, str]], situational: bool, style_key: str) -> QWidget:
        item_key = str(item_id)
        item = {"id": item_key, **self._catalog().get(item_key, {})}
        row = QFrame()
        row.setObjectName("recommendationItemRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        icon = QLabel()
        icon.setObjectName("itemIcon")
        icon.setFixedSize(40, 40)
        if self.assets is not None:
            self.assets.set_label_image(icon, self.assets.item_url(int(item_key)), f"recommendation-item:{item_key}:40", 40)
        layout.addWidget(icon)
        text = QVBoxLayout()
        purchase_label = f"Compra {position}" if not situational else f"Situacional {position}"
        owned = item_key in {self._item_id(value) for value in self._local_state().get("items", [])}
        status = "  ·  COMPRADO" if owned else ""
        name = QLabel(f"{purchase_label}: {item.get('name', item_key)}{status}")
        name.setObjectName("recommendationItemName")
        text.addWidget(name)
        text.addWidget(QLabel(self._item_explanation(item, style_key, threats, situational)))
        layout.addLayout(text, 1)
        return row

    def _item_explanation(self, item: dict[str, Any], style_key: str, threats: list[tuple[str, str]], situational: bool) -> str:
        profile = self._profile_for(self.active_champion)
        result = self.synergy.score_item(profile, style_key, str(item.get("id", "")), item, threats)
        counter = f" Countera: {', '.join(result.counter_reasons)}." if result.counter_reasons else ""
        return f"{self._item_reason(item, threats, situational, style_key)} Afinidad: {result.score:.1f}.{counter}"

    def _item_reason(self, item: dict[str, Any], threats: list[tuple[str, str]], situational: bool, style_key: str = "") -> str:
        threat_names = ", ".join(self._counter_name(key) for key, _ in threats)
        enemies = self._enemy_champions()
        choice_reason = self.CHOICE_REASONS.get((self.active_champion, style_key or self.active_style, str(item.get("id", ""))))
        if choice_reason:
            return choice_reason
        if str(item.get("id", "")) == "3111" and enemies & self.CROWD_CONTROL_ENEMIES:
            names = ", ".join(sorted(enemies & self.CROWD_CONTROL_ENEMIES))
            return f"Mercs es buena contra {names}: aporta tenacidad para salir antes de sus controles y resistencia mágica contra su daño."
        if str(item.get("id", "")) == "3047" and enemies:
            return "Estas botas reducen el daño de ataques básicos; son mejores si los rivales AD o sus carries son la principal amenaza."
        if str(item.get("id", "")) == "3071" and "Darius" in enemies:
            return "Black Cleaver es buena contra Darius porque reduce su armadura durante el intercambio y da vida para sobrevivir a su pelea larga."
        specific_reason = self.ITEM_REASONS.get(str(item.get("id", "")))
        if specific_reason:
            return specific_reason
        text = self._text(item)
        matched = [self._counter_name(key) for key, _ in threats if any(term in text for term in self.COUNTERS.get(key, ()))]
        if matched:
            return f"Se recomienda porque responde directamente a {', '.join(matched)} detectada en el equipo enemigo."
        if situational and threat_names:
            return f"Alternativa situacional contra {threat_names}: activa esta opción si esa amenaza domina la partida."
        if situational:
            return "Reserva esta opción para cubrir una necesidad defensiva u ofensiva concreta de la composición enemiga."
        tags = ", ".join(str(tag).replace("Damage", "daño").replace("AttackSpeed", "velocidad de ataque").replace("SpellDamage", "poder de habilidad") for tag in item.get("tags", []))
        return f"Es parte del núcleo porque aporta {tags or 'las estadísticas principales'} que necesita este arquetipo."

    def _enemy_champions(self) -> set[str]:
        return {
            str(player.get("champion_name", ""))
            for player in self._last_session.get("players", {}).values()
            if isinstance(player, dict) and player.get("side") == "enemy" and player.get("champion_name")
        }

    def _situational_card(self, threats: list[tuple[str, str]]) -> QWidget:
        card = QFrame()
        card.setObjectName("recommendationSituational")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("OBJETOS SITUACIONALES")
        title.setObjectName("recommendationBuildTitle")
        layout.addWidget(title)
        if not threats:
            text = "Sin amenazas claras todavía: prioriza la ruta que mejor encaje con tu composición."
        else:
            text = " · ".join(f"{label}: {self._counter_name(key)}" for key, label in threats)
        label = QLabel(text)
        label.setObjectName("recommendationReason")
        label.setWordWrap(True)
        layout.addWidget(label)
        return card

    def _enemy_items(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        players = session.get("players", {})
        local_key = session.get("local_player_key")
        local_team = session.get("local_team")
        latest: dict[str, dict[str, Any]] = {}
        for snapshot in session.get("snapshots", []):
            for key, point in snapshot.get("players", {}).items():
                if isinstance(point, dict):
                    latest[key] = point
        found: dict[str, dict[str, Any]] = {}
        for key, player in players.items():
            if key == local_key or not isinstance(player, dict):
                continue
            if player.get("side") != "enemy" and local_team and player.get("team") == local_team:
                continue
            values = latest.get(key, {}).get("items", player.get("items", []))
            for value in values if isinstance(values, list) else []:
                item_id = self._item_id(value)
                item = self._catalog().get(item_id)
                if item_id and isinstance(item, dict):
                    found[item_id] = item
        return [{"id": item_id, "name": item.get("name", f"Objeto {item_id}"), **item} for item_id, item in found.items()]

    def _detect_threats(self, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
        return [(key, label) for key, (terms, label) in self.THREATS.items() if any(term in self._text(item) for item in items for term in terms)]

    def _build_reason(self, build: dict[str, Any], threats: list[tuple[str, str]]) -> str:
        labels = [self._counter_name(key) for key, _ in threats if any(term in self._text(self._catalog().get(str(item_id), {})) for item_id in build.get("core", []) for term in self.COUNTERS.get(key, ()))]
        return "Responde a " + ", ".join(labels) + "." if labels else "Ruta válida para mantener el plan de juego del campeón."

    def _adaptive_style(self, profile: dict[str, Any], threats: list[tuple[str, str]]) -> str:
        styles = profile.get("styles", [])
        preferred = profile.get("default_style", styles[0] if styles else "")
        keys = {key for key, _ in threats}
        if "critico" in keys and "tank" in styles:
            return "tank"
        if "armadura" in keys and "on_hit" in styles:
            return "on_hit"
        if "curacion" in keys and "bruiser_ad" in styles:
            return "bruiser_ad"
        return preferred

    def _counter_name(self, key: str) -> str:
        return {"curacion": "curación", "armadura": "armadura", "resistencia_magica": "resistencia mágica", "critico": "crítico", "vida": "vida alta"}.get(key, key)

    def _summary(self, profile: dict[str, Any], threats: list[tuple[str, str]], items: list[dict[str, Any]]) -> str:
        threat_text = ", ".join(label for _, label in threats) or "ninguna todavía"
        return f"{profile.get('note', 'Perfil adaptable según los objetos enemigos.')} Amenazas: {threat_text}. Objetos enemigos visibles: {len(items)}."

    def _local_champion(self, session: dict[str, Any]) -> str:
        player = session.get("players", {}).get(session.get("local_player_key"), {})
        return str(player.get("champion_name") or session.get("champion_name") or "Campeón")

    def _style_label(self, key: str) -> str:
        return self.profiles.get("archetypes", {}).get(key, {}).get("label", key or "Adaptable")

    def _on_style_changed(self, index: int) -> None:
        if index >= 0:
            self.active_style = self.style_selector.itemData(index) or ""
            if self.active_champion and self.active_style:
                self.update_recommendations(self._last_session)

    def _populate_style_selector(self, styles: list[str], active: str) -> None:
        current_styles = [self.style_selector.itemData(index) for index in range(self.style_selector.count())]
        if current_styles != styles:
            self.style_selector.blockSignals(True)
            self.style_selector.clear()
            for key in styles:
                self.style_selector.addItem(self._style_label(key), key)
            self.style_selector.blockSignals(False)
        target_index = self.style_selector.findData(active)
        if target_index >= 0 and target_index != self.style_selector.currentIndex():
            self.style_selector.blockSignals(True)
            self.style_selector.setCurrentIndex(target_index)
            self.style_selector.blockSignals(False)

    def _profile_for(self, champion: str) -> dict[str, Any]:
        champions = self.profiles.setdefault("champions", {})
        if champion not in champions:
            primary = self.PRIMARY_STYLES.get(champion, self.profiles.get("fallback", {}).get("recommendation", "bruiser_ad"))
            champions[champion] = {
                "recommendation": primary,
                "default_style": primary,
                "styles": [primary] + [key for key in self.ARCHETYPE_ORDER if key != primary],
                "note": f"{champion}: juega alrededor de {self._style_label(primary).lower()}, respeta sus ventanas de poder y adapta la defensa a la composición enemiga. Counterea rivales que no pueden responder a ese plan; sufre contra control, alcance o anti-curación según la partida.",
            }
        profile = champions[champion]
        primary = str(profile.get("recommendation") or profile.get("default_style") or self.ARCHETYPE_ORDER[0])
        profile.setdefault("recommendation", primary)
        profile.setdefault("default_style", primary)
        profile.setdefault("styles", [primary] + [key for key in self.ARCHETYPE_ORDER if key != primary])
        return champions[champion]

    def _load_profiles(self) -> dict[str, Any]:
        try:
            return json.loads(Path(__file__).parents[2].joinpath("data", "champion_builds.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"archetypes": {}, "fallback": {"styles": []}}

    def _catalog(self) -> dict[str, Any]:
        value = self.item_catalog.get("items", self.item_catalog)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        return " ".join(str(item.get(key, "")) for key in ("name", "description", "plaintext", "tags")).casefold()

    @staticmethod
    def _item_id(value: Any) -> str:
        value = value.get("itemID", value.get("id", 0)) if isinstance(value, dict) else value
        try:
            return str(int(value)) if int(value) > 0 else ""
        except (TypeError, ValueError):
            return ""

    def _clear(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _message(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("recommendationEmptyState")
        label.setWordWrap(True)
        self.content_layout.addWidget(label)

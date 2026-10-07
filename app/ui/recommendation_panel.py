from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.live_recommendation_service import LiveRecommendationService
from app.ui.draft_tool_dialog import DraftPowerCurveWidget
from app.ui.local_analysis_dialog import DamageBarWidget
from app.ui.sistema_visual import PALETA
from app.ui.tema import (
    aplicar_tema,
)


class RecommendationPanel(QFrame):
    """One contextual dashboard: priority, champion affinity, opponents and action plan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().__init__(parent)
        self.assets = None
        self.item_catalog: dict[str, Any] = {}
        self.engine = LiveRecommendationService()
        self.draft_analyzer = DraftAnalyzerService(
            perfiles=self.engine.champions.values()
        )
        self.report = None
        self._last_report = None
        self._last_composition = None
        self._last_session = {}
        self._columns = 0
        self._scroll_position = 0
        self._expanded = {"actionPlan": True}
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_scroll)
        self.setObjectName("recommendationPanel")
        aplicar_tema(self)
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QFrame#recommendationPanel QLabel#synergyScore,
            QFrame#recommendationPanel QLabel#purchaseAffinity {{
                padding: 4px 9px; border-radius: 8px; border: 1px solid {PALETA["oro_oscuro"]};
                background: {PALETA["calida"]}; color: {PALETA["oro_suave"]}; font-weight: 700;
            }}
            QFrame#recommendationPanel QLabel#synergyScore[intensidad="alta"] {{
                background: {PALETA["activo"]}; border-color: {PALETA["oro"]}; color: {PALETA["texto"]};
            }}
            QFrame#recommendationPanel QLabel#synergyScore[intensidad="media"] {{
                background: {PALETA["calida"]}; border-color: {PALETA["oro_oscuro"]};
            }}
            QFrame#recommendationPanel QLabel#synergyScore[intensidad="baja"] {{
                background: {PALETA["superficie"]}; border-color: {PALETA["borde_sutil"]};
                color: {PALETA["secundario"]};
            }}
            QFrame#recommendationPanel QLabel#enemyStrengthBadge,
            QFrame#recommendationPanel QLabel#enemyInventoryBadge,
            QFrame#recommendationPanel QLabel#enemyBuildGold {{
                padding: 2px 6px; border-radius: 7px; border: 1px solid {PALETA["oro_oscuro"]};
                background: {PALETA["calida"]};
            }}
            QFrame#recommendationPanel QWidget#recommendationBody,
            QFrame#recommendationPanel QWidget#recommendationDashboard,
            QFrame#recommendationPanel QWidget#draftDamageCard,
            QFrame#recommendationPanel QWidget#draftCurveCard {{
                background: {PALETA["superficie"]}; border: 1px solid {PALETA["borde"]}; border-radius: 14px;
            }}
        """
        )
        self._build_ui()

    @staticmethod
    def label(text="", role="body"):
        label = QLabel(str(text))
        label.setProperty("role", role)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def card(name=""):
        frame = QFrame()
        frame.setProperty("card", "true")
        if name:
            frame.setObjectName(name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        return frame, layout

    def configure(self, assets: Any, item_catalog: dict[str, Any]) -> None:
        """Configura los recursos visuales y el catálogo de objetos del panel."""
        self.assets = assets
        self.item_catalog = item_catalog or {}
        self.engine = LiveRecommendationService(self.item_catalog)
        self.draft_analyzer = DraftAnalyzerService(
            perfiles=self.engine.champions.values()
        )
        self._last_report = None

    def _build_ui(self) -> None:
        """Construye la cabecera y el área desplazable del panel."""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        header = QHBoxLayout()
        self.portrait = self.label("LIVE", "icon")
        self.portrait.setFixedSize(54, 54)
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.portrait)
        identity = QVBoxLayout()
        identity.setSpacing(3)
        identity.addWidget(self.label("ASISTENTE DE PARTIDA · SINERGIAS", "eyebrow"))
        self.title = self.label("Esperando campeón", "title")
        identity.addWidget(self.title)
        self.meta = self.label(
            "El análisis se adapta al último estado disponible.", "muted"
        )
        identity.addWidget(self.meta)
        header.addLayout(identity, 1)
        self.mode = self.label("LIVE", "badge")
        self.mode.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self.mode)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("recommendationBody")
        self.content.setProperty("superficie", "tarjeta")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 4, 0)
        self.content_layout.setSpacing(8)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

    def icon(self, ident: str | int, size: int = 40) -> QLabel:
        """Crea una etiqueta con el icono local de un objeto."""
        label = self.label(str(ident), "icon")
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(self.engine.name(str(ident)))
        if self.assets is not None:
            self.assets.set_label_image(
                label,
                self.assets.item_url(int(ident)),
                f"synergy-live-item:{ident}:{size}",
                size,
            )
        return label

    def champion_icon(self, champion: str, size: int = 30) -> QLabel:
        """Retrato del campeón enemigo; sin assets queda el texto de respaldo."""
        label = self.label(str(champion)[:3].upper(), "icon")
        label.setObjectName("enemyChampionIcon")
        label.setFixedSize(size, size)
        label.setWordWrap(False)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(str(champion))
        if self.assets is not None:
            self.assets.set_label_image(
                label,
                self.assets.champion_url(champion),
                f"synergy-live-enemy:{champion}:{size}",
                size,
            )
        return label

    def update_recommendations(self, session: dict[str, Any]) -> None:
        """Actualiza recomendaciones y análisis con la sesión recibida."""
        self._last_session = session
        report = self.engine.analyze(session)
        self.report = report
        composition = self._team_champions(report)
        if report == self._last_report and composition == self._last_composition:
            return
        previous = self._last_report
        self._last_report = report
        self._last_composition = composition
        scroll_position = (
            self._scroll_position
            if self._restore_timer.isActive()
            else self.scroll.verticalScrollBar().value()
        )
        self.setUpdatesEnabled(False)
        try:
            self.title.setText(report["champion"])
            seconds = int(report["time"])
            gold = (
                f"{report['gold']:,} oro disponible"
                if report["gold"] is not None
                else "Oro no disponible"
            )
            self.meta.setText(
                f"{report['role']} · Nivel {report['level'] or '—'} · {seconds // 60:02d}:{seconds % 60:02d} · {report['phase']} · {gold}"
            )
            self.mode.setText(
                "REVISIÓN POSTGAME" if report["ended"] else "LIVE · ÚLTIMA MUESTRA"
            )
            if not previous or previous["champion"] != report["champion"]:
                self.portrait.clear()
                self.portrait.setText(report["champion"][:3].upper())
                if self.assets:
                    champ = report["champion"]
                    self.assets.set_label_image(
                        self.portrait,
                        self.assets.champion_url(champ),
                        f"synergy-live-champion:{champ}:54",
                        54,
                    )
            while self.content_layout.count():
                item = self.content_layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
            self.content_layout.addWidget(self._priority(report))
            self.content_layout.addWidget(self._inventory(report))
            self.dashboard = QWidget()
            self.dashboard.setObjectName("recommendationDashboard")
            self.dashboard.setProperty("superficie", "tarjeta")
            self.dashboard_grid = QGridLayout(self.dashboard)
            self.dashboard_grid.setContentsMargins(0, 0, 0, 0)
            self.dashboard_grid.setSpacing(14)
            self.left = self._recommendations(report)
            self.right = self._context(report)
            self.damage_card = self._damage_composition(report)
            self.curve_card = self._power_curve(report)
            self._columns = 0
            self._reflow()
            self.content_layout.addWidget(self.dashboard)
            self.content_layout.addWidget(
                self._details("qualityCard", "Datos y limitaciones", report["warnings"])
            )
            self.content_layout.addStretch(1)
            self.content_layout.activate()
            self._scroll_position = scroll_position
            self._restore_timer.start(0)
        finally:
            self.setUpdatesEnabled(True)

    def _restore_scroll(self):
        self.content.adjustSize()
        self.content_layout.activate()
        self.scroll.verticalScrollBar().setValue(self._scroll_position)

    def _details(self, name, title, lines):
        card, layout = self.card(name)
        toggle = QToolButton()
        toggle.setObjectName(name + "Toggle")
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        text = self.label("\n".join(f"• {line}" for line in lines), "muted")
        text.setObjectName(name + "Text")

        def expand(checked):
            self._expanded[name] = checked
            text.setVisible(checked)
            toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            )

        toggle.toggled.connect(expand)
        toggle.setChecked(self._expanded.get(name, False))
        expand(toggle.isChecked())
        layout.addWidget(toggle)
        layout.addWidget(text)
        return card

    def _priority(self, report):
        card, layout = self.card("priorityCard")
        purchase = report["purchase"]
        status = purchase["status"]
        caption = {
            "buy": "PRIORIDAD · PRÓXIMO RECALL",
            "save": "PRIORIDAD · AHORRAR",
            "full": "PRIORIDAD · REVISAR INVENTARIO",
            "postgame": "REVISIÓN · PARTIDA FINALIZADA",
            "unknown": "COMPRA PENDIENTE DE ORO",
            "stale": "ESPERANDO TELEMETRÍA",
        }.get(status, "SIN COMPRA VERIFICABLE")
        layout.addWidget(self.label(caption, "eyebrow"))
        row = QHBoxLayout()
        if purchase.get("id"):
            row.addWidget(self.icon(purchase["id"], 50))
        info = QVBoxLayout()
        if purchase.get("id"):
            info.addWidget(
                self.label(
                    f"{self.engine.name(purchase['id'])} · {purchase['cost']:,} oro",
                    "accent",
                )
            )
        info.addWidget(self.label(purchase["text"]))
        if purchase.get("target"):
            info.addWidget(
                self.label(
                    f"Objetivo: {self.engine.name(purchase['target'])} · Restan {purchase['remaining']:,} oro tras tus componentes",
                    "muted",
                )
            )
        if report["recommendations"] and status not in {"postgame", "stale", "none"}:
            rec = report["recommendations"][0]
            reason = " · ".join(rec["responses"]) or " · ".join(rec["reasons"][:2])
            info.addWidget(self.label(f"Por qué ahora: {reason}", "muted"))
        row.addLayout(info, 1)
        layout.addLayout(row)
        return card

    def _inventory(self, report):
        card, layout = self.card("inventoryCard")
        row = QHBoxLayout()
        row.addWidget(self.label("INVENTARIO OBSERVADO", "eyebrow"), 1)
        for ident in report["owned"][:7]:
            row.addWidget(self.icon(ident, 34))
        if not report["owned"]:
            row.addWidget(self.label("Sin objetos registrados", "muted"))
        layout.addLayout(row)
        return card

    @staticmethod
    def _affinity_tooltip(entry):
        """Explica de dónde salen los puntos de afinidad de una compra sugerida."""
        score = entry.get("score")
        detail = f"{score:g} pts" if score is not None else "sin puntuación"
        return (
            f"Afinidad de esta compra: {detail}, en la misma escala que las recomendaciones "
            "de sinergia (sinergia con el campeón y contramedidas rivales incluidas). "
            "Son puntos heurísticos, no un porcentaje ni una probabilidad de victoria."
        )

    def _brief(self, rec):
        """First reason as a single compact line for the item card."""
        points = list(dict.fromkeys(rec["responses"] + rec["reasons"]))
        if not points:
            return ""
        text = " ".join(points[0].split())
        return text if len(text) <= 72 else text[:71].rstrip(" ,;:.") + "…"

    def _recommendations(self, report: dict[str, Any]) -> QWidget:
        """Presenta sinergias, próximas compras y el plan de coordinación."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label("3 objetos · Sinergia", "section"))
        for position, rec in enumerate(report["recommendations"][:3], 1):
            card, body = self.card(f"synergyItem_{rec['id']}")
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            body.setContentsMargins(8, 6, 8, 6)
            body.setSpacing(0)
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(self.icon(rec["id"], 28))
            text = QVBoxLayout()
            text.setSpacing(2)
            title_row = QHBoxLayout()
            title_row.addWidget(
                self.label(f"{position:02d}  {rec['name']}", "itemName"), 1
            )
            gold = self.label(f"{rec['cost']:,} oro", "muted")
            gold.setObjectName("enemyBuildGold")
            gold.setAlignment(Qt.AlignmentFlag.AlignCenter)
            gold.setWordWrap(False)
            title_row.addWidget(gold)
            text.addLayout(title_row)
            reason = self.label(self._brief(rec), "muted")
            reason.setObjectName("synergyReason")
            reason.setWordWrap(False)
            reason.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            reason.setToolTip(self._brief(rec))
            text.addWidget(reason)
            next_buy = rec.get("next_buy")
            if next_buy:
                hint = self.label(f"Próxima compra: {next_buy}", "muted")
                hint.setObjectName("synergyNextBuy")
                hint.setWordWrap(False)
                hint.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                hint.setToolTip(f"Próxima compra: {next_buy}")
                text.addWidget(hint)
            row.addLayout(text, 1)
            score = self.label(f"{rec['score']:g} pts", "score")
            score.setWordWrap(False)
            score.setObjectName("synergyScore")
            score.setProperty(
                "intensidad",
                "alta"
                if rec["score"] >= 12
                else "media"
                if rec["score"] >= 8
                else "baja",
            )
            score.setAlignment(Qt.AlignmentFlag.AlignCenter)
            score.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
            )
            score.setToolTip(
                "Afinidad relativa al campeón y a esta partida; no es un porcentaje."
            )
            row.addWidget(score)
            body.addLayout(row)
            points = list(dict.fromkeys(rec["responses"] + rec["reasons"]))
            card.setToolTip("\n".join(f"• {p}" for p in points))
            layout.addWidget(card)
        if not report["recommendations"]:
            layout.addWidget(
                self.label(
                    "No hay candidatos compatibles verificados. Conserva tu inventario y espera datos del campeón o del catálogo.",
                    "muted",
                )
            )
        purchases = report.get("purchases") or []
        if purchases:
            layout.addSpacing(4)
            layout.addWidget(self.label("Según tus compras", "section"))
            for entry in purchases:
                card, body = self.card(f"purchaseItem_{entry['id']}")
                card.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
                )
                body.setContentsMargins(8, 6, 8, 6)
                body.setSpacing(0)
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(self.icon(entry["id"], 28))
                text = QVBoxLayout()
                text.setSpacing(2)
                text.addWidget(self.label(entry["name"], "itemName"))
                detail = (
                    f"Falta: {', '.join(entry['missing'])}"
                    if entry.get("missing")
                    else "Complétalo en tienda"
                )
                text.addWidget(
                    self.label(f"{detail} · {entry['cost']:,} oro pendiente", "muted")
                )
                row.addLayout(text, 1)
                score = entry.get("score")
                if score is not None:
                    badge = self.label(f"{score:g} pts", "score")
                    badge.setObjectName("purchaseAffinity")
                    badge.setWordWrap(False)
                    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    badge.setSizePolicy(
                        QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
                    )
                    badge.setToolTip(self._affinity_tooltip(entry))
                    row.addWidget(badge)
                body.addLayout(row)
                card.setToolTip(entry.get("reason", ""))
                layout.addWidget(card)
        layout.addWidget(
            self._details(
                "actionPlan",
                "Plan y coordinación",
                [f"{heading}: {text}" for heading, text in report["actions"]],
            )
        )
        layout.addStretch(1)
        return section

    def _context(self, report: dict[str, Any]) -> QWidget:
        """Presenta la fuerza estimada y el inventario de cada rival."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label("Rivales · Fuerza estimada", "section"))
        if report["threats"]:
            share = report["physical_share"]
            estimate = self.label(
                f"{share:.0%} físico / {1 - share:.0%} mágico · Estimación", "muted"
            )
            estimate.setToolTip(
                "Perfil de daño estimado, no medido; excluye daño verdadero.\n"
                "Fuerza = oro en objetos / 1000 + nivel × 0,6 + ajuste KDA (±2).\n"
                "No predice duelos ni tiene en cuenta posición, vida o enfriamientos."
            )
            layout.addWidget(estimate)
            unmeasured = sum(t["strength"] is None for t in report["threats"])
            if not any(t["strength_label"] for t in report["threats"]):
                layout.addWidget(
                    self.label(
                        "Sin comparación fiable: se necesitan al menos dos rivales con datos completos.",
                        "muted",
                    )
                )
            elif unmeasured:
                note = self.label(
                    f"Comparación parcial: {unmeasured} rival{'es' if unmeasured != 1 else ''} sin datos completos.",
                    "muted",
                )
                note.setObjectName("enemyPartialNote")
                layout.addWidget(note)
        for threat in self._ordered_threats(report["threats"]):
            card, body = self.card(f"enemyCard_{threat['key']}")
            body.setContentsMargins(7, 5, 7, 5)
            body.setSpacing(3)
            # Una sola línea compacta: retrato · nivel · campeón · KDA · fuerza · coste de build.
            heading = QHBoxLayout()
            heading.setSpacing(8)
            heading.addWidget(self.champion_icon(threat["champion"], 26))
            level = self.label(f"Nv {threat['level'] or '—'}", "eyebrow")
            level.setObjectName("enemyLevel")
            level.setWordWrap(False)
            level.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
            )
            heading.addWidget(level)
            name = self.label(threat["champion"], "section")
            name.setObjectName("enemyChampionName")
            name.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
            heading.addWidget(name)
            kda = self.label(threat["kda"], "muted")
            kda.setObjectName("enemyKda")
            kda.setWordWrap(False)
            kda.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            heading.addWidget(kda)
            heading.addStretch(1)
            strength_label = threat["strength_label"]
            if strength_label:
                role = (
                    "strong"
                    if strength_label.startswith("MÁS FUERTE")
                    else ("weak" if strength_label.startswith("MÁS DÉBIL") else "muted")
                )
                badge = self.label(strength_label, role)
                badge.setObjectName("enemyStrengthBadge")
                badge.setWordWrap(False)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setSizePolicy(
                    QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
                )
                badge.setToolTip(
                    "Fuerza relativa estimada; más débil no significa una baja segura."
                )
                heading.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
            inventory = threat["inventory"]
            value = inventory["value"]
            gold_text = (
                "Build: oro desconocido"
                if value is None
                else (
                    f"Build: ≥ {value:,} oro · catálogo incompleto"
                    if inventory["partial"]
                    else f"Build: {value:,} oro"
                )
            )
            gold = self.label(gold_text, "eyebrow")
            gold.setObjectName("enemyBuildGold")
            gold.setToolTip(
                "Valor de catálogo de los objetos actuales, incluidos componentes. "
                "No es oro disponible, oro ganado ni gasto histórico."
            )
            gold.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            gold.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            heading.addWidget(gold)
            body.addLayout(heading)
            icons = QGridLayout()
            icons.setHorizontalSpacing(4)
            icons.setVerticalSpacing(2)
            for index, ident in enumerate(threat["items"]):
                icon = self.icon(ident, 26)
                icon.setObjectName("enemyItemIcon")
                icon.setProperty("itemId", ident)
                icons.addWidget(icon, index // 7, index % 7)
            icons.setColumnStretch(7, 1)
            if threat["items"]:
                body.addLayout(icons)
            else:
                body.addWidget(
                    self.label(
                        "Inventario vacío"
                        if inventory["known"]
                        else "Inventario no disponible",
                        "muted",
                    )
                )
            badge_container = QWidget()
            badges = QGridLayout(badge_container)
            badges.setContentsMargins(0, 0, 0, 0)
            badges.setHorizontalSpacing(4)
            badges.setVerticalSpacing(2)
            for index, fact in enumerate(inventory["badges"]):
                badge = self.label(fact["label"], "enemyBadge")
                badge.setObjectName("enemyInventoryBadge")
                badge.setProperty("kind", fact["kind"])
                badge.setToolTip(fact["detail"])
                badge.setSizePolicy(
                    QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
                )
                badges.addWidget(badge, index // 3, index % 3)
            if inventory["badges"]:
                body.addWidget(badge_container, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                badge_container.deleteLater()
            texts = [s["evidence"] for s in threat["signals"]]
            card.setToolTip(
                "\n".join(texts)
                or "Sin amenazas adicionales identificadas en la última muestra."
            )
            if threat["stale"]:
                body.addWidget(self.label("Muestra antigua o sin timestamp", "eyebrow"))
            layout.addWidget(card)
        if not report["threats"]:
            layout.addWidget(
                self.label("Esperando rivales e inventarios identificados.", "muted")
            )
        layout.addStretch(1)
        return section

    def _damage_composition(self, report: dict[str, Any]) -> QFrame:
        """Compara composición de daño con la lógica y barra del Draft Tool."""
        tarjeta, contenido = self.card("draftDamageCard")
        contenido.addWidget(self.label("COMPOSICIÓN DE DAÑO ESTIMADA", "section"))
        equipos = self._team_champions(report)
        dano_aliado = self.draft_analyzer.calculate_team_damage_breakdown(
            equipos["ally"]
        )
        dano_rival = self.draft_analyzer.calculate_team_damage_breakdown(
            equipos["enemy"]
        )
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(self.label("Aliados", "eyebrow"))
        barra_aliada = DamageBarWidget(parent=tarjeta)
        barra_aliada.set_percentages(
            dano_aliado["physical"], dano_aliado["magic"], dano_aliado["true"]
        )
        barra_aliada.setToolTip(
            "Estimación por perfil de campeones; no es daño medido."
        )
        fila.addWidget(barra_aliada, 1)
        fila.addWidget(self.label("Rivales", "eyebrow"))
        barra_rival = DamageBarWidget(parent=tarjeta)
        barra_rival.set_percentages(
            dano_rival["physical"], dano_rival["magic"], dano_rival["true"]
        )
        barra_rival.setToolTip("Estimación por perfil de campeones; no es daño medido.")
        fila.addWidget(barra_rival, 1)
        contenido.addLayout(fila)
        return tarjeta

    def _power_curve(self, report: dict[str, Any]) -> QFrame:
        """Muestra win rate por tramo y power spike con el widget del Draft Tool."""
        tarjeta, contenido = self.card("draftCurveCard")
        equipos = self._team_champions(report)
        curva_aliada = self.draft_analyzer.calculate_team_power_curve(equipos["ally"])
        curva_rival = self.draft_analyzer.calculate_team_power_curve(equipos["enemy"])
        fase = self.draft_analyzer.analyze_power_spike_phase(curva_aliada, curva_rival)
        grafico = DraftPowerCurveWidget(tarjeta)
        grafico.setMinimumHeight(220)
        grafico.set_data(curva_aliada, curva_rival, fase)
        contenido.addWidget(grafico)
        return tarjeta

    def _team_champions(self, report: dict[str, Any]) -> dict[str, list[str]]:
        """Obtiene integrantes aliados y rivales de la sesión observada."""
        jugadores = self._last_session.get("players", {})
        jugadores = jugadores if isinstance(jugadores, dict) else {}
        clave_local = self._last_session.get("local_player_key")
        local = jugadores.get(clave_local, {})
        equipo_local = local.get("team") or self._last_session.get("local_team")
        aliados = [str(report["champion"])]
        for clave, jugador in jugadores.items() if isinstance(jugadores, dict) else []:
            if clave == clave_local or not isinstance(jugador, dict):
                continue
            if jugador.get("side") == "ally" or (
                jugador.get("side") != "enemy"
                and equipo_local
                and jugador.get("team") == equipo_local
            ):
                nombre = jugador.get("champion_name")
                if nombre:
                    aliados.append(str(nombre))
        rivales = [str(rival["champion"]) for rival in report["threats"]]
        return {"ally": aliados, "enemy": rivales}

    def _ordered_threats(self, threats):
        """Keep lane order independent of the estimated strength ranking."""
        roles = {
            "TOP": 0,
            "JUNGLE": 1,
            "MIDDLE": 2,
            "BOTTOM": 3,
            "UTILITY": 4,
            "MID": 2,
            "BOT": 3,
            "SUPPORT": 4,
        }
        players = self._last_session.get("players", {})
        matchups = self._last_session.get("lane_matchups", {})
        enemy_roles = {
            matchup.get("enemy_key"): role
            for role, matchup in matchups.items()
            if isinstance(matchup, dict) and matchup.get("enemy_key")
        }

        def position(threat):
            key = threat.get("key")
            role = (
                enemy_roles.get(key)
                or players.get(key, {}).get("role")
                or threat.get("role", "")
            )
            return roles.get(str(role).upper(), len(roles))

        return sorted(threats, key=position)

    def _reflow(self):
        if not hasattr(self, "dashboard_grid"):
            return
        # El encabezado de cada rival ocupa una sola línea (retrato, nivel, campeón, KDA,
        # fuerza y coste), así que la vista de dos columnas necesita algo más de ancho.
        columns = 2 if self.width() >= 1080 else 1
        if columns == self._columns:
            return
        self._columns = columns
        self.dashboard_grid.removeWidget(self.left)
        self.dashboard_grid.removeWidget(self.right)
        self.dashboard_grid.addWidget(self.left, 0, 0)
        self.dashboard_grid.addWidget(
            self.right, 0 if columns == 2 else 1, 1 if columns == 2 else 0
        )
        self.dashboard_grid.setColumnStretch(0, 3)
        self.dashboard_grid.setColumnStretch(1, 2 if columns == 2 else 0)
        fila_analisis = 1 if columns == 2 else 2
        self.dashboard_grid.addWidget(self.damage_card, fila_analisis, 0, 1, 2)
        self.dashboard_grid.addWidget(self.curve_card, fila_analisis + 1, 0, 1, 2)
        self.dashboard_grid.activate()
        self.content_layout.invalidate()
        self.content_layout.activate()
        self.content.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

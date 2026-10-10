"""Experiencia de coaching IA para la pestaña de repaso de una grabación."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.match_review_ai_service import MatchReviewAIService
from app.services.settings_service import SettingsService
from app.ui.async_task import run_async
from app.ui.tema import aplicar_apariencia
from data_dragon import get_champion_icon_path

CATEGORIAS_VISTA = (
    ("all", "Todas"),
    ("standout", "Destacados"),
    ("positive_fight", "Buenas peleas"),
    ("negative_fight", "Riesgos"),
    ("objective", "Objetivos"),
    ("improvement", "Mejoras"),
)
FILTROS_EVALUACION = (
    ("all", "Todas las evaluaciones"),
    ("good", "Buenas"),
    ("improvable", "Mejorables"),
    ("bad", "Malas"),
)
ETIQUETAS_EVALUACION = {"good": "BUENA", "improvable": "MEJORABLE", "bad": "MALA"}
_LOG = logging.getLogger(__name__)
ICONOS_CATEGORIA = {
    "standout": "✦",
    "positive_fight": "⚔",
    "negative_fight": "◉",
    "objective": "♜",
    "improvement": "↗",
}
ETIQUETAS_CATEGORIA = {
    "standout": "DESTACADO",
    "positive_fight": "PELEA FAVORABLE",
    "negative_fight": "RIESGO O COSTE",
    "objective": "OBJETIVOS",
    "improvement": "MEJORA",
}


class PostgameAIReview(QWidget):
    """Informe estructurado, persistente y enlazado a la reproducción.

    Attributes:
        seek_requested: Se emite con tiempo de partida al pulsar una marca.
    """

    seek_requested = Signal(float)

    def __init__(self, tracker: Any = None, parent: QWidget | None = None) -> None:
        """Crea el lector de coaching IA para el Match Review.

        Args:
            tracker: Persistencia de sesiones guardadas.
            parent: Widget contenedor opcional.

        Returns:
            None.
        """
        super().__init__(parent)
        self.tracker = tracker
        self.session: dict[str, Any] = {}
        self._generation = 0
        self._task: Any = None
        self._report: dict[str, Any] | None = None
        self._fingerprint = ""
        self._selected_insight = ""
        self._filter = "all"
        self._evaluation_filter = "all"
        self._selected_card: QFrame | None = None
        self._persistence_task: Any = None
        self._build_ui()
        self._show_empty(
            "Carga una partida con telemetría para generar una revisión personalizada."
        )

    def _build_ui(self) -> None:
        """Construye la superficie compacta del informe y sus controles."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(9)

        header = QFrame()
        header.setObjectName("postgameAIHeader")
        aplicar_apariencia(header, "tarjeta")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)
        self.portrait = QLabel("✦")
        self.portrait.setObjectName("postgameAIChampion")
        self.portrait.setFixedSize(48, 48)
        header_layout.addWidget(self.portrait)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.kicker = QLabel("SOLRALOL IA · ANÁLISIS DE PARTIDA")
        self.kicker.setObjectName("postgameAIKicker")
        title_box.addWidget(self.kicker)
        self.champion_title = QLabel("Análisis con IA")
        self.champion_title.setObjectName("postgameAIChampionTitle")
        title_box.addWidget(self.champion_title)
        self.match_context = QLabel("Registro local de la partida")
        self.match_context.setObjectName("postgameAIMatchContext")
        title_box.addWidget(self.match_context)
        header_layout.addLayout(title_box, 1)
        self.status = QLabel("Sin generar")
        self.status.setObjectName("postgameAIStatus")
        header_layout.addWidget(self.status)
        self.generate_button = QPushButton("Generar análisis")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generate)
        header_layout.addWidget(self.generate_button)
        self.retry_save_button = QPushButton("Reintentar guardado")
        self.retry_save_button.setObjectName("postgameAIOrder")
        self.retry_save_button.setVisible(False)
        self.retry_save_button.clicked.connect(self.retry_persistence)
        header_layout.addWidget(self.retry_save_button)
        root.addWidget(header)

        self.summary_card = QFrame()
        self.summary_card.setObjectName("postgameAISummary")
        aplicar_apariencia(self.summary_card, "destacada")
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(13, 11, 13, 11)
        summary_layout.setSpacing(5)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("postgameAISummaryText")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        summary_layout.addWidget(self.summary_label)
        self.summary_strength = QLabel()
        self.summary_strength.setObjectName("postgameAISummaryStrength")
        self.summary_strength.setWordWrap(True)
        self.summary_strength.setTextFormat(Qt.TextFormat.PlainText)
        summary_layout.addWidget(self.summary_strength)
        self.summary_priority = QLabel()
        self.summary_priority.setObjectName("postgameAISummaryPriority")
        self.summary_priority.setWordWrap(True)
        self.summary_priority.setTextFormat(Qt.TextFormat.PlainText)
        summary_layout.addWidget(self.summary_priority)
        self.summary_turning = QLabel()
        self.summary_turning.setObjectName("postgameAISummaryTurning")
        self.summary_turning.setWordWrap(True)
        self.summary_turning.setTextFormat(Qt.TextFormat.PlainText)
        summary_layout.addWidget(self.summary_turning)
        self.summary_coverage = QLabel()
        self.summary_coverage.setObjectName("postgameAISummaryCoverage")
        self.summary_coverage.setWordWrap(True)
        self.summary_coverage.setTextFormat(Qt.TextFormat.PlainText)
        summary_layout.addWidget(self.summary_coverage)
        root.addWidget(self.summary_card)

        self.report_count = QLabel()
        self.report_count.setObjectName("postgameAIReportCount")
        root.addWidget(self.report_count)

        self.filters_frame = QFrame()
        self.filters_frame.setObjectName("postgameAIFilters")
        filter_layout = QHBoxLayout(self.filters_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(5)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in CATEGORIAS_VISTA:
            button = QPushButton(label)
            button.setObjectName("postgameAIFilter")
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(
                lambda checked=False, filtro=key: self.set_filter(filtro)
            )
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filter_layout.addWidget(button)
        filter_layout.addStretch(1)
        self.evaluation_group = QButtonGroup(self)
        self.evaluation_group.setExclusive(True)
        self.evaluation_buttons: dict[str, QPushButton] = {}
        for key, label in FILTROS_EVALUACION:
            button = QPushButton(label)
            button.setObjectName("postgameAIEvaluationFilter")
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(
                lambda checked=False, filtro=key: self.set_evaluation_filter(filtro)
            )
            self.evaluation_group.addButton(button)
            self.evaluation_buttons[key] = button
            filter_layout.addWidget(button)
        self.order_button = QPushButton("Orden cronológico")
        self.order_button.setObjectName("postgameAIOrder")
        self.order_button.setCheckable(True)
        self.order_button.setToolTip(
            "Alterna entre orden cronológico y relevancia del informe."
        )
        self.order_button.clicked.connect(self._toggle_order)
        filter_layout.addWidget(self.order_button)
        root.addWidget(self.filters_frame)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("postgameAIInsightsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.insights_container = QWidget()
        self.insights_layout = QVBoxLayout(self.insights_container)
        self.insights_layout.setContentsMargins(0, 0, 0, 0)
        self.insights_layout.setSpacing(7)
        self.insights_layout.addStretch(1)
        self.scroll.setWidget(self.insights_container)
        root.addWidget(self.scroll, 1)

        self.empty_state = QFrame()
        self.empty_state.setObjectName("postgameAIEmpty")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(16, 18, 16, 18)
        empty_layout.setSpacing(9)
        self.empty_message = QLabel()
        self.empty_message.setObjectName("postgameAIEmptyMessage")
        self.empty_message.setWordWrap(True)
        self.empty_message.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_message)
        self.empty_generate = QPushButton("Generar análisis con IA")
        self.empty_generate.setObjectName("primaryButton")
        self.empty_generate.clicked.connect(self.generate)
        empty_layout.addWidget(self.empty_generate, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.empty_state, 1)
        self._show_report_widgets(False)

    def set_session(self, session: dict[str, Any] | None) -> None:
        """Actualiza la partida y restaura el informe guardado si coincide.

        Args:
            session: Sesión activa del reproductor.

        Returns:
            None.
        """
        self._generation += 1
        self.session = session if isinstance(session, dict) else {}
        self._report = None
        self._fingerprint = ""
        self._selected_card = None
        jugador_key = str(self.session.get("local_player_key") or "")
        jugadores = self.session.get("players")
        jugadores = jugadores if isinstance(jugadores, dict) else {}
        jugador = jugadores.get(jugador_key)
        jugador = jugador if isinstance(jugador, dict) else {}
        campeon = str(
            jugador.get("champion_name") or self.session.get("champion_name") or ""
        )
        gana = jugador.get("win")
        equipo_local = str(self.session.get("local_team") or "").upper()
        equipo_ganador = str(self.session.get("winning_team") or "").upper()
        if gana is None and equipo_local and equipo_ganador:
            gana = equipo_local == equipo_ganador
        resultado = "VICTORIA" if gana is True else "DERROTA" if gana is False else ""
        sync = self.session.get("final_sync")
        sync = sync if isinstance(sync, dict) else {}
        self.match_context.setProperty("resultado", resultado.casefold())
        self.match_context.style().unpolish(self.match_context)
        self.match_context.style().polish(self.match_context)
        self.champion_title.setText(
            f"Análisis de {campeon}" if campeon else "Análisis con IA"
        )
        self.match_context.setText(
            " · ".join(
                value
                for value in (
                    resultado,
                    str(jugador.get("role") or "").upper(),
                    str(self.session.get("game_mode") or "").replace("_", " ").title(),
                    str(sync.get("match_id") or self.session.get("session_id") or ""),
                )
                if value
            )
        )
        self._load_portrait(campeon, str(self.session.get("game_version") or "15.16.1"))
        try:
            _entrada, self._fingerprint = MatchReviewAIService().prepare_input(
                self.session
            )
        except (TypeError, ValueError, OSError):
            self._fingerprint = ""
        registro = self.session.get("ai_match_review")
        if isinstance(registro, dict) and isinstance(registro.get("analysis"), dict):
            self._report = MatchReviewAIService.normalizar_tiempos_informe(
                registro["analysis"], self._duracion_partida()
            )
            self.status.setText(
                "Actualizado"
                if registro.get("source_fingerprint") == self._fingerprint
                else "Puede estar desactualizado"
            )
            self.generate_button.setText("Regenerar análisis")
            self._render_report()
        else:
            self.status.setText(
                "Listo para analizar" if self._fingerprint else "Registro insuficiente"
            )
            self.generate_button.setText("Generar análisis")
            self._show_report_widgets(False)
            self._show_empty(
                "Genera una revisión basada en el registro cronológico y los datos disponibles del campeón."
                if self._fingerprint
                else "Esta partida no conserva un registro de eventos suficiente para un análisis con IA."
            )

    def generate(self) -> None:
        """Inicia una consulta IA en segundo plano para la sesión actual."""
        if self._task is not None:
            return
        if not self._fingerprint:
            self._show_empty(
                "No hay eventos suficientes o falta identificar el campeón de esta partida."
            )
            return
        self._generation += 1
        token = (self._generation, str(self.session.get("session_id") or ""))
        session = deepcopy(self.session)
        self.status.setText("Generando…")
        self.generate_button.setEnabled(False)
        self.generate_button.setText("Analizando partida…")
        if self._report is None:
            self._show_report_widgets(False)
            self._show_empty(
                "Analizando los momentos relevantes del jugador. La reproducción puede continuar."
            )

        def solicitud() -> tuple[dict[str, Any], str, str]:
            """Carga la clave configurada y prepara el informe fuera de la GUI."""
            settings = SettingsService().load()
            api_key = str(settings.get("gemini_api_key") or "").strip()
            if not api_key:
                raise ValueError(
                    "No hay una clave de IA configurada. Añade Gemini en Ajustes."
                )
            service = MatchReviewAIService()
            report, model, fingerprint = service.analyze_match(session, api_key)
            return report, model, fingerprint

        self._task = run_async(solicitud, on_finished=self._on_finished, token=token)

    def _on_finished(self, token: Any, result: Any, error: str | None) -> None:
        """Aplica un resultado de la petición si todavía corresponde a esta sesión."""
        self._task = None
        generation, session_id = token
        if generation != self._generation or session_id != str(
            self.session.get("session_id") or ""
        ):
            self.generate_button.setEnabled(True)
            self.generate_button.setText(
                "Regenerar análisis" if self._report else "Generar análisis"
            )
            return
        self.generate_button.setEnabled(True)
        if error:
            self.status.setText("No se pudo generar")
            self.generate_button.setText("Reintentar análisis")
            if self._report is not None:
                self._render_report()
            else:
                self._show_empty(str(error))
            return
        try:
            report, model, fingerprint = result
            now = datetime.now(UTC).isoformat()
            match_id = str(self.session.get("session_id") or "")
            registro = {
                "schema_version": 2,
                "saved_match_id": match_id,
                "recording_id": str(self.session.get("recording_id") or "") or None,
                "player_participant_id": str(
                    self.session.get("local_player_key") or ""
                ),
                "champion": str(self.session.get("champion_name") or ""),
                "provider": "Gemini",
                "model": model,
                "created_at": now,
                "source_fingerprint": fingerprint,
                "analysis": report,
            }
            self.session["ai_match_review"] = registro
            self._report = report
            self._fingerprint = fingerprint
            self.status.setText(f"Actualizado · {model}")
            self.generate_button.setText("Regenerar análisis")
            self._render_report()
            if self.tracker is not None and match_id:
                self._persist_report(match_id, registro)
        except (KeyError, TypeError, ValueError) as exception:
            self.status.setText("No se pudo guardar")
            self._show_empty(
                f"El informe llegó, pero no se pudo preparar para guardarlo: {exception}"
            )

    def _persist_report(self, match_id: str, report: dict[str, Any]) -> None:
        """Guarda el informe en la sesión canónica sin bloquear el reproductor."""
        if self._persistence_task is not None:
            return
        tracker = self.tracker
        self.retry_save_button.setEnabled(False)
        self._persistence_task = run_async(
            lambda: tracker.guardar_revision_ia(match_id, report),
            on_finished=self._on_persisted,
            token=match_id,
        )

    def _on_persisted(self, token: Any, result: Any, error: str | None) -> None:
        """Actualiza el estado de guardado y registra el fallo concreto."""
        self._persistence_task = None
        if str(token or "") != str(self.session.get("session_id") or ""):
            return
        if error:
            _LOG.error("No se pudo persistir la revisión IA: %s", error)
            self.status.setText("Informe generado · no se pudo guardar en la partida")
            self.retry_save_button.setVisible(True)
            self.retry_save_button.setEnabled(True)
            return
        self.retry_save_button.setVisible(False)
        self.status.setText("Informe guardado en la partida")

    def retry_persistence(self) -> None:
        """Reintenta guardar el informe existente sin llamar al proveedor IA.

        Args:
            Ninguno.

        Returns:
            None.
        """
        registro = self.session.get("ai_match_review")
        session_id = str(self.session.get("session_id") or "")
        if (
            self.tracker is None
            or not session_id
            or not isinstance(registro, dict)
            or not isinstance(registro.get("analysis"), dict)
        ):
            self.status.setText("No hay un informe listo para guardar")
            return
        self.status.setText("Guardando informe…")
        self._persist_report(session_id, registro)

    def set_filter(self, category: str) -> None:
        """Filtra las tarjetas existentes sin volver a consultar el modelo."""
        self._filter = category
        self._render_report()

    def set_evaluation_filter(self, evaluation: str) -> None:
        """Filtra las jugadas por valoración sin regenerar el informe.

        Args:
            evaluation: Clave de valoración o ``all``.

        Returns:
            None.
        """
        self._evaluation_filter = evaluation
        self._render_report()

    def _toggle_order(self, checked: bool) -> None:
        """Alterna el orden cronológico y el orden por relevancia."""
        self.order_button.setText(
            "Orden por relevancia" if checked else "Orden cronológico"
        )
        self._render_report()

    def _render_report(self) -> None:
        """Dibuja el resumen y las observaciones validadas del informe."""
        report = self._report
        if not isinstance(report, dict):
            self._show_report_widgets(False)
            return
        report = MatchReviewAIService.normalizar_tiempos_informe(
            report, self._duracion_partida()
        )
        self._report = report
        summary = (
            report.get("summary") if isinstance(report.get("summary"), dict) else {}
        )
        self.summary_label.setText(
            str(summary.get("overall_assessment") or "Sin resumen disponible.")
        )
        self.summary_strength.setText(
            f"FORTALEZA · {summary.get('main_strength')}"
            if summary.get("main_strength")
            else ""
        )
        self.summary_priority.setText(
            f"PRIORIDAD · {summary.get('main_improvement')}"
            if summary.get("main_improvement")
            else ""
        )
        turning_points = summary.get("turning_points")
        turning_points = turning_points if isinstance(turning_points, list) else []
        self.summary_turning.setText(
            "PUNTOS DE INFLEXIÓN · "
            + " · ".join(str(value) for value in turning_points[:3])
            if turning_points
            else ""
        )
        coverage_note = str(summary.get("coverage_note") or "").strip()
        self.summary_coverage.setText(
            f"COBERTURA · {coverage_note}" if coverage_note else ""
        )
        insights = (
            report.get("insights") if isinstance(report.get("insights"), list) else []
        )
        valid_insights = [item for item in insights if isinstance(item, dict)]
        totals = {key: 0 for key in ETIQUETAS_EVALUACION}
        for item in valid_insights:
            evaluation = str(item.get("evaluation") or "")
            if evaluation in totals:
                totals[evaluation] += 1
        self.report_count.setText(
            f"{len(valid_insights)} jugadas analizadas · "
            f"{totals['good']} buenas · {totals['improvable']} mejorables · {totals['bad']} malas"
            + (
                f" · {len(valid_insights) - sum(totals.values())} sin valoración"
                if len(valid_insights) > sum(totals.values())
                else ""
            )
        )
        if self._filter != "all":
            insights = [
                item
                for item in insights
                if isinstance(item, dict) and item.get("category") == self._filter
            ]
        if self._evaluation_filter != "all":
            insights = [
                item
                for item in insights
                if isinstance(item, dict)
                and item.get("evaluation") == self._evaluation_filter
            ]
        if self.order_button.isChecked():
            insights = sorted(insights, key=lambda item: self._relevance_order(item))
        else:
            insights = sorted(
                insights,
                key=lambda item: float(item.get("match_timestamp_seconds") or 0),
            )
        self._clear_insights()
        self._selected_card = None
        for insight in insights:
            self.insights_layout.insertWidget(
                self.insights_layout.count() - 1, self._build_insight(insight)
            )
        if not insights:
            self._show_empty(
                "El registro no contiene evidencia suficiente para conclusiones específicas."
                if report.get("no_useful_evidence")
                else "No hay observaciones en esta categoría. El informe completo sigue disponible en «Todas».",
                show_button=False,
            )
        else:
            self.empty_state.setVisible(False)
        self._show_report_widgets(True)
        self.scroll.setVisible(bool(insights))

    def _build_insight(self, insight: dict[str, Any]) -> QFrame:
        """Crea una tarjeta expandible con evaluación y marca temporal."""
        category = str(insight.get("category") or "standout")
        evaluation = str(insight.get("evaluation") or "")
        card = QFrame()
        card.setObjectName("postgameAIInsight")
        card.setProperty("category", category)
        card.setProperty("evaluation", evaluation)
        card.setProperty("seleccionado", insight.get("id") == self._selected_insight)
        card.setProperty("insightId", str(insight.get("id") or ""))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(5)
        header = QHBoxLayout()
        header.setSpacing(7)
        toggle = QPushButton(
            f"{ETIQUETAS_EVALUACION.get(evaluation, 'SIN VALORACIÓN')}  ·  "
            f"{ICONOS_CATEGORIA.get(category, '•')} {ETIQUETAS_CATEGORIA.get(category, 'ANÁLISIS')}  ·  "
            f"{insight.get('title') or 'Jugada'}"
        )
        toggle.setObjectName("postgameAIInsightToggle")
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setProperty("evaluation", evaluation)
        toggle.setProperty("category", category)
        toggle.setToolTip("Mostrar u ocultar el análisis detallado")
        header.addWidget(toggle, 1)
        timestamp = QPushButton(
            self._formato_intervalo(
                insight.get("match_timestamp_seconds"),
                insight.get("end_timestamp_seconds"),
            )
        )
        timestamp.setObjectName("postgameAIInsightTimestamp")
        timestamp.setToolTip("Ir a este momento de la partida")
        timestamp.clicked.connect(
            lambda _checked=False, item=insight: self._seek_insight(item)
        )
        header.addWidget(timestamp)

        layout.addLayout(header)
        collapsed = QLabel(
            str(insight.get("what_happened") or insight.get("description") or "")
        )
        collapsed.setObjectName("postgameAIInsightCollapsed")
        collapsed.setWordWrap(True)
        collapsed.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(collapsed)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(7, 4, 7, 0)
        detail_layout.setSpacing(4)
        fields = (
            ("QUÉ OCURRIÓ", insight.get("what_happened") or insight.get("description")),
            ("TU CONTRIBUCIÓN", insight.get("player_contribution")),
            ("POR QUÉ", insight.get("why_this_rating")),
            ("CONSECUENCIA", insight.get("consequence")),
            ("APRENDIZAJE", insight.get("learning") or insight.get("recommendation")),
            ("EVIDENCIA", insight.get("evidence")),
        )
        for label, value in fields:
            if not value:
                continue
            detail_label = QLabel(f"{label} · {value}")
            detail_label.setObjectName("postgameAIInsightDetail")
            detail_label.setWordWrap(True)
            detail_label.setTextFormat(Qt.TextFormat.PlainText)
            detail_layout.addWidget(detail_label)
        detail.setVisible(False)
        toggle.toggled.connect(detail.setVisible)
        layout.addWidget(detail)
        return card

    def _seek_insight(self, insight: dict[str, Any]) -> None:
        """Solicita a la ventana principal saltar al momento seleccionado."""
        self._selected_insight = str(insight.get("id") or "")
        self.seek_requested.emit(float(insight.get("match_timestamp_seconds") or 0))
        if self._selected_card is not None:
            self._selected_card.setProperty("seleccionado", False)
            self._selected_card.style().unpolish(self._selected_card)
            self._selected_card.style().polish(self._selected_card)
        cards = self.insights_container.findChildren(QFrame, "postgameAIInsight")
        self._selected_card = next(
            (
                card
                for card in cards
                if card.property("insightId") == self._selected_insight
            ),
            None,
        )
        if self._selected_card is not None:
            self._selected_card.setProperty("seleccionado", True)
            self._selected_card.style().unpolish(self._selected_card)
            self._selected_card.style().polish(self._selected_card)

    def _load_portrait(self, champion: str, version: str) -> None:
        """Carga el retrato disponible en caché local sin red en la interfaz."""
        self.portrait.clear()
        self.portrait.setText(champion[:1].upper() if champion else "✦")
        if not champion:
            return
        try:
            path = get_champion_icon_path(champion, version, download=False)
        except (OSError, ValueError):
            return
        if not path:
            return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.portrait.setPixmap(
                pixmap.scaled(
                    44,
                    44,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _show_empty(self, message: str, show_button: bool = True) -> None:
        """Presenta invitación, carga, error o estado vacío en español."""
        self.empty_message.setText(message)
        self.empty_generate.setVisible(show_button)
        self.empty_generate.setEnabled(self.generate_button.isEnabled())
        self.empty_state.setVisible(True)

    def _show_report_widgets(self, visible: bool) -> None:
        """Alterna el informe y su estado vacío sin reconstruir la pestaña."""
        self.summary_card.setVisible(visible)
        self.report_count.setVisible(visible)
        self.filters_frame.setVisible(visible)
        self.scroll.setVisible(visible)

    def _clear_insights(self) -> None:
        """Retira tarjetas anteriores conservando el espacio final del layout."""
        while self.insights_layout.count() > 1:
            item = self.insights_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _relevance_order(insight: dict[str, Any]) -> tuple[int, float]:
        """Ordena categorías de mayor interés y mantiene el tiempo estable."""
        order = {
            "standout": 0,
            "negative_fight": 1,
            "objective": 2,
            "positive_fight": 3,
            "improvement": 4,
        }
        return order.get(str(insight.get("category") or ""), 5), float(
            insight.get("match_timestamp_seconds") or 0
        )

    @staticmethod
    def _formato_tiempo(value: Any) -> str:
        """Convierte segundos de partida al formato visible mm:ss."""
        return MatchReviewAIService.formatear_timestamp(value)

    def _duracion_partida(self) -> float:
        """Devuelve la duración de la partida para normalizar tiempos visibles.

        Args:
            Ninguno.

        Returns:
            Duración en segundos, o cero si no está disponible.
        """
        try:
            return max(0.0, float(self.session.get("duration") or 0))
        except (TypeError, ValueError, OverflowError):
            return 0.0

    @classmethod
    def _formato_intervalo(cls, inicio: Any, fin: Any) -> str:
        """Formatea el inicio y el fin opcional de una secuencia analizada.

        Args:
            inicio: Segundo inicial de la jugada.
            fin: Segundo final opcional.

        Returns:
            Marca temporal breve para el control de búsqueda.
        """
        comienzo = cls._formato_tiempo(inicio)
        if fin is None:
            return comienzo
        final = cls._formato_tiempo(fin)
        return comienzo if final == comienzo else f"{comienzo}–{final}"

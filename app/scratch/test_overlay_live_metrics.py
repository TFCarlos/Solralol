"""Regresión de los datos faltantes y estructura fija del overlay."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGridLayout

from app.services.live_player_metrics_service import (
    build_gold_report,
    build_rival_ranking,
    estimate_gold,
)
from app.ui.overlay_settings_dashboard import VistaPreviaOverlay
from app.ui.overlay_window import (
    AlertsPanel,
    GoldPanel,
    OverlayWindow,
    PanelCompraRecomendada,
    ThreatPanel,
    _calcular_compras_recomendadas,
)


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Crea la aplicación Qt necesaria para validar la cuadrícula del panel."""
    return QApplication.instance() or QApplication([])


def test_estimate_gold_omits_unknown_telemetry() -> None:
    """No presenta como cero el oro cuando falta la telemetría de puntuación."""
    assert estimate_gold({"items": []}, {}) is None
    assert (
        estimate_gold(
            {
                "items": [{"itemID": 999999}],
                "scores": {"kills": 0, "assists": 0, "creepScore": 0},
            },
            {},
        )
        is None
    )


def test_gold_report_keeps_five_rows_and_unknown_values() -> None:
    """Devuelve cinco carriles y deja sin cifra las parejas no medibles."""
    snapshot = {
        "local_team": "ORDER",
        "game_time": 600,
        "all_players": [
            {
                "team": "ORDER",
                "position": "TOP",
                "championName": "Garen",
                "scores": {"kills": 1, "assists": 0, "creepScore": 10},
                "items": [],
            },
            {
                "team": "CHAOS",
                "position": "TOP",
                "championName": "Darius",
                "scores": {"kills": 0, "assists": 0, "creepScore": 10},
                "items": [],
            },
        ],
    }
    report = build_gold_report(snapshot, {})
    assert len(report["lanes"]) == 5
    assert report["lanes"][0]["paired"] is True
    assert report["team"]["delta"] is None
    assert all(row["delta"] is None for row in report["lanes"][1:])


def test_threat_ranking_ignores_unavailable_scores() -> None:
    """No interpreta los BattleScore ausentes como una puntuación cero."""
    snapshot = {
        "local_team": "ORDER",
        "game_time": 600,
        "all_players": [
            {
                "team": "CHAOS",
                "position": "TOP",
                "championName": "A",
                "scores": {"kills": 1, "deaths": 0, "assists": 0, "creepScore": 10},
                "items": [],
            },
            {"team": "CHAOS", "position": "MID", "championName": "B", "items": []},
        ],
    }
    ranking = build_rival_ranking(snapshot, {})
    assert ranking["strongest"]["champion"] == "A"
    assert ranking["weakest"] is None


def test_threat_ranking_marks_score_ties() -> None:
    """Expone el empate del máximo y mínimo en vez de sugerir unicidad."""
    scores = {"kills": 2, "deaths": 2, "assists": 2, "creepScore": 50}
    snapshot = {
        "local_team": "ORDER",
        "game_time": 900,
        "all_players": [
            {
                "team": "CHAOS",
                "position": "TOP",
                "championName": "Alpha",
                "scores": scores,
                "items": [],
            },
            {
                "team": "CHAOS",
                "position": "TOP",
                "championName": "Bravo",
                "scores": scores,
                "items": [],
            },
        ],
    }
    ranking = build_rival_ranking(snapshot, {})
    assert ranking["strongest_tie_count"] == 2
    assert ranking["weakest_tie_count"] == 2


def test_purchase_recommendations_use_real_engine_scores_and_filter_owned(
    monkeypatch,
) -> None:
    """Filtra el inventario y conserva las puntuaciones emitidas por el motor."""
    from types import SimpleNamespace

    class Motor:
        def rank_candidates(self, profile, style, items, threats, **kwargs):
            return [
                SimpleNamespace(
                    item_id="100", name="Uno", score=30.5, reasons=("Afinidad",)
                ),
                SimpleNamespace(
                    item_id="200", name="Dos", score=22.0, reasons=("Rival",)
                ),
                SimpleNamespace(item_id="300", name="Tres", score=12.0, reasons=()),
            ]

    class Curador:
        motor_sinergia = Motor()

        def curar(self, variant, profile, candidates, rune_page):
            return {"situational_item_candidates": candidates}

    class Analizador:
        def __init__(self):
            self.curador = Curador()
            self.items = {key: {"name": key} for key in ("100", "200", "300")}
            self.version = "16.1.1"

        def get_champion_profile(self, champion):
            return {"character": champion, "basic_info": {"play_style": "mage"}}

        def _variante_recomendaciones_curada(
            self, champion, profile, rune_page=None, role=None
        ):
            return {
                "item_candidates": [
                    {"item_id": "100", "name": "Uno", "score": 30.5},
                    {"item_id": "200", "name": "Dos", "score": 22.0},
                    {"item_id": "300", "name": "Tres", "score": 12.0},
                ]
            }

    monkeypatch.setattr(
        "app.services.draft_analyzer_service.DraftAnalyzerService", Analizador
    )
    result = _calcular_compras_recomendadas("Lux", (), ("100",), None)
    assert [item["item_id"] for item in result] == ["200", "300"]
    assert [item["score"] for item in result] == [22.0, 12.0]


def test_gold_widget_uses_independent_numeric_grid_cells(
    aplicacion: QApplication,
) -> None:
    """Mantiene las columnas numéricas separadas y cinco filas visibles."""
    panel = GoldPanel({})
    panel.render(
        {
            "team": {"delta": 1900},
            "lanes": [
                {
                    "role": role,
                    "ally": {"champion": "Garen", "gold": 3200},
                    "enemy": {"champion": "Darius", "gold": 2700},
                    "paired": True,
                    "delta": 500,
                }
                for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
            ],
        }
    )
    layout = panel.rows[0].layout()
    assert isinstance(layout, QGridLayout)
    assert layout.columnCount() == 6
    assert len(panel.rows) == 5
    assert all(row.delta.text() == "+500" for row in panel.rows)
    assert panel.total_value.text() == "+1.9K"


def test_alerts_are_not_suppressed_during_recording(aplicacion: QApplication) -> None:
    """Encola y muestra eventos de juego aunque la grabación siga activa."""
    panel = AlertsPanel({})
    panel.duration_seconds = 10
    panel.set_recording(True)
    panel.render(
        [
            {
                "kind": "objective",
                "key": "dragon",
                "name": "Dragón",
                "remaining": 45,
                "spawn_at": 1500,
            }
        ]
    )
    assert panel.alert_timer.isActive()
    assert len(panel.rows) == 1
    assert panel.rows[0].text.text() == "Grabación iniciada"
    assert len(panel._queued_alerts) == 1


def test_test_alert_uses_temporary_notification_row(aplicacion: QApplication) -> None:
    """La prueba de Ajustes reutiliza la fila de alerta y activa su temporizador."""
    panel = AlertsPanel({})
    panel.enqueue_test_alert()
    assert panel.alert_timer.isActive()
    assert panel.rows[0].text.text() == "Dragón en"


def test_preview_proxy_keeps_the_real_overlay_widget_visible(
    aplicacion: QApplication,
) -> None:
    """El preview incrustado no deja oculto el widget nativo del HUD."""
    panel = ThreatPanel({})
    panel.render(
        {
            "strongest": {"champion": "Annie", "role": "MID", "score": 1324},
            "weakest": {"champion": "Xin Zhao", "role": "JGL", "score": 642},
        }
    )
    preview = VistaPreviaOverlay(panel)
    preview.show()
    aplicacion.processEvents()
    assert preview.proxy.widget() is panel
    assert not panel.isHidden()
    assert not preview.grab().isNull()
    preview.close()


def test_purchase_cards_render_real_scores_and_names(aplicacion: QApplication) -> None:
    """Renderiza nombre, puntuación y barra en las tarjetas existentes."""
    panel = PanelCompraRecomendada({})
    panel.render(
        "Gragas",
        [
            {"item_id": "3100", "name": "Perdición del liche", "score": 37.9},
            {"item_id": "4646", "name": "Sobrecarga tormentosa", "score": 23.9},
            {"item_id": "4645", "name": "Llamasombría", "score": 19.6},
        ],
    )
    assert panel.cards[0]["name"].toolTip() == "Perdición del liche"
    assert panel.cards[0]["name"].text()
    assert panel.cards[0]["score"].text() == "37.9 · Sinergia"
    assert not panel.cards[0]["icon"].pixmap().isNull()
    assert panel.cards[0]["bar"].value() == 100
    assert panel.cards[1]["bar"].value() == 63


@pytest.mark.parametrize(
    "panel_class", [AlertsPanel, GoldPanel, ThreatPanel, PanelCompraRecomendada]
)
def test_bottom_right_drag_scales_the_panel_proportionally(
    aplicacion: QApplication, panel_class
) -> None:
    """El asa Qt cambia la escala de cada tipo de ventana independiente."""
    panel = panel_class({})
    if isinstance(panel, AlertsPanel):
        panel.enqueue_test_alert()
    elif isinstance(panel, GoldPanel):
        panel.render({"team": {"delta": 1}, "lanes": []})
    elif isinstance(panel, ThreatPanel):
        panel.render(
            {
                "strongest": {"champion": "Annie", "score": 1200},
                "weakest": {"champion": "Xin Zhao", "score": 600},
            }
        )
    else:
        panel.render(
            "Gragas",
            [
                {"item_id": "3100", "name": "Perdición del liche", "score": 37.9},
                {"item_id": "4646", "name": "Sobrecarga tormentosa", "score": 23.9},
                {"item_id": "4645", "name": "Llamasombría", "score": 19.6},
            ],
        )
    panel.set_scale(1.0)
    panel.set_editing(True)
    released_scales = []
    panel.moved_callback = lambda widget: released_scales.append(widget.scale_factor)
    panel.show()
    aplicacion.processEvents()
    panel._resize_logical_panel()
    ancho_inicial, alto_inicial = panel.width(), panel.height()
    punto = QPoint(ancho_inicial - 6, alto_inicial - 6)
    evento_movimiento = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(punto),
        QPointF(panel.viewport().mapToGlobal(punto)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(panel.viewport(), evento_movimiento)
    assert panel.viewport().cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    QTest.mousePress(panel.viewport(), Qt.MouseButton.LeftButton, pos=punto)
    QTest.mouseMove(panel.viewport(), QPoint(punto.x() - 20, punto.y() - 20), 80)
    QTest.mouseRelease(
        panel.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(punto.x() - 20, punto.y() - 20),
    )
    aplicacion.processEvents()
    assert panel.scale_factor < 1.0
    assert panel.transform().m11() == pytest.approx(panel.scale_factor)
    assert panel.transform().m22() == pytest.approx(panel.scale_factor)
    assert panel.width() < ancho_inicial
    assert panel.height() < alto_inicial
    assert released_scales == [panel.scale_factor]
    assert panel.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    panel.close()


def test_edit_mode_temporarily_overrides_click_through_and_restores_it(
    aplicacion: QApplication,
) -> None:
    """Edit mode captures input and restores per-panel click-through afterward."""

    class Persistencia:
        def save(self, settings):
            self.saved = dict(settings)

    persistencia = Persistencia()
    ajustes = {"overlay_panel_click_through": {"gold": True}}
    overlay = OverlayWindow({}, settings_service=persistencia, settings=ajustes)
    overlay.begin_editing("gold")
    flags_edicion = overlay.panels["gold"].windowFlags()
    assert not flags_edicion & Qt.WindowType.WindowTransparentForInput
    overlay.set_panel_scale("gold", 0.72)
    overlay.end_editing()
    flags_juego = overlay.panels["gold"].windowFlags()
    assert flags_juego & Qt.WindowType.WindowTransparentForInput
    assert overlay.panel_scale("gold") == pytest.approx(0.72)
    assert overlay.panel_scale("threat") == pytest.approx(1.0)
    assert persistencia.saved["overlay_panel_scales"]["gold"] == pytest.approx(0.72)
    overlay.close()
    restaurado = OverlayWindow(
        {}, settings_service=Persistencia(), settings=persistencia.saved
    )
    assert restaurado.panel_scale("gold") == pytest.approx(0.72)
    assert restaurado.panel_scale("alerts") == pytest.approx(1.0)
    restaurado.close()


def test_recommendation_worker_uses_run_async_single_callable_contract(
    aplicacion: QApplication, monkeypatch
) -> None:
    """Fija todos los parámetros en una función cero-args para el pool Qt."""
    import app.ui.overlay_window as modulo

    class Persistencia:
        def save(self, settings):
            self.saved = dict(settings)

    captured = {}

    def run_async(function, *, on_finished, token):
        captured.update(function=function, callback=on_finished, token=token)
        return object()

    monkeypatch.setattr(modulo, "run_async", run_async)
    overlay = OverlayWindow({}, settings_service=Persistencia(), settings={})
    overlay._update_purchase_panel(
        {
            "game_mode": "CLASSIC",
            "local_player": {"championName": "Gragas", "team": "ORDER", "items": []},
            "all_players": [],
        }
    )
    assert callable(captured["function"])
    assert captured["function"].func is _calcular_compras_recomendadas
    assert captured["token"][1] == overlay._purchase_signature[0]
    assert captured["token"][2] == overlay._purchase_signature
    assert captured["function"].args[0] == "Gragas"
    overlay.close()


def test_demo_display_shows_and_hides_all_four_real_overlay_windows(
    aplicacion: QApplication,
) -> None:
    """Comprueba visibilidad nativa de las cuatro ventanas fuera de partida."""

    class Persistencia:
        def save(self, settings):
            self.saved = dict(settings)

    overlay = OverlayWindow({}, settings_service=Persistencia(), settings={})
    overlay.show_demo_overlays()
    aplicacion.processEvents()
    assert set(overlay.panels) == {"alerts", "gold", "threat", "purchase"}
    assert all(panel.isVisible() for panel in overlay.panels.values())
    assert all(not panel.grab().isNull() for panel in overlay.panels.values())
    assert overlay.in_game is False
    overlay.end_demo_overlays()
    aplicacion.processEvents()
    assert not any(panel.isVisible() for panel in overlay.panels.values())
    assert overlay.in_game is False
    overlay.close()


def test_live_match_visibility_survives_edit_mode_transitions(
    aplicacion: QApplication,
) -> None:
    """Mantiene los paneles activos al restaurar click-through tras editar."""

    class Persistencia:
        def save(self, settings):
            self.saved = dict(settings)

    overlay = OverlayWindow({}, settings_service=Persistencia(), settings={})
    overlay.update_snapshot(
        {"game_time": 10, "game_mode": "CLASSIC", "local_player": {}, "all_players": []}
    )
    aplicacion.processEvents()
    assert overlay.in_game
    assert all(
        overlay.panels[key].isVisible() for key in ("gold", "threat", "purchase")
    )
    overlay.begin_editing("gold")
    overlay.end_editing()
    aplicacion.processEvents()
    assert overlay.panels["gold"].isVisible()
    assert overlay.panels["threat"].isVisible()
    assert overlay.panels["purchase"].isVisible()
    overlay.clear()
    aplicacion.processEvents()
    assert not any(panel.isVisible() for panel in overlay.panels.values())
    overlay.close()

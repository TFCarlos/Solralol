from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
)

from app.ui.home_dashboard import HomeDashboard


def test_home_dashboard_handles_empty_data_and_responsive_widths() -> None:
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    analytics = {
        "total": 0,
        "played": 0,
        "winrate": None,
        "hours": [],
        "weekdays": [],
        "peak_hour": None,
        "best_hour": None,
        "worst_hour": None,
        "lanes": [],
        "champions": [],
        "modes": [],
        "teammates": [],
        "matchups": [],
    }
    dashboard.set_dashboard_data(None, {"matches": []}, analytics, "League cerrado")

    for width, height in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dashboard.resize(width, height)
        dashboard.show()
        app.processEvents()
        assert dashboard.width() == width
        assert dashboard.history_status.text().startswith("0 partidas")
        assert dashboard.history_card.height() <= dashboard.history_card.maximumHeight()

    dashboard.close()


def test_dashboard_panels_do_not_overlap_at_target_desktop_sizes() -> None:
    """Comprueba reflujo y límites del historial en cuatro tamaños objetivo."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    matches = [
        {"stable_match_id": str(index), "result": "victory", "champion_name": "Briar"}
        for index in range(30)
    ]
    analytics = {
        "total": 30,
        "played": 30,
        "winrate": 60,
        "hours": [],
        "weekdays": [],
        "peak_hour": None,
        "best_hour": None,
        "worst_hour": None,
        "lanes": [("jungle", 30)],
        "champions": [("Briar", 30)],
        "classes": [],
        "modes": [("Normal", 30)],
        "teammates": [],
        "hardest_matchups": [
            {"champion_id": 122, "champion": "Darius", "games": 4, "winrate": 25},
            {"champion_id": 35, "champion": "Shaco", "games": 3, "winrate": 33},
        ],
        "matchups": [
            {"champion_id": 154, "champion": "Zac", "games": 4, "winrate": 75},
            {"champion_id": 8, "champion": "Vladimir", "games": 3, "winrate": 67},
        ],
    }
    dashboard.set_dashboard_data(None, {"matches": matches}, analytics, "Local")
    viewport = QScrollArea()
    viewport.setWidgetResizable(True)
    viewport.setWidget(dashboard)

    for width, height in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        viewport.resize(width, height)
        viewport.show()
        app.processEvents()
        history = dashboard.history_card.geometry()
        next_row = dashboard.teammates_card.geometry()
        assert history.height() > 350
        assert next_row.top() >= history.bottom() - 1
        difficult, favorable = dashboard.matchups_groups
        assert not difficult.geometry().intersects(favorable.geometry())
        matchup_rows = dashboard.insights_card.findChildren(QFrame, "homeMatchupRow")
        assert len(matchup_rows) == 4

    dashboard.close()
    viewport.close()


def test_history_consumes_viewport_height_without_pushing_bottom_cards() -> None:
    """Aumenta filas visibles al crecer la ventana y conserva el panel inferior."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    matches = [
        {"stable_match_id": str(index), "result": "victory", "champion_name": "Briar"}
        for index in range(30)
    ]
    dashboard.set_dashboard_data(
        None,
        {"matches": matches},
        {
            "total": 30,
            "played": 30,
            "lanes": [("jungle", 30)],
            "teammates": [],
            "matchups": [],
        },
        "Local",
    )
    viewport = QScrollArea()
    viewport.setWidgetResizable(True)
    viewport.setWidget(dashboard)
    viewport.resize(1600, 800)
    viewport.show()
    app.processEvents()
    altura_compacta = dashboard.history_card.height()
    compact_bottom = dashboard.teammates_card.geometry().bottom()
    viewport.resize(1600, 1100)
    app.processEvents()

    assert dashboard.history_card.height() > altura_compacta + 100
    assert dashboard.teammates_card.geometry().bottom() <= dashboard.height()
    assert compact_bottom <= dashboard.height()
    assert dashboard.history_scroll.verticalScrollBar().maximum() > 0
    dashboard.close()
    viewport.close()


def test_teammate_and_matchup_panels_render_distinct_structured_rows() -> None:
    """Presenta identidad, muestras y WR en filas independientes y legibles."""
    _app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    analytics = {
        "total": 20,
        "team_data_matches": 18,
        "opponent_data_matches": 16,
        "teammates": [
            {
                "name": "luxbox",
                "tag_line": "EUW",
                "games": 12,
                "winrate": 61,
                "winrate_delta": 17,
                "champion_name": "Briar",
            }
        ],
        "hardest_matchups": [
            {"champion_id": 122, "champion": "Darius", "games": 3, "winrate": 0}
        ],
        "matchups": [
            {"champion_id": 154, "champion": "Zac", "games": 4, "winrate": 75}
        ],
    }
    dashboard.set_dashboard_data(None, {"matches": []}, analytics, "Local")

    assert len(dashboard.teammates_card.findChildren(QFrame, "homeTeammateRow")) == 1
    assert len(dashboard.insights_card.findChildren(QFrame, "homeMatchupRow")) == 2
    assert "18/20" in " ".join(
        label.text() for label in dashboard.teammates_card.findChildren(QLabel)
    )
    assert "61% WR" in " ".join(
        label.text() for label in dashboard.teammates_card.findChildren(QLabel)
    )
    assert dashboard.teammates_card.findChild(
        QLabel, "homeTeammateDelta"
    ).toolTip() == (
        "Comparación entre tu winrate con este jugador y tu winrate sin él."
    )
    assert (
        dashboard.teammates_card.findChild(QFrame, "homeTeammateAvatar").findChild(
            QLabel, "homeTeammateAvatarImage"
        )
        is not None
    )
    dashboard.close()


def test_history_shows_exact_probable_ambiguous_team_and_unavailable_states() -> None:
    """Distingue rival fiable, probable, ambiguo con equipo y datos ausentes."""
    _app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    matches = [
        {
            "game_id": "exact",
            "champion_name": "Briar",
            "opponent_champion_name": "Zac",
            "opponent_resolution": {
                "champion_name": "Zac",
                "confidence": 1.0,
                "state": "exact",
            },
            "opponent_state": "exact",
        },
        {
            "game_id": "probable",
            "champion_name": "Briar",
            "opponent_champion_name": "Amumu",
            "opponent_resolution": {
                "champion_name": "Amumu",
                "confidence": 0.6,
                "state": "probable",
            },
            "opponent_state": "probable",
        },
        {
            "game_id": "ambiguous",
            "champion_name": "Briar",
            "opponent_state": "ambiguous",
            "enemy_team": [
                {"champion_name": "Zac"},
                {"champion_name": "Ahri"},
                {"champion_name": "Darius"},
                {"champion_name": "Jinx"},
                {"champion_name": "Nami"},
            ],
        },
        {
            "game_id": "unavailable",
            "champion_name": "Briar",
            "opponent_state": "unavailable",
        },
        {
            "game_id": "legacy",
            "champion_name": "Briar",
            "opponent_champion_id": 154,
            "opponent_champion_name": "Zac",
        },
    ]
    dashboard.set_dashboard_data(
        None,
        {"matches": matches},
        {"total": 4, "teammates": [], "matchups": []},
        "Local",
    )

    rows = dashboard.history_card.findChildren(QFrame, "savedGameRow")
    assert len(rows) == 5
    assert rows[0].findChild(QLabel, "homeOpponentName").text() == "Zac"
    probable = rows[1].findChild(QLabel, "savedGameMatchup")
    assert probable.text() == "VS probable"
    assert "Rival probable" in probable.toolTip()
    ambiguous = rows[2]
    assert len(ambiguous.findChildren(QLabel, "savedGameEnemyIcon")) == 5
    assert ambiguous.findChild(QLabel, "homeEnemyTeamOverflow").text() == "+2"
    unknown = rows[3].findChild(QLabel, "homeOpponentUnknown")
    assert unknown.text() == "—"
    assert unknown.toolTip() == (
        "No hay datos suficientes del equipo rival para esta partida."
    )
    assert rows[4].findChild(QLabel, "homeOpponentName").text() == "Zac"
    dashboard.close()


def test_collection_panel_keeps_progression_metrics_structured() -> None:
    """Presenta colección LCU como métricas, progreso y título activo."""
    _app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {"matches": []},
        {"total": 0, "teammates": [], "matchups": []},
        "Local",
        {
            "masteries": [{"champion_id": 233, "points": 189432}],
            "champions": {"owned_count": 249, "total_count": 251},
            "skins": {"owned_count": 262},
            "challenges": {"tier": "PLATINUM", "points": 12860, "count": 5},
            "titles": {"selected": "Absolute Unit"},
        },
    )

    progress = dashboard.collection_card.findChild(
        QProgressBar, "homeCollectionProgress"
    )
    assert progress.value() == 249
    assert progress.maximum() == 251
    assert "262" in " ".join(
        label.text() for label in dashboard.collection_card.findChildren(QLabel)
    )
    assert dashboard.collection_card.findChild(QLabel, "homeChallengeTier").text() == (
        "PLATINUM"
    )
    assert dashboard.collection_card.findChild(QLabel, "homeActiveTitle").text() == (
        "Absolute Unit"
    )
    dashboard.close()


def test_matchups_render_on_first_show_at_all_desktop_sizes() -> None:
    """Comprueba que los grupos y filas aparecen sin depender de un resize."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    dashboard.resize(0, 0)
    analytics = {
        "total": 12,
        "opponent_exact": 12,
        "opponent_probable": 0,
        "opponent_ambiguous": 0,
        "opponent_unavailable": 0,
        "hardest_matchups": [
            {"champion": "Darius", "games": 4, "winrate": 25},
            {"champion": "Jax", "games": 3, "winrate": 33},
        ],
        "matchups": [
            {"champion": "Zac", "games": 4, "winrate": 75},
            {"champion": "Vladimir", "games": 3, "winrate": 67},
        ],
        "teammates": [],
    }
    matches = [
        {"stable_match_id": str(index), "result": "victory"} for index in range(12)
    ]
    dashboard.set_dashboard_data(None, {"matches": matches}, analytics, "Local")
    viewport = QScrollArea()
    viewport.setWidgetResizable(True)
    viewport.setWidget(dashboard)

    for width, height in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        viewport.resize(width, height)
        viewport.show()
        app.processEvents()
        rows = dashboard.insights_card.findChildren(QFrame, "homeMatchupRow")
        assert len(rows) == 4
        assert all(
            row.isVisible() and row.width() > 0 and row.height() >= 52 for row in rows
        )
        assert all(
            dashboard.matchups_grid_host.rect().contains(group.geometry())
            for group in dashboard.matchups_groups
        )
        counts_before = tuple(
            group.findChildren(QFrame, "homeMatchupRow").__len__()
            for group in dashboard.matchups_groups
        )
        dashboard.resize(width - 80, height)
        app.processEvents()
        counts_after = tuple(
            group.findChildren(QFrame, "homeMatchupRow").__len__()
            for group in dashboard.matchups_groups
        )
        assert counts_after == counts_before == (2, 2)
        viewport.hide()

    dashboard.close()
    viewport.close()


def test_async_matchup_data_replaces_initial_empty_grid_without_resize() -> None:
    """Verifica la transición de carga vacía a rankings al mismo ancho."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    viewport = QScrollArea()
    viewport.setWidgetResizable(True)
    viewport.setWidget(dashboard)
    viewport.resize(1600, 900)
    dashboard.set_dashboard_data(
        None,
        {"matches": []},
        {"total": 0, "teammates": [], "matchups": [], "hardest_matchups": []},
        "Cargando",
    )
    viewport.show()
    app.processEvents()
    dashboard.set_dashboard_data(
        None,
        {"matches": [{"stable_match_id": "1", "result": "victory"}]},
        {
            "total": 1,
            "teammates": [],
            "matchups": [{"champion": "Zac", "games": 3, "winrate": 67}],
            "hardest_matchups": [{"champion": "Darius", "games": 3, "winrate": 33}],
        },
        "Local",
    )
    app.processEvents()

    rows = dashboard.insights_card.findChildren(QFrame, "homeMatchupRow")
    assert len(rows) == 2
    assert all(row.isVisible() and row.width() > 0 and row.height() > 0 for row in rows)
    assert dashboard.matchups_grid.count() == 2

    dashboard.close()
    viewport.close()


def test_collection_ownership_labels_and_unavailable_state() -> None:
    """Explica propiedad, porcentaje, colección completa y falta de consulta."""
    _app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {"matches": []},
        {"total": 0, "teammates": [], "matchups": []},
        "Local",
        {"champions": {"owned_count": 250, "total_count": 251}},
    )
    textos = [label.text() for label in dashboard.collection_card.findChildren(QLabel)]
    assert "CAMPEONES EN PROPIEDAD" in textos
    assert "250 de 251 campeones" in textos
    assert "99,6% de la colección" in textos
    assert "Te falta 1 campeón para completar la colección." in textos
    dashboard.set_dashboard_data(
        None,
        {"matches": []},
        {"total": 0, "teammates": [], "matchups": []},
        "Local",
        {"champions": {"owned_count": 251, "total_count": 251}},
    )
    assert "Colección completa" in [
        label.text() for label in dashboard.collection_card.findChildren(QLabel)
    ]
    dashboard.set_dashboard_data(
        None,
        {"matches": []},
        {"total": 0, "teammates": [], "matchups": []},
        "Local",
        {"champions": None},
    )
    assert "No se pudo consultar la colección de campeones" in [
        label.text() for label in dashboard.collection_card.findChildren(QLabel)
    ]
    dashboard.close()


def test_home_dashboard_renders_history_in_bounded_batches() -> None:
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    matches = [
        {
            "stable_match_id": str(index),
            "result": "victory" if index % 2 else "defeat",
            "champion_name": "Briar",
            "lane": "jungle",
            "duration_seconds": 1800,
            "started_at": "2026-10-07T19:00:00+00:00",
        }
        for index in range(1000)
    ]
    dashboard.set_dashboard_data(
        {"gameName": "Jugador", "puuid": "test"},
        {"matches": matches},
        {
            "total": 1000,
            "played": 1000,
            "winrate": 50,
            "hours": [(19, 1000)],
            "weekdays": [(2, 1000)],
            "peak_hour": 19,
            "best_hour": None,
            "worst_hour": None,
            "lanes": [("jungle", 1000)],
            "champions": [("Briar", 1000)],
            "modes": [("CLASSIC", 1000)],
            "teammates": [],
            "matchups": [],
        },
        "League conectado",
    )
    app.processEvents()

    assert dashboard.match_rows.count() == 25
    assert dashboard.history_scroll.widget() is dashboard.history_content
    assert dashboard.playstyle_card.findChildren(QProgressBar)
    primera_fila = dashboard.match_rows.itemAt(0).widget()
    assert primera_fila.findChild(QLabel, "savedGameChampIcon") is not None
    dashboard._load_more()
    assert dashboard.match_rows.count() == 50
    primera_fila = dashboard.match_rows.itemAt(0).widget()
    dashboard.set_dashboard_data(
        {"gameName": "Jugador", "puuid": "test"},
        {"matches": matches},
        {
            "total": 1000,
            "played": 1000,
            "winrate": 50,
            "hours": [(19, 1000)],
            "weekdays": [(2, 1000)],
            "peak_hour": 19,
            "best_hour": None,
            "worst_hour": None,
            "lanes": [("jungle", 1000)],
            "champions": [("Briar", 1000)],
            "modes": [("CLASSIC", 1000)],
            "teammates": [],
            "matchups": [],
        },
        "Conectado, refresco de estado",
    )
    assert dashboard.match_rows.count() == 50
    assert dashboard.match_rows.itemAt(0).widget() is primera_fila
    dashboard.close()


def test_analyzable_badge_emits_saved_session_identifier() -> None:
    """Verifica que la insignia abre el identificador vinculado desde Home."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {
            "matches": [
                {
                    "stable_match_id": "42",
                    "result": "victory",
                    "champion_name": "Briar",
                    "performance_summary": {
                        "points": 671,
                        "global_rank": 6,
                        "award": "",
                        "version": 4,
                        "calibration_version": "2026.10",
                        "state": "POSTGAME_FINAL",
                    },
                    "analyzable": True,
                    "saved_match_link": {
                        "matched": True,
                        "saved_match_id": "session-42",
                        "confidence": 1.0,
                    },
                }
            ]
        },
        {"total": 1, "played": 1, "teammates": [], "matchups": []},
        "Local",
    )
    received: list[str] = []
    dashboard.saved_match_requested.connect(received.append)
    badge = dashboard.findChild(QPushButton, "homeAnalyzableBadge")
    assert badge is not None and badge.isEnabled()
    score = dashboard.findChild(QLabel, "homePerformanceScore")
    assert score is not None
    assert score.text() == "671p · 6º"

    badge.click()
    app.processEvents()

    assert received == ["session-42"]
    dashboard.close()


def test_home_score_and_analyzable_badges_fit_all_supported_viewports() -> None:
    """Mantiene puntuación y acceso visibles en resoluciones de escritorio."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {
            "matches": [
                {
                    "stable_match_id": "briar-1",
                    "game_id": "briar-1",
                    "result": "defeat",
                    "champion_name": "Briar",
                    "opponent_champion_name": "Naafiri",
                    "lane": "jungle",
                    "duration_seconds": 1971,
                    "kills": 12,
                    "deaths": 7,
                    "assists": 4,
                    "cs": 225,
                    "started_at": "2026-10-08T18:00:00+00:00",
                    "performance_summary": {
                        "points": 671,
                        "global_rank": 6,
                        "award": "",
                        "version": 4,
                        "calibration_version": "2026.10",
                        "state": "POSTGAME_FINAL",
                    },
                    "analyzable": True,
                    "saved_match_link": {
                        "matched": True,
                        "saved_match_id": "session-briar-1",
                        "confidence": 1.0,
                    },
                }
            ]
        },
        {"total": 1, "played": 1, "teammates": [], "matchups": []},
        "Historial sincronizado",
    )
    dashboard.show()
    app.processEvents()

    for width, height in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dashboard.resize(width, height)
        app.processEvents()
        score = dashboard.findChild(QLabel, "homePerformanceScore")
        badge = dashboard.findChild(QPushButton, "homeAnalyzableBadge")
        assert score is not None and score.isVisible()
        assert badge is not None and badge.isVisible() and badge.isEnabled()
        assert not score.geometry().intersects(badge.geometry())
        assert score.text() == "671p · 6º"

    dashboard.close()


def test_home_score_refresh_preserves_history_filter_and_scroll_position() -> None:
    """Actualiza BattleScore sin devolver la lista al principio ni limpiar filtros."""
    app = QApplication.instance() or QApplication([])
    dashboard = HomeDashboard()
    matches = [
        {
            "stable_match_id": str(index),
            "game_id": str(index),
            "result": "defeat",
            "champion_name": "Briar",
            "mode": "CLASSIC",
            "queue_id": 430,
            "started_at": f"2026-10-{(index % 28) + 1:02d}T18:00:00+00:00",
        }
        for index in range(60)
    ]
    dashboard.set_dashboard_data(
        None,
        {"matches": matches},
        {"total": 60, "played": 60, "teammates": [], "matchups": []},
        "Historial local",
    )
    dashboard.show()
    app.processEvents()
    dashboard.filter_combo.setCurrentIndex(dashboard.filter_combo.findData("normal"))
    app.processEvents()
    scrollbar = dashboard.history_scroll.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    app.processEvents()
    posicion = scrollbar.value()
    assert posicion > 0

    matches[0] = {
        **matches[0],
        "performance_summary": {
            "points": 671,
            "global_rank": 6,
            "award": "",
            "version": 4,
            "calibration_version": "2026.10",
            "state": "POSTGAME_FINAL",
        },
    }
    dashboard.set_dashboard_data(
        None,
        {"matches": matches, "last_sync": "2026-10-09T12:00:00+00:00"},
        {"total": 60, "played": 60, "teammates": [], "matchups": []},
        "Puntuaciones actualizadas",
    )
    app.processEvents()

    assert dashboard.filter_combo.currentData() == "normal"
    assert dashboard.history_scroll.verticalScrollBar().value() == posicion
    dashboard.close()

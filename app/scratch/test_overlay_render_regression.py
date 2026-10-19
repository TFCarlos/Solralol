"""Regresiones de renderizado, geometría y visibilidad de overlays Qt."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from _paths import DATA_DIR
import app.ui.overlay_window as overlay_module
from app.ui.overlay_window import (
    PANEL_KEYS,
    AlertsPanel,
    GoldPanel,
    OverlayWindow,
    PanelCompraRecomendada,
    ThreatPanel,
)
from app.ui.overlay_settings_dashboard import OverlaySettingsDashboard
from app.services.live_data_worker import LiveDataWorker


class _PersistenciaMemoria:
    """Persistencia efímera para aislar los ajustes personales en tests."""

    def load(self) -> dict:
        """Devuelve configuración vacía.

        Parámetros: ninguno.
        Retorno: diccionario vacío.
        """
        return {}

    def save(self, _settings: dict) -> None:
        """Descarta la configuración generada por las pruebas.

        Parámetros: documento temporal.
        Retorno: None; no escribe archivos.
        """
        return None


class OverlayRenderRegressionTest(unittest.TestCase):
    """Comprueba que los cuatro proxies renderizan y mantienen su geometría."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepara QApplication para las pruebas de widgets.

        Parámetros: clase de tests.
        Retorno: None; crea la aplicación Qt una sola vez.
        """
        cls.aplicacion = QApplication.instance() or QApplication([])

    def test_shadow_on_proxy_and_content_size_are_rendered(self) -> None:
        """Evita ocultar superficies embebidas y verifica pixeles Qt opacos.

        Parámetros: instancia de unittest.
        Retorno: None; falla si cualquier panel queda transparente o recortado.
        """
        oro = GoldPanel({})
        oro.render(
            {
                "team": {"delta": 850},
                "lanes": [
                    {
                        "role": rol,
                        "ally": {"champion": "Garen", "gold": 3100},
                        "enemy": {"champion": "Darius", "gold": 2800},
                        "paired": True,
                        "delta": 300,
                    }
                    for rol in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
                ],
            }
        )
        alertas = AlertsPanel({})
        alertas.render(
            [
                {
                    "kind": "objective",
                    "key": "test-dragon",
                    "name": "Dragón en 45 s",
                    "remaining": 45,
                }
            ]
        )
        amenaza = ThreatPanel({})
        amenaza.render(
            {
                "strongest": {"champion": "Garen", "role": "TOP", "score": 1324},
                "weakest": {"champion": "Xin Zhao", "role": "JUNGLE", "score": 642},
            }
        )
        compra = PanelCompraRecomendada({})
        compra.render(
            "Gragas",
            [
                {"item_id": "3100", "name": "Perdición del liche", "score": 37.9},
                {"item_id": "4646", "name": "Sobrecarga tormentosa", "score": 23.9},
                {"item_id": "4645", "name": "Llamasombría", "score": 19.6},
            ],
        )
        paneles = (oro, alertas, amenaza, compra)
        for panel in paneles:
            panel._resize_logical_panel()
            panel.show()
        self.aplicacion.processEvents()
        try:
            for panel in paneles:
                self.assertIsNone(panel.card.graphicsEffect())
                self.assertIsNotNone(panel.proxy.graphicsEffect())
                self.assertEqual(panel.proxy.boundingRect().height(), panel.card.height())
                self.assertEqual(panel.height(), panel.card.height())
                imagen = panel.grab().toImage()
                self.assertLess(
                    imagen.pixelColor(0, 0).alpha(),
                    imagen.pixelColor(imagen.width() // 2, 0).alpha(),
                    panel.key,
                )
                opacos = sum(
                    imagen.pixelColor(x, y).alpha() > 0
                    for y in range(imagen.height())
                    for x in range(imagen.width())
                )
                self.assertGreater(opacos, 1000, panel.key)
            self.assertGreater(oro.height(), 64)
            self.assertGreater(compra.height(), 64)
        finally:
            for panel in paneles:
                panel.close()

    def test_opacity_is_clamped_and_restored_from_percentage(self) -> None:
        """Persiste el porcentaje como alfa Qt entre cero y uno.

        Parámetros: instancia de unittest.
        Retorno: None; comprueba escritura, carga y conversión de porcentaje.
        """
        ajustes = {"overlay_panel_opacity": {"gold": 73}}
        primero = OverlayWindow({}, _PersistenciaMemoria(), ajustes)
        self.assertEqual(primero.panel_opacity("gold"), 73)
        self.assertAlmostEqual(
            primero.panels["gold"].windowOpacity(), int(0.73 * 255) / 255
        )
        primero.set_panel_opacity("gold", 81)
        self.assertEqual(ajustes["overlay_panel_opacity"]["gold"], 81)
        self.assertAlmostEqual(
            primero.panels["gold"].windowOpacity(), int(0.81 * 255) / 255
        )
        primero.set_panel_opacity("gold", 300)
        self.assertAlmostEqual(primero.panels["gold"].windowOpacity(), 1.0)
        primero.close()

    def test_game_state_clickthrough_tab_and_recreation_lifecycle(self) -> None:
        """Mantiene instancias tras transiciones y aplica TAB y click-through.

        Parámetros: instancia de unittest.
        Retorno: None; valida los estados lógicos y flags Qt de cada panel.
        """
        ajustes = {
            "overlay_panels": {key: True for key in PANEL_KEYS},
            "overlay_tab_only": {key: False for key in PANEL_KEYS},
        }
        gestor = OverlayWindow({}, _PersistenciaMemoria(), ajustes)
        identidad = {key: id(panel) for key, panel in gestor.panels.items()}
        snapshot = {"game_time": 12, "local_player": {}, "all_players": []}
        gestor.update_snapshot(snapshot)
        self.aplicacion.processEvents()
        for key in ("gold", "threat", "purchase"):
            self.assertTrue(gestor.panels[key].isVisible())
        self.assertFalse(gestor.panels["alerts"].isVisible())
        gestor.set_panel_click_through("gold", True)
        self.assertTrue(
            gestor.panels["gold"].windowFlags()
            & Qt.WindowType.WindowTransparentForInput
        )
        self.assertTrue(gestor.panels["gold"].isVisible())
        gestor.set_panel_click_through("gold", False)
        gestor.set_tab_only("threat", True)
        self.assertFalse(gestor.panels["threat"].isVisible())
        gestor._on_tab_changed(True)
        self.assertTrue(gestor.panels["threat"].isVisible())
        gestor.clear()
        self.assertFalse(any(panel.isVisible() for panel in gestor.panels.values()))
        gestor.update_snapshot(snapshot)
        self.aplicacion.processEvents()
        for key, panel in gestor.panels.items():
            self.assertEqual(id(panel), identidad[key])
        gestor.close()

    def test_offscreen_panel_is_clamped_to_a_real_monitor(self) -> None:
        """Recupera una ventana guardada fuera de las pantallas conectadas.

        Parámetros: instancia de unittest.
        Retorno: None; verifica intersección con un monitor real.
        """
        panel = GoldPanel({})
        panel.move(-10000, -10000)
        OverlayWindow._clamp_panel_position(panel)
        pantalla = self.aplicacion.primaryScreen()
        self.assertIsNotNone(pantalla)
        self.assertTrue(pantalla.availableGeometry().intersects(panel.frameGeometry()))
        panel.close()

    def test_repeated_telemetry_does_not_repaint_stable_panel_content(self) -> None:
        """Evita reconstrucciones cuando la telemetría visible no cambia.

        Parámetros: instancia de unittest.
        Retorno: None; verifica que las rutas de actualización salen por diff.
        """
        oro = GoldPanel({})
        informe = {
            "team": {"delta": 850},
            "lanes": [{"role": "TOP", "ally": {"champion": "Garen", "gold": 3000}}],
        }
        oro.render(informe)
        with patch.object(oro, "_render_lanes", side_effect=AssertionError):
            oro.render(informe)

        amenaza = ThreatPanel({})
        ranking = {"strongest": {"champion": "Garen", "role": "TOP", "score": 192}}
        amenaza.render(ranking)
        with patch.object(amenaza, "_render_row", side_effect=AssertionError):
            amenaza.render(ranking)
        oro.close()
        amenaza.close()

    def test_stable_snapshots_do_not_toggle_or_raise_overlay_windows(self) -> None:
        """Mantiene ventanas y stacking sin operaciones repetidas por sondeo.

        Parámetros: instancia de unittest.
        Retorno: None; comprueba que snapshots iguales no ocultan ni elevan paneles.
        """
        ajustes = {"overlay_panels": {key: True for key in PANEL_KEYS}}
        gestor = OverlayWindow({}, _PersistenciaMemoria(), ajustes)
        snapshot = {"game_time": 18, "local_player": {}, "all_players": []}
        gestor.update_snapshot(snapshot)
        self.aplicacion.processEvents()
        espias = {}
        for clave, panel in gestor.panels.items():
            patchers = tuple(
                patch.object(panel, nombre, wraps=getattr(panel, nombre))
                for nombre in ("show", "hide", "raise_")
            )
            espias[clave] = (patchers, tuple(espia.start() for espia in patchers))
        try:
            for _ in range(8):
                gestor.update_snapshot(snapshot)
            self.aplicacion.processEvents()
            for clave, (_, controles) in espias.items():
                for control in controles:
                    self.assertEqual(control.call_count, 0, f"{clave}.{control}")
        finally:
            for patchers, _ in espias.values():
                for espia in patchers:
                    espia.stop()
            gestor.close()

    def test_failed_live_poll_does_not_end_match_before_grace_threshold(self) -> None:
        """Conserva el estado LIVE durante fallos puntuales de telemetría.

        Parámetros: instancia de unittest.
        Retorno: None; cierra la sesión solo tras el umbral de fallos seguidos.
        """
        worker = LiveDataWorker({})
        worker.was_in_game = True
        worker.game_service.get_game_snapshot = lambda: None
        worker._finish_tracking = Mock()
        finales: list[bool] = []
        worker.game_ended.connect(lambda: finales.append(True))

        worker.read_snapshot()
        worker.read_snapshot()
        self.assertTrue(worker.was_in_game)
        self.assertEqual(finales, [])
        worker.read_snapshot()

        self.assertFalse(worker.was_in_game)
        self.assertEqual(finales, [True])
        worker._finish_tracking.assert_called_once_with()

    def test_identical_click_through_setting_does_not_hide_window(self) -> None:
        """No oculta ni recrea la ventana al reaplicar la misma opción.

        Parámetros: instancia de unittest.
        Retorno: None; confirma que flags duplicados no alteran visibilidad.
        """
        panel = GoldPanel({})
        panel.show()
        self.aplicacion.processEvents()
        with patch.object(panel, "hide", wraps=panel.hide) as ocultar:
            panel.set_click_through(False)
            self.assertEqual(ocultar.call_count, 0)
            panel.set_click_through(True)
            self.assertEqual(ocultar.call_count, 1)
            panel.set_click_through(True)
            self.assertEqual(ocultar.call_count, 1)
        self.assertTrue(panel.isVisible())
        panel.close()

    def test_settings_previews_show_the_shared_overlay_renderers(self) -> None:
        """Comprueba que las tarjetas de Ajustes no queden como fondos vacíos.

        Parámetros: instancia de unittest.
        Retorno: None; valida píxeles diversos de cada preview real.
        """
        gestor = OverlayWindow({}, _PersistenciaMemoria(), {})
        dashboard = OverlaySettingsDashboard(gestor, {})
        dashboard.show()
        self.aplicacion.processEvents()
        try:
            for clave, vista in dashboard.previews.items():
                imagen = vista.grab().toImage()
                colores = {
                    imagen.pixelColor(x, y).rgba()
                    for y in range(0, imagen.height(), 8)
                    for x in range(0, imagen.width(), 8)
                }
                self.assertGreater(len(colores), 8, clave)
        finally:
            dashboard.close()
            gestor.close()

    def test_practice_tool_overlay_uses_live_session_recommendations(self) -> None:
        """Muestra en el overlay de práctica la lista del motor LIVE compartido.

        Parámetros: instancia de unittest.
        Retorno: None; valida recomendaciones reales y su presentación en el panel.
        """
        catalogo = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        jugadores = {
            "local": {
                "player_key": "local",
                "team": "ORDER",
                "side": "ally",
                "role": "mid",
                "champion_name": "Zed",
                "items": ["1055", "3006"],
                "current_gold": 1300,
                "kills": 2,
                "deaths": 1,
                "assists": 3,
                "level": 8,
            }
        }
        for indice, (campeon, rol) in enumerate(
            zip(
                ("Aatrox", "Lee Sin", "Ahri", "Jinx", "Nautilus"),
                ("top", "jungle", "mid", "bot", "support"),
            )
        ):
            jugadores[f"enemy-{indice}"] = {
                "player_key": f"enemy-{indice}",
                "team": "CHAOS",
                "side": "enemy",
                "role": rol,
                "champion_name": campeon,
                "items": ["3036", "3075"] if indice == 0 else ["3006"],
                "kills": 4 if indice == 0 else 1,
                "deaths": 1,
                "assists": 2,
                "level": 9,
            }
        sesion = {
            "game_mode": "PRACTICETOOL",
            "duration": 900,
            "local_team": "ORDER",
            "local_player_key": "local",
            "champion_name": "Zed",
            "players": jugadores,
            "snapshots": [{"time": 900, "players": jugadores}],
        }

        def ejecutar_worker(funcion, *, on_finished, token):
            resultado = funcion()
            on_finished(token, resultado, None)
            return None

        worker_original = overlay_module.run_async
        overlay_module.run_async = ejecutar_worker
        gestor = OverlayWindow(catalogo, _PersistenciaMemoria(), {})
        try:
            gestor.update_recommendation_session(sesion)
            gestor.update_snapshot(
                {
                    "game_time": 900,
                    "game_mode": "PRACTICETOOL",
                    "local_team": "ORDER",
                    "local_player": {
                        "championName": "Zed",
                        "team": "ORDER",
                        "items": [{"itemID": "1055"}, {"itemID": "3006"}],
                    },
                    "all_players": [],
                }
            )
            self.aplicacion.processEvents()
            panel = gestor.panels["purchase"]
            visibles = [
                card
                for card in panel.cards
                if not card["widget"].isHidden()
            ]
            self.assertGreaterEqual(len(visibles), 2)
            self.assertTrue(panel.status_label.isHidden())
            nombres = [card["name"].toolTip() for card in visibles]
            self.assertTrue(any(nombres))
        finally:
            overlay_module.run_async = worker_original
            gestor.close()

    def test_identical_purchase_models_keep_widgets_icons_and_geometry(self) -> None:
        """Comprueba que snapshots idénticos no repinten ni reconstruyan compras.

        Parámetros: instancia de unittest.
        Retorno: None; compara modelo, widgets, iconos y geometría tras 500 renders.
        """
        panel = PanelCompraRecomendada({})
        recomendaciones = [
            {"item_id": str(3000 + indice), "name": f"Objeto {indice}", "score": 30.0 - indice}
            for indice in range(3)
        ]
        panel.render("Zed", recomendaciones)
        self.aplicacion.processEvents()
        ids_widgets = tuple(id(card["widget"]) for card in panel.cards)
        ids_iconos = tuple(id(card["icon"]) for card in panel.cards)
        geometria = panel.geometry()
        cambios = panel.model_change_count
        iconos = patch.object(panel, "_set_item_icon", wraps=panel._set_item_icon)
        with iconos as cargar_icono:
            for _ in range(500):
                panel.render("Zed", recomendaciones)
        self.aplicacion.processEvents()
        self.assertEqual(panel.model_change_count, cambios)
        self.assertEqual(cargar_icono.call_count, 0)
        self.assertEqual(tuple(id(card["widget"]) for card in panel.cards), ids_widgets)
        self.assertEqual(tuple(id(card["icon"]) for card in panel.cards), ids_iconos)
        self.assertEqual(panel.geometry(), geometria)
        self.assertTrue(panel._showing_recommendations)

    def test_temporary_empty_and_stale_purchase_results_preserve_current_cards(self) -> None:
        """Conserva la lista válida si falla el cálculo o llega una generación vieja.

        Parámetros: instancia de unittest.
        Retorno: None; valida que solo el token vigente pueda sustituir el modelo.
        """
        gestor = OverlayWindow({}, _PersistenciaMemoria(), {})
        identidad = ("session-1", "Zed", "PRACTICETOOL")
        panel = gestor.panels["purchase"]
        recomendaciones = [
            {"item_id": str(3000 + indice), "name": f"Objeto {indice}", "score": 30.0 - indice}
            for indice in range(3)
        ]
        try:
            gestor._purchase_context = identidad
            gestor._purchase_recommendations = recomendaciones
            panel.render("Zed", recomendaciones)
            token = (2, identidad, ("current",))
            obsoleto = (1, identidad, ("old",))
            gestor._purchase_request_token = token
            ids_antes = panel._rendered_recommendations
            gestor._apply_purchase_recommendations(obsoleto, [], None)
            gestor._apply_purchase_recommendations(token, [], None)
            self.assertEqual(panel._rendered_recommendations, ids_antes)
            self.assertTrue(panel._showing_recommendations)
            self.assertTrue(panel.status_label.isHidden())
            self.assertEqual(gestor._purchase_recommendations, recomendaciones)
        finally:
            gestor.close()

    def test_incomplete_live_identity_does_not_hide_valid_purchase_cards(self) -> None:
        """Evita destellos de fallback si LIVE omite al jugador local un ciclo.

        Parámetros: instancia de unittest.
        Retorno: None; comprueba que un roster incompleto conserva tarjetas válidas.
        """
        gestor = OverlayWindow({}, _PersistenciaMemoria(), {})
        identidad = ("session-1", "Zed", "PRACTICETOOL")
        recomendaciones = [
            {"item_id": str(3000 + indice), "name": f"Objeto {indice}", "score": 30.0 - indice}
            for indice in range(3)
        ]
        panel = gestor.panels["purchase"]
        try:
            gestor._purchase_context = identidad
            gestor._purchase_recommendations = recomendaciones
            panel.render("Zed", recomendaciones)
            gestor._update_purchase_session(
                {"game_mode": "PRACTICETOOL", "players": {}, "local_player_key": "local"}
            )
            self.assertTrue(panel._showing_recommendations)
            self.assertTrue(panel.status_label.isHidden())
            self.assertEqual(len(panel._rendered_recommendations), 3)
        finally:
            gestor.close()

    def test_purchase_changes_update_slots_without_resizing_or_replacing_cards(self) -> None:
        """Actualiza puntuaciones e ítems dentro de los mismos tres slots.

        Parámetros: instancia de unittest.
        Retorno: None; valida identidad de widgets y geometría ante cambios reales.
        """
        panel = PanelCompraRecomendada({})
        base = [
            {"item_id": str(3000 + indice), "name": f"Objeto {indice}", "score": 30.0 - indice}
            for indice in range(3)
        ]
        panel.render("Zed", base)
        self.aplicacion.processEvents()
        ids_widgets = tuple(id(card["widget"]) for card in panel.cards)
        geometria = panel.geometry()
        cambio_puntuacion = [dict(item) for item in base]
        cambio_puntuacion[0]["score"] = 34.0
        panel.render("Zed", cambio_puntuacion)
        self.assertEqual(tuple(id(card["widget"]) for card in panel.cards), ids_widgets)
        self.assertEqual(panel.geometry(), geometria)
        self.assertEqual(panel.cards[0]["score"].text(), "34.0 · Sinergia")
        cambio_item = [dict(item) for item in cambio_puntuacion]
        cambio_item[1] = {"item_id": "7777", "name": "Objeto nuevo", "score": 20.0}
        panel.render("Zed", cambio_item)
        self.assertEqual(tuple(id(card["widget"]) for card in panel.cards), ids_widgets)
        self.assertEqual(panel.geometry(), geometria)
        self.assertEqual(panel.cards[1]["icon"].property("rendered_item_id"), "7777")


if __name__ == "__main__":
    unittest.main()

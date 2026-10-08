"""Pruebas del resumen general, logros especiales y comparación de equipos."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel

import app.services.servicio_puntuacion_rendimiento as puntuacion
import app.ui.live_match_analysis_dialog as live_ui
from app.services.servicio_puntuacion_rendimiento import (
    REFERENCIAS,
    VERSION_PUNTUACION,
    EntradaRendimientoJugador,
    clasificar_jugadores,
)
from app.ui.desglose_rendimiento_dialogo import DialogoDesgloseRendimiento
from app.ui.postgame_sidebar import PostgameSidebar
from app.ui.todos_rendimiento import (
    BarraMiniRendimiento,
    DistribucionComparativa,
    EtiquetaElidida,
    RetratoCampeon,
    TarjetaJugadorCompacta,
    VistaTodosRendimiento,
)


def _ranking_falso(monkeypatch, puntuaciones, modo="postgame"):
    """Clasifica diez resultados controlados para aislar cálculos de equipo."""
    categorias_base = {
        clave: {
            "final": 0,
            "reference": referencia,
            "completeness": 1.0,
            "submetrics": {
                "participacion": 1.0,
                "bajas_y_asistencias": 1.0,
                "eficiencia_combate": 1.0,
            }
            if clave == "combate"
            else {"metric": 1.0},
        }
        for clave, referencia in REFERENCIAS.items()
    }

    def puntuar(entrada, duracion, modo_actual):
        """Devuelve una ficha de puntuación con los puntos solicitados."""
        categorias = {clave: dict(valor) for clave, valor in categorias_base.items()}
        for clave, datos_categoria in categorias.items():
            datos_categoria["submetrics"] = dict(categorias_base[clave]["submetrics"])
        total = puntuaciones[entrada.id_participante]
        for clave, proporcion in zip(
            REFERENCIAS, (0.30, 0.15, 0.25, 0.15, 0.15), strict=True
        ):
            categorias[clave]["final"] = total * proporcion
        return {
            "participant_id": entrada.id_participante,
            "champion": entrada.campeon,
            "team": entrada.equipo,
            "role": entrada.rol,
            "version": VERSION_PUNTUACION,
            "total": puntuaciones[entrada.id_participante],
            "completeness": 1.0,
            "categories": categorias,
            "awards": [],
        }

    monkeypatch.setattr(puntuacion, "puntuar_jugador", puntuar)
    entradas = [
        EntradaRendimientoJugador(
            f"p{indice}", "Campeón", "azul" if indice < 5 else "rojo", "TOP", {}
        )
        for indice in range(10)
    ]
    return clasificar_jugadores(entradas, 1800, "azul", modo)


def test_logro_faker_usa_umbral_estricto_y_admite_varios(monkeypatch):
    """El umbral es >1000, sin depender de los premios MVP/SVP."""
    ranking = _ranking_falso(
        monkeypatch,
        {
            f"p{i}": value
            for i, value in enumerate((999, 1000, 1001, 1200, 1100, 1, 2, 3, 4, 5))
        },
    )
    jugadores = ranking["by_id"]
    assert jugadores["p0"]["faker_unlocked"] is False
    assert jugadores["p1"]["faker_unlocked"] is False
    assert jugadores["p2"]["faker_unlocked"] is True
    assert jugadores["p3"]["faker_unlocked"] is True
    assert jugadores["p2"]["awards"] == []
    assert jugadores["p2"]["faker_provisional"] is False


def test_promedios_de_equipo_y_logro_t1_superan_1000(monkeypatch):
    """Los equipos promedian cinco jugadores y activan el logro en postpartida."""
    valores = {
        **{f"p{i}": 1001 for i in range(5)},
        **{f"p{i}": 800 for i in range(5, 10)},
    }
    ranking = _ranking_falso(monkeypatch, valores)
    azul = ranking["teams"]["azul"]
    rojo = ranking["teams"]["rojo"]
    assert azul["score"] == 1001
    assert rojo["score"] == 800
    assert azul["t1_unlocked"] is True
    assert rojo["t1_unlocked"] is False
    assert azul["result"] == "victoria"
    assert sum(azul["categories"].values()) == azul["score"]


def test_ambos_equipos_pueden_desbloquear_t1(monkeypatch):
    """El logro de equipo es independiente de victoria y derrota."""
    ranking = _ranking_falso(monkeypatch, {f"p{i}": 1100 + i for i in range(10)})
    assert all(equipo["t1_unlocked"] for equipo in ranking["teams"].values())
    assert ranking["teams"]["azul"]["result"] == "victoria"
    assert ranking["teams"]["rojo"]["result"] == "derrota"


def test_tarjeta_muestra_sv_p_en_tercer_puesto_global(monkeypatch):
    """La tarjeta conserva la posición global y el premio del motor común."""
    app = QApplication.instance() or QApplication([])
    valores = {f"p{i}": 400 for i in range(10)}
    valores.update({"p0": 1300, "p1": 1200, "p5": 1100})
    ranking = _ranking_falso(monkeypatch, valores)
    assert ranking["by_id"]["p5"]["global_rank"] == 3
    assert ranking["by_id"]["p5"]["awards"] == ["SVP"]
    jugador = {
        "champion_name": "Braum",
        "riot_id": "Support#EUW",
        "role": "UTILITY",
        "team": "rojo",
    }
    tarjeta = TarjetaJugadorCompacta(
        jugador, ranking["by_id"]["p5"], None, lambda _key: None, False, {}, {}
    )
    assert tarjeta.findChild(QLabel, "allPlayerRank").text() == "3º"
    assert "SVP" in tarjeta.findChild(QLabel, "allPlayerAward").text()
    tarjeta.close()
    app.processEvents()


def test_t1_no_se_desbloquea_en_1000_y_sin_diez_participantes(monkeypatch):
    """El logro exige promedio estricto y comparación de dos equipos completos."""
    ranking = _ranking_falso(monkeypatch, {f"p{i}": 1000 for i in range(10)})
    assert all(not equipo["t1_unlocked"] for equipo in ranking["teams"].values())


def test_vista_muestra_diez_tarjetas_por_equipo_y_barras(monkeypatch):
    """La página representa tarjetas, valores por encima de referencia y grupos."""
    app = QApplication.instance() or QApplication([])
    ranking = _ranking_falso(monkeypatch, {f"p{i}": 1100 - i * 10 for i in range(10)})
    jugadores = {
        f"p{i}": {
            "champion_name": f"Campeón {i}",
            "riot_id": f"Cuenta{i}#EUW",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[i % 5],
            "team": "azul" if i < 5 else "rojo",
            "stats": {"kills": i, "deaths": 2, "assists": 5},
        }
        for i in range(10)
    }
    for i in range(10):
        ranking["by_id"][f"p{i}"]["riot_id"] = f"Cuenta{i}#EUW"
    llamados = []
    vista = VistaTodosRendimiento(
        {"players": jugadores, "local_team": "azul"}, ranking, None, llamados.append
    )
    vista.resize(1600, 900)
    vista.show()
    app.processEvents()
    tarjetas = vista.findChildren(TarjetaJugadorCompacta)
    assert len(tarjetas) == 10
    assert [len(grupo._jugadores) for grupo in vista.grupos] == [5, 5]
    assert len(vista.findChildren(BarraMiniRendimiento)) == 60
    cuenta = vista.findChild(EtiquetaElidida)
    assert cuenta is not None and cuenta.toolTip() == "Cuenta0#EUW"
    assert cuenta.text() == "Cuenta0#EUW" or cuenta.text().endswith("…")
    assert len(vista.findChildren(QLabel, "specialPerformanceAchievement")) >= 12
    assert "110%" in [label.text() for label in vista.findChildren(QLabel)]
    tarjeta = next(card for card in tarjetas if card.participant_id == "p7")
    QTest.mouseClick(tarjeta, Qt.MouseButton.LeftButton)
    assert llamados == ["p7"]
    vista.close()


def test_tarjetas_se_adaptan_a_los_cuatro_tamanos_de_escritorio(monkeypatch):
    """Las cinco tarjetas caben en una fila en los anchos de escritorio pedidos."""
    app = QApplication.instance() or QApplication([])
    ranking = _ranking_falso(monkeypatch, {f"p{i}": 500 for i in range(10)})
    jugadores = {
        f"p{i}": {
            "champion_name": f"Campeón {i}",
            "riot_id": "CuentaConUnNombreMuyLargo#EUW" if i == 0 else f"Cuenta{i}#EUW",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[i % 5],
            "team": "azul" if i < 5 else "rojo",
        }
        for i in range(10)
    }
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        vista = VistaTodosRendimiento(
            {"players": jugadores, "local_team": "azul"},
            ranking,
            None,
            lambda _key: None,
        )
        vista.resize(ancho, alto)
        vista.show()
        app.processEvents()
        for grupo in vista.grupos:
            assert grupo._grid.columnCount() == 5
            posiciones = [grupo._grid.getItemPosition(i) for i in range(1, 6)]
            assert [posicion[1] for posicion in posiciones] == list(range(5))
            assert all(grupo._jugadores[i].width() >= 180 for i in range(5))
        cuentas = vista.findChildren(EtiquetaElidida)
        assert any(
            cuenta.toolTip() == "CuentaConUnNombreMuyLargo#EUW" for cuenta in cuentas
        )
        assert all(
            cuenta.text() == "CuentaConUnNombreMuyLargo#EUW"
            or cuenta.text().endswith("…")
            for cuenta in cuentas
            if cuenta.toolTip() == "CuentaConUnNombreMuyLargo#EUW"
        )
        vista.close()


def test_logro_faker_aparece_en_el_desglose_detallado():
    """La ficha detallada distingue el logro especial del resto de logros."""
    app = QApplication.instance() or QApplication([])
    entrada = EntradaRendimientoJugador(
        "jugador",
        "Campeón",
        "azul",
        "TOP",
        {"kills": 1, "deaths": 0, "assists": 2, "team_kills": 3},
    )
    resultado = puntuacion.puntuar_jugador(entrada, 1800)
    resultado.update({"faker_unlocked": True, "faker_provisional": False})
    dialogo = DialogoDesgloseRendimiento(resultado)
    insignia = dialogo.findChild(QLabel, "specialPerformanceAchievement")
    assert insignia is not None
    assert insignia.text() == "★ ¿Faker?"
    dialogo.close()
    app.processEvents()


def test_barra_redondeada_muestra_overflow_y_tooltip_real():
    """La barra pinta el excedente dentro del track y explica el valor exacto."""
    app = QApplication.instance() or QApplication([])
    barra = BarraMiniRendimiento("objetivos", 298, 250, 1.0)
    barra.resize(160, 9)
    barra.show()
    app.processEvents()
    imagen = barra.grab().toImage()
    assert abs(barra.porcentaje - 119.2) < 0.001
    assert "298.0 / 250 puntos" in barra.toolTip()
    assert "119.2%" in barra.toolTip()
    assert imagen.pixelColor(80, 4) == QColor("#829bb6")
    assert imagen.pixelColor(157, 4) == QColor("#d0bb7b")
    barra.close()
    app.processEvents()
    no_disponible = BarraMiniRendimiento("vision", None, 150, None)
    assert no_disponible.porcentaje is None
    assert "no disponibles" in no_disponible.toolTip()


def test_retrato_recorta_icono_en_esquinas_redondeadas():
    """El marco evita que el retrato sobresalga de sus esquinas suaves."""
    app = QApplication.instance() or QApplication([])
    retrato = RetratoCampeon("")
    imagen_fuente = QPixmap(72, 72)
    imagen_fuente.fill(QColor("#ff0000"))
    retrato.setPixmap(imagen_fuente)
    retrato.show()
    app.processEvents()
    imagen = retrato.grab().toImage()
    assert imagen.pixelColor(27, 27) == QColor("#ff0000")
    assert imagen.pixelColor(1, 1) != QColor("#ff0000")
    retrato.close()
    app.processEvents()


def test_comparacion_de_equipos_se_apila_y_se_recoloca_al_redimensionar(
    monkeypatch,
):
    """Los paneles simétricos evitan solapamiento en un ancho reducido."""
    app = QApplication.instance() or QApplication([])
    ranking = _ranking_falso(monkeypatch, {f"p{i}": 800 + i * 20 for i in range(10)})
    jugadores = {
        f"p{i}": {
            "champion_name": f"Campeón {i}",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[i % 5],
            "team": "azul" if i < 5 else "rojo",
        }
        for i in range(10)
    }
    vista = VistaTodosRendimiento(
        {"players": jugadores, "local_team": "azul"}, ranking, None, lambda _key: None
    )
    vista.resize(820, 430)
    vista.show()
    app.processEvents()
    distribucion = vista.findChild(DistribucionComparativa)
    assert distribucion is not None and distribucion._colocado is True
    assert len(vista.findChildren(QFrame, "teamPerformancePanel")) == 2
    assert len(vista.findChildren(QLabel, "teamComparisonVs")) == 1
    assert {
        label.text() for label in vista.findChildren(QLabel, "teamMatchResult")
    } == {
        "VICTORIA",
        "DERROTA",
    }
    izquierdo, divisor, derecho = distribucion._paneles
    assert izquierdo.geometry().bottom() < divisor.geometry().top()
    assert divisor.geometry().bottom() < derecho.geometry().top()
    assert vista.scroll.verticalScrollBar().maximum() > 0
    deltas = vista.findChildren(QLabel, "teamCategoryAdvantage")
    assert any(delta.text() == "+30" for delta in deltas)
    assert any(delta.property("advantage") == "behind" for delta in deltas)
    assert any(
        isinstance(barra, BarraMiniRendimiento)
        and barra.referencia == REFERENCIAS[barra.categoria]
        for barra in vista.findChildren(BarraMiniRendimiento)
    )
    vista.resize(1200, 600)
    app.processEvents()
    assert distribucion._colocado is False
    assert izquierdo.geometry().right() < derecho.geometry().left()
    vista.close()
    app.processEvents()


class _AssetsFalsos:
    """Proporciona el contrato mínimo de retratos para el diálogo de prueba."""

    version = "prueba"

    def champion_url(self, champion):
        """Devuelve una URL vacía para usar el fallback del retrato."""
        return ""

    def set_label_image(self, label, *args, **kwargs):
        """Deja visible el fallback de texto del retrato."""


def test_navegacion_todos_y_click_abre_desglose_correcto(monkeypatch):
    """El botón Todos abre la vista y conserva el identificador clicado."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        live_ui.LiveMatchAnalysisDialog, "_prepare_session", lambda _self: None
    )
    jugadores = {
        f"p{i}": {
            "champion_name": f"Campeón {i}",
            "riot_id": f"Cuenta{i}#EUW",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[i % 5],
            "team": "azul" if i < 5 else "rojo",
        }
        for i in range(10)
    }
    dialogo = live_ui.LiveMatchAnalysisDialog(
        {"players": jugadores, "local_team": "azul", "duration": 1800},
        _AssetsFalsos(),
        {},
    )
    botones = dialogo.findChildren(type(dialogo.role_buttons["UTILITY"]))
    assert any(boton.text() == "TODOS" for boton in botones)
    dialogo.all_players_button.click()
    assert dialogo.current_view == "all_players"
    assert len(dialogo._all_players_page.findChildren(TarjetaJugadorCompacta)) == 10
    dialogos = []

    def ejecutar(dialogo_actual):
        """Registra el diálogo de desglose sin abrir un loop modal."""
        dialogos.append(dialogo_actual)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", ejecutar)
    tarjeta = next(
        card
        for card in dialogo._all_players_page.findChildren(TarjetaJugadorCompacta)
        if card.participant_id == "p8"
    )
    QTest.mouseClick(tarjeta, Qt.MouseButton.LeftButton)
    assert dialogos[0].resultado["participant_id"] == "p8"
    assert dialogos[0].resultado["riot_id"] == "Cuenta8#EUW"
    tarjeta.setFocus()
    QTest.keyClick(tarjeta, Qt.Key.Key_Return)
    assert dialogos[1].resultado["participant_id"] == "p8"
    dialogo.show_role("TOP")
    assert dialogo.current_view == "role"
    dialogo.close()
    app.processEvents()


def test_hover_no_cambia_tamano_y_tarjeta_admite_foco_de_teclado():
    """El estado hover mantiene el layout y expone la tarjeta al teclado."""
    app = QApplication.instance() or QApplication([])
    resultado = puntuacion.puntuar_jugador(
        EntradaRendimientoJugador("p", "Braum", "azul", "UTILITY", {}), 1800
    )
    resultado.update({"global_rank": 1, "total": 700, "categories": {}})
    abiertos = []
    tarjeta = TarjetaJugadorCompacta(
        {"champion_name": "Braum", "riot_id": "Cuenta#EUW", "team": "azul"},
        resultado,
        None,
        abiertos.append,
        True,
        {},
        {},
    )
    tarjeta.resize(300, tarjeta.sizeHint().height())
    tarjeta.show()
    app.processEvents()
    tamano = tarjeta.size()
    QTest.mouseMove(tarjeta, tarjeta.rect().center())
    app.processEvents()
    assert tarjeta.size() == tamano
    assert tarjeta.focusPolicy() == Qt.FocusPolicy.StrongFocus
    tarjeta.setFocus()
    QTest.keyClick(tarjeta, Qt.Key.Key_Space)
    assert abiertos == ["p"]
    tarjeta.close()
    app.processEvents()


def test_resumen_de_equipo_se_guarda_en_scoring_del_partido(monkeypatch):
    """El Saved Match conserva medias y logros del modelo de puntuación."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    jugadores = {
        f"p{i}": {
            "champion_name": f"Campeón {i}",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[i % 5],
            "team": "azul" if i < 5 else "rojo",
            "win": i < 5,
        }
        for i in range(10)
    }
    puntos = {
        f"p{i}": {"kills": 2, "deaths": 1, "assists": 3, "cs": 100, "level": 14}
        for i in range(10)
    }
    sesion = {
        "players": jugadores,
        "snapshots": [{"time": 1800, "players": puntos}],
        "duration": 1800,
        "winning_team": "azul",
        "postgame": True,
        "local_player_key": "p0",
    }
    sidebar = PostgameSidebar(sesion)
    persistido = sesion["performance_scoring"]
    assert persistido["version"] == VERSION_PUNTUACION
    assert set(persistido["teams"]) == {"azul", "rojo"}
    assert all("t1_unlocked" in equipo for equipo in persistido["teams"].values())
    sidebar.close()
    app.processEvents()

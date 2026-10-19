"""Regresiones visuales de iconos y visor de notas de parche."""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton, QWidget

from app.ui.estilo_global import ESTILO_GLOBAL
from app.ui.meta_page import (
    DialogoImagenParche,
    ImagenNotaInteractiva,
    ImagenParche,
    PaginaMeta,
)


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Crea una única aplicación Qt para las pruebas de widgets Meta."""
    return QApplication.instance() or QApplication([])


class RecursosFalsos:
    """Expone URLs y captura las solicitudes de icono del encabezado."""

    def __init__(self) -> None:
        self.solicitudes: list[tuple[Any, ...]] = []

    def item_url(self, item_id: int) -> str:
        """Devuelve la URL sintética de un objeto."""
        return f"https://assets.test/item/{item_id}.png"

    def champion_ability_url(self, champion: str, slot: str) -> str:
        """Devuelve la URL sintética de una habilidad."""
        return f"https://assets.test/{champion}/{slot}.png"

    def champion_url(self, champion: str) -> str:
        """Devuelve la URL sintética del retrato de campeón."""
        return f"https://assets.test/{champion}.png"

    def set_label_image(self, *args: Any, **kwargs: Any) -> None:
        """Registra una solicitud de recurso sin iniciar red."""
        self.solicitudes.append((*args, kwargs))


def test_iconos_de_objeto_y_habilidad_se_solicitan_para_el_encabezado(
    aplicacion: QApplication,
) -> None:
    """Conserva la referencia al objeto y al slot de habilidad al pintar nodos."""
    pagina = PaginaMeta.__new__(PaginaMeta)
    QWidget.__init__(pagina)
    pagina.assets = RecursosFalsos()

    objeto = pagina._crear_icono_nota({"kind": "item", "item_id": "3073"})
    habilidad = pagina._crear_icono_nota(
        {"kind": "detail", "champion_id": "Ambessa", "ability_slot": "passive"}
    )

    assert objeto is not None and habilidad is not None
    assert isinstance(objeto, QLabel) and isinstance(habilidad, QLabel)
    assert not isinstance(objeto, ImagenNotaInteractiva)
    assert not isinstance(habilidad, ImagenNotaInteractiva)
    assert objeto.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert habilidad.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert objeto.objectName() == "patchNoteIconFallback"
    assert len(pagina.assets.solicitudes) == 2
    assert pagina.assets.solicitudes[0][1] == "https://assets.test/item/3073.png"
    assert pagina.assets.solicitudes[1][1] == "https://assets.test/Ambessa/passive.png"


def test_imagen_destacada_abre_dialogo_grande_al_hacer_clic(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abre el visor con la imagen original al pulsar la miniatura destacada."""
    recibidas: list[QPixmap] = []

    def abrir(visor: DialogoImagenParche) -> int:
        """Captura el diálogo en lugar de bloquear la prueba con su modalidad."""
        recibidas.append(visor._imagen_original)
        return 0

    monkeypatch.setattr(DialogoImagenParche, "exec", abrir)
    vista = ImagenParche(QPixmap(1200, 675))
    vista.resize(500, 260)
    vista.show()
    QTest.mouseClick(vista, Qt.MouseButton.LeftButton)

    assert len(recibidas) == 1
    assert recibidas[0].size().width() == 1200
    assert vista.cursor().shape() == Qt.CursorShape.PointingHandCursor
    vista.close()


def test_dialogo_escala_al_area_visible_y_admite_cierre_por_boton(
    aplicacion: QApplication,
) -> None:
    """Mantiene la proporción de la imagen grande en el tamaño actual del visor."""
    visor = DialogoImagenParche(QPixmap(1600, 900))
    visor.resize(900, 600)
    visor.show()
    aplicacion.processEvents()
    imagen = visor.imagen.pixmap()

    assert imagen is not None and not imagen.isNull()
    assert abs(imagen.width() / imagen.height() - 16 / 9) < 0.02
    visor.findChild(QPushButton).click()
    assert not visor.isVisible()
    visor.close()


def test_widgets_de_imagen_no_generan_advertencias_qss_repetidas(
    aplicacion: QApplication,
) -> None:
    """Construye/actualiza la jerarquía con tema heredado y captura avisos Qt."""
    avisos: list[str] = []
    tema_anterior = aplicacion.styleSheet()
    aplicacion.setStyleSheet(ESTILO_GLOBAL)

    def capturar(tipo: object, contexto: object, mensaje: str) -> None:
        if "could not parse stylesheet" in mensaje.casefold():
            avisos.append(mensaje)

    manejador_anterior = qInstallMessageHandler(capturar)
    try:
        pagina = PaginaMeta.__new__(PaginaMeta)
        QWidget.__init__(pagina)
        pagina.assets = RecursosFalsos()
        hero = ImagenParche(QPixmap(1200, 675), pagina)
        hero.resize(600, 300)
        media = [
            ImagenNotaInteractiva("", f"fallback {indice}", None, pagina)
            for indice in range(12)
        ]
        nodo = {
            "title": "Campeones",
            "kind": "section",
            "blocks": [],
            "children": [
                {
                    "title": "Ambessa",
                    "kind": "champion",
                    "champion_id": "Ambessa",
                    "blocks": [],
                    "children": [
                        {
                            "title": "Pasiva - Caza del perrodraco",
                            "kind": "detail",
                            "champion_id": "Ambessa",
                            "ability_slot": "passive",
                            "blocks": [],
                            "children": [],
                        }
                    ],
                },
                {
                    "title": "Experimento de hexarmadura",
                    "kind": "item",
                    "item_id": "3073",
                    "blocks": [],
                    "children": [],
                },
            ],
        }
        tarjeta = pagina._crear_acordeon(nodo, 0, "patch")
        pagina.resize(900, 700)
        tarjeta.resize(800, 500)
        tarjeta.show()
        hero.show()
        for miniatura in media:
            miniatura.show()
            miniatura.resize(180, 110)
            miniatura.repaint()
        botones = tarjeta.findChildren(QToolButton)
        boton_raiz = next(
            boton for boton in botones if boton.text().startswith("Campeones")
        )
        assert boton_raiz.x() < 30
        assert boton_raiz.width() < tarjeta.width() // 2
        for boton in botones:
            boton.setChecked(not boton.isChecked())
        aplicacion.processEvents()
        for miniatura in media:
            miniatura.setCursor(Qt.CursorShape.PointingHandCursor)
            miniatura.repaint()
        hero.resize(700, 350)
        aplicacion.processEvents()
    finally:
        qInstallMessageHandler(manejador_anterior)
        aplicacion.setStyleSheet(tema_anterior)

    assert avisos == []

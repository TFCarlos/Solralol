"""Captura Qt del an?lisis real sin permitir peticiones de red."""

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import requests
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.ui.local_analysis_dialog import LocalAnalysisDialog


def rechazar_red(*args: object, **kwargs: object) -> None:
    """Rechaza cualquier petici?n remota durante la captura."""
    raise RuntimeError("La verificaci?n visual solo admite datos locales")


def capturar() -> None:
    """Captura ventana y contenido completo a tres tama?os y cierra Qt."""
    for nombre, ancho, alto in (
        ("normal", 1500, 1000),
        ("estrecho", 916, 1000),
        ("maximizado", 1920, 1080),
    ):
        ventana.resize(ancho, alto)
        for _ in range(20):
            aplicacion.processEvents()
        ventana.matchups_panel.grab().save(
            str(destino / f"refinamiento_{nombre}_matchups.png")
        )
        ventana.recommendations_panel.grab().save(
            str(destino / f"refinamiento_{nombre}_recomendaciones.png")
        )
        ventana.grab().save(str(destino / f"refinamiento_{nombre}.png"))
        ventana._scroll_analisis.widget().grab().save(
            str(destino / f"refinamiento_{nombre}_completo.png")
        )
        print(
            nombre,
            "hero",
            ventana.champion_banner.height(),
            "scroll_horizontal",
            ventana._scroll_analisis.horizontalScrollBar().maximum(),
            "filas",
            ventana.item_table.rowCount(),
            "scroll_tabla",
            ventana.item_table.verticalScrollBar().maximum(),
            "estado",
            ventana.status.text(),
        )
    ventana.close()
    aplicacion.quit()


requests.sessions.Session.request = rechazar_red
aplicacion = QApplication([])
for fuente in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + fuente)
ventana = LocalAnalysisDialog()
ventana.resize(1500, 1000)
ventana.show()
destino = Path("app/scratch")
QTimer.singleShot(1600, capturar)
aplicacion.exec()

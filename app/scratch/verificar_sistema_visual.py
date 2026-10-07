"""Galería Qt reproducible de pantallas reales con integraciones simuladas."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget
from pytest import MonkeyPatch

from app.scratch.test_pantallas_sistema_visual import RecursosPrueba, ventana_global
from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog
from app.ui.match_inspector_dialog import MatchInspectorDialog
from app.ui.postgame_replay_window import PostgameReplayWindow
from app.ui.startup_window import StartupWindow


def capturar() -> None:
    """Captura destinos, ajustes y diálogos a varios tamaños, sin red ni claves."""
    aplicacion = QApplication.instance() or QApplication([])
    destino = Path("app/scratch/galeria_sistema_visual")
    destino.mkdir(exist_ok=True)
    capturas = []
    with tempfile.TemporaryDirectory() as directorio, MonkeyPatch.context() as parche:
        generador = ventana_global.__wrapped__(aplicacion, parche, Path(directorio))
        ventana = next(generador)
        for nombre, ancho, alto in (("normal", 1500, 1000), ("minimo", 1000, 700), ("maximizado", 1920, 1080), ("ultrawide", 2560, 1080)):
            ventana.resize(ancho, alto)
            for indice, pagina in enumerate(("inicio", "analisis", "live", "guardadas", "grabaciones", "ajustes", "draft")):
                if indice == 6:
                    ventana.open_draft_tool_dialog()
                ventana.pages.setCurrentIndex(indice)
                QTest.qWait(100)
                archivo = destino / f"{nombre}_{pagina}.png"
                ventana.grab().save(str(archivo))
                if nombre == "normal":
                    capturas.append(archivo)
                print(nombre, pagina, ventana.size().toTuple(), "pagina", ventana.pages.size().toTuple())
        ventana.resize(1500, 1000)
        ventana.pages.setCurrentIndex(5)
        ajustes = ventana.pages.widget(5).findChild(QTabWidget, "settingsTabs")
        for indice in range(4):
            ajustes.setCurrentIndex(indice)
            QTest.qWait(100)
            archivo = destino / f"ajustes_{indice}.png"
            ventana.grab().save(str(archivo))
            capturas.append(archivo)
        recursos = RecursosPrueba()
        parche.setattr(LiveMatchAnalysisDialog, "_prepare_session", lambda self: None)
        componentes = {
            "arranque": StartupWindow("Preparando interfaz", "Solo datos locales"),
            "inspector": MatchInspectorDialog({"champion_name": "Aatrox", "allies": [], "enemies": []}, assets=recursos),
            "analisis_live": LiveMatchAnalysisDialog({}, recursos, {}),
            "repaso": PostgameReplayWindow(library=ventana.recording_library),
        }
        for nombre, componente in componentes.items():
            componente.show()
            QTest.qWait(100)
            archivo = destino / f"secundaria_{nombre}.png"
            componente.grab().save(str(archivo))
            capturas.append(archivo)
            componente.hide()
        componentes["arranque"].stop()
        componentes["repaso"].player.stop()
        try:
            next(generador)
        except StopIteration:
            pass
        lienzo = QPixmap(1400, ((len(capturas) + 1) // 2) * 500)
        lienzo.fill(QColor("#05070c"))
        pintor = QPainter(lienzo)
        for indice, archivo in enumerate(capturas):
            imagen = QPixmap(str(archivo)).scaled(700, 470)
            x, y = indice % 2 * 700, indice // 2 * 500
            pintor.drawPixmap(x, y + 25, imagen)
            pintor.setPen(QColor("#e1dab2"))
            pintor.drawText(x + 12, y + 18, archivo.stem)
        pintor.end()
        lienzo.save(str(destino / "contacto.png"))


if __name__ == "__main__":
    capturar()

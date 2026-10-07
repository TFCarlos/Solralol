"""Worker Qt secuencial para cargar un análisis local completo."""

from __future__ import annotations

import copy
import logging
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from app.services.analisis_local_service import AnalisisLocalService


class AnalisisLocalWorker(QThread):
    """Emite resultados etiquetados sin tocar widgets ni ejecutar renderizado."""

    analisis_listo = Signal(int, str, dict)
    analisis_fallido = Signal(int, str)

    def __init__(
        self,
        servicio: AnalisisLocalService,
        generacion: int,
        clave: str,
        perfil: dict[str, Any],
        linea: str,
        rango: str,
        pagina_defecto: dict[str, Any],
        parent: QObject | None = None,
    ) -> None:
        """Captura servicio, generación, filtros, perfil y padre; retorna None."""
        super().__init__(parent)
        self.servicio = servicio
        self.generacion = generacion
        self.clave = clave
        self.perfil = copy.deepcopy(perfil)
        self.linea = linea
        self.rango = rango
        self.pagina_defecto = pagina_defecto

    def run(self) -> None:
        """Carga la selección capturada y emite datos o error identificado; retorna None."""
        try:
            resultado = self.servicio.cargar(
                self.perfil,
                self.linea,
                self.rango,
                self.pagina_defecto,
                self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.analisis_listo.emit(self.generacion, self.clave, resultado)
        except InterruptedError:
            return
        except Exception:
            logging.getLogger(__name__).exception(
                "No se pudo preparar el análisis local"
            )
            self.analisis_fallido.emit(self.generacion, self.clave)

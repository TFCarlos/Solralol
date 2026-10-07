"""Comprobacion local sin red del dialogo y sus selectores."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtWidgets import QApplication

from app.ui.local_analysis_dialog import LocalAnalysisDialog

app = QApplication.instance() or QApplication([])
with patch(
    "requests.sessions.Session.request",
    side_effect=AssertionError("Red durante navegacion"),
):
    dialogo = LocalAnalysisDialog()
    for campeon, linea, rango in [
        ("Aatrox", "top", "emerald_plus"),
        ("Ahri", "mid", "emerald_plus"),
        ("Ahri", "support", "challenger"),
    ]:
        inicio = perf_counter()
        dialogo.champion_combo.setCurrentIndex(dialogo.champion_combo.findText(campeon))
        dialogo.analysis_lane_combo.setCurrentIndex(
            dialogo.analysis_lane_combo.findData(linea)
        )
        dialogo.analysis_rank_combo.setCurrentIndex(
            dialogo.analysis_rank_combo.findData(rango)
        )
        limite = inicio + 5
        while perf_counter() < limite and (
            dialogo._carga_pendiente or dialogo._worker_analisis is not None
        ):
            app.processEvents()
        assert not dialogo._carga_pendiente and dialogo._worker_analisis is None
        print(
            campeon,
            linea,
            rango,
            round((perf_counter() - inicio) * 1000, 2),
            dialogo.status.text(),
        )
    dialogo.close()

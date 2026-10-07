"""Mide JSON, SQLite comparativo y selección Qt con la red prohibida."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.repositorio_campeones import LINEAS, RANGOS, RepositorioCampeones


def medir(operacion: Callable[[], object], repeticiones: int = 100) -> float:
    """Mide operación repetida y devuelve mediana en milisegundos."""
    tiempos = []
    for _ in range(repeticiones):
        inicio = perf_counter()
        operacion()
        tiempos.append((perf_counter() - inicio) * 1000)
    return round(median(tiempos), 4)


def main() -> None:
    """Compara almacenamiento real y máximo conceptual y mide UI local; retorna None."""
    repo = RepositorioCampeones()
    documento = repo.obtener_campeon("Aatrox").datos
    informe = {}
    informe["json_parse_ms"] = medir(
        lambda: json.loads(repo.ruta("Aatrox").read_text(encoding="utf-8"))
    )
    informe["json_lookup_cached_ms"] = medir(
        lambda: repo.consultar("Aatrox", "top", "emerald_plus")
    )
    informe["json_lookup_cold_ms"] = medir(
        lambda: RepositorioCampeones().consultar("Aatrox", "top", "emerald_plus")
    )
    with TemporaryDirectory() as temporal:
        ruta_db = Path(temporal) / "comparacion.db"
        conexion = sqlite3.connect(ruta_db)
        conexion.execute(
            "CREATE TABLE champions (champion TEXT PRIMARY KEY, metadata TEXT)"
        )
        conexion.execute(
            "CREATE TABLE analysis (champion TEXT, role TEXT, rank TEXT, payload TEXT, PRIMARY KEY (champion, role, rank))"
        )
        for ruta in repo.raiz.glob("*.json"):
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            matriz = datos.pop("ranks")
            conexion.execute(
                "INSERT INTO champions VALUES (?,?)",
                (
                    ruta.stem,
                    json.dumps(datos, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            for rango, bloque in matriz.items():
                for linea, variante in bloque.items():
                    conexion.execute(
                        "INSERT INTO analysis VALUES (?,?,?,?)",
                        (
                            ruta.stem,
                            linea,
                            rango,
                            json.dumps(
                                variante, ensure_ascii=False, separators=(",", ":")
                            ),
                        ),
                    )
        conexion.commit()
        consulta = lambda: [
            json.loads(valor)
            for valor in conexion.execute(
                "SELECT a.payload, c.metadata FROM analysis a JOIN champions c USING(champion) WHERE a.champion=? AND a.role=? AND a.rank=?",
                ("aatrox", "top", "emerald_plus"),
            ).fetchone()
        ]
        informe["sqlite_lookup_ms"] = medir(consulta)
        informe["sqlite_bytes"] = ruta_db.stat().st_size
        conexion.close()
        sintetico = copy.deepcopy(documento)
        variante = documento["ranks"]["emerald_plus"]["top"]
        sintetico["ranks"] = {
            rango: {
                linea: dict(copy.deepcopy(variante), rank=rango, role=linea)
                for linea in LINEAS
            }
            for rango in RANGOS
        }
        prueba = RepositorioCampeones(Path(temporal) / "sintetico")
        informe["json_write_full_champion_ms"] = medir(
            lambda: prueba.guardar("Aatrox", sintetico), 10
        )
        informe["json_full_champion_bytes"] = prueba.ruta("Aatrox").stat().st_size
        informe["json_full_lookup_cached_ms"] = medir(
            lambda: prueba.consultar("Aatrox", "top", "emerald_plus"), 30
        )
        informe["json_full_parse_ms"] = medir(
            lambda: json.loads(prueba.ruta("Aatrox").read_text(encoding="utf-8")), 30
        )
    informe["json_dataset_bytes"] = sum(
        ruta.stat().st_size for ruta in repo.raiz.glob("*.json")
    )
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    aplicacion = QApplication.instance() or QApplication([])
    assert aplicacion is not None
    with patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Red durante navegación"),
    ):
        dialogo = LocalAnalysisDialog()
        muestras = []
        for indice in range(8):
            campeon, linea = ("Aatrox", "top") if indice % 2 == 0 else ("Ahri", "mid")
            dialogo.champion_combo.setCurrentIndex(
                dialogo.champion_combo.findText(campeon)
            )
            dialogo.analysis_lane_combo.setCurrentIndex(
                dialogo.analysis_lane_combo.findData(linea)
            )
            dialogo.analysis_rank_combo.setCurrentIndex(
                dialogo.analysis_rank_combo.findData("emerald_plus")
            )
            bucle = QEventLoop()
            reloj = QTimer()
            reloj.timeout.connect(
                lambda bucle=bucle: (
                    bucle.quit()
                    if not dialogo._carga_pendiente and dialogo._worker_analisis is None
                    else None
                )
            )
            reloj.start(1)
            limite = QTimer()
            limite.setSingleShot(True)
            limite.timeout.connect(bucle.quit)
            limite.start(5000)
            bucle.exec()
            reloj.stop()
            limite.stop()
            assert not dialogo._carga_pendiente and dialogo._worker_analisis is None
            muestras.append(dict(campeon=campeon, **dialogo._tiempos_ultima_carga))
        informe["qt_samples"] = muestras
        dialogo.close()
    print(json.dumps(informe, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Ajustes de Qt Multimedia para la reproducción de Solralol."""

from __future__ import annotations

import os

CODIFICADORES_VIDEO_MEDIA_FOUNDATION = ("h264_mf", "hevc_mf", "av1_mf")


def excluir_codificadores_media_foundation() -> None:
    """Evita que Qt inicialice codificadores MF que Solralol no utiliza.

    Conserva las exclusiones configuradas por el entorno y añade los
    codificadores de vídeo Media Foundation antes de cargar el backend Qt.
    """
    variable = "QT_FFMPEG_EXCLUDE_ENCODERS"
    configurados = os.environ.get(variable, "").split(",")
    nombres = [nombre.strip() for nombre in configurados if nombre.strip()]
    conocidos = {nombre.casefold() for nombre in nombres}

    for codificador in CODIFICADORES_VIDEO_MEDIA_FOUNDATION:
        if codificador.casefold() not in conocidos:
            nombres.append(codificador)
            conocidos.add(codificador.casefold())

    os.environ[variable] = ",".join(nombres)

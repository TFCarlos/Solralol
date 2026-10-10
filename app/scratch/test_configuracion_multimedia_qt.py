"""Pruebas de configuración del backend multimedia de Qt."""

from __future__ import annotations

import os

import pytest

from app.utils.configuracion_multimedia_qt import (
    CODIFICADORES_VIDEO_MEDIA_FOUNDATION,
    excluir_codificadores_media_foundation,
)


def test_excluir_codificadores_media_foundation_conserva_y_deduplica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Añade exclusiones MF sin perder valores previos ni duplicarlos."""
    monkeypatch.setenv("QT_FFMPEG_EXCLUDE_ENCODERS", "libx264,H264_MF")

    excluir_codificadores_media_foundation()

    actual = os.environ["QT_FFMPEG_EXCLUDE_ENCODERS"].split(",")
    assert actual == ["libx264", "H264_MF", "hevc_mf", "av1_mf"]
    assert len(actual) == len({valor.casefold() for valor in actual})


def test_excluir_codificadores_media_foundation_cubre_video_qt() -> None:
    """Mantiene la lista de exclusión alineada con los codificadores de vídeo MF."""
    assert set(CODIFICADORES_VIDEO_MEDIA_FOUNDATION) == {
        "h264_mf",
        "hevc_mf",
        "av1_mf",
    }

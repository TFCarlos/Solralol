import os
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from pytest import MonkeyPatch

from app.ui.postgame_replay_window import PostgameReplayWindow
from app.ui.recordings_page import RecordingsPage


class _Fuente:
    def isEmpty(self) -> bool:
        return False


class _Reproductor:
    def __init__(self, position: int = 0, duration: int = 0) -> None:
        self.position_ms = position
        self.duration_ms = duration
        self.playback_state = QMediaPlayer.PlaybackState.PausedState
        self.set_positions: list[int] = []
        self.pause = Mock(side_effect=self._pausar)
        self.play = Mock(side_effect=self._reproducir)

    def _pausar(self) -> None:
        self.playback_state = QMediaPlayer.PlaybackState.PausedState

    def _reproducir(self) -> None:
        self.playback_state = QMediaPlayer.PlaybackState.PlayingState

    def source(self) -> _Fuente:
        return _Fuente()

    def position(self) -> int:
        return self.position_ms

    def duration(self) -> int:
        return self.duration_ms

    def setPosition(self, value: int) -> None:
        self.set_positions.append(value)

    def playbackState(self) -> QMediaPlayer.PlaybackState:
        return self.playback_state


def test_atras_y_adelante_del_repaso_se_limita_a_duracion_conocida() -> None:
    """Limita saltos de cinco segundos al intervalo real del vídeo."""
    player = _Reproductor(position=2_000, duration=600_000)
    ventana = SimpleNamespace(player=player)

    PostgameReplayWindow.seek_relative(ventana, -5)
    assert player.set_positions == [0]

    player.position_ms = 599_000
    PostgameReplayWindow.seek_relative(ventana, 5)
    assert player.set_positions == [0, 600_000]


def test_salto_del_repaso_acepta_duracion_aun_desconocida() -> None:
    """Permite buscar mientras Qt todavía no informa la duración."""
    player = _Reproductor(position=0, duration=0)
    ventana = SimpleNamespace(player=player)

    PostgameReplayWindow.seek_relative(ventana, 5)

    assert player.set_positions == [5_000]


def test_salto_de_grabaciones_guarda_posicion_durante_carga() -> None:
    """Conserva una búsqueda solicitada antes de recibir la duración."""
    pagina = SimpleNamespace(
        current_path=Path("partida.mp4"),
        player=_Reproductor(position=0, duration=0),
        pending_seek_ms=0,
    )
    pagina.seek_to_ms = MethodType(RecordingsPage.seek_to_ms, pagina)

    RecordingsPage.seek_by_ms(pagina, 5_000)

    assert pagina.pending_seek_ms == 5_000
    assert pagina.player.set_positions == []


def test_seek_de_grabaciones_no_supera_duracion_y_cero() -> None:
    """Evita posiciones negativas y superiores a la duración conocida."""
    pagina = SimpleNamespace(
        current_path=Path("partida.mp4"),
        player=_Reproductor(position=0, duration=600_000),
        pending_seek_ms=0,
    )
    pagina.seek_to_ms = MethodType(RecordingsPage.seek_to_ms, pagina)

    RecordingsPage.seek_by_ms(pagina, -5_000)
    RecordingsPage.seek_by_ms(pagina, 605_000)

    assert pagina.player.set_positions == [0, 600_000]


def test_abrir_repaso_pausa_sin_tocar_posicion_ni_grabacion() -> None:
    """Pausa solo el reproductor cuando estaba reproduciendo."""
    player = _Reproductor(position=12_345)
    player.playback_state = QMediaPlayer.PlaybackState.PlayingState
    pagina = SimpleNamespace(player=player)

    RecordingsPage.pause_for_replay(pagina)

    player.pause.assert_called_once_with()
    assert player.position_ms == 12_345
    player.play.assert_not_called()


def test_abrir_repaso_deja_en_pausa_el_reproductor_ya_pausado() -> None:
    """No altera un vídeo que ya estaba en pausa."""
    player = _Reproductor(position=12_345)
    pagina = SimpleNamespace(player=player)

    RecordingsPage.pause_for_replay(pagina)

    player.pause.assert_not_called()
    assert player.position_ms == 12_345


def test_espacio_alterna_reproduccion_sin_reiniciar() -> None:
    """Alterna pausa y reproducción conservando la posición actual."""
    player = _Reproductor(position=123_456)
    pagina = SimpleNamespace(current_path=Path("partida.mp4"), player=player)
    ventana = SimpleNamespace(
        player=player, status_label=SimpleNamespace(setText=Mock())
    )

    RecordingsPage.toggle_play(pagina)
    PostgameReplayWindow.toggle_play(ventana)
    PostgameReplayWindow.toggle_play(ventana)

    player.play.assert_has_calls([(), ()])
    player.pause.assert_called_once_with()
    assert player.position_ms == 123_456


def test_atajos_no_se_ejecutan_mientras_se_escribe(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ignora atajos de reproducción cuando el foco es un campo de texto."""
    app = QApplication.instance() or QApplication([])
    editor = QLineEdit()
    editor.setFocus()
    monkeypatch.setattr(QApplication, "focusWidget", lambda: editor)
    action = Mock()
    receptor = SimpleNamespace()

    RecordingsPage._run_playback_shortcut(receptor, action)
    PostgameReplayWindow._run_replay_shortcut(receptor, action)

    action.assert_not_called()
    editor.deleteLater()
    app.processEvents()


def test_atajos_solo_actuan_en_el_panel_de_reproduccion() -> None:
    """Limita QShortcut al panel y deja que el campo externo reciba Espacio."""
    app = QApplication.instance() or QApplication([])
    panel = QWidget()
    video = QWidget(panel)
    video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    video.resize(100, 40)
    panel.resize(100, 40)
    panel.show()
    video.setFocus()
    accion = Mock()
    receptor = SimpleNamespace(
        video_widget=video,
        toggle_play=accion,
        seek_by_ms=Mock(),
        _run_playback_shortcut=MethodType(
            RecordingsPage._run_playback_shortcut, SimpleNamespace()
        ),
    )
    RecordingsPage._install_playback_shortcuts(receptor)
    app.processEvents()

    QTest.keyClick(video, Qt.Key.Key_Space)
    assert accion.call_count == 1
    assert all(
        shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        for shortcut in receptor._playback_shortcuts
    )

    editor = QLineEdit()
    editor.show()
    editor.setFocus()
    app.processEvents()
    QTest.keyClick(editor, Qt.Key.Key_Space)

    assert editor.text() == " "
    assert accion.call_count == 1
    panel.close()
    editor.close()

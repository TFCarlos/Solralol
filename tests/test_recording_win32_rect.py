"""The recording and overlay services must use one ctypes RECT ABI."""

import ctypes
import sys
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from app.services import game_window_geometry, recording_service


@pytest.mark.skipif(sys.platform != "win32", reason="requires Win32 user32")
def test_get_window_rect_stays_compatible_after_both_services_import():
    user32 = ctypes.windll.user32
    assert recording_service._RECT is wintypes.RECT
    assert user32.GetWindowRect.argtypes[1] == ctypes.POINTER(wintypes.RECT)

    desktop = user32.GetDesktopWindow()
    rect = recording_service._RECT()
    assert user32.GetWindowRect(desktop, ctypes.byref(rect))
    assert rect.right > rect.left and rect.bottom > rect.top

    # A bad HWND is an ordinary native failure, not a ctypes type exception.
    assert not user32.GetWindowRect(wintypes.HWND(0), ctypes.byref(rect))
    game_rect = game_window_geometry.league_client_rect_pixels()
    assert game_rect is None or isinstance(game_rect, dict)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Win32 user32")
def test_recording_enumerator_with_no_game_does_not_raise():
    result = recording_service.find_game_window()
    assert result is None or (isinstance(result[0], int) and result[0] != 0)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Win32 callback ABI")
def test_bad_window_does_not_abort_native_enumeration(monkeypatch):
    seen = []

    def window_text_length(hwnd):
        seen.append(int(hwnd))
        if int(hwnd) == 123:
            raise OSError("window disappeared")
        return 0

    def enumerate_windows(callback, _):
        assert callback(123, 0)
        assert callback(456, 0)
        return True

    monkeypatch.setattr(recording_service, "_user32", SimpleNamespace(
        GetWindowTextLengthW=window_text_length, EnumWindows=enumerate_windows,
    ))
    assert recording_service.find_game_window() is None
    assert seen == [123, 456]

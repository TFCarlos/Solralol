"""Locate the League game client area without Qt or an extra process."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


def league_client_rect_pixels() -> dict[str, int] | None:
    if os.name != "nt":
        return None
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[dict[str, int]] = []

    def inspect(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return True
        try:
            path = ctypes.create_unicode_buffer(1024)
            length = wintypes.DWORD(len(path))
            if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                return True
            if path.value.rsplit("\\", 1)[-1].casefold() != "league of legends.exe":
                return True
        finally:
            kernel32.CloseHandle(process)
        client, origin = wintypes.RECT(), wintypes.POINT()
        if user32.GetClientRect(hwnd, ctypes.byref(client)) and user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            width, height = client.right - client.left, client.bottom - client.top
            if width >= 640 and height >= 360:
                found.append({"x": origin.x, "y": origin.y, "width": width, "height": height})
                return False
        return True

    user32.EnumWindows(enum_proc(inspect), 0)
    return found[0] if found else None


def _rect_union_area(rectangles: list[tuple[int, int, int, int]]) -> int:
    if not rectangles:
        return 0
    xs = sorted({edge for rect in rectangles for edge in (rect[0], rect[2])})
    area = 0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((rect[1], rect[3]) for rect in rectangles if rect[0] < right and rect[2] > left)
        covered = 0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start > end:
                    covered += end - start
                    start, end = next_start, next_end
                else:
                    end = max(end, next_end)
            covered += end - start
        area += (right - left) * covered
    return area


def _occlusion_for_rects(game: tuple[int, int, int, int], occluders: list[tuple[int, int, int, int]], overlays: dict[str, tuple[int, int, int, int]]) -> dict[str, object]:
    clipped = [(max(game[0], row[0]), max(game[1], row[1]), min(game[2], row[2]), min(game[3], row[3]))
               for row in occluders]
    clipped = [row for row in clipped if row[2] > row[0] and row[3] > row[1]]
    area = max(1, (game[2] - game[0]) * (game[3] - game[1]))
    ratio = min(1.0, _rect_union_area(clipped) / area)
    covered = []
    for panel, rect in overlays.items():
        right, bottom = rect[0] + rect[2], rect[1] + rect[3]
        if any(max(rect[0], row[0]) < min(right, row[2]) and max(rect[1], row[1]) < min(bottom, row[3]) for row in occluders):
            covered.append(panel)
    return {"gameOccluded": ratio >= 0.22, "occlusionRatio": round(ratio, 3), "coveredPanels": covered}


def overlay_window_visibility(overlays: list[dict]) -> dict[str, object]:
    """Run native geometry reads in per-monitor physical pixel coordinates."""
    if os.name != "nt":
        return {"gameVisible": False, "gameOccluded": True, "coveredPanels": []}
    user32 = ctypes.windll.user32
    setter = getattr(user32, "SetThreadDpiAwarenessContext", None)
    previous = None
    if setter is not None:
        try:
            setter.argtypes = [ctypes.c_void_p]
            setter.restype = ctypes.c_void_p
            previous = setter(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except (AttributeError, OSError, TypeError):
            previous = None
    try:
        return _overlay_window_visibility_native(overlays)
    finally:
        if previous:
            try:
                setter(previous)
            except (AttributeError, OSError, TypeError):
                pass


def _overlay_window_visibility_native(overlays: list[dict]) -> dict[str, object]:
    """Check the visible League HWND and topmost external windows in one Win32 pass."""
    empty = {"gameVisible": False, "gameOccluded": True, "coveredPanels": []}
    if os.name != "nt":
        return empty
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    except (AttributeError, OSError):
        dwmapi = None
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD)]
    user32.GetLayeredWindowAttributes.restype = wintypes.BOOL
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    excluded = set()
    windows = []
    supplied = overlays if isinstance(overlays, list) else []
    if len(supplied) > 8:
        return empty
    rects = {}
    for row in supplied:
        if not isinstance(row, dict) or not isinstance(row.get("panel"), str):
            continue
        try:
            excluded.add(int(row.get("hwnd")))
            rect = row.get("rect")
            values = [int(rect[key]) for key in ("x", "y", "width", "height")]
            if values[2] > 0 and values[3] > 0:
                rects[row["panel"]] = tuple(values)
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
    process_names: dict[int, str] = {}
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enumerate_window(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if int(hwnd) in excluded:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in process_names:
            process = kernel32.OpenProcess(0x1000, False, pid.value)
            name = ""
            if process:
                try:
                    path = ctypes.create_unicode_buffer(1024)
                    length = wintypes.DWORD(len(path))
                    if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                        name = path.value.rsplit("\\", 1)[-1].casefold()
                finally:
                    kernel32.CloseHandle(process)
            process_names[pid.value] = name
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            return True
        extended_style = user32.GetWindowLongW(hwnd, -20)
        if extended_style & 0x00080000:  # WS_EX_LAYERED
            color_key, alpha, flags = wintypes.DWORD(), wintypes.BYTE(), wintypes.DWORD()
            if user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(color_key), ctypes.byref(alpha), ctypes.byref(flags)) and flags.value & 0x2 and alpha.value == 0:
                return True
        class_buffer = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        class_name = class_buffer.value
        if dwmapi is not None:
            cloaked = wintypes.DWORD()
            try:
                if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                    return True
            except (AttributeError, OSError):
                pass
        windows.append({"hwnd": int(hwnd), "pid": pid.value, "name": process_names[pid.value],
                        "class": class_name, "rect": bounds})
        if (process_names[pid.value] == "league of legends.exe"
            and bounds[2] - bounds[0] >= 640 and bounds[3] - bounds[1] >= 360):
            return False  # EnumWindows is top-to-bottom; lower windows cannot occlude League.
        return True

    user32.EnumWindows(enum_proc(enumerate_window), 0)
    games = [index for index, row in enumerate(windows)
             if row["name"] == "league of legends.exe"
             and row["rect"][2] - row["rect"][0] >= 640
             and row["rect"][3] - row["rect"][1] >= 360]
    if not games:
        return empty
    game_index = max(games, key=lambda index: (windows[index]["rect"][2] - windows[index]["rect"][0]) * (windows[index]["rect"][3] - windows[index]["rect"][1]))
    game = windows[game_index]["rect"]
    shell_classes = {"progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"}
    occluders = [row["rect"] for row in windows[:game_index]
                 if row["hwnd"] not in excluded and row["class"].casefold() not in shell_classes]
    occlusion = _occlusion_for_rects(game, occluders[:100], rects)
    return {"gameVisible": True, **occlusion}

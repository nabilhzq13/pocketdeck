"""Screens (monitors) and moving a just-launched app's window onto a chosen screen.

Coordinates are physical pixels: server.py makes the process per-monitor DPI aware at start."""
import ctypes
import ctypes.wintypes as wt
import threading
import time

from . import winapi

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------- friendly monitor names


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32),
                ("scaling", ctypes.c_uint32), ("refreshRate", RATIONAL),
                ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wt.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO),
                ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):  # contents not needed, only the 64-byte size
    _fields_ = [("raw", ctypes.c_uint64 * 8)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID),
                ("id", ctypes.c_uint32)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("edidManufactureId", ctypes.c_uint16),
                ("edidProductCodeId", ctypes.c_uint16), ("connectorInstance", ctypes.c_uint32),
                ("monitorFriendlyDeviceName", wt.WCHAR * 64), ("monitorDevicePath", wt.WCHAR * 128)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", wt.WCHAR * 32)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT),
                                     wt.LPARAM)
user32.GetDisplayConfigBufferSizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                               ctypes.POINTER(ctypes.c_uint32)]
user32.QueryDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                      ctypes.POINTER(PATH_INFO), ctypes.POINTER(ctypes.c_uint32),
                                      ctypes.POINTER(MODE_INFO), ctypes.c_void_p]
user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.POINTER(DEVICE_INFO_HEADER)]
user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p, MONITORENUMPROC, wt.LPARAM]
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wt.UINT]
user32.IsZoomed.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.IsWindow.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND

INTERNAL_TECH = {6, 11, 13, 0x80000000}  # LVDS, embedded DisplayPort, embedded UDI, internal


def _friendly_names():
    """GDI device name (\\\\.\\DISPLAY1) -> (monitor name, is laptop panel)."""
    out = {}
    n_paths, n_modes = ctypes.c_uint32(), ctypes.c_uint32()
    for _ in range(3):
        if user32.GetDisplayConfigBufferSizes(2, ctypes.byref(n_paths), ctypes.byref(n_modes)):
            return out
        paths = (PATH_INFO * n_paths.value)()
        modes = (MODE_INFO * n_modes.value)()
        rc = user32.QueryDisplayConfig(2, ctypes.byref(n_paths), paths, ctypes.byref(n_modes),
                                       modes, None)  # QDC_ONLY_ACTIVE_PATHS
        if rc == 0:
            break
        if rc != 122:  # ERROR_INSUFFICIENT_BUFFER: the setup changed, try again
            return out
    else:
        return out
    for p in paths[:n_paths.value]:
        src = SOURCE_DEVICE_NAME()
        src.header.type, src.header.size = 1, ctypes.sizeof(src)
        src.header.adapterId, src.header.id = p.sourceInfo.adapterId, p.sourceInfo.id
        tgt = TARGET_DEVICE_NAME()
        tgt.header.type, tgt.header.size = 2, ctypes.sizeof(tgt)
        tgt.header.adapterId, tgt.header.id = p.targetInfo.adapterId, p.targetInfo.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(src.header)):
            continue
        user32.DisplayConfigGetDeviceInfo(ctypes.byref(tgt.header))
        internal = p.targetInfo.outputTechnology in INTERNAL_TECH
        name = "Laptop screen" if internal else tgt.monitorFriendlyDeviceName.strip()
        prev = out.get(src.viewGdiDeviceName)
        if prev:  # duplicate mode: one desktop shown on two screens
            name, internal = f"{prev[0]} + {name}", prev[1] or internal
        out[src.viewGdiDeviceName] = (name, internal)
    return out


_cache = {"at": 0.0, "list": []}
_lock = threading.Lock()


def list_screens(max_age=3.0):
    with _lock:
        if time.monotonic() - _cache["at"] < max_age:
            return _cache["list"]
    names = _friendly_names()
    found = []

    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r, w = mi.rcMonitor, mi.rcWork
            name, internal = names.get(mi.szDevice, ("", False))
            found.append({"id": mi.szDevice, "name": name, "internal": internal,
                          "primary": bool(mi.dwFlags & 1),
                          "width": r.right - r.left, "height": r.bottom - r.top,
                          "x": r.left, "y": r.top,
                          "work": (w.left, w.top, w.right, w.bottom)})
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    found.sort(key=lambda s: (s["x"], s["y"]))
    for i, s in enumerate(found):
        if not s["name"]:
            s["name"] = f"Screen {i + 1}"
    with _lock:
        _cache.update(at=time.monotonic(), list=found)
    return found


def public(screens):
    """What the phone needs to draw the picker."""
    return [{k: s[k] for k in ("id", "name", "internal", "primary", "width", "height", "x", "y")}
            for s in screens]


def resolve(choice):
    """choice: a screen id (\\\\.\\DISPLAY2), 'laptop', 'primary', 'external', or a monitor name.
    Returns None for 'ask'/'none'/'' or when that screen is not connected."""
    if not choice or choice in ("ask", "none"):
        return None
    screens = list_screens()
    low = str(choice).lower()
    for s in screens:
        if s["id"].lower() == low:
            return s
    if low == "laptop":
        return next((s for s in screens if s["internal"]), None)
    if low == "primary":
        return next((s for s in screens if s["primary"]), None)
    if low == "external":
        return next((s for s in screens if not s["internal"]), None)
    return next((s for s in screens if low in s["name"].lower()), None)

# ---------------------------------------------------------------- moving windows


SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10


def screen_of(hwnd):
    hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(mi)
    return mi.szDevice if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)) else None


def move_window(hwnd, screen, maximize=False):
    was_max = bool(user32.IsZoomed(hwnd))
    if was_max or user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    left, top, right, bottom = screen["work"]
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    # Step 1: put it on the target screen so Windows rescales it for that screen's DPI.
    if not user32.SetWindowPos(hwnd, None, left + 20, top + 20, 0, 0, flags | SWP_NOSIZE):
        return False  # usually an app running as administrator
    time.sleep(0.08)
    # Step 2: fit and centre it in the screen's work area (above the taskbar).
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w = min(r.right - r.left, right - left)
    h = min(r.bottom - r.top, bottom - top)
    user32.SetWindowPos(hwnd, None, left + (right - left - w) // 2,
                        top + (bottom - top - h) // 2, w, h, flags)
    if maximize or was_max:
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    return True


def snapshot():
    """Call just before launching: which windows exist and which one is in front."""
    fg = user32.GetForegroundWindow()
    return {w["hwnd"] for w in winapi.list_windows()}, int(fg or 0)


def place_after_launch(before, screen, maximize=False, timeout=20.0):
    """Watch for the launched app's window and move it to `screen`, in a background thread.

    New windows that appear after the launch belong to the app. If none appears, the app was
    already open and Windows brought its existing window to the front, so that one is moved.
    Windows of the same app keep being watched for a few seconds, because many apps show a
    splash screen first or restore their saved position right after opening."""
    before_windows, before_fg = before

    def work():
        start = time.monotonic()
        seen = {}          # hwnd -> first time seen
        moves = {}         # hwnd -> number of moves
        app_pid, done_at = None, None
        while time.monotonic() - start < timeout:
            now = time.monotonic()
            wins = winapi.list_windows()
            cands = [w for w in wins if w["hwnd"] not in before_windows
                     and (app_pid is None or w["pid"] == app_pid)]
            if not cands and app_pid is None and now - start > 0.6:
                fg = int(user32.GetForegroundWindow() or 0)
                if fg and fg != before_fg:
                    cands = [w for w in wins if w["hwnd"] == fg]
            for w in cands:
                h = w["hwnd"]
                seen.setdefault(h, now)
                if now - seen[h] < 0.3 or moves.get(h, 0) >= 3:
                    continue  # let the app finish placing it; don't fight it forever
                if screen_of(h) != screen["id"] or (maximize and not user32.IsZoomed(h)):
                    if move_window(h, screen, maximize):
                        moves[h] = moves.get(h, 0) + 1
                app_pid = app_pid or w["pid"]
                done_at = done_at or now + 4.0
            if done_at and now > done_at:
                return
            time.sleep(0.2)

    threading.Thread(target=work, name="place-window", daemon=True).start()

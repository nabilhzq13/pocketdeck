"""Thin ctypes wrappers around the Windows APIs PocketDeck needs:
keyboard/mouse injection, window list + focus, clipboard, power, theme, power mode."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time
import uuid
import winreg

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
powrprof = ctypes.WinDLL("powrprof")

ULONG_PTR = ctypes.c_size_t
CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------- SendInput


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT

KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "lwin": 0x5B, "rwin": 0x5C, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C, "prtsc": 0x2C,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "pause": 0x13, "menu": 0x5D,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "nexttrack": 0xB0,
    "prevtrack": 0xB1, "mediastop": 0xB2, "playpause": 0xB3,
    "plus": 0xBB, "=": 0xBB, "minus": 0xBD, "-": 0xBD, ",": 0xBC, "comma": 0xBC, ".": 0xBE,
    "period": 0xBE, "/": 0xBF, "slash": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, "`": 0xC0,
}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    VK[_c] = ord(_c.upper())
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
            0x2C, 0x90, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


def _send(inputs):
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError("Windows blocked the input (an admin window may be focused)")


def _key(vk, up=False):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def parse_chord(chord):
    names = [p.strip().lower() for p in chord.replace(" + ", "+").split("+")]
    names = [n for n in names if n]
    vks = []
    for n in names:
        if n not in VK:
            raise ValueError(f"Unknown key '{n}'")
        vks.append(VK[n])
    return vks


def hotkey(spec):
    """spec: 'ctrl+shift+esc' or several chords separated by spaces/commas: 'ctrl+k ctrl+c'."""
    chords = [c for c in spec.replace(",", " ").split() if c]
    for i, chord in enumerate(chords):
        vks = parse_chord(chord)
        _send([_key(v) for v in vks] + [_key(v, True) for v in reversed(vks)])
        if i < len(chords) - 1:
            time.sleep(0.04)


def tap_vk(vk):
    _send([_key(vk), _key(vk, True)])


def type_text(text):
    inputs = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            inputs += [_key(0x0D), _key(0x0D, True)]
            continue
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):
            code = int.from_bytes(units[i:i + 2], "little")
            for up in (False, True):
                inp = INPUT(type=1)
                inp.ki = KEYBDINPUT(wVk=0, wScan=code,
                                    dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                                    time=0, dwExtraInfo=0)
                inputs.append(inp)
    for i in range(0, len(inputs), 200):
        _send(inputs[i:i + 200])
        time.sleep(0.01)


MOUSE_MOVE, L_DOWN, L_UP, R_DOWN, R_UP, M_DOWN, M_UP, WHEEL, HWHEEL = (
    0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40, 0x800, 0x1000)


def _mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=ctypes.c_uint32(int(data)).value,
                        dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def mouse_move(dx, dy):
    _send([_mouse(MOUSE_MOVE, dx, dy)])


def mouse_click(button="left", double=False):
    down, up = {"left": (L_DOWN, L_UP), "right": (R_DOWN, R_UP), "middle": (M_DOWN, M_UP)}[button]
    seq = [_mouse(down), _mouse(up)]
    _send(seq * (2 if double else 1))


def mouse_button(button, pressed):
    down, up = {"left": (L_DOWN, L_UP), "right": (R_DOWN, R_UP)}[button]
    _send([_mouse(down if pressed else up)])


def mouse_scroll(dy=0, dx=0):
    seq = []
    if dy:
        seq.append(_mouse(WHEEL, data=int(dy)))
    if dx:
        seq.append(_mouse(HWHEEL, data=int(dx)))
    _send(seq)

# ---------------------------------------------------------------- windows


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
for _fn, _args in {
    "IsWindowVisible": [wt.HWND], "GetWindowTextLengthW": [wt.HWND],
    "GetWindowTextW": [wt.HWND, wt.LPWSTR, ctypes.c_int], "GetWindow": [wt.HWND, wt.UINT],
    "GetWindowLongW": [wt.HWND, ctypes.c_int], "IsIconic": [wt.HWND],
    "ShowWindow": [wt.HWND, ctypes.c_int], "SetForegroundWindow": [wt.HWND],
    "BringWindowToTop": [wt.HWND], "PostMessageW": [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM],
    "GetWindowThreadProcessId": [wt.HWND, ctypes.POINTER(wt.DWORD)],
    "EnumWindows": [WNDENUMPROC, wt.LPARAM], "IsWindow": [wt.HWND],
}.items():
    getattr(user32, _fn).argtypes = _args
user32.GetWindow.restype = wt.HWND
user32.GetForegroundWindow.restype = wt.HWND
user32.GetShellWindow.restype = wt.HWND
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]


def list_windows():
    out = []
    shell = user32.GetShellWindow()
    foreground = user32.GetForegroundWindow()

    def cb(hwnd, _):
        if not hwnd or hwnd == shell or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):            # GW_OWNER: skip dialogs / popups
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
            return True
        cloaked = wt.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)  # DWMWA_CLOAKED
        if cloaked.value:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append({"hwnd": int(hwnd), "title": buf.value, "pid": pid.value,
                    "active": hwnd == foreground, "minimized": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]


def uwp_pid(hwnd, host_pid):
    """Store apps live inside ApplicationFrameHost; the real app owns a child window."""
    found = []

    def cb(child, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
        if pid.value != host_pid:
            found.append(pid.value)
            return False
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return found[0] if found else host_pid


def window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_shown(hwnd):
    return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd))


def focus_window(hwnd):
    if not user32.IsWindow(hwnd):
        raise ValueError("That window is gone")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)               # SW_RESTORE
    # An empty input event gives this process permission to change the foreground window.
    _send([_mouse(0)])
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)


def window_command(hwnd, cmd):
    if cmd == "focus":
        focus_window(hwnd)
    elif cmd == "minimize":
        user32.ShowWindow(hwnd, 6)
    elif cmd == "maximize":
        user32.ShowWindow(hwnd, 3)
    elif cmd == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE (app may ask to save)
    else:
        raise ValueError(f"Unknown window command '{cmd}'")

# ---------------------------------------------------------------- clipboard


user32.OpenClipboard.argtypes = [wt.HWND]
user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]


def _open_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.03)
    raise OSError("Clipboard is busy")


def set_clipboard(text):
    data = text.encode("utf-16-le") + b"\0\0"
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(13, h):
            raise OSError("Could not set clipboard")
    finally:
        user32.CloseClipboard()


def get_clipboard():
    _open_clipboard()
    try:
        h = user32.GetClipboardData(13)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()

# ---------------------------------------------------------------- power


powrprof.SetSuspendState.argtypes = [wt.BOOLEAN, wt.BOOLEAN, wt.BOOLEAN]


def power(cmd):
    if cmd == "lock":
        user32.LockWorkStation()
    elif cmd == "sleep":
        powrprof.SetSuspendState(False, False, False)
    elif cmd == "hibernate":
        powrprof.SetSuspendState(True, False, False)
    elif cmd == "screen_off":
        user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)   # SC_MONITORPOWER off
    elif cmd in ("shutdown", "restart", "signout", "cancel"):
        flag = {"shutdown": ["/s", "/t", "5"], "restart": ["/r", "/t", "5"],
                "signout": ["/l"], "cancel": ["/a"]}[cmd]
        subprocess.run(["shutdown", *flag], creationflags=CREATE_NO_WINDOW, check=False)
    else:
        raise ValueError(f"Unknown power command '{cmd}'")

# ---------------------------------------------------------------- theme


_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPCWSTR, wt.UINT,
                                       wt.UINT, ctypes.c_void_p]


def is_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def set_theme(mode):
    dark = (not is_dark()) if mode == "toggle" else mode == "dark"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if dark else 1)
    user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 2, 300, None)
    return dark

# ---------------------------------------------------------------- power mode (Win 11 slider)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


POWER_MODES = {
    "efficiency": "961cc777-2547-4f9d-8174-7d86181b8a7a",
    "balanced": "00000000-0000-0000-0000-000000000000",
    "performance": "ded574b5-45a0-4f42-8737-46345c09c238",
}


def get_power_mode():
    fn = getattr(powrprof, "PowerGetEffectiveOverlayScheme", None)
    if not fn:
        return None
    g = _GUID()
    if fn(ctypes.byref(g)) != 0:
        return None
    s = str(uuid.UUID(bytes_le=bytes(g)))
    return next((k for k, v in POWER_MODES.items() if v == s), None)


def set_power_mode(mode):
    fn = getattr(powrprof, "PowerSetActiveOverlayScheme", None)
    if not fn or mode not in POWER_MODES:
        raise ValueError("Power mode not supported here")
    g = _GUID.from_buffer_copy(uuid.UUID(POWER_MODES[mode]).bytes_le)
    fn.argtypes = [_GUID]
    if fn(g) != 0:
        raise OSError("Windows refused the power mode (a custom power plan may be active)")

# ---------------------------------------------------------------- misc


def launch(target, args=None):
    if args:
        subprocess.Popen([target, *args], creationflags=0)
    else:
        os.startfile(target)


def run_command(cmd, shell="cmd", wait=False):
    argv = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
            if shell == "powershell" else ["cmd", "/c", cmd])
    if not wait:
        subprocess.Popen(argv, creationflags=CREATE_NO_WINDOW)
        return None
    r = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                       creationflags=CREATE_NO_WINDOW, errors="replace")
    return (r.stdout or r.stderr or "").strip()[-600:]

"""Friendly names for processes ("Google Chrome" instead of chrome.exe)."""
import os
import threading
import time

import psutil

try:
    import win32api
except Exception:  # pywin32 missing: fall back to exe names
    win32api = None

_lock = threading.Lock()
_pid_cache = {}     # pid -> (expires, info)
_desc_cache = {}    # exe path -> description


def _description(path):
    if path in _desc_cache:
        return _desc_cache[path]
    desc = None
    if win32api and path:
        try:
            langs = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")
            for lang, cp in langs or []:
                d = win32api.GetFileVersionInfo(
                    path, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription")
                if d and d.strip():
                    desc = d.strip()
                    break
        except Exception:
            desc = None
    _desc_cache[path] = desc
    return desc


def _pretty(exe_name):
    base = os.path.splitext(exe_name)[0]
    return base[:1].upper() + base[1:]


def _info(exe, exe_name):
    name = _description(exe) if exe else None
    # Some descriptions are useless ("Application", "Host Process") – keep exe name then.
    if not name or len(name) > 40 or name.lower() in {"application", "app"}:
        name = _pretty(exe_name)
    return {"name": name, "exe": exe, "exe_name": exe_name}


def describe_pid(pid, fallback_path=None):
    """fallback_path: the exe path when Windows hides the process (games with anti-cheat run
    protected, so it cannot be opened, but their audio session still names the exe)."""
    now = time.monotonic()
    with _lock:
        hit = _pid_cache.get(pid)
        if hit and hit[0] > now:
            return hit[1]
    try:
        p = psutil.Process(pid)
        exe_name = p.name()
        try:
            exe = p.exe()
        except (psutil.AccessDenied, OSError):
            exe = None
        info = _info(exe, exe_name)
    except psutil.NoSuchProcess:
        return None
    except (psutil.AccessDenied, ValueError):
        if not fallback_path or not psutil.pid_exists(pid):
            return None
        info = _info(fallback_path, os.path.basename(fallback_path))
    with _lock:
        _pid_cache[pid] = (now + 60, info)
    return info


_dos_devices = {}


def dos_path(nt_path):
    r"""\Device\HarddiskVolume2\Games\x.exe -> D:\Games\x.exe"""
    import ctypes
    import string
    if not _dos_devices:
        k32 = ctypes.WinDLL("kernel32")
        buf = ctypes.create_unicode_buffer(1024)
        for letter in string.ascii_uppercase:
            if k32.QueryDosDeviceW(f"{letter}:", buf, 1024):
                _dos_devices[buf.value.lower() + "\\"] = f"{letter}:\\"
    low = nt_path.lower()
    for dev, drive in _dos_devices.items():
        if low.startswith(dev):
            return drive + nt_path[len(dev):]
    return None

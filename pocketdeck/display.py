"""Monitor brightness (laptop panel via WMI, external monitors via DDC/CI) and projection mode.

screen_brightness_control uses pywin32's COM (WMI) and may initialise/uninitialise COM on the
thread it runs on. Sharing a thread with pycaw's COM objects crashed the process, so every
brightness call runs on one dedicated thread."""
import functools
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import screen_brightness_control as sbc


def _init_thread():
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)


_exec = ThreadPoolExecutor(1, initializer=_init_thread, thread_name_prefix="display")


def _on_display_thread(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if threading.current_thread().name.startswith("display"):
            return fn(*args, **kwargs)
        return _exec.submit(fn, *args, **kwargs).result()
    return wrapper


_lock = threading.Lock()
_monitors = {"at": 0.0, "list": []}


@_on_display_thread
def monitors(max_age=20.0):
    with _lock:
        if time.monotonic() - _monitors["at"] < max_age:
            return _monitors["list"]
    out = []
    try:
        infos = sbc.list_monitors_info()
    except Exception:
        infos = []
    for i, m in enumerate(infos):
        method = getattr(m.get("method"), "__name__", "")
        builtin = method == "WMI"
        label = "Laptop screen" if builtin else " ".join(
            x for x in (m.get("manufacturer"), m.get("model")) if x and x != "None") or f"Monitor {i + 1}"
        out.append({"index": i, "name": label, "builtin": builtin})
    with _lock:
        _monitors.update(at=time.monotonic(), list=out)
    return out


@_on_display_thread
def brightness():
    out = []
    for m in monitors():
        try:
            val = sbc.get_brightness(display=m["index"])[0]
        except Exception:
            val = None
        out.append({**m, "brightness": val})
    return out


@_on_display_thread
def set_brightness(value, display="all"):
    value = int(max(0, min(100, float(value))))
    targets = [m["index"] for m in monitors()] if display in ("all", None) else [int(display)]
    errors = []
    for idx in targets:
        try:
            sbc.set_brightness(value, display=idx)
        except Exception as e:  # DDC/CI disabled on the monitor, etc.
            errors.append(str(e))
    if errors and len(errors) == len(targets):
        raise OSError("Brightness change failed. For external monitors, turn on DDC/CI in the "
                      "monitor's on-screen menu.")


@_on_display_thread
def step_brightness(delta, display="all"):
    cur = [m for m in brightness() if m["brightness"] is not None]
    if display not in ("all", None):
        cur = [m for m in cur if m["index"] == int(display)]
    if not cur:
        raise OSError("No adjustable displays found")
    for m in cur:
        set_brightness(m["brightness"] + float(delta), m["index"])


def projection(mode):
    flag = {"internal": "/internal", "pc": "/internal", "clone": "/clone",
            "duplicate": "/clone", "extend": "/extend", "external": "/external",
            "second": "/external"}.get(mode)
    if not flag:
        raise ValueError(f"Unknown display mode '{mode}'")
    subprocess.Popen(["DisplaySwitch.exe", flag], creationflags=0x08000000)

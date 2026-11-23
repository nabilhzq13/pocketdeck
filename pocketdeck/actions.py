"""Runs one button action. Called on a COM-initialised worker thread.
Returns an optional short message that the phone shows as a toast."""
import os
import time

import psutil

from . import apps, audio, display, screens, sonar, winapi
from .procinfo import describe_pid

MEDIA_VK = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2}


def _launch(a, t):
    """Open an app, website or file; if a screen was chosen, move its window there."""
    screen = screens.resolve(a.get("screen"))
    before = screens.snapshot() if screen else None
    if t == "app":
        appid = a.get("appid") or apps.resolve(a.get("name", ""))
        if not appid:
            raise ValueError(f"App '{a.get('name')}' is not installed")
        apps.launch(appid)
    else:
        target = a.get("target") or a.get("url")
        if not target:
            raise ValueError("Nothing to open")
        if t == "url" and "://" not in target:
            target = "https://" + target
        winapi.launch(target, a.get("args"))
    if screen:
        screens.place_after_launch(before, screen, bool(a.get("maximize")))
        return f"Opening on {screen['name']}"
    return None


# Never force-quit these: Windows itself, shells and hosts shared by many programs, PocketDeck.
PROTECTED = {"explorer.exe", "applicationframehost.exe", "dwm.exe", "csrss.exe", "winlogon.exe",
             "svchost.exe", "lsass.exe", "services.exe", "searchhost.exe", "textinputhost.exe",
             "startmenuexperiencehost.exe", "shellexperiencehost.exe", "runtimebroker.exe",
             "dllhost.exe", "rundll32.exe", "msedgewebview2.exe", "conhost.exe", "openconsole.exe",
             "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe",
             "pythonw.exe"}


def _close_window(hwnd):
    """Close a window. If the app only hid itself in the system tray and keeps running, tell the
    phone so it can offer to quit the app completely."""
    pid = winapi.window_pid(hwnd)
    info = describe_pid(pid) or {}
    exe_name = (info.get("exe_name") or "").lower()
    winapi.window_command(hwnd, "close")
    if not pid or not info.get("exe") or exe_name in PROTECTED:
        return None  # Store apps (in ApplicationFrameHost) are suspended by Windows anyway
    for _ in range(12):
        time.sleep(0.25)
        if not winapi.window_shown(hwnd):
            break
    else:
        return None  # still open: the app is probably asking to save something
    time.sleep(0.6)
    if not psutil.pid_exists(pid):
        return None  # it really quit
    exe = info["exe"]
    for w in winapi.list_windows():  # another window of it is still open: nothing hidden
        other = describe_pid(w["pid"])
        if other and other.get("exe") == exe:
            return None
    return {"message": f"{info['name']} is still running in the background",
            "background": {"pid": pid, "exe": exe, "name": info["name"]}}


def _quit_app(pid, exe, name):
    """End the app's own process tree: its main process (climbing to the top process with the
    same name, as multi-process apps like Discord have) and everything it started."""
    try:
        proc = psutil.Process(int(pid))
        if (proc.exe() or "").lower() != (exe or "").lower():
            return f"{name} is already closed"  # that process id now belongs to something else
    except (psutil.NoSuchProcess, ValueError, TypeError):
        return f"{name} is already closed"
    except psutil.AccessDenied:
        raise OSError(f"Windows did not let PocketDeck quit {name}. It may be running as "
                      "administrator.")
    if os.path.basename(exe).lower() in PROTECTED:
        raise ValueError(f"PocketDeck does not force-quit {name}")
    root, own = proc, proc.name()
    while True:
        try:
            parent = root.parent()
        except psutil.Error:
            break
        if parent is None or parent.name() != own:
            break
        root = parent
    procs = [root] + root.children(recursive=True)
    denied = False
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            denied = True
    _, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            denied = True
    if denied:
        raise OSError(f"Windows did not let PocketDeck quit {name}. It may be running as "
                      "administrator.")
    return f"Quit {name}"


def _sonar(a):
    cmd = a.get("cmd", "preset")
    if cmd == "preset":
        return "Sonar: " + sonar.select_preset(a.get("preset", ""), a.get("device"))
    if cmd == "output":
        return "Sonar plays through " + sonar.set_output(a.get("output") or a.get("device", ""))
    if cmd == "volume":
        ch, change = a.get("channel", "master"), a.get("change", "up")
        label = dict(sonar.CHANNELS).get(sonar._channel(ch), "Sonar")
        if change == "mute":
            return f"{label} muted" if sonar.set_mute(ch, a.get("mode", "toggle")) else f"{label} on"
        if change == "set":
            sonar.set_volume(ch, a.get("value", 50))
        else:
            sonar.step_volume(ch, float(a.get("step", 10)) * (1 if change == "up" else -1))
        return None
    raise ValueError(f"Unknown Sonar command '{cmd}'")


def run(a):
    t = a.get("type")
    if t in ("app", "open", "url"):
        return _launch(a, t)
    elif t == "command":
        out = winapi.run_command(a["cmd"], a.get("shell", "cmd"), bool(a.get("wait")))
        return out or None
    elif t == "hotkey":
        winapi.hotkey(a["keys"])
    elif t == "text":
        winapi.type_text(a.get("text", "") + ("\n" if a.get("enter") else ""))
    elif t == "media":
        winapi.tap_vk(MEDIA_VK[a.get("cmd", "playpause")])
    elif t == "volume":
        cmd = a.get("cmd", "up")
        if cmd == "mute":
            return "Muted" if audio.set_master_mute(a.get("mode", "toggle")) else "Unmuted"
        if cmd == "set":
            audio.set_master(a["value"])
        else:
            audio.step_master(float(a.get("step", 5)) * (1 if cmd == "up" else -1))
    elif t == "mic":
        return "Mic muted" if audio.set_mic_mute(
            {"toggle": "toggle", "mute": "mute", "unmute": "unmute"}[a.get("cmd", "toggle")]
        ) else "Mic live"
    elif t == "audio_device":
        if a.get("cmd", "next") == "next":
            return "Output: " + audio.cycle_device(a.get("names"))
        devs = audio.devices()
        dev_id = a.get("id") if any(d["id"] == a.get("id") for d in devs) else None
        if not dev_id and a.get("name"):
            dev_id = next((d["id"] for d in devs if a["name"].lower() in d["name"].lower()), None)
        if not dev_id:
            raise ValueError("Output device not found (is it connected?)")
        audio.set_default_device(dev_id)
    elif t == "brightness":
        cmd = a.get("cmd", "up")
        target = a.get("display", "all")
        if cmd == "set":
            display.set_brightness(a["value"], target)
        else:
            display.step_brightness(float(a.get("step", 10)) * (1 if cmd == "up" else -1), target)
    elif t == "display":
        display.projection(a.get("mode", "extend"))
    elif t == "theme":
        return "Dark mode" if winapi.set_theme(a.get("mode", "toggle")) else "Light mode"
    elif t == "power_mode":
        winapi.set_power_mode(a.get("mode", "balanced"))
    elif t == "power":
        winapi.power(a.get("cmd", "lock"))
    elif t == "clipboard":
        winapi.set_clipboard(a.get("text", ""))
        return "Copied to PC clipboard"
    elif t == "window":
        if a.get("cmd") == "close":
            return _close_window(int(a["hwnd"]))
        winapi.window_command(int(a["hwnd"]), a.get("cmd", "focus"))
    elif t == "sonar":
        return _sonar(a)
    elif t == "quit_app":
        return _quit_app(a.get("pid"), a.get("exe", ""), a.get("name") or "The app")
    elif t == "delay":
        time.sleep(min(10.0, float(a.get("ms", 200)) / 1000))
    elif t == "macro":
        msg = None
        for step in a.get("steps", [])[:50]:
            r = run(step)
            msg = (r.get("message") if isinstance(r, dict) else r) or msg
        return msg
    elif t == "page":
        return None  # handled on the phone
    else:
        raise ValueError(f"Unknown action type '{t}'")
    return None

"""Installed apps from the Start menu (desktop + Store apps), launched through shell:AppsFolder."""
import json
import os
import re
import subprocess
import threading
import time

_SKIP = re.compile(r"uninstall|readme|release notes|\bhelp\b|manual|documentation|license|"
                   r"module docs|error reporter|updater|troubleshooter", re.I)
_lock = threading.Lock()
_cache = {"at": 0.0, "apps": []}


def list_apps(max_age=600):
    with _lock:
        if _cache["apps"] and time.monotonic() - _cache["at"] < max_age:
            return _cache["apps"]
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
        capture_output=True, timeout=30, creationflags=0x08000000)
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    apps, seen = [], set()
    for a in data:
        name, appid = (a.get("Name") or "").strip(), (a.get("AppID") or "").strip()
        if not name or not appid or appid.lower().startswith(("http:", "https:")):
            continue
        if _SKIP.search(name) or name.startswith("{"):
            continue
        if (name.lower(), appid.lower()) in seen:
            continue
        seen.add((name.lower(), appid.lower()))
        apps.append({"name": name, "appid": appid})
    apps.sort(key=lambda a: a["name"].lower())
    with _lock:
        _cache.update(at=time.monotonic(), apps=apps)
    return apps


def resolve(name):
    """Find an AppID by (case-insensitive) app name; exact match first, then prefix."""
    apps = list_apps()
    low = name.lower()
    for a in apps:
        if a["name"].lower() == low:
            return a["appid"]
    for a in apps:
        if a["name"].lower().startswith(low):
            return a["appid"]
    return None


def launch(appid):
    try:
        os.startfile("shell:AppsFolder\\" + appid)
    except OSError:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid])

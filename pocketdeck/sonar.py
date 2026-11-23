"""SteelSeries Sonar control through the local web service that SteelSeries GG runs.

GG writes its address to coreProps.json; GG's /subApps tells where Sonar's own service listens
(the port changes every time GG starts). Only the Classic mode mixer is supported for volumes."""
import json
import ssl
import threading
import time
import urllib.error
import urllib.request

CORE_PROPS = r"C:\ProgramData\SteelSeries\GG\coreProps.json"
CHANNELS = [("master", "Master"), ("game", "Game"), ("chatRender", "Chat"), ("media", "Media"),
            ("aux", "Aux"), ("chatCapture", "Mic")]
PRESET_DEVICES = [("game", "Game"), ("chatRender", "Chat"), ("media", "Media"), ("aux", "Aux"),
                  ("chatCapture", "Mic")]
OUTPUT_ROUTES = ["game", "chat", "media", "aux"]   # Sonar's names for the playback channels

_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE     # GG uses a self-signed certificate on 127.0.0.1
_lock = threading.Lock()
_state = {"base": None, "configs": None, "configs_at": 0.0}


class SonarUnavailable(OSError):
    pass


def _http(method, url, timeout=3.0):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, context=_ssl if url.startswith("https") else None,
                                timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else None


def _discover():
    try:
        with open(CORE_PROPS, encoding="utf-8") as f:
            gg = json.load(f)["ggEncryptedAddress"]
        sonar = _http("GET", f"https://{gg}/subApps")["subApps"]["sonar"]
    except (OSError, KeyError, ValueError) as e:
        raise SonarUnavailable("SteelSeries GG is not running") from e
    if not (sonar.get("isEnabled") and sonar.get("isRunning")):
        raise SonarUnavailable("Sonar is turned off in SteelSeries GG")
    return sonar["metadata"]["webServerAddress"]


def _call(method, path):
    """Call Sonar; if GG restarted (new port), find it again and retry once."""
    for attempt in (0, 1):
        with _lock:
            if not _state["base"] or attempt:
                _state["base"] = _discover()
            base = _state["base"]
        try:
            return _http(method, base + path)
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError):
            if attempt:
                raise SonarUnavailable("Sonar is not answering")
    return None


def _configs(max_age=120.0):
    with _lock:
        fresh = _state["configs"] is not None and time.monotonic() - _state["configs_at"] < max_age
        if fresh:
            return _state["configs"]
    data = _call("GET", "/configs") or []
    slim = [{"id": c["id"], "name": c["name"], "device": c["virtualAudioDevice"],
             "favorite": bool(c.get("isFavorite")), "order": c.get("favoritePosition") or 0}
            for c in data]
    with _lock:
        _state.update(configs=slim, configs_at=time.monotonic())
    return slim

# ---------------------------------------------------------------- reading


def status():
    """Everything the Sonar panel shows. None when Sonar is not available."""
    try:
        mode = _call("GET", "/mode/")
        selected = {c["virtualAudioDevice"]: {"id": c["id"], "name": c["name"]}
                    for c in _call("GET", "/configs/selected") or []}
        routes = {r["id"]: r["deviceId"] for r in _call("GET", "/classicRedirections") or []}
        outputs = [{"id": d["id"], "name": d["friendlyName"]}
                   for d in _call("GET", "/audioDevices") or []
                   if d.get("dataFlow") == "render" and not d.get("isVad")
                   and d.get("state") == "active"]
        channels = []
        if mode == "classic":
            vol = _call("GET", "/volumeSettings/classic")
            for cid, name in CHANNELS:
                src = vol["masters"]["classic"] if cid == "master" else vol["devices"][cid]["classic"]
                channels.append({"id": cid, "name": name, "volume": round(src["volume"] * 100),
                                 "muted": bool(src["muted"])})
        favorites = {}
        for c in sorted((c for c in _configs() if c["favorite"]), key=lambda c: c["order"]):
            favorites.setdefault(c["device"], []).append({"id": c["id"], "name": c["name"]})
    except SonarUnavailable as e:
        return {"available": False, "reason": str(e)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "reason": "Sonar sent something unexpected"}
    used = {routes.get(r) for r in OUTPUT_ROUTES if routes.get(r)}
    return {"available": True, "mode": mode, "channels": channels,
            "presets": {d: selected.get(d) for d, _ in PRESET_DEVICES},
            "favorites": favorites, "outputs": outputs,
            "output": used.pop() if len(used) == 1 else ("mixed" if used else None)}


def presets(device):
    """All presets for one channel, favourites first."""
    items = [c for c in _configs(max_age=10) if c["device"] == device]
    items.sort(key=lambda c: (not c["favorite"], c["order"] if c["favorite"] else 0,
                              c["name"].lower()))
    return [{"id": c["id"], "name": c["name"], "favorite": c["favorite"]} for c in items]

# ---------------------------------------------------------------- changing


def _channel(cid):
    ids = {c for c, _ in CHANNELS}
    aliases = {"chat": "chatRender", "mic": "chatCapture", "microphone": "chatCapture"}
    cid = aliases.get(str(cid).lower(), cid)
    if cid not in ids:
        raise ValueError(f"Unknown Sonar channel '{cid}'")
    return cid


def _volume_now(cid):
    vol = _call("GET", "/volumeSettings/classic")
    src = vol["masters"]["classic"] if cid == "master" else vol["devices"][cid]["classic"]
    return src["volume"] * 100, bool(src["muted"])


def set_volume(cid, value):
    cid = _channel(cid)
    v = max(0.0, min(100.0, float(value))) / 100
    _call("PUT", f"/volumeSettings/classic/{cid}/Volume/{json.dumps(round(v, 3))}")


def step_volume(cid, delta):
    cid = _channel(cid)
    now, _ = _volume_now(cid)
    set_volume(cid, now + float(delta))


def set_mute(cid, mode="toggle"):
    cid = _channel(cid)
    _, muted = _volume_now(cid)
    new = (not muted) if mode == "toggle" else mode == "mute"
    _call("PUT", f"/volumeSettings/classic/{cid}/Mute/{json.dumps(new)}")
    return new


def select_preset(preset, device=None):
    """preset: an id, or a name (matched within `device` when given)."""
    items = _configs(max_age=10)
    if device:
        items = [c for c in items if c["device"] == _device(device)]
    hit = next((c for c in items if c["id"] == preset), None) or next(
        (c for c in items if c["name"].lower() == str(preset).lower()), None)
    if not hit:
        raise ValueError(f"Sonar preset '{preset}' not found")
    _call("PUT", f"/configs/{hit['id']}/select")
    return hit["name"]


def _device(d):
    return {"chat": "chatRender", "mic": "chatCapture"}.get(str(d).lower(), d)


def set_output(device):
    """Send all of Sonar's playback channels to one speaker/headset (id or part of its name)."""
    outs = [d for d in _call("GET", "/audioDevices") or []
            if d.get("dataFlow") == "render" and not d.get("isVad") and d.get("state") == "active"]
    hit = next((d for d in outs if d["id"] == device), None) or next(
        (d for d in outs if str(device).lower() in d["friendlyName"].lower()), None)
    if not hit:
        raise ValueError(f"Output '{device}' is not connected")
    for route in OUTPUT_ROUTES:
        _call("PUT", f"/classicRedirections/{route}/deviceId/{hit['id']}")
    return hit["friendlyName"]

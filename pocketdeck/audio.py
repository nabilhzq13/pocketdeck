"""Audio: master volume, microphone, per-app mixer and output-device switching.

Talks to Windows Core Audio through pycaw's interface definitions, but not through pycaw's
helpers: those read every property of every device on each call. Interfaces are always obtained
with QueryInterface (never ctypes.cast, which skips AddRef and later double-releases the object
and corrupts memory). Must run on a thread that has initialised COM."""
import comtypes
from comtypes import CLSCTX_ALL, GUID
from pycaw.api.audioclient import ISimpleAudioVolume
from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
from pycaw.api.endpointvolume import IAudioEndpointVolume
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY
from pycaw.constants import CLSID_MMDeviceEnumerator, ERole
from pycaw.pycaw import AudioUtilities

from .procinfo import describe_pid, dos_path

RENDER, CAPTURE = 0, 1
_PK_FRIENDLY_NAME = PROPERTYKEY()
_PK_FRIENDLY_NAME.fmtid = GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}")
_PK_FRIENDLY_NAME.pid = 14


def _enumerator():
    return comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                                     comtypes.CLSCTX_INPROC_SERVER)


def _default(flow):
    try:
        return _enumerator().GetDefaultAudioEndpoint(flow, ERole.eMultimedia.value)
    except comtypes.COMError:  # no device of that kind
        return None


def _name(dev):
    try:
        pv = dev.OpenPropertyStore(0).GetValue(_PK_FRIENDLY_NAME)  # 0 = STGM_READ
        try:
            return pv.GetValue() or ""
        finally:
            pv.clear()
    except comtypes.COMError:
        return ""


def _endpoint_volume(dev):
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return iface.QueryInterface(IAudioEndpointVolume)


def _volume_of(flow):
    dev = _default(flow)
    if dev is None:
        return None, None
    return dev, _endpoint_volume(dev)

# ---------------------------------------------------------------- master & mic


def master():
    dev, ev = _volume_of(RENDER)
    if ev is None:
        return None
    return {"id": dev.GetId(), "name": _name(dev),
            "volume": round(ev.GetMasterVolumeLevelScalar() * 100), "muted": bool(ev.GetMute())}


def _clamp(v):
    return max(0.0, min(100.0, float(v)))


def set_master(value):
    _, ev = _volume_of(RENDER)
    if ev is None:
        raise OSError("No speakers or headphones found")
    value = _clamp(value)
    ev.SetMasterVolumeLevelScalar(value / 100, None)
    if value > 0 and ev.GetMute():
        ev.SetMute(0, None)


def step_master(delta):
    _, ev = _volume_of(RENDER)
    if ev is None:
        raise OSError("No speakers or headphones found")
    set_master(ev.GetMasterVolumeLevelScalar() * 100 + float(delta))


def _toggle_mute(flow, mode, missing):
    _, ev = _volume_of(flow)
    if ev is None:
        raise OSError(missing)
    new = (not ev.GetMute()) if mode == "toggle" else mode == "mute"
    ev.SetMute(int(new), None)
    return new


def set_master_mute(mode="toggle"):
    return _toggle_mute(RENDER, mode, "No speakers or headphones found")


def mic():
    dev, ev = _volume_of(CAPTURE)
    if ev is None:
        return None
    return {"name": _name(dev) or "Microphone",
            "volume": round(ev.GetMasterVolumeLevelScalar() * 100), "muted": bool(ev.GetMute())}


def set_mic(value):
    _, ev = _volume_of(CAPTURE)
    if ev is None:
        raise OSError("No microphone found")
    ev.SetMasterVolumeLevelScalar(_clamp(value) / 100, None)


def set_mic_mute(mode="toggle"):
    return _toggle_mute(CAPTURE, mode, "No microphone found")

# ---------------------------------------------------------------- per-app mixer


def _raw_sessions():
    """Yields (pid, exe path from the session id, ISimpleAudioVolume) for every live session on
    every active output. Apps are often not on the default output: SteelSeries Sonar puts games
    on "Sonar - Gaming", and Windows lets you pick an output per app."""
    coll = _enumerator().EnumAudioEndpoints(RENDER, 1)  # DEVICE_STATE_ACTIVE
    for d in range(coll.GetCount()):
        try:
            dev = coll.Item(d)
            mgr = dev.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(
                IAudioSessionManager2)
            sessions = mgr.GetSessionEnumerator()
            count = sessions.GetCount()
        except comtypes.COMError:
            continue
        for i in range(count):
            try:
                ctl = sessions.GetSession(i)
                if ctl is None:
                    continue
                ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                if ctl2.GetState() == 2:  # AudioSessionStateExpired
                    continue
                pid = ctl2.GetProcessId()
                ident = ctl2.GetSessionIdentifier() or ""
                vol = ctl2.QueryInterface(ISimpleAudioVolume)
            except comtypes.COMError:
                continue
            yield pid, _exe_from_identifier(ident), vol


def _exe_from_identifier(ident):
    r"""'{dev}|\Device\HarddiskVolume2\Riot Games\...\VALORANT-Win64-Shipping.exe%b{..}'"""
    if "|" not in ident:
        return None
    nt = ident.split("|", 1)[1].split("%", 1)[0]
    if not nt.lower().endswith(".exe"):
        return None
    return dos_path(nt) or nt


def _session_key(pid, exe_path=None):
    if pid == 0:
        return "system", {"name": "System sounds", "exe": None}
    info = describe_pid(pid, exe_path)
    if not info:
        return None, None
    return info["exe_name"].lower(), info


# Audio plumbing, not apps: SteelSeries Sonar's routing streams and Windows' audio engine.
HIDDEN = {"audiodg.exe", "steelseriessonar.exe", "steelseriesggclient.exe"}


def sessions():
    """One row per app (Chrome opens several sessions; they are merged)."""
    rows = {}
    for pid, exe_path, vol in _raw_sessions():
        key, info = _session_key(pid, exe_path)
        if not key or key in HIDDEN:
            continue
        row = rows.setdefault(key, {"key": key, "name": info["name"], "exe": info["exe"],
                                    "volume": 0, "muted": True})
        row["volume"] = max(row["volume"], round(vol.GetMasterVolume() * 100))
        row["muted"] = row["muted"] and bool(vol.GetMute())
    return sorted(rows.values(), key=lambda r: (r["key"] == "system", r["name"].lower()))


def _matching(key):
    return [vol for pid, exe, vol in _raw_sessions() if _session_key(pid, exe)[0] == key]


def set_session(key, value):
    targets = _matching(key)
    if not targets:
        raise ValueError("That app is not playing audio any more")
    value = _clamp(value) / 100
    for vol in targets:
        vol.SetMasterVolume(value, None)
        if value > 0 and vol.GetMute():
            vol.SetMute(0, None)


def set_session_mute(key, mode="toggle"):
    targets = _matching(key)
    if not targets:
        raise ValueError("That app is not playing audio any more")
    new = (not all(v.GetMute() for v in targets)) if mode == "toggle" else mode == "mute"
    for vol in targets:
        vol.SetMute(int(new), None)
    return new

# ---------------------------------------------------------------- output devices


def devices():
    default = _default(RENDER)
    default_id = default.GetId() if default is not None else None
    coll = _enumerator().EnumAudioEndpoints(RENDER, 1)  # DEVICE_STATE_ACTIVE
    out = []
    for i in range(coll.GetCount()):
        dev = coll.Item(i)
        dev_id = dev.GetId()
        out.append({"id": dev_id, "name": _name(dev) or "Audio device",
                    "default": dev_id == default_id})
    out.sort(key=lambda d: d["name"].lower())
    return out


def set_default_device(dev_id):
    AudioUtilities.SetDefaultDevice(
        dev_id, roles=[ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])


def cycle_device(names=None):
    """Switch to the next active output. `names` optionally limits the cycle to devices whose
    name contains one of the given strings."""
    devs = devices()
    if names:
        devs = [d for d in devs if any(n.lower() in d["name"].lower() for n in names)]
    if not devs:
        raise OSError("No matching output devices")
    idx = next((i for i, d in enumerate(devs) if d["default"]), -1)
    nxt = devs[(idx + 1) % len(devs)]
    set_default_device(nxt["id"])
    return nxt["name"]

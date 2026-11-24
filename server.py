"""PocketDeck – turn a phone or iPad into a Stream Deck for this Windows PC.

Run:  python server.py              (opens the pairing page on this PC)
      python server.py --no-browser
      pythonw server.py --background (hidden, restarts after a crash; see autostart.ps1)
      python server.py --stop        (stops the background server)
"""
import os
import site
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(os.path.join(ROOT, ".deps"))

if "--background" in sys.argv or "--stop" in sys.argv:
    from pocketdeck import launcher
    sys.exit(launcher.main(ROOT, sys.argv))

# COM in multithreaded mode everywhere: COM objects may be garbage-collected on a different
# thread than the one that made them, which crashes in single-threaded (STA) mode.
sys.coinit_flags = 0  # COINIT_MULTITHREADED, read by comtypes on import

import ctypes  # noqa: E402
import faulthandler  # noqa: E402

# Real pixel coordinates on every screen, so windows land where intended on mixed-DPI setups.
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2

_crash_log = open(os.path.join(ROOT, "crash.log"), "a", encoding="utf-8")
faulthandler.enable(_crash_log)  # writes a traceback here if the process ever crashes natively

import asyncio  # noqa: E402
import hmac  # noqa: E402
import ipaddress  # noqa: E402
import json  # noqa: E402
from html import escape as html_escape  # noqa: E402
import logging  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

import comtypes  # noqa: E402
import psutil  # noqa: E402
from aiohttp import WSMsgType, web  # noqa: E402

from pocketdeck import actions, apps, audio, display, screens, sonar, stats, winapi  # noqa: E402
from pocketdeck.appicon import make_app_icon  # noqa: E402
from pocketdeck.icons import IconCache  # noqa: E402
from pocketdeck.media import NowPlaying  # noqa: E402
from pocketdeck.procinfo import describe_pid  # noqa: E402

VERSION = "1.0"
WEB = os.path.join(ROOT, "web")
CONFIG = os.path.join(ROOT, "config.json")
DEFAULT_CONFIG = os.path.join(ROOT, "config.default.json")
SETTINGS = os.path.join(ROOT, "settings.json")
CACHE = os.path.join(ROOT, "cache")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pocketdeck")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("screen_brightness_control").setLevel(logging.CRITICAL)  # noisy EDID warnings

# ------------------------------------------------------------------ settings & config


def load_settings():
    data = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
    changed = False
    if not data.get("token"):
        data["token"], changed = secrets.token_urlsafe(18), True
    if not data.get("port"):
        data["port"], changed = 8765, True
    if "gpu_stats" not in data:
        data["gpu_stats"], changed = True, True
    if changed:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    return data


def load_config():
    if not os.path.exists(CONFIG):
        save_config(first_run_config())
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def first_run_config():
    """The starter layout, trimmed to this PC: app buttons only for apps that are installed, and
    the Sonar page only when SteelSeries GG is installed."""
    with open(DEFAULT_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        installed = bool(apps.list_apps())
    except Exception:
        installed = False  # can't tell: keep every button
    has_sonar = os.path.exists(sonar.CORE_PROPS)
    pages = []
    for page in cfg["pages"]:
        if page.get("name") == "Sonar" and not has_sonar:
            continue
        keep = []
        for item in page.get("items", []):
            a = item.get("action") or {}
            if installed and a.get("type") == "app" and not apps.resolve(a.get("name", "")):
                continue
            if item.get("widget") == "sonar" and not has_sonar:
                continue
            keep.append(item)
        page["items"] = keep
        pages.append(page)
    cfg["pages"] = pages
    log.info("Created config.json for this PC")
    return cfg


def save_config(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get("pages"), list) or not cfg["pages"]:
        raise ValueError("Config needs at least one page")
    if os.path.exists(CONFIG):
        shutil.copyfile(CONFIG, CONFIG + ".bak")
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


TAILNET = ipaddress.ip_network("100.64.0.0/10")  # addresses Tailscale hands out


def lan_addresses():
    skip = ("virtualbox", "vmware", "vethernet", "loopback", "hyper-v", "wsl")
    skip_ips = ("192.168.56.",)  # VirtualBox host-only network
    stats_ = psutil.net_if_stats()
    found = []
    for name, addrs in psutil.net_if_addrs().items():
        if any(s in name.lower() for s in skip) or not stats_.get(name, None) or not stats_[name].isup:
            continue
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.", *skip_ips)):
                if name.lower().startswith("tailscale") or ipaddress.ip_address(a.address) in TAILNET:
                    # Tailscale: same address on every network, even when the phone is elsewhere
                    rank, label = -1, "Tailscale"
                elif a.address.startswith("192.168.137."):  # Windows Mobile hotspot
                    rank, label = 0, "Mobile hotspot"
                elif "bluetooth" in name.lower():
                    # e.g. joined an iPhone's Personal Hotspot over Bluetooth: no Wi-Fi needed
                    rank, label = 0, "Bluetooth"
                elif "wi-fi" in name.lower() or "wlan" in name.lower():
                    rank, label = 1, "Wi-Fi"
                elif "ethernet" in name.lower():
                    rank, label = 2, "Ethernet"
                else:
                    rank, label = 3, name
                found.append((rank, a.address, name, label))
    found.sort()
    return [{"ip": ip, "adapter": name, "label": label} for _, ip, name, label in found]


def network_names():
    """Interface alias -> network name (e.g. "Home Wi-Fi"), for labelling the pairing codes."""
    import subprocess
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetConnectionProfile | ForEach-Object { $_.InterfaceAlias + '|' + $_.Name }"],
            capture_output=True, text=True, timeout=8, creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return dict(line.split("|", 1) for line in out.splitlines() if "|" in line)

# ------------------------------------------------------------------ worker threads


def _com_init():
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)


def _com_init_sta():
    comtypes.CoInitialize()  # the shell icon APIs prefer single-threaded COM


class Coalescer:
    """For sliders: only the newest value per key is applied; stale values are dropped."""

    def __init__(self, name, on_error):
        self.pending, self.cv, self.on_error = {}, threading.Condition(), on_error
        threading.Thread(target=self._loop, name=name, daemon=True).start()

    def put(self, key, fn, value):
        with self.cv:
            self.pending[key] = (fn, value)
            self.cv.notify()

    def _loop(self):
        _com_init()
        while True:
            with self.cv:
                while not self.pending:
                    self.cv.wait()
                key = next(iter(self.pending))
                fn, value = self.pending.pop(key)
            try:
                fn(value)
            except Exception as e:
                self.on_error(key, e)


class Deck:
    def __init__(self):
        self.settings = load_settings()
        self.token = self.settings["token"]
        stats.enable_gpu(self.settings.get("gpu_stats", True))
        self.config = load_config()
        self.config_mtime = os.path.getmtime(CONFIG)
        self.clients = set()
        self.status = {}
        self.last_sent = ""
        self.pool = ThreadPoolExecutor(4, initializer=_com_init, thread_name_prefix="action")
        self.status_pool = ThreadPoolExecutor(1, initializer=_com_init, thread_name_prefix="status")
        # SteelSeries Sonar is read over HTTP on its own thread, so a slow GG never stalls the deck
        self.sonar_pool = ThreadPoolExecutor(1, thread_name_prefix="sonar")
        self.sonar_status = None
        self._sonar_job = None
        # one thread: the shell image list is not reliable when used from several threads
        self.icon_pool = ThreadPoolExecutor(1, initializer=_com_init_sta, thread_name_prefix="icon")
        self.icons = IconCache(os.path.join(CACHE, "icons"))
        self.media = NowPlaying()
        self.loop = None
        self._err_at = {}
        self.audio_set = Coalescer("audio-set", self._set_error)
        self.bright_set = Coalescer("brightness-set", self._set_error)
        self.wake = None

    # ---------------------------------------------------------------- status

    def _collect(self, tick):
        s = dict(self.status)

        def safe(key, fn):
            try:
                s[key] = fn()
            except Exception as e:
                log.debug("status %s failed: %s", key, e)
                s[key] = None

        safe("volume", audio.master)
        safe("mic", audio.mic)
        safe("sessions", audio.sessions)
        safe("windows", self._windows)
        if tick % 3 == 0 or "devices" not in s:
            safe("devices", audio.devices)
            safe("displays", display.brightness)
            safe("screens", lambda: screens.public(screens.list_screens()))
            safe("dark", winapi.is_dark)
            safe("power_mode", winapi.get_power_mode)
        if tick % 2 == 0 or "stats" not in s:
            safe("stats", stats.snapshot)
        return s

    def _windows(self):
        out = []
        for w in winapi.list_windows():
            info = describe_pid(w["pid"]) or {}
            exe_name = (info.get("exe_name") or "").lower()
            if exe_name in ("textinputhost.exe",):
                continue
            if exe_name == "applicationframehost.exe":
                real = winapi.uwp_pid(w["hwnd"], w["pid"])
                info = (describe_pid(real) if real != w["pid"] else None) or {
                    "name": w["title"], "exe": None}
            out.append({"hwnd": w["hwnd"], "title": w["title"], "active": w["active"],
                        "minimized": w["minimized"], "app": info.get("name", ""),
                        "exe": info.get("exe")})
        return out

    async def status_loop(self):
        tick = 0
        while True:
            if self.clients:
                try:
                    s = await self.loop.run_in_executor(self.status_pool, self._collect, tick)
                    s["media"] = await self.media.read()
                    if tick % 2 == 0:
                        self.refresh_sonar()
                    s["sonar"] = self.sonar_status
                    self.status = s
                    await self.push_status()
                except Exception as e:
                    log.warning("status loop: %s", e)
                if tick % 2 == 0:
                    await self._check_config_file()
                tick += 1
            self.wake = asyncio.Event()
            try:
                await asyncio.wait_for(self.wake.wait(), 1.0)
            except asyncio.TimeoutError:
                pass

    def refresh_sonar(self):
        if self._sonar_job is not None and not self._sonar_job.done():
            return
        self._sonar_job = self.loop.run_in_executor(self.sonar_pool, sonar.status)

        def done(fut):
            if not fut.cancelled() and fut.exception() is None:
                self.sonar_status = fut.result()
        self._sonar_job.add_done_callback(done)

    def poke(self):
        """Refresh status soon (after an action) instead of waiting a full second."""
        if self.wake is not None:
            self.loop.call_later(0.25, self.wake.set)

    async def push_status(self, force=False):
        msg = json.dumps({"op": "status", "status": self.status}, separators=(",", ":"))
        if force or msg != self.last_sent:
            self.last_sent = msg
            await self.broadcast_raw(msg)

    async def broadcast_raw(self, msg):
        for ws in list(self.clients):
            try:
                await ws.send_str(msg)
            except Exception:
                self.clients.discard(ws)

    async def broadcast(self, obj):
        await self.broadcast_raw(json.dumps(obj, separators=(",", ":")))

    async def _check_config_file(self):
        try:
            m = os.path.getmtime(CONFIG)
        except OSError:
            return
        if m != self.config_mtime:
            self.config_mtime = m
            try:
                self.config = load_config()
                await self.broadcast({"op": "config", "config": self.config})
                log.info("config.json changed on disk – reloaded")
            except Exception as e:
                log.warning("config.json is invalid, keeping the old one: %s", e)

    def _set_error(self, key, err):
        now = time.monotonic()
        if now - self._err_at.get(key, 0) > 5:
            self._err_at[key] = now
            asyncio.run_coroutine_threadsafe(
                self.broadcast({"op": "toast", "error": True, "message": str(err)}), self.loop)

    # ---------------------------------------------------------------- websocket

    async def ws_handler(self, request):
        if not hmac.compare_digest(request.query.get("token", ""), self.token):
            return web.Response(status=401, text="Bad token – scan the QR code again")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        self.clients.add(ws)
        log.info("phone connected: %s (%d online)", request.remote, len(self.clients))
        await ws.send_json({"op": "hello", "config": self.config, "status": self.status,
                            "server": {"name": socket.gethostname(), "version": VERSION}})
        self.poke()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                asyncio.create_task(self.handle(ws, data))
        finally:
            self.clients.discard(ws)
            log.info("phone disconnected: %s", request.remote)
        return ws

    async def reply(self, ws, rid, ok=True, message=None, **extra):
        if rid is None:
            return
        try:
            await ws.send_json({"op": "result", "id": rid, "ok": ok, "message": message, **extra})
        except Exception:
            pass

    async def handle(self, ws, d):
        op, rid = d.get("op"), d.get("id")
        try:
            if op == "action":
                a = d.get("action") or {}
                msg = None
                if a.get("type") == "media" and await self.media.control(a.get("cmd", "playpause")):
                    pass
                else:
                    msg = await self.loop.run_in_executor(self.pool, actions.run, a)
                extra = {}
                if isinstance(msg, dict):  # e.g. {"message": ..., "background": {...}}
                    extra = {k: v for k, v in msg.items() if k != "message"}
                    msg = msg.get("message")
                await self.reply(ws, rid, True, msg, **extra)
                if a.get("type") == "sonar":
                    self.refresh_sonar()
                self.poke()
            elif op == "set":
                self._set(d.get("target"), d.get("key"), d.get("value"))
            elif op == "mouse":
                winapi.mouse_move(d.get("dx", 0), d.get("dy", 0))
            elif op == "click":
                winapi.mouse_click(d.get("button", "left"), bool(d.get("double")))
            elif op == "mouse_button":
                winapi.mouse_button(d.get("button", "left"), bool(d.get("pressed")))
            elif op == "scroll":
                winapi.mouse_scroll(d.get("dy", 0), d.get("dx", 0))
            elif op == "session_mute":
                await self.loop.run_in_executor(self.pool, audio.set_session_mute, d["key"])
                self.poke()
            elif op == "save_config":
                await self.loop.run_in_executor(None, save_config, d.get("config"))
                self.config = d["config"]
                self.config_mtime = os.path.getmtime(CONFIG)
                # config first, so the phone has the new layout when the reply arrives
                await self.broadcast({"op": "config", "config": self.config})
                await self.reply(ws, rid, True, "Saved")
            elif op == "apps":
                lst = await self.loop.run_in_executor(self.pool, apps.list_apps, 0 if d.get("refresh") else 600)
                await self.reply(ws, rid, True, apps=lst)
            elif op == "sonar_presets":
                lst = await self.loop.run_in_executor(self.sonar_pool, sonar.presets, d.get("device", "game"))
                await self.reply(ws, rid, True, presets=lst)
            elif op == "clipboard_get":
                text = await self.loop.run_in_executor(self.pool, winapi.get_clipboard)
                await self.reply(ws, rid, True, text=text)
            elif op == "refresh":
                await self.push_status(force=True)
            else:
                raise ValueError(f"Unknown op '{op}'")
        except Exception as e:
            log.warning("%s failed: %s", op, e)
            await self.reply(ws, rid, False, str(e) or e.__class__.__name__)

    def _set(self, target, key, value):
        value = float(value)
        if target == "volume":
            self.audio_set.put("volume", audio.set_master, value)
        elif target == "mic":
            self.audio_set.put("mic", audio.set_mic, value)
        elif target == "session":
            self.audio_set.put("session:" + str(key), lambda v, k=key: audio.set_session(k, v), value)
        elif target == "sonar":
            ch = str(key)
            self.audio_set.put("sonar:" + ch, lambda v, ch=ch: sonar.set_volume(ch, v), value)
        elif target == "brightness":
            k = "all" if key in (None, "all") else int(key)
            self.bright_set.put("bright:" + str(k), lambda v, k=k: display.set_brightness(v, k), value)
        else:
            raise ValueError(f"Unknown slider '{target}'")

    # ---------------------------------------------------------------- http

    def _authed(self, request):
        return hmac.compare_digest(request.query.get("token", ""), self.token)

    async def icon(self, request):
        if not self._authed(request):
            return web.Response(status=401)
        src = request.query.get("src", "")
        if not src and request.query.get("app"):
            appid = await self.loop.run_in_executor(self.pool, apps.resolve, request.query["app"])
            src = "app:" + appid if appid else ""
        if not src:
            return web.Response(status=404)
        data = await self.loop.run_in_executor(self.icon_pool, self.icons.get, src)
        if not data:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/png",
                            headers={"Cache-Control": "max-age=604800"})

    async def art(self, request):
        if not self._authed(request):
            return web.Response(status=401)
        item = self.media.art.get(request.match_info["h"])
        if not item:
            return web.Response(status=404)
        return web.Response(body=item[0], content_type=item[1],
                            headers={"Cache-Control": "max-age=86400"})

    async def ping(self, request):
        return web.Response(status=200 if self._authed(request) else 401, text="ok")

    async def index(self, request):
        return web.FileResponse(os.path.join(WEB, "index.html"),
                                headers={"Cache-Control": "no-cache"})

    async def app_icon(self, request):
        size = 512 if "512" in request.path else 180
        path = os.path.join(CACHE, f"appicon-{size}.png")
        if not os.path.exists(path):
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "wb") as f:
                f.write(make_app_icon(size))
        return web.FileResponse(path, headers={"Cache-Control": "max-age=86400"})

    async def pair(self, request):
        if request.remote not in ("127.0.0.1", "::1"):
            return web.Response(status=403, text="Open the pairing page on the PC itself.")
        import qrcode
        import qrcode.image.svg
        port = self.settings["port"]
        addrs = lan_addresses()
        nets = await self.loop.run_in_executor(None, network_names)
        # One code per network: the address changes with every Wi-Fi (home, campus, hotspot).
        cards = []
        for a in addrs:
            link = f"http://{a['ip']}:{port}/#t={self.token}"
            svg = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage,
                              box_size=12, border=2).to_string(encoding="unicode")
            if a["label"] == "Tailscale":
                title = "Tailscale: works on any network"
            else:
                title = a["label"] + (f": {nets[a['adapter']]}" if nets.get(a["adapter"]) else "")
            cards.append(f'<figure class="card"><div class="qr">{svg}</div><figcaption>'
                         f'<b>{html_escape(title)}</b><span>http://{a["ip"]}:{port}</span>'
                         f'</figcaption></figure>')
        if not cards:
            cards.append('<p>No network found. Connect to Wi-Fi or turn on Mobile hotspot, '
                         'then reload this page.</p>')
        with open(os.path.join(WEB, "pair.html"), encoding="utf-8") as f:
            html = f.read()
        rows = "".join(f'<li><code>{a["ip"]}</code><span>{html_escape(a["label"])}</span></li>'
                       for a in addrs)
        html = (html.replace("{{CARDS}}", "".join(cards))
                .replace("{{ADDRS}}", rows or "<li>No network found. Connect to Wi-Fi.</li>")
                .replace("{{FIRST_IP}}", addrs[0]["ip"] if addrs else "localhost")
                .replace("{{TOKEN}}", self.token)
                .replace("{{PORT}}", str(port)).replace("{{LOCAL}}", f"http://localhost:{port}/#t={self.token}"))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


async def main():
    deck = Deck()
    deck.loop = asyncio.get_running_loop()

    def quiet_resets(loop, ctx):
        # A phone that sleeps drops its connection abruptly; Windows reports that as an error.
        if isinstance(ctx.get("exception"), ConnectionResetError):
            return
        loop.default_exception_handler(ctx)

    deck.loop.set_exception_handler(quiet_resets)
    app = web.Application(middlewares=[no_cache])
    app.router.add_get("/", deck.index)
    app.router.add_get("/ws", deck.ws_handler)
    app.router.add_get("/icon", deck.icon)
    app.router.add_get("/art/{h}", deck.art)
    app.router.add_get("/pair", deck.pair)
    app.router.add_get("/api/ping", deck.ping)
    app.router.add_get("/app-icon-180.png", deck.app_icon)
    app.router.add_get("/app-icon-512.png", deck.app_icon)
    app.router.add_static("/static/", WEB)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    port = deck.settings["port"]
    await web.TCPSite(runner, "0.0.0.0", port).start()
    asyncio.create_task(deck.status_loop())
    # warm the app list so the editor opens fast
    deck.loop.run_in_executor(deck.pool, apps.list_apps)

    print("\n  PocketDeck is running")
    print(f"  Pair a phone:  http://localhost:{port}/pair   (open on this PC)")
    for a in lan_addresses():
        print(f"  Phone URL:     http://{a['ip']}:{port}   [{a['adapter']}]")
    print("  Stop with Ctrl+C\n")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://localhost:{port}/pair")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

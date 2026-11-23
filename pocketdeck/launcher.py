"""Background mode: run the server with no window and restart it if it crashes.

    pythonw server.py --background   start (used by the Windows startup shortcut)
    python  server.py --stop         stop the background server

The server itself runs as python.exe (the program Windows Firewall already allows), started
with no console window by this small supervisor."""
import os
import socket
import subprocess
import sys
import time

import psutil

CREATE_NO_WINDOW = 0x08000000


def _pidfile(root):
    return os.path.join(root, "cache", "background.pid")


def _port(root):
    import json
    try:
        with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
            return int(json.load(f).get("port", 8765))
    except (OSError, ValueError):
        return 8765


def _already_running(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def stop(root):
    try:
        with open(_pidfile(root), encoding="utf-8") as f:
            pids = [int(x) for x in f.read().split()]
    except (OSError, ValueError):
        print("PocketDeck is not running in the background.")
        return 0
    for pid in pids:  # supervisor first, so it does not restart the server
        try:
            psutil.Process(pid).terminate()
        except psutil.Error:
            pass
    try:
        os.remove(_pidfile(root))
    except OSError:
        pass
    print("PocketDeck stopped.")
    return 0


def supervise(root):
    os.makedirs(os.path.join(root, "cache"), exist_ok=True)
    log_path = os.path.join(root, "pocketdeck.log")
    if os.path.exists(log_path) and os.path.getsize(log_path) > 1_000_000:
        os.replace(log_path, log_path + ".old")
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    port = _port(root)
    if _already_running(port):
        log.write(f"--- {time.ctime()}: already running on port {port}\n")
        return 0
    python = os.path.join(os.path.dirname(sys.executable), "python.exe")
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    crashes = []
    while True:
        log.write(f"--- {time.ctime()}: starting PocketDeck\n")
        child = subprocess.Popen([python, os.path.join(root, "server.py"), "--no-browser"],
                                 cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        with open(_pidfile(root), "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {child.pid}")
        code = child.wait()
        log.write(f"--- {time.ctime()}: server exited with code {code}\n")
        if code == 0:
            break
        now = time.time()
        crashes = [t for t in crashes if now - t < 300] + [now]
        if len(crashes) >= 5:
            log.write("--- stopped restarting: 5 crashes in 5 minutes. See crash.log.\n")
            break
        time.sleep(3)
    try:
        os.remove(_pidfile(root))
    except OSError:
        pass
    return 0


def main(root, argv):
    return stop(root) if "--stop" in argv else supervise(root)

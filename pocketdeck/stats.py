"""System stats: CPU, RAM, disk, battery, network speed, NVIDIA GPU."""
import shutil
import subprocess
import threading
import time

import psutil

_net = {"t": time.monotonic(), "io": psutil.net_io_counters()}
_gpu = {"data": None, "at": 0.0, "busy": False, "enabled": True}
_NVSMI = shutil.which("nvidia-smi")


def enable_gpu(on):
    """Polling nvidia-smi can keep a sleeping laptop GPU awake; settings.json can turn it off."""
    _gpu["enabled"] = bool(on)
psutil.cpu_percent(None)  # prime


def _poll_gpu():
    try:
        r = subprocess.run([_NVSMI, "--query-gpu=name,utilization.gpu,temperature.gpu,"
                            "memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        name, *nums = [x.strip() for x in r.stdout.splitlines()[0].split(",")]
        util, temp, used, total = (round(float(n)) for n in nums)
        _gpu["data"] = {"name": name.replace("NVIDIA GeForce ", "").replace(" Laptop GPU", ""),
                        "util": util, "temp": temp, "mem_used": used, "mem_total": total}
    except Exception:
        _gpu["data"] = None
    finally:
        _gpu["at"], _gpu["busy"] = time.monotonic(), False


def gpu():
    if not _gpu["enabled"]:
        return None
    if _NVSMI and not _gpu["busy"] and time.monotonic() - _gpu["at"] > 4:
        _gpu["busy"] = True
        threading.Thread(target=_poll_gpu, daemon=True).start()
    return _gpu["data"]


def snapshot():
    vm = psutil.virtual_memory()
    now, io = time.monotonic(), psutil.net_io_counters()
    dt = max(0.001, now - _net["t"])
    up = (io.bytes_sent - _net["io"].bytes_sent) / dt
    down = (io.bytes_recv - _net["io"].bytes_recv) / dt
    _net.update(t=now, io=io)
    try:
        disk = psutil.disk_usage("C:\\")
        disk_d = {"percent": round(disk.percent), "free_gb": round(disk.free / 2**30)}
    except OSError:
        disk_d = None
    bat = psutil.sensors_battery()
    bat_d = None
    if bat:
        secs = bat.secsleft if isinstance(bat.secsleft, int) and bat.secsleft > 0 else None
        bat_d = {"percent": round(bat.percent), "plugged": bool(bat.power_plugged), "secs": secs}
    return {
        "cpu": round(psutil.cpu_percent(None)),
        "cpu_freq": round(psutil.cpu_freq().current) if psutil.cpu_freq() else None,
        "ram": round(vm.percent), "ram_used": round(vm.used / 2**30, 1),
        "ram_total": round(vm.total / 2**30, 1),
        "disk": disk_d, "battery": bat_d,
        "net_up": round(up), "net_down": round(down),
        "uptime": int(time.time() - psutil.boot_time()),
        "gpu": gpu(),
    }

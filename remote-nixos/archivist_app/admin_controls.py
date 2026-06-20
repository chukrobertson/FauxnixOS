from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.config import ARCHIVE_ROOT, DATA_DIR, KNOWLEDGEBASE_DIR


SERVER_STARTED_TS = time.time()
RESTART_EXIT_CODE = 20
HOST_STATS_SETTINGS_PATH = DATA_DIR / "host_stats_settings.json"
DEFAULT_HOST_STATS_SETTINGS = {
    "cpu_threshold_percent": 85,
    "gpu_threshold_percent": 85,
    "ram_threshold_percent": 85,
    "vram_threshold_percent": 85,
    "temperature_threshold_c": 82,
    "poll_seconds": 10,
    "schedule_enabled": True,
    "quiet_start": "",
    "quiet_end": "",
}


def _run_command(args: list[str], timeout: int = 6) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "command": " ".join(args),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(error), "command": " ".join(args)}


def _ollama_ps() -> dict:
    if not shutil.which("ollama"):
        return {"available": False, "running_models": [], "raw": "", "error": "ollama not found on PATH"}
    result = _run_command(["ollama", "ps"], timeout=8)
    models = []
    for line in result.get("stdout", "").splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return {
        "available": True,
        "running_models": models,
        "raw": result.get("stdout", ""),
        "error": result.get("stderr", "") if not result.get("ok") else "",
    }


def _nvidia_summary() -> dict:
    if not shutil.which("nvidia-smi"):
        return {"available": False, "raw": "", "error": "nvidia-smi not found on PATH"}
    result = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=6,
    )
    cards = []
    for line in result.get("stdout", "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        name, memory_used, memory_total, util, power = parts[:5]
        temperature = parts[5] if len(parts) > 5 else None
        cards.append(
            {
                "name": name,
                "memory_used_mb": _to_number(memory_used),
                "memory_total_mb": _to_number(memory_total),
                "utilization_percent": _to_number(util),
                "power_watts": _to_number(power),
                "temperature_c": _to_number(temperature) if temperature is not None else None,
            }
        )
    return {
        "available": bool(result.get("ok")),
        "gpus": cards,
        "raw": result.get("stdout", ""),
        "error": result.get("stderr", "") if not result.get("ok") else "",
    }


def _to_number(value: str) -> float | int | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _windows_host_counters() -> dict:
    if platform.system().lower() != "windows":
        return {"available": False, "error": "Windows performance counters unavailable on this host."}
    memory = _windows_memory_status()
    if not shutil.which("powershell"):
        return {"available": bool(memory.get("available")), "error": "PowerShell not found on PATH.", **memory}
    command = (
        "$cpu=(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
        "$os=Get-CimInstance Win32_OperatingSystem; "
        "[pscustomobject]@{cpu_percent=[math]::Round([double]$cpu,1);"
        "memory_total_kb=[double]$os.TotalVisibleMemorySize;"
        "memory_free_kb=[double]$os.FreePhysicalMemory} | ConvertTo-Json -Compress"
    )
    result = _run_command(["powershell", "-NoProfile", "-Command", command], timeout=5)
    if not result.get("ok") or result.get("stderr"):
        cpu = _windows_cpu_counter()
        return {
            "available": bool(memory.get("available") or cpu is not None),
            "error": result.get("stderr") or "Unable to read host counters.",
            **memory,
            "cpu_percent": cpu,
        }
    try:
        data = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {"available": bool(memory.get("available")), "error": "Host counter output was not valid JSON.", **memory}
    total = int(float(data.get("memory_total_kb") or 0) * 1024)
    free = int(float(data.get("memory_free_kb") or 0) * 1024)
    used = max(0, total - free)
    memory_percent = round((used / total) * 100, 1) if total else None
    if not total and memory.get("available"):
        total = memory.get("memory_total_bytes")
        used = memory.get("memory_used_bytes")
        memory_percent = memory.get("memory_percent")
    cpu = data.get("cpu_percent")
    if cpu is None:
        cpu = _windows_cpu_counter()
    return {
        "available": True,
        "cpu_percent": cpu,
        "memory_total_bytes": total or None,
        "memory_used_bytes": used or None,
        "memory_percent": memory_percent,
    }


def _windows_cpu_counter() -> float | None:
    if not shutil.which("powershell"):
        return None
    command = "(Get-Counter '\\Processor(_Total)\\% Processor Time' -SampleInterval 1 -MaxSamples 1).CounterSamples.CookedValue"
    result = _run_command(["powershell", "-NoProfile", "-Command", command], timeout=6)
    if not result.get("ok"):
        return None
    value = _to_number(result.get("stdout", "").splitlines()[-1] if result.get("stdout") else "")
    return round(float(value), 1) if value is not None else None


def _windows_memory_status() -> dict:
    try:
        import ctypes
    except ImportError:
        return {"available": False}

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"available": False}
    used = max(0, int(status.ullTotalPhys) - int(status.ullAvailPhys))
    return {
        "available": True,
        "memory_total_bytes": int(status.ullTotalPhys),
        "memory_used_bytes": used,
        "memory_percent": round(float(status.dwMemoryLoad), 1),
    }


def _clamp_number(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _normalize_host_stats_settings(settings: dict | None = None) -> dict:
    normalized = dict(DEFAULT_HOST_STATS_SETTINGS)
    if isinstance(settings, dict):
        normalized.update(settings)
    normalized["cpu_threshold_percent"] = _clamp_number(normalized.get("cpu_threshold_percent"), 1, 100, 85)
    normalized["gpu_threshold_percent"] = _clamp_number(normalized.get("gpu_threshold_percent"), 1, 100, 85)
    normalized["ram_threshold_percent"] = _clamp_number(normalized.get("ram_threshold_percent"), 1, 100, 85)
    normalized["vram_threshold_percent"] = _clamp_number(normalized.get("vram_threshold_percent"), 1, 100, 85)
    normalized["temperature_threshold_c"] = _clamp_number(normalized.get("temperature_threshold_c"), 30, 115, 82)
    normalized["poll_seconds"] = _clamp_number(normalized.get("poll_seconds"), 5, 300, 10)
    normalized["schedule_enabled"] = bool(normalized.get("schedule_enabled", True))
    normalized["quiet_start"] = str(normalized.get("quiet_start") or "")[:5]
    normalized["quiet_end"] = str(normalized.get("quiet_end") or "")[:5]
    return normalized


def _load_host_stats_settings() -> dict:
    if not HOST_STATS_SETTINGS_PATH.exists():
        return _normalize_host_stats_settings()
    try:
        loaded = json.loads(HOST_STATS_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    return _normalize_host_stats_settings(loaded)


def update_host_stats_settings(settings: dict) -> dict:
    current = _load_host_stats_settings()
    current.update({key: value for key, value in (settings or {}).items() if value is not None})
    current = _normalize_host_stats_settings(current)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HOST_STATS_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def _is_active(job: dict | None) -> bool:
    job = job or {}
    return bool(job.get("running") or job.get("building_queue") or job.get("pause_requested"))


def archive_control_status(
    *,
    index_job: dict | None = None,
    embedding_job: dict | None = None,
    pre_dedupe_job: dict | None = None,
) -> dict:
    uptime = max(0, int(time.time() - SERVER_STARTED_TS))
    launcher_managed = os.getenv("ARCHIVIST_LAUNCHER") == "1"
    return {
        "server": {
            "pid": os.getpid(),
            "python": sys.executable,
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "uptime_seconds": uptime,
            "host": os.getenv("ARCHIVIST_HOST", "0.0.0.0"),
            "port": int(os.getenv("ARCHIVIST_PORT", "8000")),
            "launcher_managed": launcher_managed,
            "restart_exit_code": RESTART_EXIT_CODE,
        },
        "archive": {
            "archive_root": str(ARCHIVE_ROOT),
            "knowledgebase_root": str(KNOWLEDGEBASE_DIR),
            "data_dir": str(DATA_DIR),
            "index": index_job or {},
            "embeddings": embedding_job or {},
            "pre_dedupe": pre_dedupe_job or {},
            "busy": bool(_is_active(index_job) or (embedding_job or {}).get("running") or (pre_dedupe_job or {}).get("running")),
        },
        "ollama": _ollama_ps(),
        "gpu": _nvidia_summary(),
    }


def host_stats() -> dict:
    counters = _windows_host_counters()
    gpu = _nvidia_summary()
    settings = _load_host_stats_settings()
    gpus = gpu.get("gpus") or []
    primary_gpu = gpus[0] if gpus else {}
    vram_total_mb = primary_gpu.get("memory_total_mb")
    vram_used_mb = primary_gpu.get("memory_used_mb")
    vram_percent = None
    if vram_total_mb:
        vram_percent = round((float(vram_used_mb or 0) / float(vram_total_mb)) * 100, 1)
    temperatures = []
    for item in gpus:
        if item.get("temperature_c") is not None:
            temperatures.append({"label": item.get("name") or "GPU", "temperature_c": item.get("temperature_c"), "kind": "gpu"})
    thresholds = {
        "cpu": (counters.get("cpu_percent") or 0) >= settings["cpu_threshold_percent"],
        "gpu": (primary_gpu.get("utilization_percent") or 0) >= settings["gpu_threshold_percent"],
        "ram": (counters.get("memory_percent") or 0) >= settings["ram_threshold_percent"],
        "vram": (vram_percent or 0) >= settings["vram_threshold_percent"],
        "temperature": any((item.get("temperature_c") or 0) >= settings["temperature_threshold_c"] for item in temperatures),
    }
    return {
        "summary": "Host telemetry loaded." if counters.get("available") or gpu.get("available") else "Host telemetry is partially unavailable.",
        "captured_ts": time.time(),
        "settings": settings,
        "host": {
            "platform": platform.platform(),
            "hostname": platform.node(),
            "cpu_count": os.cpu_count() or 1,
        },
        "cpu": {"available": counters.get("available"), "usage_percent": counters.get("cpu_percent"), "threshold": thresholds["cpu"]},
        "memory": {
            "available": counters.get("available"),
            "used_bytes": counters.get("memory_used_bytes"),
            "total_bytes": counters.get("memory_total_bytes"),
            "usage_percent": counters.get("memory_percent"),
            "threshold": thresholds["ram"],
        },
        "gpu": {
            "available": gpu.get("available"),
            "error": gpu.get("error", ""),
            "cards": gpus,
            "usage_percent": primary_gpu.get("utilization_percent"),
            "vram_used_mb": vram_used_mb,
            "vram_total_mb": vram_total_mb,
            "vram_percent": vram_percent,
            "threshold": thresholds["gpu"] or thresholds["vram"],
        },
        "temperatures": temperatures,
        "thresholds": thresholds,
    }


def free_gpu(model: str | None = None) -> dict:
    ps = _ollama_ps()
    if not ps.get("available"):
        return {"ok": False, "summary": ps.get("error") or "Ollama is not available.", "results": [], "ollama": ps}
    models = [model] if model else ps.get("running_models", [])
    models = [item for item in models if item]
    if not models:
        return {"ok": True, "summary": "No running Ollama models to stop.", "results": [], "ollama": ps}
    results = [_run_command(["ollama", "stop", item], timeout=12) for item in models]
    stopped = sum(1 for item in results if item.get("ok"))
    return {
        "ok": stopped == len(results),
        "summary": f"Requested stop for {stopped} of {len(results)} running Ollama model(s).",
        "results": results,
        "ollama": _ollama_ps(),
        "gpu": _nvidia_summary(),
    }


def _schedule_exit(code: int, delay_seconds: float = 1.25) -> None:
    def exit_later() -> None:
        time.sleep(delay_seconds)
        os._exit(code)

    threading.Thread(target=exit_later, daemon=True).start()


def request_server_restart(index_job: dict | None = None, *, force: bool = False) -> dict:
    if _is_active(index_job) and not force:
        raise ValueError("Indexing is active. Pause or finish indexing before restarting, or use a force restart.")
    launcher_managed = os.getenv("ARCHIVIST_LAUNCHER") == "1"
    _schedule_exit(RESTART_EXIT_CODE)
    return {
        "ok": True,
        "action": "restart",
        "summary": "Archivist restart requested. The launcher will restart it automatically if this server was started with Start_Archivist.bat.",
        "launcher_managed": launcher_managed,
        "exit_code": RESTART_EXIT_CODE,
    }


def request_server_stop(index_job: dict | None = None, *, force: bool = False) -> dict:
    if _is_active(index_job) and not force:
        raise ValueError("Indexing is active. Pause or finish indexing before stopping the server, or use a force stop.")
    _schedule_exit(0)
    return {
        "ok": True,
        "action": "stop",
        "summary": "Archivist server stop requested. Use Start_Archivist.bat to bring it back up.",
        "launcher_managed": os.getenv("ARCHIVIST_LAUNCHER") == "1",
        "exit_code": 0,
    }

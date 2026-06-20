from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from app.config import DATA_DIR


PC_RGB_SETTINGS_PATH = DATA_DIR / "pc_rgb_settings.json"
OPENRGB_COMMAND_LOCK = threading.Lock()
TELEMETRY_LOCK = threading.Lock()
TELEMETRY_THREAD_STARTED = False
TELEMETRY_STOP = threading.Event()
DEFAULT_PC_RGB_SETTINGS = {
    "provider": "openrgb",
    "enabled": False,
    "executable_path": "",
    "use_client": True,
    "server": "127.0.0.1:6742",
    "red": 199,
    "green": 18,
    "blue": 255,
    "brightness": 100,
    "mode": "static",
    "telemetry_enabled": False,
    "telemetry_interval_seconds": 10,
    "ambient_mood": "archive",
    "roles": {
        "ram": {
            "enabled": False,
            "device": "",
            "zone": "",
            "led_count": 8,
            "targets": [],
            "metric": "memory",
            "mode": "direct",
        },
        "cpu_fan": {
            "enabled": False,
            "device": "",
            "zone": "",
            "led_count": 16,
            "targets": [],
            "metric": "cpu",
            "mode": "direct",
        },
        "case_fans": {
            "enabled": False,
            "device": "",
            "zone": "",
            "led_count": 12,
            "targets": [],
            "mood": "archive",
            "mode": "direct",
        },
    },
    "last_applied_ts": None,
    "last_result": None,
    "last_telemetry_ts": None,
    "last_telemetry_result": None,
}


def _clamp_int(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _normalize_target(target, fallback_led_count: int) -> dict | None:
    if isinstance(target, str):
        parts = [part.strip() for part in target.split("|")]
        target = {
            "device": parts[0] if len(parts) > 0 else "",
            "zone": parts[1] if len(parts) > 1 else "",
            "led_count": parts[2] if len(parts) > 2 else fallback_led_count,
            "label": parts[3] if len(parts) > 3 else "",
            "metric": parts[4] if len(parts) > 4 else "",
            "mood": parts[5] if len(parts) > 5 else "",
        }
    if not isinstance(target, dict):
        return None
    device = str(target.get("device") or "").strip()
    if not device:
        return None
    return {
        "device": device,
        "zone": str(target.get("zone") or "").strip(),
        "led_count": _clamp_int(target.get("led_count"), 1, 240, fallback_led_count),
        "label": str(target.get("label") or "").strip(),
        "metric": str(target.get("metric") or "").strip().lower()[:40],
        "mood": str(target.get("mood") or "").strip().lower()[:40],
    }


def _normalize_role(role: dict | None, defaults: dict) -> dict:
    normalized = dict(defaults)
    if isinstance(role, dict):
        normalized.update(role)
    normalized["enabled"] = bool(normalized.get("enabled", False))
    normalized["device"] = str(normalized.get("device") or "").strip()
    normalized["zone"] = str(normalized.get("zone") or "").strip()
    normalized["led_count"] = _clamp_int(normalized.get("led_count"), 1, 240, defaults.get("led_count", 8))
    normalized["metric"] = str(normalized.get("metric") or defaults.get("metric") or "").strip().lower()[:40]
    normalized["mood"] = str(normalized.get("mood") or defaults.get("mood") or "").strip().lower()[:40]
    normalized["mode"] = str(normalized.get("mode") or defaults.get("mode") or "direct").strip().lower()[:40]
    if normalized["mode"] not in {"direct", "static"}:
        normalized["mode"] = "direct"
    targets = []
    for target in normalized.get("targets") or []:
        clean = _normalize_target(target, normalized["led_count"])
        if clean:
            targets.append(clean)
    if not targets and normalized["device"]:
        clean = _normalize_target(
            {
                "device": normalized["device"],
                "zone": normalized["zone"],
                "led_count": normalized["led_count"],
                "label": normalized.get("label") or "",
            },
            normalized["led_count"],
        )
        if clean:
            targets.append(clean)
    normalized["targets"] = targets
    if targets:
        first = targets[0]
        normalized["device"] = first.get("device") or ""
        normalized["zone"] = first.get("zone") or ""
        normalized["led_count"] = first.get("led_count") or normalized["led_count"]
    return normalized


def _normalize_settings(settings: dict | None = None) -> dict:
    normalized = dict(DEFAULT_PC_RGB_SETTINGS)
    normalized["roles"] = {key: dict(value) for key, value in DEFAULT_PC_RGB_SETTINGS["roles"].items()}
    if isinstance(settings, dict):
        normalized.update(settings)
    normalized["provider"] = "openrgb"
    normalized["enabled"] = bool(normalized.get("enabled", False))
    normalized["executable_path"] = str(normalized.get("executable_path") or "").strip()
    normalized["server"] = str(normalized.get("server") or DEFAULT_PC_RGB_SETTINGS["server"]).strip()
    normalized["use_client"] = bool(normalized.get("use_client", True))
    normalized["red"] = _clamp_int(normalized.get("red"), 0, 255, DEFAULT_PC_RGB_SETTINGS["red"])
    normalized["green"] = _clamp_int(normalized.get("green"), 0, 255, DEFAULT_PC_RGB_SETTINGS["green"])
    normalized["blue"] = _clamp_int(normalized.get("blue"), 0, 255, DEFAULT_PC_RGB_SETTINGS["blue"])
    normalized["brightness"] = _clamp_int(normalized.get("brightness"), 0, 100, DEFAULT_PC_RGB_SETTINGS["brightness"])
    normalized["mode"] = str(normalized.get("mode") or "static").strip().lower()[:40] or "static"
    if normalized["mode"] not in {"static", "direct", "off"}:
        normalized["mode"] = "static"
    normalized["telemetry_enabled"] = bool(normalized.get("telemetry_enabled", False))
    if not normalized["enabled"]:
        normalized["telemetry_enabled"] = False
    normalized["telemetry_interval_seconds"] = _clamp_int(normalized.get("telemetry_interval_seconds"), 5, 300, 10)
    normalized["ambient_mood"] = str(normalized.get("ambient_mood") or "archive").strip().lower()[:40] or "archive"
    roles = normalized.get("roles") if isinstance(normalized.get("roles"), dict) else {}
    normalized["roles"] = {
        "ram": _normalize_role(roles.get("ram"), DEFAULT_PC_RGB_SETTINGS["roles"]["ram"]),
        "cpu_fan": _normalize_role(roles.get("cpu_fan"), DEFAULT_PC_RGB_SETTINGS["roles"]["cpu_fan"]),
        "case_fans": _normalize_role(roles.get("case_fans"), DEFAULT_PC_RGB_SETTINGS["roles"]["case_fans"]),
    }
    return normalized


def load_pc_rgb_settings() -> dict:
    if not PC_RGB_SETTINGS_PATH.exists():
        return _normalize_settings()
    try:
        loaded = json.loads(PC_RGB_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    return _normalize_settings(loaded)


def save_pc_rgb_settings(settings: dict | None = None) -> dict:
    current = load_pc_rgb_settings()
    current.update({key: value for key, value in (settings or {}).items() if value is not None})
    current = _normalize_settings(current)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PC_RGB_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return pc_rgb_status(current)


def _candidate_openrgb_paths(configured_path: str = "") -> list[Path]:
    candidates: list[Path] = []
    for value in [configured_path, os.getenv("OPENRGB_PATH", ""), os.getenv("OPENRGB_EXE", "")]:
        value = str(value or "").strip().strip('"')
        if value:
            candidates.append(Path(value))
    for name in ["OpenRGB", "OpenRGB.exe", "openrgb"]:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if platform.system().lower() == "windows":
        for root in [os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"), os.getenv("LOCALAPPDATA")]:
            if root:
                candidates.append(Path(root) / "OpenRGB" / "OpenRGB.exe")
    seen = set()
    unique = []
    for item in candidates:
        key = str(item).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def find_openrgb_executable(settings: dict | None = None) -> Path | None:
    settings = settings or load_pc_rgb_settings()
    for candidate in _candidate_openrgb_paths(settings.get("executable_path", "")):
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _rgb_hex(settings: dict) -> str:
    if settings.get("mode") == "off":
        return "000000"
    brightness = _clamp_int(settings.get("brightness"), 0, 100, 100) / 100
    red = round(_clamp_int(settings.get("red"), 0, 255, 0) * brightness)
    green = round(_clamp_int(settings.get("green"), 0, 255, 0) * brightness)
    blue = round(_clamp_int(settings.get("blue"), 0, 255, 0) * brightness)
    return f"{red:02X}{green:02X}{blue:02X}"


def _run_openrgb(settings: dict, args: list[str], timeout: int = 15) -> dict:
    executable = find_openrgb_executable(settings)
    if not executable:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "OpenRGB executable was not found. Install OpenRGB or set its executable path.",
            "command": "OpenRGB " + " ".join(args),
        }
    try:
        with OPENRGB_COMMAND_LOCK:
            result = subprocess.run([str(executable), *args], capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "command": f"{executable.name} " + " ".join(args),
        }
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "returncode": None,
            "stdout": (error.stdout or "").strip() if isinstance(error.stdout, str) else "",
            "stderr": "OpenRGB command timed out.",
            "command": f"{executable.name} " + " ".join(args),
        }
    except OSError as error:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(error), "command": f"{executable.name} " + " ".join(args)}


def _client_args(settings: dict) -> list[str]:
    if not settings.get("use_client", True):
        return []
    server = str(settings.get("server") or DEFAULT_PC_RGB_SETTINGS["server"]).strip()
    return ["--client", server] if server else ["--client"]


def _selector_args(role: dict) -> list[str]:
    args = []
    device = str(role.get("device") or "").strip()
    zone = str(role.get("zone") or "").strip()
    if device:
        args.extend(["--device", device])
    if zone:
        args.extend(["--zone", zone])
    return args


def _role_targets(role: dict) -> list[dict]:
    targets = role.get("targets") or []
    if targets:
        return [target for target in targets if target.get("device")]
    if role.get("device"):
        return [
            {
                "device": role.get("device"),
                "zone": role.get("zone") or "",
                "led_count": role.get("led_count") or 1,
                "label": role.get("label") or "",
            }
        ]
    return []


def _hex_color(red: int, green: int, blue: int, brightness: int = 100) -> str:
    scale = _clamp_int(brightness, 0, 100, 100) / 100
    r = round(_clamp_int(red, 0, 255, 0) * scale)
    g = round(_clamp_int(green, 0, 255, 0) * scale)
    b = round(_clamp_int(blue, 0, 255, 0) * scale)
    return f"{r:02X}{g:02X}{b:02X}"


def _blend(start: tuple[int, int, int], end: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, float(amount or 0)))
    return tuple(round(start[index] + (end[index] - start[index]) * amount) for index in range(3))


def _color_tuple_to_hex(color: tuple[int, int, int], brightness: int = 100) -> str:
    return _hex_color(color[0], color[1], color[2], brightness)


def _metric_value(metrics: dict, metric: str) -> float:
    metric = (metric or "").lower()
    if metric == "memory":
        return float((metrics.get("memory") or {}).get("usage_percent") or 0)
    if metric == "vram":
        return float((metrics.get("gpu") or {}).get("vram_percent") or 0)
    if metric == "gpu":
        return float((metrics.get("gpu") or {}).get("usage_percent") or 0)
    if metric == "temperature":
        temps = [float(item.get("temperature_c") or 0) for item in metrics.get("temperatures") or []]
        return min(100.0, max(temps or [0]) / 95 * 100)
    return float((metrics.get("cpu") or {}).get("usage_percent") or 0)


def _meter_colors(percent: float, count: int, brightness: int, palette: str = "telemetry") -> list[str]:
    count = _clamp_int(count, 1, 240, 8)
    percent = max(0.0, min(100.0, float(percent or 0)))
    active = round(count * percent / 100)
    colors = []
    if palette == "ram":
        low, high, idle = (10, 214, 255), (199, 18, 255), (4, 29, 39)
    else:
        low, high, idle = (24, 243, 199), (255, 91, 143), (15, 24, 29)
    for index in range(count):
        if index < active:
            amount = index / max(1, count - 1)
            colors.append(_color_tuple_to_hex(_blend(low, high, amount), brightness))
        else:
            colors.append(_color_tuple_to_hex(idle, max(18, round(brightness * 0.34))))
    return colors


def _mood_colors(mood: str, count: int, brightness: int, phase: int = 0) -> list[str]:
    count = _clamp_int(count, 1, 240, 12)
    palettes = {
        "archive": [(10, 214, 255), (199, 18, 255), (24, 243, 199)],
        "thinking": [(255, 209, 102), (199, 18, 255), (10, 214, 255)],
        "writing": [(24, 243, 199), (255, 209, 102), (199, 18, 255)],
        "searching": [(10, 214, 255), (35, 92, 255), (24, 243, 199)],
        "enriching": [(199, 18, 255), (255, 91, 143), (255, 209, 102)],
        "calm": [(24, 243, 199), (10, 214, 255), (116, 244, 214)],
        "alert": [(255, 91, 143), (255, 209, 102), (255, 91, 143)],
    }
    palette = palettes.get((mood or "archive").lower(), palettes["archive"])
    colors = []
    for index in range(count):
        shifted = (index + phase) % count
        span = shifted / max(1, count - 1)
        left = palette[0] if span < 0.5 else palette[1]
        right = palette[1] if span < 0.5 else palette[2]
        amount = span * 2 if span < 0.5 else (span - 0.5) * 2
        colors.append(_color_tuple_to_hex(_blend(left, right, amount), brightness))
    return colors


def _role_color_command(settings: dict, role: dict, color_builder) -> dict:
    if not role.get("enabled"):
        return {"ok": True, "skipped": True, "summary": "Role is disabled."}
    targets = _role_targets(role)
    if not targets:
        return {"ok": False, "skipped": True, "summary": "Role needs an OpenRGB device selector before Archivist can address it."}
    mode = role.get("mode") or "direct"
    results = []
    for target in targets:
        colors = color_builder(target)
        selector = {**role, **target}
        args = [*_client_args(settings), *_selector_args(selector), "--mode", mode, "--color", ",".join(colors)]
        result = _run_openrgb(settings, args, timeout=18)
        results.append({"target": target, "result": result})
    ok = all((item.get("result") or {}).get("ok") for item in results)
    return {"ok": ok, "results": results, "summary": "Role rendered." if ok else "One or more OpenRGB role targets failed."}


def role_summaries(settings: dict) -> list[dict]:
    roles = settings.get("roles") or {}
    summaries = []
    for key, label in [("ram", "RAM telemetry"), ("cpu_fan", "CPU fan donut"), ("case_fans", "Archivist ambience")]:
        role = roles.get(key) or {}
        summaries.append(
            {
                "role": key,
                "label": label,
                "enabled": bool(role.get("enabled")),
                "device": role.get("device") or "",
                "zone": role.get("zone") or "",
                "led_count": sum(int(target.get("led_count") or 0) for target in _role_targets(role)) or role.get("led_count") or 0,
                "target_count": len(_role_targets(role)),
                "targets": _role_targets(role),
                "metric": role.get("metric") or role.get("mood") or "",
            }
        )
    return summaries


def has_active_lighting_role(settings: dict) -> bool:
    roles = settings.get("roles") or {}
    return any(bool(role.get("enabled") and _role_targets(role)) for role in roles.values())


def _last_lighting_result_ok(settings: dict) -> bool:
    last = settings.get("last_telemetry_result") or settings.get("last_result") or {}
    return bool(last.get("ok"))


def pc_rgb_status(settings: dict | None = None, *, scan: bool = False) -> dict:
    settings = _normalize_settings(settings or load_pc_rgb_settings())
    executable = find_openrgb_executable(settings)
    data = {
        "provider": "openrgb",
        "enabled": bool(settings.get("enabled")),
        "available": bool(executable),
        "executable_path": str(executable) if executable else "",
        "settings": settings,
        "hex": _rgb_hex(settings),
        "roles": role_summaries(settings),
        "summary": "OpenRGB was not found. Install it or set the executable path.",
    }
    if not settings.get("enabled"):
        data["summary"] = "PC RGB extension is off. Archivist will not send OpenRGB commands until it is enabled."
        if scan:
            data["scan"] = {
                "ok": True,
                "skipped": True,
                "stdout": "",
                "stderr": "",
                "summary": data["summary"],
            }
        return data
    if executable:
        data["summary"] = (
            "OpenRGB executable found and the last lighting command succeeded."
            if _last_lighting_result_ok(settings)
            else "OpenRGB executable found. Keep the SDK server running when Use SDK server is on."
        )
    if scan:
        result = _run_openrgb(settings, [*_client_args(settings), "--list-devices"], timeout=20)
        data["scan"] = result
        if not result.get("ok"):
            detail = result.get("stderr") or "OpenRGB device detection failed."
            data["summary"] = (
                f"{detail} Last lighting command succeeded, so control is available even though device listing failed."
                if _last_lighting_result_ok(settings)
                else detail
            )
    return data


def apply_pc_rgb(settings: dict | None = None) -> dict:
    current = load_pc_rgb_settings()
    current.update({key: value for key, value in (settings or {}).items() if value is not None})
    current = _normalize_settings(current)
    if not current.get("enabled"):
        current["telemetry_enabled"] = False
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PC_RGB_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
        data = pc_rgb_status(current)
        data["result"] = {
            "ok": True,
            "skipped": True,
            "summary": "PC RGB extension is off; no OpenRGB command was sent.",
        }
        data["summary"] = data["result"]["summary"]
        return data
    color = _rgb_hex(current)
    mode = "off" if current.get("mode") == "off" else current.get("mode") or "static"
    args = [*_client_args(current), "--mode", mode, "--color", color]
    result = _run_openrgb(current, args, timeout=18)
    current["last_applied_ts"] = time.time() if result.get("ok") else current.get("last_applied_ts")
    current["last_result"] = result
    current["mode"] = mode
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PC_RGB_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    data = pc_rgb_status(current)
    data["result"] = result
    data["summary"] = "PC RGB updated through OpenRGB." if result.get("ok") else (result.get("stderr") or "OpenRGB command failed.")
    return data


def save_pc_rgb_map(settings: dict | None = None) -> dict:
    return save_pc_rgb_settings(settings)


def apply_pc_rgb_telemetry(
    metrics: dict,
    settings: dict | None = None,
    *,
    mood: str | None = None,
    include_ambience: bool = True,
) -> dict:
    current = _normalize_settings(settings or load_pc_rgb_settings())
    if not current.get("enabled"):
        current["telemetry_enabled"] = False
        current["last_telemetry_ts"] = time.time()
        current["last_telemetry_result"] = {
            "ok": True,
            "skipped": True,
            "results": [],
            "summary": "PC RGB extension is off; lighting telemetry was skipped.",
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PC_RGB_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
        data = pc_rgb_status(current)
        data["telemetry"] = current["last_telemetry_result"]
        data["summary"] = current["last_telemetry_result"]["summary"]
        return data
    brightness = current.get("brightness", 100)
    roles = current.get("roles") or {}
    phase = 0
    results = []

    ram = roles.get("ram") or {}
    ram_metric = ram.get("metric") or "memory"
    if ram.get("enabled"):
        ram_target_values = []

        def ram_colors(target: dict) -> list[str]:
            target_metric = target.get("metric") or ram_metric
            target_value = _metric_value(metrics, target_metric)
            ram_target_values.append(
                {
                    "device": target.get("device") or "",
                    "zone": target.get("zone") or "",
                    "label": target.get("label") or "",
                    "metric": target_metric,
                    "value": target_value,
                }
            )
            return _meter_colors(target_value, target.get("led_count") or ram.get("led_count") or 8, brightness, "ram")

        results.append({
            "role": "ram",
            "metric": ram_metric,
            "target_values": ram_target_values,
            "result": _role_color_command(
                current,
                ram,
                ram_colors,
            ),
        })

    cpu = roles.get("cpu_fan") or {}
    cpu_metric = cpu.get("metric") or "cpu"
    cpu_value = _metric_value(metrics, cpu_metric)
    if cpu.get("enabled"):
        results.append({
            "role": "cpu_fan",
            "metric": cpu_metric,
            "value": cpu_value,
            "result": _role_color_command(
                current,
                cpu,
                lambda target: _meter_colors(cpu_value, target.get("led_count") or cpu.get("led_count") or 16, brightness, "telemetry"),
            ),
        })

    case_fans = roles.get("case_fans") or {}
    ambient_mood = mood or case_fans.get("mood") or current.get("ambient_mood") or "archive"
    if include_ambience and case_fans.get("enabled"):
        results.append({
            "role": "case_fans",
            "mood": ambient_mood,
            "result": _role_color_command(
                current,
                case_fans,
                lambda target: _mood_colors(ambient_mood, target.get("led_count") or case_fans.get("led_count") or 12, brightness, phase),
            ),
        })

    ok = all((item.get("result") or {}).get("ok") for item in results) if results else False
    summary = "Lighting telemetry applied." if ok else "Lighting telemetry needs enabled roles with OpenRGB device selectors."
    if results and not include_ambience:
        summary = (
            "Live RAM/CPU lighting telemetry applied; ambience left unchanged."
            if ok
            else "Live RAM/CPU lighting telemetry encountered an OpenRGB issue; ambience left unchanged."
        )
    latest = load_pc_rgb_settings()
    latest["ambient_mood"] = ambient_mood
    latest["last_telemetry_ts"] = time.time()
    latest["last_telemetry_result"] = {"ok": ok, "results": results, "summary": summary}
    current = _normalize_settings(latest)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PC_RGB_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    data = pc_rgb_status(current)
    data["telemetry"] = current["last_telemetry_result"]
    data["summary"] = summary
    return data


def update_pc_rgb_telemetry(
    *,
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    ambient_mood: str | None = None,
) -> dict:
    current = load_pc_rgb_settings()
    if enabled is not None:
        current["telemetry_enabled"] = bool(enabled)
    if not current.get("enabled"):
        current["telemetry_enabled"] = False
    if interval_seconds is not None:
        current["telemetry_interval_seconds"] = interval_seconds
    if ambient_mood:
        current["ambient_mood"] = ambient_mood
        current["roles"]["case_fans"]["mood"] = ambient_mood
    return save_pc_rgb_settings(current)


def start_pc_rgb_telemetry_scheduler(metric_provider) -> None:
    global TELEMETRY_THREAD_STARTED
    with TELEMETRY_LOCK:
        if TELEMETRY_THREAD_STARTED:
            return
        TELEMETRY_THREAD_STARTED = True

    def loop() -> None:
        last_run = 0.0
        while not TELEMETRY_STOP.is_set():
            try:
                settings = load_pc_rgb_settings()
                interval = settings.get("telemetry_interval_seconds", 10)
                now = time.time()
                if settings.get("enabled") and settings.get("telemetry_enabled") and has_active_lighting_role(settings) and now - last_run >= interval:
                    last_run = now
                    apply_pc_rgb_telemetry(metric_provider(), settings, include_ambience=False)
            except Exception:
                pass
            TELEMETRY_STOP.wait(1.0)

    threading.Thread(target=loop, daemon=True).start()

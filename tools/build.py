"""Build or flash an isolated SDK app with project-local ESP-IDF tools."""
import argparse
import os
import re
import subprocess
from pathlib import Path

from prepare_sdk import ROOT, SDK, prepare


def environment():
    env = os.environ.copy()
    if os.name == "nt":
        # This workspace installs the win64 toolchain. Some desktop executor
        # environments omit the architecture variables used by Python/IDF.
        env.setdefault("PROCESSOR_ARCHITECTURE", "AMD64")
    tools = ROOT / ".tools/espressif"
    python_pattern = "*/Scripts/python.exe" if os.name == "nt" else "*/bin/python"
    pythons = list((tools / "python_env").glob(python_pattern))
    if len(pythons) != 1:
        raise RuntimeError("Install the ESP-IDF Python environment first")
    python = pythons[0]
    bins = [str(python.parent)]
    suffix = ".exe" if os.name == "nt" else ""
    executables = {name + suffix for name in
                   ("cmake", "ninja", "xtensa-esp32s3-elf-gcc",
                    "xtensa-esp-elf-gcc", "ccache")}
    bins.extend(sorted({str(p.parent) for p in (tools / "tools").rglob("*")
                        if p.name in executables and p.is_file()}))
    env.update(IDF_PATH=(SDK / "esp-idf").as_posix(), ADF_PATH=SDK.as_posix(),
               IDF_TOOLS_PATH=str(tools),
               IDF_PYTHON_ENV_PATH=str(python.parent.parent),
               ESP_ROM_ELF_DIR=(
                   tools / "tools/esp-rom-elfs/20241011").as_posix(),
               IDF_TARGET="esp32s3", PYTHONUTF8="1",
               PATH=os.pathsep.join(bins + [env["PATH"]]))
    return python, env


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["baseline", "headvoice"])
    parser.add_argument("action", choices=["build", "flash", "monitor"],
                        default="build", nargs="?")
    parser.add_argument("--port")
    parser.add_argument("--gesture-agent-config", type=Path,
                        help="Private HTTPS bridge config with explicit fixed gesture meanings")
    parser.add_argument("--gesture-agent-probe", action="store_true",
                        help="Explicit diagnostic hg_agent session CLI; no bridge credential required")
    parser.add_argument("--baud", type=int, choices=[115200, 230400, 460800, 921600],
                        help="Flash baud rate; reduce it if the USB link has packet errors")
    parser.add_argument("--stage", choices=[1, 2, 3], type=int, default=3)
    parser.add_argument("--rotate-cw90", action="store_true")
    parser.add_argument("--invert-tilt", action="store_true")
    parser.add_argument("--gimbal", action="store_true")
    parser.add_argument("--vision", choices=["coco", "face", "hand", "face-hand"],
                        help="Build backend (default: coco); for flash/monitor, require a matching cached build")
    parser.add_argument("--work-name",
                        help="Separate build workspace under .work (e.g. face-candidate)")
    parser.add_argument("--face-selftest", action="store_true",
                        help="Diagnostic face stage 2 only: run the pinned official JPEG once before camera inference")
    parser.add_argument("--hand-weights", type=Path,
                        help="Generated hv_hand_weights.h for hand builds; omitted means detection-only, never fake classifications")
    parser.add_argument("--hand-native-partition",
                        help="Build the pinned 11-class ESP-DL classifier; read its model from an existing data partition (build only, no model write)")
    parser.add_argument("--wdt-rom", choices=["on", "off"],
                        help="Explicit watchdog implementation for an isolated comparison build; omitted keeps the SDK default")
    args = parser.parse_args()
    vision = args.vision or "coco"
    if vision in ("face", "hand", "face-hand") and (args.mode != "headvoice" or args.gimbal):
        parser.error("--vision face/hand requires headvoice without --gimbal")
    if vision in ("hand", "face-hand") and args.action == "build" and args.stage != 2:
        parser.error("--vision hand currently requires --stage 2")
    if args.gesture_agent_config and (args.action != "build" or vision not in ("hand", "face-hand") or
                                     not args.work_name or not args.gesture_agent_config.is_file()):
        parser.error("--gesture-agent-config requires an isolated hand build and an existing config")
    if args.gesture_agent_probe and (args.action != "build" or args.mode != "headvoice" or
                                    vision not in ("hand", "face-hand") or not args.work_name or
                                    args.work_name in ("headvoice", "baseline")):
        parser.error("--gesture-agent-probe requires an isolated hand build")
    if args.hand_weights and (args.action != "build" or vision not in ("hand", "face-hand") or not args.hand_weights.is_file()):
        parser.error("--hand-weights requires a hand build and an existing generated model header")
    if args.hand_native_partition and (
            args.action != "build" or args.mode != "headvoice" or vision not in ("hand", "face-hand") or
            args.hand_weights or not args.work_name or args.work_name in ("headvoice", "baseline") or
            not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_-]{0,14}", args.hand_native_partition)):
        parser.error("--hand-native-partition requires an isolated hand build, a valid partition label, and no --hand-weights")
    if args.face_selftest and (args.action != "build" or args.mode != "headvoice" or
                              vision != "face" or args.stage != 2 or
                              not args.work_name or args.work_name == "headvoice"):
        parser.error("--face-selftest requires a face stage 2 build and an isolated --work-name")
    if args.work_name is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.work_name):
        parser.error("--work-name must use lowercase letters, digits, _ or -")
    if args.action != "build" and not args.port:
        parser.error("--port is required; never guess the board port")
    if args.baud and args.action != "flash":
        parser.error("--baud is only supported for flash")
    if args.wdt_rom and (args.action != "build" or not args.work_name or args.work_name in ("headvoice", "baseline")):
        parser.error("--wdt-rom requires an isolated --work-name build")
    app = prepare(args.mode, vision, args.work_name, args.face_selftest) if args.action == "build" else ROOT / \
        ".work" / (args.work_name or args.mode) / "apps"
    if args.wdt_rom:
        config_path = app / "sdkconfig"
        setting = "CONFIG_HAL_WDT_USE_ROM_IMPL=y" if args.wdt_rom == "on" else "# CONFIG_HAL_WDT_USE_ROM_IMPL is not set"
        config, count = re.subn(r"^(?:CONFIG_HAL_WDT_USE_ROM_IMPL=.*|# CONFIG_HAL_WDT_USE_ROM_IMPL is not set)$",
                                setting, config_path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        if count != 1:
            raise RuntimeError("Watchdog implementation SDK configuration seam changed")
        config_path.write_text(config, encoding="utf-8")
    if args.action != "build" and args.mode == "headvoice" and args.vision:
        cache = app / "build/CMakeCache.txt"
        match = re.search(r"^HEADVOICE_VISION:STRING=(coco|face|hand|face-hand)$",
                          cache.read_text(encoding="utf-8") if cache.exists() else "",
                          re.MULTILINE)
        if not match or match[1] != args.vision:
            parser.error("--vision does not match this workspace; build the requested backend first")
    if args.action == "flash":
        cache = app / "build/CMakeCache.txt"
        cached = cache.read_text(encoding="utf-8") if cache.exists() else ""
        if re.search(r"^HEADVOICE_HAND_NATIVE_PARTITION:[^=\r\n]+=.+$", cached, re.MULTILINE):
            parser.error("Native hand firmware needs an explicit application/model deployment after backing up the selected model partition; full SDK flash would overwrite model assets")
    python, env = environment()
    command = [str(python), str(SDK / "esp-idf/tools/idf.py")]
    if args.action == "build":
        command += ["-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON"]
    if args.mode == "headvoice" and args.action == "build":
        header = ""
        if args.gesture_agent_config:
            from gesture_agent_config import write_config
            header = str(write_config(args.gesture_agent_config, app / "main/hv_config/gesture_agent.h"))
        command += [f"-DHEADVOICE_STAGE={args.stage}",
                    f"-DHEADVOICE_GESTURE_AGENT_HEADER={header}",
                    f"-DHEADVOICE_GESTURE_AGENT_PROBE={int(args.gesture_agent_probe)}",
                    f"-DHEADVOICE_ROTATE_CW90={int(args.rotate_cw90)}",
                    f"-DHEADVOICE_INVERT_TILT={int(args.invert_tilt)}",
                    f"-DHEADVOICE_GIMBAL={int(args.gimbal)}",
                    f"-DHEADVOICE_VISION={vision}",
                    f"-DHEADVOICE_HAND_WEIGHTS_FILE={args.hand_weights.resolve() if args.hand_weights else ''}",
                    f"-DHEADVOICE_HAND_NATIVE_PARTITION={args.hand_native_partition or ''}",
                    f"-DHEADVOICE_FACE_SELFTEST={int(args.face_selftest)}"]
    if args.port:
        command += ["-p", args.port]
    if args.baud:
        command += ["-b", str(args.baud)]
    command += [args.action]
    raise SystemExit(subprocess.call(command, cwd=app, env=env))

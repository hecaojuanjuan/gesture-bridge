"""Build or flash an isolated SDK app with project-local ESP-IDF tools."""
import argparse
import os
import subprocess

from prepare_sdk import ROOT, SDK, prepare


def environment():
    env = os.environ.copy()
    if os.name == "nt":
        # This workspace installs the win64 toolchain. Some desktop executor
        # environments omit the architecture variables used by Python/IDF.
        env.setdefault("PROCESSOR_ARCHITECTURE", "AMD64")
    tools = ROOT / ".tools/espressif"
    pythons = list((tools / "python_env").glob("*/Scripts/python.exe"))
    if len(pythons) != 1:
        raise RuntimeError("Install the ESP-IDF Python environment first")
    python = pythons[0]
    bins = [str(python.parent)]
    executables = {"cmake.exe", "ninja.exe", "xtensa-esp32s3-elf-gcc.exe",
                   "xtensa-esp-elf-gcc.exe", "ccache.exe"}
    bins.extend(str(p.parent) for p in (tools / "tools").rglob("*.exe")
                if p.name in executables)
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
    parser.add_argument("--stage", choices=[1, 2, 3], type=int, default=3)
    parser.add_argument("--rotate-cw90", action="store_true")
    parser.add_argument("--invert-tilt", action="store_true")
    args = parser.parse_args()
    if args.action != "build" and not args.port:
        parser.error("--port is required; never guess the board port")
    app = prepare(args.mode) if args.action == "build" else ROOT / \
        ".work" / args.mode / "apps"
    python, env = environment()
    command = [str(python), str(SDK / "esp-idf/tools/idf.py")]
    if args.action == "build":
        command += ["-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON"]
    if args.mode == "headvoice" and args.action == "build":
        command += [f"-DHEADVOICE_STAGE={args.stage}",
                    f"-DHEADVOICE_ROTATE_CW90={int(args.rotate_cw90)}",
                    f"-DHEADVOICE_INVERT_TILT={int(args.invert_tilt)}"]
    if args.port:
        command += ["-p", args.port]
    command += [args.action]
    raise SystemExit(subprocess.call(command, cwd=app, env=env))

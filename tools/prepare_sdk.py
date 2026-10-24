"""Prepare an isolated app from the pinned SDK; never edit vendor."""
import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "vendor/official-sdk"
BASE = "89020f5e04bf777ae1672b8f3d320bc6e0ef3e0c"


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError(f"Upstream seam changed: {old[:90]!r}")
    return text.replace(old, new)


def prepare(mode):
    head = subprocess.check_output(
        ["git", "-C", str(SDK), "rev-parse", "HEAD"], text=True).strip()
    if head != BASE:
        raise RuntimeError(f"Expected {BASE}, found {head}; review diff first")
    if subprocess.check_output(["git", "-C", str(SDK), "diff", "HEAD"]):
        raise RuntimeError("Vendor has modified tracked files")
    app = ROOT / ".work" / mode / "apps"
    app.mkdir(parents=True, exist_ok=True)
    ignored = shutil.ignore_patterns("build", "dependencies.lock")
    shutil.copytree(SDK / "apps", app, dirs_exist_ok=True, ignore=ignored)
    # Absolute paths make moving the application independent of SDK internals.
    cmake = (app / "main/CMakeLists.txt").read_text(encoding="utf-8")
    cmake = cmake.replace(
        '${CMAKE_CURRENT_LIST_DIR}/../../components/agora_iot_sdk',
        (SDK / "components/agora_iot_sdk").as_posix())
    (app / "main/CMakeLists.txt").write_text(cmake, encoding="utf-8")
    project = (app / "CMakeLists.txt").read_text(encoding="utf-8")
    version = BASE[:12] + ("-headvoice" if mode ==
                           "headvoice" else "-baseline")
    project = project.replace('project(vb701n)',
                              f'set(PROJECT_VER "{version}")\nproject(vb701n)')
    (app / "CMakeLists.txt").write_text(project, encoding="utf-8")
    if mode == "baseline":
        return app
    subprocess.run([sys.executable, str(
        ROOT / "tools/verify_audio.py")], check=True)
    patches = []

    def edit(name, transform):
        path = app / "main" / name
        before = path.read_text(encoding="utf-8")
        after = transform(before)
        path.write_text(after, encoding="utf-8")
        patches.extend(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=f"a/apps/main/{name}", tofile=f"b/apps/main/{name}"))

    edit("qm_config/qm_config.h", lambda s: s +
         "\n#define CONFIG_HEADVOICE_SUPPORT 1\n")
    edit("main.c", lambda s: replace(
        replace(s, '#include "qm.h"', '#include "qm.h"\n'
                '#include "headvoice_app.h"'),
        '    example_pose_run();',
        '#if !defined(CONFIG_HEADVOICE_SUPPORT) || !CONFIG_HEADVOICE_SUPPORT\n'
        '    example_pose_run();\n#endif').replace(
        '\n#if defined(CONFIG_QM_POMODORO_SUPPORT)',
        '\n#if CONFIG_HEADVOICE_SUPPORT\n'
        '    if (headvoice_start() != ESP_OK) {\n'
        '        QM_LOGE("main", "HeadVoice unavailable; see diagnostics");\n'
        '    }\n#endif\n\n#if defined(CONFIG_QM_POMODORO_SUPPORT)'))
    edit("CMakeLists.txt", lambda s: s + '\ninclude("' +
         (ROOT / "headvoice/firmware/integration.cmake").as_posix() + '")\n')
    edit("peripheral/bsp_camera.h", lambda s: replace(
        s, '#include <stdbool.h>',
        '#include <stdbool.h>\n#include <stddef.h>\n'
        '#include <stdint.h>\n'
        'typedef void (*bsp_camera_frame_fn)(const uint8_t *, size_t, '
        'uint32_t, uint32_t, uint32_t, uint64_t);\n'
        'esp_err_t bsp_camera_set_frame_callback('
        'bsp_camera_frame_fn callback);'))
    edit("peripheral/bsp_camera.c", lambda s: replace(
        replace(s, '#include "bsp_camera.h"',
                '#include "bsp_camera.h"\n#include "esp_timer.h"\n'
                'static bsp_camera_frame_fn s_frame_callback;\n'
                'esp_err_t bsp_camera_set_frame_callback('
                'bsp_camera_frame_fn callback)\n'
                '{\n  if (s_frame_callback) return ESP_ERR_INVALID_STATE;\n'
                '  s_frame_callback = callback;\n  return ESP_OK;\n}\n'),
        '        frames++;',
        '        /* MMAP bytes are borrowed until QBUF below. */\n'
        '        if (s_frame_callback) {\n'
        '            s_frame_callback(buf.index < CAM_BUF_NUM ? '
        's_cam.buffer[buf.index] : NULL,\n'
        '                buf.bytesused, s_cam.width, s_cam.height, '
        's_cam.pixel_format,\n'
        '                (uint64_t)(esp_timer_get_time() / 1000));\n'
        '        }\n        frames++;'))
    edit("pose/yolo11_pose.h", lambda s: replace(
        s, '    float yaw;', '    unsigned person_count;\n'
        '    float eye_x1, eye_y1, eye_x2, eye_y2;\n'
        '    bool head_valid;\n    float yaw;').replace(
            '#include <stddef.h>',
            '#include <stddef.h>\n#include <stdbool.h>'))
    edit("pose/yolo11_pose.cpp", lambda s: replace(
        s, '    const auto &res = pose_results.front();',
        '    if (out) {\n'
        '        out->person_count = pose_results.size();\n'
        '        if (pose_results.size() == 1) {\n'
        '            const auto &r = pose_results.front();\n'
        '            const auto &k = r.keypoint;\n'
        '            if (k.size() >= 10 && r.score >= 0.5f) {\n'
        '                out->eye_x1 = k[2]; out->eye_y1 = k[3];\n'
        '                out->eye_x2 = k[4]; out->eye_y2 = k[5];\n'
        '                out->head_valid = kpt_valid(k[0], k[1]) &&\n'
        '                    kpt_valid(k[2], k[3]) && '
        'kpt_valid(k[4], k[5]) &&\n'
        '                    k[0] > 0 && k[1] > 0 && '
        'k[0] < (int)img.width && k[1] < (int)img.height &&\n'
        '                    k[2] > 0 && k[3] > 0 && k[4] > 0 && k[5] > 0 &&\n'
        '                    k[2] < (int)img.width && '
        'k[4] < (int)img.width &&\n'
        '                    k[3] < (int)img.height && '
        'k[5] < (int)img.height;\n'
        '            }\n        }\n    }\n'
        '    const auto &res = pose_results.front();', count=2))
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts/integration.patch").write_text(
        "".join(patches), encoding="utf-8")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["baseline", "headvoice"])
    print(prepare(parser.parse_args().mode))

"""Prepare an isolated app from the pinned SDK; never edit vendor."""
import argparse
import difflib
import json
import re
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


def reentrant_mqtt(source):
    """Keep topic tokenization independent of newlib's implicit strtok state."""
    source = replace(source, '    char *delim = "/";',
                     '    char *delim = "/";\n    char *context = NULL;')
    source = replace(source, 'strtok(topicString, delim)',
                     'strtok_r(topicString, delim, &context)')
    return replace(source, 'strtok(NULL, delim)',
                   'strtok_r(NULL, delim, &context)')


def apply_cloud_identity(app, config_path=ROOT / ".local/cloud.json"):
    """Override only the copied app; keep credentials out of shared patches."""
    if not config_path.exists():
        return None
    try:
        identity = json.loads(config_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid local cloud configuration") from None
    if not isinstance(identity, dict):
        raise ValueError("Local cloud configuration must be an object")
    pid, secret = identity.get("pid"), identity.get("secret")
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        raise ValueError("Local cloud PID must be a positive uint32")
    valid_secret = (isinstance(secret, str) and
                    re.fullmatch(r"[0-9A-Fa-f]{32}", secret))
    if not valid_secret:
        raise ValueError(
            "Local cloud secret must contain 32 hexadecimal digits")
    path = app / "main/cloud/ljyd_cloud.h"
    source = path.read_text(encoding="utf-8")
    for macro, value in (("CONFIG_XJIANG_CLOUD_PID", str(pid)),
                         ("CONFIG_XJIANG_CLOUD_SECERT", f'"{secret}"')):
        source, count = re.subn(
            rf"^#define[ \t]+{macro}[ \t]+[^\r\n]*",
            f"#define {macro} {value}", source, flags=re.MULTILINE)
        if count != 1:
            raise RuntimeError("Cloud identity macro seam changed")
    path.write_text(source, encoding="utf-8")
    return pid


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
    pid = apply_cloud_identity(app)
    if pid is not None:
        print(f"Using local cloud product PID={pid}")
    patches = []

    def edit(name, transform):
        path = app / "main" / name
        before = path.read_text(encoding="utf-8")
        after = transform(before)
        path.write_text(after, encoding="utf-8")
        patches.extend(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=f"a/apps/main/{name}", tofile=f"b/apps/main/{name}"))

    firmware = (ROOT / "headvoice/firmware").as_posix()
    edit("CMakeLists.txt", lambda s: s.rstrip() +
         '\ntarget_sources(${COMPONENT_LIB} PRIVATE "' + firmware +
         '/hv_provision_cli.c" "' + firmware +
         '/hv_voice_probe.c" "' + firmware +
         '/hv_panel.c")\ntarget_include_directories('
         '${COMPONENT_LIB} PRIVATE "' + firmware + '")\n')

    def probe_source(relative, transform):
        original = SDK / "qumios-dev" / relative
        before = original.read_text(encoding="utf-8")
        after = transform(before)
        target = app / "main/hv_diagnostics" / original.name
        target.parent.mkdir(exist_ok=True)
        target.write_text(after, encoding="utf-8")
        edit("CMakeLists.txt", lambda s: replace(
            s, '${QDEV}/' + relative, target.as_posix()))
        patches.extend(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=f"a/qumios-dev/{relative}",
            tofile=f"b/apps/main/hv_diagnostics/{original.name}"))

    probe_source("platform/mcu/esp32s3/qm_audio/"
                 "qm_audio_device_vb701n.c", lambda s: replace(
                     replace(s, '#include "qm.h"',
                             '#include "qm.h"\n#include "hv_voice_probe.h"'),
                     '    if (!g_mic_logged) {',
                     '    hv_voice_probe_mic(data, len);\n'
                     '    if (!g_mic_logged) {'))
    probe_source("components/qm_agent/src/transport/"
                 "qm_agent_transport_agora.c", lambda s: replace(
                     replace(s, '#include "qm_agent_internal.h"',
                             '#include "qm_agent_internal.h"\n'
                             '#include "hv_voice_probe.h"'),
                     '    return agora_rtc_send_audio_data('
                     'ctx->conn_id, data, len, &info);',
                     '    int result = agora_rtc_send_audio_data('
                     'ctx->conn_id, data, len, &info);\n'
                     '    hv_voice_probe_tx(len, result);\n'
                     '    return result;'))
    edit("main.c", lambda s: replace(
        replace(s, '#include "ljyd_provision.h"',
                '#include "ljyd_provision.h"\n'
                '#include "hv_provision_cli.h"'),
        '    if (ljyd_provision_init() != QM_EOK) {',
        '    hv_provision_cli_init();\n'
        '    if (ljyd_provision_init() != QM_EOK) {'))
    edit("cloud/ljyd_provision.c", lambda s: replace(
        s, '#include "ljyd_provision.h"',
        '#include "ljyd_provision.h"\n#include "hv_panel.h"').replace(
        '    int ret = qm_wifi_init();',
        '    hv_panel_network("connecting");\n    int ret = qm_wifi_init();').replace(
        '    ret = qm_provision_start(provision_handle);',
        '    hv_panel_network("provisioning");\n'
        '    ret = qm_provision_start(provision_handle);\n'
        '    if (ret != QM_EOK) hv_panel_network("error");').replace(
        '    memset(pending_ssid, 0, sizeof(pending_ssid));',
        '    hv_panel_network("connecting");\n'
        '    memset(pending_ssid, 0, sizeof(pending_ssid));').replace(
        '            ljyd_cloud_on_network_up();',
        '            hv_panel_network("cloud_connecting");\n'
        '            ljyd_cloud_on_network_up();').replace(
        '            ljyd_cloud_on_network_down();',
        '            hv_panel_network("disconnected");\n'
        '            ljyd_cloud_on_network_down();').replace(
        'QM_LOGE(LOG_TAG,', 'hv_panel_network("error");\n        QM_LOGE(LOG_TAG,'))
    # Observe cloud events without replacing the voice agent's callback.
    edit("cloud/ljyd_cloud.c", lambda s: replace(
        s, '#include "ljyd_cloud.h"',
        '#include "ljyd_cloud.h"\n#include "hv_panel.h"').replace(
        '        case QM_IOT_EVENT_CLOUD_CONN:',
        '        case QM_IOT_EVENT_CLOUD_CONN:\n'
        '            hv_panel_network("online");').replace(
        '        case QM_IOT_EVENT_CLOUD_DISCONN:',
        '        case QM_IOT_EVENT_CLOUD_DISCONN:\n'
        '            hv_panel_network("disconnected");').replace(
        '        case QM_IOT_EVENT_CONNING_CLOUD:',
        '        case QM_IOT_EVENT_CONNING_CLOUD:\n'
        '            hv_panel_network("cloud_connecting");'))
    (ROOT / "artifacts").mkdir(exist_ok=True)
    if mode == "baseline":
        (ROOT / "artifacts/baseline-integration.patch").write_text(
            "".join(patches), encoding="utf-8")
        return app
    probe_source("components/mqtt/iot_mqtt_client.c", reentrant_mqtt)
    # Nano printf does not support the 64-bit timestamps in HV JSON logs.
    config_path = app / "sdkconfig"
    before = config_path.read_text(encoding="utf-8")
    after = replace(before, "CONFIG_NEWLIB_NANO_FORMAT=y",
                    "# CONFIG_NEWLIB_NANO_FORMAT is not set")
    config_path.write_text(after, encoding="utf-8")
    patches.extend(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile="a/apps/sdkconfig", tofile="b/apps/sdkconfig"))
    subprocess.run([sys.executable, str(
        ROOT / "tools/verify_audio.py")], check=True)

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

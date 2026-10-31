"""Prepare an isolated app from the pinned SDK; never edit vendor."""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("HEADVOICE_SDK", ROOT / "vendor/official-sdk")).resolve()
BASE = "89020f5e04bf777ae1672b8f3d320bc6e0ef3e0c"
FACE_SELFTEST_URL = (
    "https://raw.githubusercontent.com/espressif/esp-dl/"
    "dc380d450835d42f92777121a0cd4fc67d7c3a8c/"
    "examples/human_face_detect/main/human_face.jpg")
FACE_SELFTEST_SHA256 = "65d23c18bd5d75370d3eff48130ac441b99f9ffd75bbfd6eff4c9ae0d8b4d68a"


def face_selftest_fixture(path=None):
    """Verify the public upstream example, kept outside versioned source assets."""
    path = Path(path) if path is not None else ROOT / ".local/face-selftest/human_face.jpg"
    if not path.is_file():
        raise ValueError(f"Download {FACE_SELFTEST_URL} to {path} for --face-selftest")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != FACE_SELFTEST_SHA256:
        raise ValueError("Official face selftest fixture SHA256 mismatch")
    return data


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


def prepare(mode, vision="coco", work_name=None, face_selftest=False):
    if mode not in ("baseline", "headvoice") or vision not in ("coco", "face", "hand"):
        raise ValueError("Unsupported firmware mode or vision backend")
    if mode != "headvoice" and vision != "coco":
        raise ValueError("The selected vision backend requires headvoice mode")
    if work_name is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", work_name):
        raise ValueError("Work name must use lowercase letters, digits, _ or -")
    fixture = None
    if face_selftest:
        if mode != "headvoice" or vision != "face" or not work_name or work_name == "headvoice":
            raise ValueError("Face selftest requires face mode in an explicitly isolated workspace")
        fixture = face_selftest_fixture()
    head = subprocess.check_output(
        ["git", "-C", str(SDK), "rev-parse", "HEAD"], text=True).strip()
    if head != BASE:
        raise RuntimeError(f"Expected {BASE}, found {head}; review diff first")
    if subprocess.check_output(["git", "-C", str(SDK), "diff", "HEAD"]):
        raise RuntimeError("Vendor has modified tracked files")
    app = ROOT / ".work" / (work_name or mode) / "apps"
    app.mkdir(parents=True, exist_ok=True)
    ignored = shutil.ignore_patterns("build", "dependencies.lock")
    shutil.copytree(SDK / "apps", app, dirs_exist_ok=True, ignore=ignored)
    if fixture is not None:
        destination = app / "main/hv_fixtures/human_face.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fixture)
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
    panel = json.loads((ROOT / "panel/protocol.json").read_text(encoding="utf-8"))
    siid = panel.get("siid")
    if (type(siid) is not int or not 1 <= siid <= 255 or
            panel.get("commandPiid") != 1 or panel.get("reportPiid") != 2):
        raise ValueError("Panel protocol requires uint8 SIID and command/report PIIDs 1/2")
    edit("CMakeLists.txt", lambda s: s.rstrip() +
         '\ntarget_sources(${COMPONENT_LIB} PRIVATE "' + firmware +
         '/hv_provision_cli.c" "' + firmware +
         '/hv_voice_probe.c")\ntarget_include_directories('
         '${COMPONENT_LIB} PRIVATE "' + firmware + '")\n')
    edit("CMakeLists.txt", lambda s: s +
         '\ntarget_sources(${COMPONENT_LIB} PRIVATE "' + firmware +
         '/hv_panel.c" "' + (ROOT / "headvoice/core/hv_light.c").as_posix() +
         '")\ntarget_include_directories(${COMPONENT_LIB} PRIVATE "' +
         (ROOT / "headvoice/core").as_posix() + '")\n')
    edit("CMakeLists.txt", lambda s: s +
         f'\ntarget_compile_definitions(${{COMPONENT_LIB}} PRIVATE HV_PANEL_SIID={siid})\n')
    edit("lj_components/iot_control/iot_control.c", lambda s: replace(
        replace(s, '#include "iot_control.h"',
                '#include "iot_control.h"\n#include "hv_panel.h"'),
        '    for (i = 0; i < QM_ARRAY_SIZE(s_table); i++) {',
        '    if (hv_panel_on_property(property)) return;\n'
        '    for (i = 0; i < QM_ARRAY_SIZE(s_table); i++) {'))
    edit("main.c", lambda s: replace(
        replace(s, '#include "iot_control.h"',
                '#include "iot_control.h"\n#include "hv_panel.h"'),
        '    if (iot_control_init(ljyd_cloud_get_handle()) != QM_EOK) {',
        '    if (hv_panel_init() != QM_EOK) QM_LOGE("main", "Panel unavailable");\n'
        '    if (iot_control_init(ljyd_cloud_get_handle()) != QM_EOK) {'))

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
        '    if (agent_app_init(ljyd_cloud_get_handle()) != QM_EOK) {',
        '    hv_provision_cli_init();\n'
        '    if (agent_app_init(ljyd_cloud_get_handle()) != QM_EOK) {'))
    (ROOT / "artifacts").mkdir(exist_ok=True)
    probe_source("components/mqtt/iot_mqtt_client.c", reentrant_mqtt)
    edit("cloud/ljyd_provision.c", lambda s: replace(
        s, '        case QM_WIFI_EVENT_STA_DISCONNECTED:\n'
        '            QM_LOGW(LOG_TAG, "wifi disconnected");\n'
        '            ljyd_cloud_on_network_down();\n'
        '            (void)qm_wifi_connect();\n',
        '        case QM_WIFI_EVENT_STA_DISCONNECTED:\n'
        '            QM_LOGW(LOG_TAG, "wifi disconnected");\n'
        '            ljyd_cloud_on_network_down();\n'
        '            /* qm_wifi owns reconnect backoff and explicit stop. */\n'))
    # Agora startup overflowed the SDK's 3072-byte control task on this board.
    # Keep the override in the copied app, including baseline comparisons.
    edit("qm_config/qm_config.h", lambda s: s +
         "\n/* HeadVoice: measured qm_agent_ctl overflow during Agora startup. */\n"
         "#define CONFIG_QM_AGENT_CONTROL_TASK_STACK_SIZE (8 * 1024)\n")
    # Nano printf does not support the 64-bit timestamps in HV JSON logs.
    config_path = app / "sdkconfig"
    before = config_path.read_text(encoding="utf-8")
    after = replace(before, "CONFIG_NEWLIB_NANO_FORMAT=y",
                    "# CONFIG_NEWLIB_NANO_FORMAT is not set")
    # The board has octal 8 MB PSRAM. The vendor enables experimental 120 MHz
    # without temperature compensation. Use the supported 80 MHz operating
    # point for both external memories and verify PSRAM at boot.
    for old, new in (
        ("CONFIG_ESPTOOLPY_FLASHFREQ_120M=y", "# CONFIG_ESPTOOLPY_FLASHFREQ_120M is not set"),
        ("# CONFIG_ESPTOOLPY_FLASHFREQ_80M is not set", "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y"),
        ("CONFIG_SPIRAM_SPEED_120M=y", "# CONFIG_SPIRAM_SPEED_120M is not set"),
        ("# CONFIG_SPIRAM_SPEED_80M is not set", "CONFIG_SPIRAM_SPEED_80M=y"),
        ("CONFIG_SPIRAM_SPEED=120", "CONFIG_SPIRAM_SPEED=80"),
        ("# CONFIG_SPIRAM_MEMTEST is not set", "CONFIG_SPIRAM_MEMTEST=y"),
        ("CONFIG_HEAP_POISONING_DISABLED=y", "# CONFIG_HEAP_POISONING_DISABLED is not set"),
        ("# CONFIG_HEAP_POISONING_LIGHT is not set", "CONFIG_HEAP_POISONING_LIGHT=y"),
    ):
        after = replace(after, old, new)
    config_path.write_text(after, encoding="utf-8")
    patches.extend(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile="a/apps/sdkconfig", tofile="b/apps/sdkconfig"))
    if mode == "baseline":
        patch = (app.parent / "integration.patch" if work_name else
                 ROOT / "artifacts/baseline-integration.patch")
        patch.write_text(
            "".join(patches), encoding="utf-8")
        return app
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
    if vision in ("face", "hand"):
        component_name = "human_face_detect" if vision == "face" else "hand_detect"
        component = ROOT / "headvoice/third_party" / component_name
        upstream = json.loads((component / "UPSTREAM.json").read_text(encoding="utf-8"))
        for name, expected in upstream["files"].items():
            if hashlib.sha256((component / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Vendored {component_name} component changed: {name}")
        shutil.copytree(component, app / "main/pose/private" / component_name,
                        dirs_exist_ok=True)
        if vision == "face":
            edit(f"pose/private/{component_name}/idf_component.yml", lambda s: replace(
                s, "    version: ~3.2.0", "    version: ~3.2.0\n    override_path: ../esp-dl"))
        else:
            edit(f"pose/private/{component_name}/idf_component.yml", lambda s: replace(
                s, '    override_path: "../../esp-dl"', '    override_path: "../esp-dl"'))
        edit("idf_component.yml", lambda s: replace(
            s, "  coco_pose:\n", f"  {component_name}:\n"
            f"    path: pose/private/{component_name}\n  coco_pose:\n"))
        edit("CMakeLists.txt", lambda s: replace(
            s, "list(APPEND COMPONENT_REQUIRES coco_pose esp-dl)",
            f"list(APPEND COMPONENT_REQUIRES coco_pose esp-dl {component_name})"))
        # Pin model storage to rodata: changing backends never changes partitions.
        with config_path.open("a", encoding="utf-8") as config:
            prefix = "HUMAN_FACE_DETECT" if vision == "face" else "HAND_DETECT"
            config.write(f"\nCONFIG_{prefix}_MODEL_IN_FLASH_RODATA=y\n"
                         f"# CONFIG_{prefix}_MODEL_IN_FLASH_PARTITION is not set\n"
                         f"# CONFIG_{prefix}_MODEL_IN_SDCARD is not set\n")
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
    edit("peripheral/bsp_camera.c", lambda s: replace(
        replace(s,
                '        if ((frames % CAM_LOG_EVERY_FRAMES) == 0) {\n'
                '            TickType_t now = xTaskGetTickCount();',
                '        TickType_t now = xTaskGetTickCount();\n'
                '        if ((TickType_t)(now - t0) >= pdMS_TO_TICKS(1000)) {'),
        '            ESP_LOGE(LOG_TAG, "VIDIOC_QBUF return failed, errno=%d", errno);\n'
        '        }\n',
        '            ESP_LOGE(LOG_TAG, "VIDIOC_QBUF return failed, errno=%d", errno);\n'
        '        }\n'
        '        /* A disconnected sensor may dequeue empty frames immediately.\n'
        '         * Return its buffer before yielding so CLI/Wi-Fi remain usable. */\n'
        '        if (buf.bytesused != expect) vTaskDelay(pdMS_TO_TICKS(100));\n'))
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
    patch = (app.parent / "integration.patch" if work_name else
             ROOT / "artifacts/integration.patch")
    patch.write_text(
        "".join(patches), encoding="utf-8")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["baseline", "headvoice"])
    parser.add_argument("--vision", choices=["coco", "face", "hand"], default="coco")
    parser.add_argument("--work-name")
    parser.add_argument("--face-selftest", action="store_true")
    args = parser.parse_args()
    print(prepare(args.mode, args.vision, args.work_name, args.face_selftest))

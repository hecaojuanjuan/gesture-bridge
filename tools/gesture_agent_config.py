"""Validate local gesture settings and emit a private build-only C header."""
import json
from pathlib import Path
from urllib.parse import urlsplit


def write_config(source, destination):
    config = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"url", "token", "bindings"}:
        raise ValueError("Gesture agent config needs url, token and bindings")
    url, token, bindings = config["url"], config["token"], config["bindings"]
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise ValueError("Bridge URL must be an ASCII HTTPS URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.path != "/v1/gesture" or len(url) > 255):
        raise ValueError("Bridge URL must be https://host[:port]/v1/gesture")
    if (not isinstance(token, str) or not 32 <= len(token) <= 128 or
            any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ValueError("Bridge token must be 32..128 printable ASCII characters")
    if not isinstance(bindings, dict) or not bindings or set(bindings) - {"open_palm", "v_sign"}:
        raise ValueError("Bind open_palm and/or v_sign explicitly")
    for meaning in bindings.values():
        if (not isinstance(meaning, str) or not meaning.strip() or
                len(meaning.encode("utf-8")) > 180 or any(ord(c) < 32 for c in meaning)):
            raise ValueError("Each meaning must be 1..180 UTF-8 bytes without control characters")
    values = {"HV_GESTURE_BRIDGE_URL": url, "HV_GESTURE_BRIDGE_TOKEN": token,
              "HV_GESTURE_OPEN_PALM": bindings.get("open_palm", ""),
              "HV_GESTURE_V_SIGN": bindings.get("v_sign", "")}
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("/* Generated private configuration. Do not commit. */\n" +
                      "\n".join(f"#define {key} {json.dumps(value, ensure_ascii=False)}"
                                for key, value in values.items()) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return output.resolve()


def integrate_agent(source, replace):
    """Patch only reviewed pinned seams; lifecycle entry points share one lock."""
    source = replace(source, '#include "agent_app.h"',
                     '#include "agent_app.h"\n#include "hv_gesture_agent_port.h"')
    source = replace(source, 'static void abort_tts_wait(void);',
                     'static void abort_tts_wait(void);\nstatic void on_wakeup(void);\n'
                     'static void on_cloud_event(ljyd_cloud_event_t event, void *handle, void *userdata);')
    source = replace(source, '    switch ((qm_agent_event_id_t)event_id) {',
                     '    hv_gesture_agent_port_notice(event_id, notice);\n'
                     '    switch ((qm_agent_event_id_t)event_id) {')
    for signature in ('static void on_wakeup(void)',
                      'static void on_cloud_event(ljyd_cloud_event_t event, void *iot_handle, void *userdata)',
                      'int agent_app_leave(void)'):
        name = signature.split('(')[0].split()[-1]
        source = replace(source, signature + '\n{',
                         signature.replace(name, name + '_unlocked').replace('int agent_app_leave_unlocked',
                                                                            'static int agent_app_leave_unlocked') + '\n{')
    source = replace(source, 'int agent_app_init(void *iot_handle)\n{\n    int ret;',
                     'int agent_app_init(void *iot_handle)\n{\n    int ret;\n'
                     '    ret = hv_gesture_agent_port_init();\n    if (ret != QM_EOK) return ret;')
    for signature in ('int agent_app_abort_output(void)', 'int agent_app_user_corpus(const char *text)'):
        source = replace(source, signature + '\n{', signature + '\n{\n    hv_gesture_agent_port_cancel();')
    source = replace(source, 'int agent_app_set_resource_mode(qm_bool active)\n{',
                     'int agent_app_set_resource_mode(qm_bool active)\n{\n'
                     '    hv_gesture_agent_port_resource_mode(active != QM_FALSE);')
    return source + '\n#include "hv_gesture_agent_port.inc"\n'

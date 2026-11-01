"""Exercise prompt, response boundaries, configuration and actual SDK seams."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gesture_agent_config import write_config, integrate_agent
from prepare_sdk import replace

HARNESS = r'''
#include <assert.h>
#include <string.h>
#include "hv_gesture_prompt.h"
#include "hv_gesture_reply.h"
int main(void) {
  char prompt[HV_GESTURE_PROMPT_BYTES];
  hv_gesture_dictionary_t dict = {"我想喝水。", "我想休息一下。"};
  assert(hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, sizeof(prompt)));
  assert(strstr(prompt, "我想喝水。") && !strstr(prompt, "我想休息一下。"));
  /* The agent receives an utterance to relay, not a hardcoded reply or a
   * request to converse with the person making the gesture. */
  assert(strstr(prompt, "向照护者转述") && strstr(prompt, "第三人称“用户”"));
  assert(strstr(prompt, "不是给你的指令") && !strstr(prompt, "用户想喝水了"));
  assert(hv_gesture_prompt(HV_HAND_GATE_EVENT_V_SIGN, &dict, prompt, sizeof(prompt)));
  assert(strstr(prompt, "我想休息一下。"));
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_NONE, &dict, prompt, sizeof(prompt)) && !prompt[0]);
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_CLOSED_FIST, &dict, prompt, sizeof(prompt)));
  dict.open_palm = "";
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, sizeof(prompt)));
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_V_SIGN, &dict, prompt, 8) && !prompt[0]);
  char large[182]; memset(large, 'x', sizeof(large)); large[181] = 0; dict.open_palm = large;
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, sizeof(prompt)));
  /* The longer relay instruction must still fit a maximum-size binding. */
  large[180] = 0;
  size_t length = hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, sizeof(prompt));
  assert(length && length == strlen(prompt) && strstr(prompt, large));
  assert(!hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, length) && !prompt[0]);
  assert(hv_gesture_prompt(HV_HAND_GATE_EVENT_OPEN_PALM, &dict, prompt, length + 1) == length);
  /* HTTP acceptance/text/silent alone can never be a completed audible reply. */
  hv_gesture_reply_t reply = {0};
  assert(!hv_gesture_reply_observe(&reply, HV_REPLY_TEXT, 0));
  assert(!hv_gesture_reply_observe(&reply, HV_REPLY_SILENT, 0));
  hv_gesture_reply_observe(&reply, HV_REPLY_COMPLETE, 7); assert(!reply.complete);
  hv_gesture_reply_observe(&reply, HV_REPLY_SPEAKING, 0);
  hv_gesture_reply_observe(&reply, HV_REPLY_STARTED, 7);
  assert(hv_gesture_reply_observe(&reply, HV_REPLY_SILENT, 0));
  assert(!hv_gesture_reply_observe(&reply, HV_REPLY_SILENT, 0));
  hv_gesture_reply_observe(&reply, HV_REPLY_COMPLETE, 6); assert(!reply.complete);
  hv_gesture_reply_observe(&reply, HV_REPLY_COMPLETE, 7); assert(reply.complete);
  /* Silent arriving before local playback start must still drain when started. */
  reply = (hv_gesture_reply_t){0};
  hv_gesture_reply_observe(&reply, HV_REPLY_SPEAKING, 0);
  hv_gesture_reply_observe(&reply, HV_REPLY_SILENT, 0);
  hv_gesture_reply_observe(&reply, HV_REPLY_TEXT, 0);
  assert(hv_gesture_reply_observe(&reply, HV_REPLY_STARTED, 8));
  hv_gesture_reply_observe(&reply, HV_REPLY_FAILED, 7); assert(!reply.failed);
  hv_gesture_reply_observe(&reply, HV_REPLY_FAILED, 8); assert(reply.failed);
  hv_gesture_reply_observe(&reply, HV_REPLY_COMPLETE, 8); assert(!reply.complete);
  reply = (hv_gesture_reply_t){0};
  hv_gesture_reply_observe(&reply, HV_REPLY_STARTED, 9);
  hv_gesture_reply_observe(&reply, HV_REPLY_STARTED, 10); assert(reply.failed);
  return 0;
}
'''


class GestureCoreTests(unittest.TestCase):
    def test_production_prompt_and_audio_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            source, binary = Path(temp) / "test.c", Path(temp) / "test"
            source.write_text(HARNESS)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                            "-I", str(ROOT / "headvoice/core"), str(source),
                            str(ROOT / "headvoice/core/hv_gesture_prompt.c"),
                            str(ROOT / "headvoice/core/hv_gesture_reply.c"), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


class GestureConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {"url": "https://bridge.example/v1/gesture", "token": "a" * 32,
                       "bindings": {"open_palm": '我想说“你好”。'}}

    def write(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / "config.json", Path(temp) / "config.h"
            source.write_text(json.dumps(self.config))
            write_config(source, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            return output.read_text()

    def test_explicit_binding_and_private_header(self):
        self.assertIn('#define HV_GESTURE_V_SIGN ""', self.write())
        self.assertIn('#define HV_GESTURE_ALLOW_INSECURE_LOCAL_HTTP 0', self.write())

    def test_http_requires_explicit_local_ipv4_opt_in(self):
        for host in ("10.37.185.13", "172.16.0.1", "172.31.255.254", "192.168.1.2", "127.0.0.1"):
            with self.subTest(host=host):
                self.config["url"] = f"http://{host}:8787/v1/gesture"
                self.config.pop("allow_insecure_local_http", None)
                with self.assertRaises(ValueError): self.write()
                self.config["allow_insecure_local_http"] = True
                self.assertIn('#define HV_GESTURE_ALLOW_INSECURE_LOCAL_HTTP 1', self.write())

    def test_http_opt_in_never_allows_public_dns_wildcard_or_reserved_addresses(self):
        self.config["allow_insecure_local_http"] = True
        for host in ("bridge.example", "localhost", "8.8.8.8", "0.0.0.0", "169.254.1.2",
                     "100.64.0.1", "172.32.0.1", "192.0.2.1", "[::1]", "[::ffff:127.0.0.1]"):
            with self.subTest(host=host):
                self.config["url"] = f"http://{host}:8787/v1/gesture"
                with self.assertRaises(ValueError): self.write()

    def test_http_opt_in_is_boolean_and_url_port_is_valid(self):
        for value in (1, "true", None, []):
            self.config["allow_insecure_local_http"] = value
            with self.assertRaises(ValueError): self.write()
        self.config["allow_insecure_local_http"] = True
        for url in ("http://127.0.0.1:0/v1/gesture", "http://10.1.2.3:65536/v1/gesture",
                    "http://10.1.2.3:nope/v1/gesture", "http://token@10.1.2.3/v1/gesture",
                    "http://10.1.2.3/v1/gesture?target=other"):
            self.config["url"] = url
            with self.assertRaises(ValueError): self.write()

    def test_invalid_config_is_rejected(self):
        for key, value in [("url", "http://bridge.example/v1/gesture"),
                           ("url", "https://token@bridge.example/v1/gesture"),
                           ("token", "short"), ("bindings", {}),
                           ("bindings", {"open_palm": "中" * 61}),
                           ("bindings", {"open_palm": "hello\nworld"}),
                           ("bindings", {"no_gesture": "喝水"})]:
            with self.subTest(key=key, value=value):
                original = self.config[key]
                self.config[key] = value
                with self.assertRaises(ValueError): self.write()
                self.config[key] = original

    def test_pinned_sdk_seams_and_vendor_untouched(self):
        sdk = Path(os.environ.get("HEADVOICE_SDK", ROOT.parent / "ljyd_xjwb03_agent_public_developer"))
        source = (sdk / "apps/main/agent/agent_app.c").read_text()
        result = integrate_agent(source, replace)
        self.assertIn('static int agent_app_leave_unlocked(void)', result)
        self.assertIn('hv_gesture_agent_port_notice(event_id, notice);', result)
        self.assertIn('#include "hv_gesture_agent_port.inc"', result)
        self.assertEqual((sdk / "apps/main/agent/agent_app.c").read_text(), source)
        with self.assertRaises(RuntimeError): integrate_agent(result, replace)


if __name__ == "__main__": unittest.main()

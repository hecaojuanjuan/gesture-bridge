"""Execute the USB dictionary protocol and durable-publication failure paths."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_gesture_agent_worker import CJSON, ROOT, STUBS

HARNESS = r'''
#include "hv_gesture_agent.c"
static void command(const char *id,const char *verb,const char *gesture,const char *hex) {
  char *argv[]={(char*)"hg_dict",(char*)id,(char*)verb,(char*)gesture,(char*)hex};
  registered_command->function(NULL,0,gesture?5:3,argv);
}
static void gesture_during_commit(void) {
  unsigned before=queue_calls;
  hv_gesture_agent_submit(HV_HAND_GATE_EVENT_OPEN_PALM,now_ms);
  assert(queue_calls==before); /* No event sees a half-published dictionary. */
}
int main(void) {
  assert(hv_gesture_agent_init()==ESP_OK && registered_command);
  assert(!s_persisted && !s_storage_error);
  command("1","get",NULL,NULL);
  command("2","set","open_palm","E68891E683B3E5969DE6B0B4");
  assert(!strcmp(s_bindings.open_palm,"我想喝水") && s_persisted && storage_commits==1);
  expected_prompt="我想喝水";
  gesture_request_t event={HV_HAND_GATE_EVENT_OPEN_PALM,now_ms,1};
  process_request(&event); assert(http_calls==1 && !atomic_load(&s_active_sequence));
  /* Empty meanings are real unbindings, not a fallback to compiled defaults. */
  command("3","set","open_palm","-");
  event.captured_ms=now_ms; process_request(&event); assert(http_calls==1);
  command("4","set","v_sign","e4bc91e681af");
  assert(!s_bindings.open_palm[0] && !strcmp(s_bindings.v_sign,"休息"));
  s_dictionary_loaded=false; s_persisted=false;
  memset(&s_bindings,0,sizeof(s_bindings)); dictionary_load();
  assert(s_persisted && !s_bindings.open_palm[0] && !strcmp(s_bindings.v_sign,"休息"));
  command("5","get",NULL,NULL);
  unsigned writes=storage_commits;
  const char *bad[]={"0","GG","00","0A","7f","c080","eda080","f4908080","e688","e280a8","c280"};
  for (unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i)
    command("6","set","open_palm",bad[i]);
  command("0","set","open_palm","61");
  command("1000000000","set","open_palm","61");
  command("999999999999999999999","set","open_palm","61");
  command("+1","set","open_palm","61");
  command("7","set","closed_fist","61");
  assert(storage_commits==writes && !s_bindings.open_palm[0]);
  atomic_store(&s_busy,true); command("8","set","open_palm","61");
  assert(storage_commits==writes); atomic_store(&s_busy,false);
  storage_open_error=123; command("9","set","open_palm","61");
  assert(!s_bindings.open_palm[0] && !s_persisted && s_storage_error==123);
  storage_open_error=0; storage_set_error=124; command("10","set","open_palm","61");
  assert(!s_bindings.open_palm[0] && s_storage_error==124 && storage_commits==writes);
  storage_set_error=0; storage_commit_error=125; command("11","set","open_palm","61");
  assert(!s_bindings.open_palm[0] && !s_persisted && s_storage_error==125);
  storage_commit_error=0; during_commit=gesture_during_commit;
  command("12","set","open_palm","e68891e683b3e5969de6b0b4"); during_commit=NULL;
  assert(!strcmp(s_bindings.open_palm,"我想喝水") && !atomic_load(&s_busy) && s_persisted);
  /* A 180-byte value reaches the actual CLI in a single <400-byte line. */
  char longest[363]; memset(longest,'6',362); longest[362]=0;
  command("13","set","open_palm",longest); /* 181 bytes: reject */
  longest[360]=0; command("999999999","set","open_palm",longest);
  assert(strlen(s_bindings.open_palm)==180);
  assert(strlen("hg_dict 999999999 set open_palm ")+strlen(longest)+2<400);
  /* JSON escaping is preserved and test input cannot inject a second record. */
  command("14","set","open_palm","22e5969de6b0b45c22");
  command("15","get",NULL,NULL);
  assert(storage_opens==storage_closes);
  assert(hv_gesture_agent_active_sequence()==0);
  hv_gesture_agent_text(0,"ignored without a current transaction",false);
  atomic_store(&s_active_sequence,77);
  hv_gesture_agent_text(76,"ignored stale transaction",false);
  hv_gesture_agent_text(hv_gesture_agent_active_sequence(),"用户想喝水了。",false);
  hv_gesture_agent_text(77,"不完整的文字",true);
  atomic_store(&s_active_sequence,0);
  /* Corrupt persisted input is reported, never used as an utterance. */
  dictionary_storage_t invalid={.version=2};
  memcpy(storage_blob,&invalid,sizeof(invalid)); storage_length=sizeof(invalid);
  s_dictionary_loaded=false; s_persisted=false; dictionary_load();
  assert(!s_persisted && s_storage_error==ESP_ERR_INVALID_ARG);
  command("16","get",NULL,NULL);
  command("17","arm",NULL,NULL); /* Weak fallback in non-hand/stage builds. */
  assert(storage_opens==storage_closes);
  return 0;
}
'''


class DictionaryFirmwareTests(unittest.TestCase):
    def test_runtime_dictionary_persistence_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "stubs.h").write_text(STUBS, encoding="utf-8")
            (temp / "qm.h").write_text('#include <stdlib.h>\n#define qm_malloc malloc\n#define qm_free free\n')
            for name in ("esp_err.h", "esp_random.h", "esp_timer.h", "qm_http_client.h", "qm_cli.h", "nvs.h",
                         "qm_agent_event.h", "freertos/FreeRTOS.h", "freertos/task.h", "freertos/queue.h"):
                path = temp / name
                path.parent.mkdir(exist_ok=True)
                path.write_text('#include "stubs.h"\n')
            (temp / "config.h").write_text(
                '#define HV_GESTURE_BRIDGE_URL "https://bridge.invalid/v1/gesture"\n'
                '#define HV_GESTURE_BRIDGE_TOKEN "test-token"\n'
                '#define HV_GESTURE_OPEN_PALM "我想喝水。"\n#define HV_GESTURE_V_SIGN ""\n', encoding="utf-8")
            (temp / "test.c").write_text(HARNESS, encoding="utf-8")
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                            "-Dqm_malloc=malloc", "-Dqm_free=free",
                            '-DHV_GESTURE_AGENT_CONFIG_HEADER="config.h"', "-I", str(temp),
                            "-I", str(ROOT / "headvoice/firmware"), "-I", str(ROOT / "headvoice/core"),
                            "-I", str(CJSON), str(temp / "test.c"),
                            str(ROOT / "headvoice/core/hv_gesture_prompt.c"), str(CJSON / "cJSON.c"),
                            "-o", str(temp / "test")], check=True)
            result = subprocess.run([str(temp / "test")], check=True, capture_output=True, text=True)
            reports = [json.loads(line[4:]) for line in result.stdout.splitlines() if line.startswith("HGD ")]
            by_id = {report["id"]: report for report in reports}
            self.assertEqual(by_id[2]["bindings"]["open_palm"], "我想喝水")
            self.assertTrue(by_id[2]["ok"] and by_id[2]["persisted"])
            self.assertEqual(by_id[5]["bindings"], {"open_palm": "", "v_sign": "休息"})
            self.assertEqual(by_id[8]["code"], "busy")
            for request_id in (9, 10, 11):
                self.assertFalse(by_id[request_id]["ok"])
                self.assertEqual(by_id[request_id]["code"], "storage_failed")
                self.assertEqual(by_id[request_id]["bindings"]["open_palm"], "")
            self.assertEqual(by_id[15]["bindings"]["open_palm"], '"喝水\\"')
            self.assertTrue(all(report["boot"] == "1234567812345678" for report in reports))
            self.assertTrue(all(report["max_age_ms"] == 1000 for report in reports))
            self.assertEqual(by_id[17]["code"], "unsupported")
            self.assertFalse(by_id[17]["scan_supported"])
            agents = [json.loads(line[9:]) for line in result.stdout.splitlines() if line.startswith("HG_AGENT ")]
            replies = [record for record in agents if record["state"] == "reply"]
            self.assertEqual([(r["id"], r["text"], r["truncated"]) for r in replies],
                             [(77, "用户想喝水了。", False), (77, "不完整的文字", True)])

    def test_arm_strong_backend_override_and_submit_handoff_race(self):
        harness = r'''
#include "hv_gesture_agent.c"
void scan_test_dispatch(void (*callback)(void));
unsigned scan_test_arm_calls(void);
static void arm(const char *id) {
  char *argv[]={(char*)"hg_dict",(char*)id,(char*)"arm"};
  dictionary_command(NULL,0,3,argv);
}
static void submit_during_arm(void) {
  hv_gesture_agent_submit(HV_HAND_GATE_EVENT_OPEN_PALM,now_ms);
}
int main(void) {
  assert(hv_gesture_agent_init()==ESP_OK);
  arm("1"); headvoice_scan_status_t scan; headvoice_scan_status(&scan);
  assert(scan.supported && scan.armed && scan.generation==2);
  arm("2"); headvoice_scan_status(&scan); assert(scan.generation==2);
  unsigned calls=scan_test_arm_calls(); atomic_store(&s_busy,true);
  arm("3"); assert(scan_test_arm_calls()==calls && atomic_load(&s_busy));
  atomic_store(&s_busy,false);
  /* The hand controller is disarmed but still dispatching a real event.
   * Its submit interleaves after CLI busy-check and must retain the worker. */
  scan_test_dispatch(submit_during_arm); arm("4");
  assert(queue_calls==1 && atomic_load(&s_busy));
  headvoice_scan_status(&scan); assert(!scan.armed && scan.generation==2);
  atomic_store(&s_busy,false); scan_test_dispatch(NULL);
  arm("5"); headvoice_scan_status(&scan); assert(scan.armed && scan.generation==3);
  return 0;
}
'''
        override = r'''
/* A separate translation unit proves the hand backend overrides weak defaults. */
#define WORKER_STUBS_H
typedef int esp_err_t;
#include "headvoice_app.h"
static headvoice_scan_status_t scan={.supported=true,.generation=1,.palm_count=1,.last_gesture="open_palm"};
static void (*dispatch_callback)(void);
static unsigned calls;
void headvoice_scan_status(headvoice_scan_status_t *out) { *out=scan; }
bool headvoice_scan_arm(void) {
  ++calls;
  if(dispatch_callback) { dispatch_callback(); return false; }
  if(!scan.armed) { scan.armed=true; ++scan.generation; }
  return true;
}
void scan_test_dispatch(void (*callback)(void)) { scan.armed=false; dispatch_callback=callback; }
unsigned scan_test_arm_calls(void) { return calls; }
'''
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "stubs.h").write_text(STUBS, encoding="utf-8")
            (temp / "qm.h").write_text('#include <stdlib.h>\n#define qm_malloc malloc\n#define qm_free free\n')
            for name in ("esp_err.h", "esp_random.h", "esp_timer.h", "qm_http_client.h", "qm_cli.h", "nvs.h",
                         "qm_agent_event.h", "freertos/FreeRTOS.h", "freertos/task.h", "freertos/queue.h"):
                path = temp / name
                path.parent.mkdir(exist_ok=True)
                path.write_text('#include "stubs.h"\n')
            (temp / "config.h").write_text(
                '#define HV_GESTURE_BRIDGE_URL "https://bridge.invalid/v1/gesture"\n'
                '#define HV_GESTURE_BRIDGE_TOKEN "test-token"\n'
                '#define HV_GESTURE_OPEN_PALM "我想喝水。"\n#define HV_GESTURE_V_SIGN ""\n', encoding="utf-8")
            (temp / "test.c").write_text(harness, encoding="utf-8")
            (temp / "scan.c").write_text(override, encoding="utf-8")
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                            "-Dqm_malloc=malloc", "-Dqm_free=free",
                            '-DHV_GESTURE_AGENT_CONFIG_HEADER="config.h"', "-I", str(temp),
                            "-I", str(ROOT / "headvoice/firmware"), "-I", str(ROOT / "headvoice/core"),
                            "-I", str(CJSON), str(temp / "test.c"), str(temp / "scan.c"),
                            str(ROOT / "headvoice/core/hv_gesture_prompt.c"), str(CJSON / "cJSON.c"),
                            "-o", str(temp / "test")], check=True)
            result = subprocess.run([str(temp / "test")], check=True, capture_output=True, text=True)
            reports = [json.loads(line[4:]) for line in result.stdout.splitlines() if line.startswith("HGD ")]
            by_id = {report["id"]: report for report in reports}
            self.assertTrue(by_id[1]["scan_armed"])
            self.assertEqual(by_id[2]["scan_generation"], 2)
            self.assertEqual(by_id[3]["code"], "busy")
            self.assertEqual(by_id[4]["code"], "busy")
            self.assertTrue(by_id[4]["agent_busy"])
            self.assertFalse(by_id[4]["scan_armed"])
            self.assertEqual(by_id[5]["scan_generation"], 3)


if __name__ == "__main__": unittest.main()

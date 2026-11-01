"""Exercise the real diagnostic CLI/task using deterministic SDK boundaries."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUBS = r'''
#ifndef PROBE_STUBS_H
#define PROBE_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef int esp_err_t;
typedef int portMUX_TYPE;
typedef struct { int unused; } qm_agent_event_notice_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define QM_EOK 0
#define QM_ETIMEOUT 2
#define QM_ENOMEM 5
#define QM_ENOSYS 6
#define QM_EBUSY 7
#define QM_EIO 8
#define QM_EINTR 9
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) do { assert(!*(p)); *(p)=1; } while(0)
#define portEXIT_CRITICAL(p) do { assert(*(p)); *(p)=0; } while(0)
static uint64_t now_ms=1000, arm_ms, abort_at;
static unsigned starts, ends, arms, spawned, ready_calls;
static int begin_result, ready_result=1, poll_result=2, end_result, register_result;
static bool task_failure;
static void (*pending_task)(void*);
static void test_tick(void);
static int64_t esp_timer_get_time(void) { return (int64_t)now_ms*1000; }
static void vTaskDelay(unsigned ms) { now_ms+=ms; test_tick(); }
static void vTaskDelete(void *task) { assert(!task); }
static int xTaskCreate(void (*fn)(void*),const char *name,unsigned stack,void *arg,unsigned priority,void *handle)
{ assert(fn && name && stack>=8192); (void)arg;(void)priority;(void)handle;
  ++spawned; pending_task=fn; return !task_failure; }
struct qm_cli_command { const char *name, *help; void (*function)(char*,int,int,char**); };
static int qm_cli_register_command(const struct qm_cli_command *c) { assert(c && c->function); return register_result; }
#define qm_cli_printf printf
int hv_gesture_agent_port_begin_detail(const char **detail) {
  ++starts; *detail=begin_result ? "cloud_disconnected" : "ready"; return begin_result;
}
int hv_gesture_agent_port_status(const char **detail) {
  *detail=begin_result ? "cloud_disconnected" : "ready"; return begin_result;
}
int hv_gesture_agent_port_ready(void) { ++ready_calls; return ready_result; }
int hv_gesture_agent_port_arm(void) { ++arms; arm_ms=now_ms; return 0; }
int hv_gesture_agent_port_poll(void) { return poll_result; }
int hv_gesture_agent_port_end(void) { ++ends; return end_result; }
#endif
'''
HARNESS = r'''
#include "hv_gesture_probe.c"
static void test_tick(void) { if (abort_at && now_ms>=abort_at) s_probe_abort=true; }
static void command(const char *action, const char *marker) {
  char *argv[]={"hg_agent",(char*)action,(char*)marker}; probe_command(NULL,0,3,argv);
}
static void run(void) { assert(pending_task); pending_task(NULL); assert(!s_probe_busy); }
int main(void) {
  register_result=-1; assert(hv_gesture_probe_init()==ESP_FAIL);
  register_result=0; assert(hv_gesture_probe_init()==ESP_OK);
  char *status[]={"hg_agent","status"};
  probe_command(NULL,0,2,status);
  begin_result=-QM_EBUSY; probe_command(NULL,0,2,status); begin_result=0;
  assert(!starts && !ends && !arms && !spawned && !s_probe_busy && !s_probe_abort);
  command("probe","bad"); assert(!spawned);
  command("probe","GB12345678"); assert(spawned==1 && s_probe_busy);
  command("probe","GB87654321"); assert(spawned==1);
  command("abort","GB87654321"); assert(!s_probe_abort);
  command("abort","GB12345678"); run(); assert(!starts && !ends);
  command("probe","GB12345678"); uint64_t before=now_ms;
  run(); assert(starts==1 && ends==1 && arms==1 && arm_ms-before>=600);
  begin_result=-QM_EBUSY; command("probe","GB12345678");
  run(); assert(starts==2 && ends==1 && arms==1); /* no ownership, no cleanup */
  begin_result=0; ready_result=0; command("probe","GB12345678"); before=now_ms;
  run(); assert(now_ms-before>=15000 && ends==2 && arms==1);
  ready_result=1; poll_result=0; command("probe","GB12345678");
  abort_at=now_ms+1000; run(); assert(ends==3 && arms==2); abort_at=0;
  command("probe","GB12345678"); before=now_ms;
  run(); assert(now_ms-before>=90600 && ends==4); /* bounded even without host */
  task_failure=true; command("probe","GB12345678"); assert(!s_probe_busy);
  task_failure=false; poll_result=2; end_result=-QM_EIO;
  command("probe","GB12345678"); run(); assert(ends==5);
  end_result=0; poll_result=HV_GESTURE_PORT_COMPLETION_UNSUPPORTED;
  command("probe","GB12345678"); run(); assert(ends==6);
  return 0;
}
'''


class DiagnosticFirmwareTests(unittest.TestCase):
    def test_ownership_quiet_readiness_abort_and_deadlines(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "stubs.h").write_text(STUBS)
            for name in ("esp_err.h", "esp_timer.h", "qm.h", "qm_cli.h", "qm_agent_event.h",
                         "freertos/FreeRTOS.h", "freertos/task.h"):
                path = temp / name; path.parent.mkdir(exist_ok=True)
                path.write_text('#include "stubs.h"\n')
            (temp / "test.c").write_text(HARNESS)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                            "-DHV_GESTURE_AGENT_DIAGNOSTICS=1", "-I", str(temp),
                            "-I", str(ROOT / "headvoice/firmware"), str(temp / "test.c"),
                            "-o", str(temp / "test")], check=True)
            result = subprocess.run([str(temp / "test")], check=True, capture_output=True, text=True)
            records = [json.loads(line[9:]) for line in result.stdout.splitlines()
                       if line.startswith("HG_PROBE ")]
            states = [record["state"] for record in records]
            self.assertEqual(states.count("ready"), 5)
            self.assertEqual(states.count("playback_complete"), 2)
            self.assertEqual(states.count("ended"), 5)
            self.assertEqual(states.count("playback_completion_unsupported"), 1)
            self.assertIn("not_owned", states)
            self.assertIn("cleanup_failed", states)
            unavailable = [record for record in records if record["state"] == "unavailable"]
            self.assertEqual([(record["code"], record.get("detail")) for record in unavailable],
                             [(-9, "cancelled"), (-7, "cloud_disconnected"), (-5, None)])
            status = [json.loads(line[len("HG_AGENT_STATUS "):]) for line in result.stdout.splitlines()
                      if line.startswith("HG_AGENT_STATUS ")]
            self.assertEqual(status, [{"v": 1, "code": 0, "detail": "ready"},
                                      {"v": 1, "code": -7, "detail": "cloud_disconnected"}])


if __name__ == "__main__": unittest.main()

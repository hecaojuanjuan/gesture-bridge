"""Execute the real async worker and HTTP envelope with deterministic I/O."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CJSON = ROOT.parent / "ljyd_xjwb03_agent_public_developer/qumios-dev/components/cjson"
STUBS = r'''
#ifndef WORKER_STUBS_H
#define WORKER_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "cJSON.h"
typedef int esp_err_t;
typedef int qm_bool;
typedef void *QueueHandle_t;
typedef struct { int unused; } qm_agent_event_notice_t;
#define ESP_OK 0
#define ESP_ERR_NO_MEM -2
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define CONFIG_QM_CLI_SUPPORT 1
#define CONFIG_QM_CLI_INBUF_SIZE 512
#define CONFIG_QM_CLI_MAX_ARG_NUM 8
#define QM_EOK 0
#define QM_ETIMEOUT 2
#define QM_EFULL 3
#define QM_ENOMEM 5
#define QM_ENOSYS 6
#define QM_EBUSY 7
#define QM_EIO 8
#define QM_EINTR 9
#define QM_EINVAL 10
#define QM_EINIT 11
#define QM_TRUE 1
#define QM_FALSE 0
#define QM_HTTP_POST 1
#define pdTRUE 1
#define pdPASS 1
#define portMAX_DELAY 0xffffffffu
#define pdMS_TO_TICKS(x) (x)
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) do { assert(!*(p)); *(p)=1; } while(0)
#define portEXIT_CRITICAL(p) do { assert(*(p)); *(p)=0; } while(0)
typedef unsigned nvs_handle_t;
#define NVS_READONLY 0
#define NVS_READWRITE 1
static int storage_open_error, storage_set_error, storage_commit_error;
static unsigned storage_opens, storage_closes, storage_commits;
static unsigned char storage_blob[512], storage_pending[512];
static size_t storage_length, storage_pending_length;
static void (*during_commit)(void);
static esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle) {
  assert(!strcmp(name,"hv_gesture") && (mode==NVS_READONLY || mode==NVS_READWRITE));
  if (storage_open_error) return storage_open_error;
  ++storage_opens; *handle=1; return ESP_OK;
}
static esp_err_t nvs_get_blob(nvs_handle_t handle,const char *key,void *value,size_t *length) {
  assert(handle==1 && !strcmp(key,"dictionary"));
  if (!storage_length) return ESP_ERR_NVS_NOT_FOUND;
  if (*length<storage_length) return ESP_ERR_INVALID_ARG;
  memcpy(value,storage_blob,storage_length); *length=storage_length; return ESP_OK;
}
static esp_err_t nvs_set_blob(nvs_handle_t handle,const char *key,const void *value,size_t length) {
  assert(handle==1 && !strcmp(key,"dictionary") && length<=sizeof(storage_pending));
  if (storage_set_error) return storage_set_error;
  memcpy(storage_pending,value,length); storage_pending_length=length; return ESP_OK;
}
static esp_err_t nvs_commit(nvs_handle_t handle) {
  assert(handle==1); ++storage_commits;
  if (during_commit) during_commit();
  if (storage_commit_error) return storage_commit_error;
  memcpy(storage_blob,storage_pending,storage_pending_length); storage_length=storage_pending_length;
  return ESP_OK;
}
static void nvs_close(nvs_handle_t handle) { assert(handle==1); ++storage_closes; }
struct qm_cli_command { const char *name,*help; void (*function)(char*,int,int,char**); };
static const struct qm_cli_command *registered_command;
static int qm_cli_register_command(const struct qm_cli_command *command) {
  assert(!strcmp(command->name,"hg_dict")); registered_command=command; return 0;
}
typedef struct { const char *name, *value; } qm_http_header_t;
typedef struct {
  int method; const char *url, *body; int body_len; const char *content_type;
  const qm_http_header_t *headers; int header_count; unsigned timeout_ms, max_body_len;
  int disable_auto_redirect; void *user;
  int (*on_body)(const char *,int,void *); qm_bool (*interrupted)(void *);
} qm_http_client_request_t;
typedef struct { int status_code; } qm_http_client_response_t;
static uint64_t now_ms=1000;
static unsigned start_calls, cleanup_calls, http_calls, queue_calls;
static int begin_result, ready_result=1, poll_result=2, http_result, response_status=200;
static bool cancelled, bad_ack, task_failure;
static const char *expected_prompt="我想喝水。";
static int64_t esp_timer_get_time(void) { return (int64_t)now_ms*1000; }
static uint32_t esp_random(void) { return 0x12345678; }
static void vTaskDelay(unsigned ms) { now_ms+=ms; }
static QueueHandle_t xQueueCreate(unsigned count,size_t size) { assert(count==1 && size); return (void*)1; }
static void vQueueDelete(QueueHandle_t q) { assert(q); }
static int xTaskCreate(void (*fn)(void*),const char *name,unsigned stack,void *arg,unsigned priority,void *handle)
{ assert(fn && name && stack>=8192); (void)arg;(void)priority;(void)handle;return !task_failure; }
static int xQueueReceive(QueueHandle_t q,void *out,unsigned wait) { (void)q;(void)out;(void)wait;return 0; }
static int xQueueSend(QueueHandle_t q,const void *in,unsigned wait) { assert(q && in && wait==0);++queue_calls;return 1; }
int hv_gesture_agent_port_begin_detail(const char **detail) {
  ++start_calls; *detail=begin_result ? "cloud_disconnected" : "ready"; return begin_result;
}
int hv_gesture_agent_port_ready(void) { return ready_result; }
const char *hv_gesture_agent_port_ready_detail(void) { return ready_result==1 ? "ready" : "waiting_running"; }
int hv_gesture_agent_port_arm(void) { return cancelled ? -QM_EINTR : 0; }
int hv_gesture_agent_port_poll(void) { return poll_result; }
bool hv_gesture_agent_port_cancelled(void *unused) { (void)unused; return cancelled; }
int hv_gesture_agent_port_end(void) { ++cleanup_calls; return 0; }
static int qm_http_client_execute(const qm_http_client_request_t *request,qm_http_client_response_t *response) {
  ++http_calls;
  assert(request->method==QM_HTTP_POST && request->disable_auto_redirect);
  assert(!strcmp(request->url,"https://bridge.invalid/v1/gesture"));
  assert(!strcmp(request->headers->name,"Authorization"));
  assert(!strcmp(request->headers->value,"Bearer test-token"));
  assert(request->body_len==(int)strlen(request->body));
  cJSON *body=cJSON_Parse(request->body); assert(body);
  const char *id=cJSON_GetObjectItem(body,"event_id")->valuestring;
  const char *prompt=cJSON_GetObjectItem(body,"prompt")->valuestring;
  assert(strstr(prompt,expected_prompt));
  assert(strstr(id,"1234567812345678-")==id);
  char output[256]; snprintf(output,sizeof(output),"{\"accepted\":true,\"event_id\":\"%s\"}",bad_ack?"wrong":id);
  cJSON_Delete(body);
  response->status_code=response_status;
  assert(request->on_body(output,7,request->user)==0);
  assert(request->on_body(output+7,(int)strlen(output)-7,request->user)==0);
  assert(!request->interrupted(request->user));
  return http_result;
}
#endif
'''
HARNESS = r'''
#include "hv_gesture_agent.c"
int main(void) {
  task_failure=true; assert(hv_gesture_agent_init()==ESP_ERR_NO_MEM && !s_requests);
  task_failure=false; assert(hv_gesture_agent_init()==0);
  hv_gesture_agent_submit(HV_HAND_GATE_EVENT_NONE,now_ms); assert(!queue_calls);
  hv_gesture_agent_submit(HV_HAND_GATE_EVENT_OPEN_PALM,now_ms);
  hv_gesture_agent_submit(HV_HAND_GATE_EVENT_V_SIGN,now_ms); assert(queue_calls==1);
  gesture_request_t event={HV_HAND_GATE_EVENT_OPEN_PALM,now_ms,1};
  process_request(&event); assert(http_calls==1 && cleanup_calls==1);
  unsigned calls=http_calls;
  event.gesture=HV_HAND_GATE_EVENT_V_SIGN; event.captured_ms=now_ms;
  process_request(&event); assert(http_calls==calls); /* unbound */
  event.gesture=HV_HAND_GATE_EVENT_OPEN_PALM; event.captured_ms=now_ms-1;
  now_ms+=3001; process_request(&event); assert(http_calls==calls); /* expired */
  event.captured_ms=now_ms; begin_result=-QM_EBUSY;
  process_request(&event); assert(http_calls==calls && cleanup_calls==1);
  begin_result=0; ready_result=0;
  process_request(&event); assert(http_calls==calls && cleanup_calls==2); /* ready timeout */
  ready_result=-QM_EINTR; event.captured_ms=now_ms;
  process_request(&event); assert(http_calls==calls && cleanup_calls==3);
  ready_result=1; event.captured_ms=now_ms; bad_ack=true;
  process_request(&event); assert(http_calls==calls+1 && cleanup_calls==4);
  bad_ack=false; event.captured_ms=now_ms; response_status=502;
  process_request(&event); assert(http_calls==calls+2 && cleanup_calls==5);
  response_status=200; event.captured_ms=now_ms; http_result=-QM_ETIMEOUT;
  process_request(&event); assert(http_calls==calls+3 && cleanup_calls==6); /* no retry */
  http_result=0; event.captured_ms=now_ms; poll_result=-QM_EIO;
  process_request(&event); assert(http_calls==calls+4 && cleanup_calls==7);
  event.captured_ms=now_ms; poll_result=0;
  process_request(&event); assert(http_calls==calls+5 && cleanup_calls==8); /* no audio timeout */
  event.captured_ms=now_ms; poll_result=HV_GESTURE_PORT_COMPLETION_UNSUPPORTED;
  process_request(&event); assert(http_calls==calls+6 && cleanup_calls==9);
  return 0;
}
'''


class WorkerTests(unittest.TestCase):
    def test_actual_worker_request_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "stubs.h").write_text(STUBS)
            (temp / "qm.h").write_text('#include <stdlib.h>\n#define qm_malloc malloc\n#define qm_free free\n')
            for name in ("esp_err.h", "esp_random.h", "esp_timer.h", "qm_http_client.h", "qm_cli.h", "nvs.h",
                         "qm_agent_event.h", "freertos/FreeRTOS.h", "freertos/task.h", "freertos/queue.h"):
                path = temp / name; path.parent.mkdir(exist_ok=True)
                path.write_text('#include "stubs.h"\n')
            (temp / "config.h").write_text(
                '#define HV_GESTURE_BRIDGE_URL "https://bridge.invalid/v1/gesture"\n'
                '#define HV_GESTURE_BRIDGE_TOKEN "test-token"\n'
                '#define HV_GESTURE_OPEN_PALM "我想喝水。"\n#define HV_GESTURE_V_SIGN ""\n')
            (temp / "test.c").write_text(HARNESS)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                            "-Dqm_malloc=malloc", "-Dqm_free=free",
                            '-DHV_GESTURE_AGENT_CONFIG_HEADER="config.h"', "-I", str(temp),
                            "-I", str(ROOT / "headvoice/firmware"), "-I", str(ROOT / "headvoice/core"),
                            "-I", str(CJSON), str(temp / "test.c"),
                            str(ROOT / "headvoice/core/hv_gesture_prompt.c"), str(CJSON / "cJSON.c"),
                            "-o", str(temp / "test")], check=True)
            result = subprocess.run([str(temp / "test")], check=True, capture_output=True, text=True)
            records = [json.loads(line[9:]) for line in result.stdout.splitlines()]
            states = [record["state"] for record in records]
            self.assertEqual(states.count("playback_complete"), 1)
            self.assertEqual(states.count("playback_completion_unsupported"), 1)
            self.assertIn("busy", states)
            self.assertIn("expired", states)
            self.assertIn("unbound", states)
            unavailable = [record for record in records if record["state"] == "unavailable"]
            self.assertEqual([(record["code"], record["detail"]) for record in unavailable],
                             [(-7, "cloud_disconnected")])
            self.assertEqual(states.count("failed"), 7)
            failures = [record for record in records if record["state"] == "failed"]
            self.assertEqual([record["phase"] for record in failures],
                             ["connecting", "connecting", "sending", "sending", "sending", "reply", "reply"])
            self.assertTrue(all(record.get("detail") == "waiting_running" for record in failures[:2]))
            self.assertTrue(all("detail" not in record for record in failures[2:]))


if __name__ == "__main__": unittest.main()

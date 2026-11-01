#include "hv_gesture_agent.h"
#include "hv_gesture_probe.h"
#include <stdio.h>

#if defined(HV_GESTURE_AGENT_CONFIG_HEADER)
#include HV_GESTURE_AGENT_CONFIG_HEADER
#include <stdatomic.h>
#include <string.h>
#include "cJSON.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "hv_gesture_agent_port.h"
#include "hv_gesture_prompt.h"
#include "qm.h"
#include "qm_http_client.h"

typedef struct {
  hv_hand_gate_event_t gesture;
  uint64_t captured_ms;
  unsigned sequence;
} gesture_request_t;
static QueueHandle_t s_requests;
static atomic_bool s_busy;
static atomic_uint s_sequence;
static char s_boot[17];
static const hv_gesture_dictionary_t s_dictionary = {
  .open_palm = HV_GESTURE_OPEN_PALM, .v_sign = HV_GESTURE_V_SIGN
};

static uint64_t gesture_now(void) { return (uint64_t)(esp_timer_get_time() / 1000); }
static void report(unsigned sequence, const char *state, int code)
{
  printf("HG_AGENT {\"v\":1,\"id\":%u,\"state\":\"%s\",\"code\":%d}\n",
         sequence, state, code);
}

typedef struct { char bytes[256]; size_t length; } response_body_t;
static int response_body(const char *data, int length, void *user)
{
  response_body_t *body = user;
  if (length < 0 || (size_t)length >= sizeof(body->bytes) - body->length) return -QM_EFULL;
  memcpy(body->bytes + body->length, data, (size_t)length);
  body->length += (size_t)length;
  body->bytes[body->length] = '\0';
  return QM_EOK;
}

static qm_bool request_cancelled(void *unused)
{
  return hv_gesture_agent_port_cancelled(unused) ? QM_TRUE : QM_FALSE;
}

static int send_prompt(const gesture_request_t *event, const char *prompt)
{
  char id[32];
  snprintf(id, sizeof(id), "%s-%u", s_boot, event->sequence);
  cJSON *payload = cJSON_CreateObject();
  if (!payload) return -QM_ENOMEM;
  bool ok = cJSON_AddStringToObject(payload, "event_id", id) &&
            cJSON_AddStringToObject(payload, "prompt", prompt);
  char *json = ok ? cJSON_PrintUnformatted(payload) : NULL;
  cJSON_Delete(payload);
  if (!json) return -QM_ENOMEM;
  qm_http_header_t authorization = { .name = "Authorization", .value = "Bearer " HV_GESTURE_BRIDGE_TOKEN };
  response_body_t body = {0};
  qm_http_client_request_t request = {
    .method = QM_HTTP_POST, .url = HV_GESTURE_BRIDGE_URL,
    .body = json, .body_len = (int)strlen(json), .content_type = "application/json",
    .headers = &authorization, .header_count = 1, .timeout_ms = 15000,
    .max_body_len = sizeof(body.bytes) - 1, .disable_auto_redirect = QM_TRUE,
    .user = &body, .on_body = response_body, .interrupted = request_cancelled
  };
  qm_http_client_response_t response = {0};
  int ret = qm_http_client_execute(&request, &response);
  cJSON_free(json);
  if (ret != QM_EOK) return ret;
  if (response.status_code != 200) return -QM_EIO;
  payload = cJSON_Parse(body.bytes);
  cJSON *accepted = cJSON_GetObjectItemCaseSensitive(payload, "accepted");
  cJSON *reply_id = cJSON_GetObjectItemCaseSensitive(payload, "event_id");
  ok = cJSON_IsTrue(accepted) && cJSON_IsString(reply_id) && !strcmp(reply_id->valuestring, id);
  cJSON_Delete(payload);
  return ok ? QM_EOK : -QM_EIO;
}

static void process_request(const gesture_request_t *event)
{
  char prompt[HV_GESTURE_PROMPT_BYTES];
  if (!hv_gesture_prompt(event->gesture, &s_dictionary, prompt, sizeof(prompt))) {
    report(event->sequence, "unbound", -QM_EINVAL);
    return;
  }
  uint64_t now = gesture_now();
  if (now < event->captured_ms || now - event->captured_ms > 3000) {
    report(event->sequence, "expired", -QM_ETIMEOUT);
    return;
  }
  int ret = hv_gesture_agent_port_begin();
  if (ret != QM_EOK) { report(event->sequence, "unavailable", ret); return; }
  report(event->sequence, "connecting", 0);
  uint64_t deadline = now + 15000, quiet_since = 0;
  for (;;) {
    now = gesture_now();
    ret = hv_gesture_agent_port_ready();
    if (ret < 0) break;
    if (now >= deadline) { ret = -QM_ETIMEOUT; break; }
    if (ret == 1) {
      if (!quiet_since) quiet_since = now;
      if (now - quiet_since >= 600) { ret = QM_EOK; break; }
    } else quiet_since = 0;
    vTaskDelay(pdMS_TO_TICKS(20));
  }
  if (ret == QM_EOK) ret = hv_gesture_agent_port_arm();
  if (ret == QM_EOK) {
    report(event->sequence, "sending", 0);
    ret = send_prompt(event, prompt);
  }
  if (ret == QM_EOK) {
    report(event->sequence, "accepted", 0);
    deadline = gesture_now() + 45000;
    bool started = false;
    for (;;) {
      int state = hv_gesture_agent_port_poll();
      if (state < 0) { ret = state; break; }
      if (state >= 1 && !started) { report(event->sequence, "speaking", 0); started = true; }
      if (state == 2) { report(event->sequence, "playback_complete", 0); break; }
      if (state == HV_GESTURE_PORT_COMPLETION_UNSUPPORTED) {
        report(event->sequence, "playback_completion_unsupported", -QM_ENOSYS);
        break;
      }
      if (gesture_now() >= deadline) { ret = -QM_ETIMEOUT; break; }
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
  if (ret != QM_EOK) report(event->sequence, "failed", ret);
  int cleanup = hv_gesture_agent_port_end();
  if (cleanup != QM_EOK) report(event->sequence, "cleanup_failed", cleanup);
}

static void gesture_task(void *unused)
{
  (void)unused;
  for (;;) {
    gesture_request_t request;
    if (xQueueReceive(s_requests, &request, portMAX_DELAY) != pdTRUE) continue;
    process_request(&request);
    atomic_store(&s_busy, false);
  }
}

esp_err_t hv_gesture_agent_init(void)
{
  esp_err_t diagnostic = hv_gesture_probe_init();
  if (diagnostic != ESP_OK) return diagnostic;
  if (s_requests) return ESP_OK;
  snprintf(s_boot, sizeof(s_boot), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
  s_requests = xQueueCreate(1, sizeof(gesture_request_t));
  if (!s_requests) return ESP_ERR_NO_MEM;
  /* HTTPS/JSON run on an internal stack, never on the vision task or callbacks. */
  if (xTaskCreate(gesture_task, "hv_gesture_agent", 8192, NULL, 3, NULL) != pdPASS) {
    vQueueDelete(s_requests); s_requests = NULL; return ESP_ERR_NO_MEM;
  }
  report(0, "ready", 0);
  return ESP_OK;
}

void hv_gesture_agent_submit(hv_hand_gate_event_t event, uint64_t captured_ms)
{
  if (event != HV_HAND_GATE_EVENT_OPEN_PALM && event != HV_HAND_GATE_EVENT_V_SIGN) return;
  unsigned sequence = atomic_fetch_add(&s_sequence, 1) + 1;
  if (!s_requests) { report(sequence, "unavailable", -QM_EINIT); return; }
  if (atomic_exchange(&s_busy, true)) { report(sequence, "busy", -QM_EBUSY); return; }
  gesture_request_t request = {event, captured_ms, sequence};
  if (xQueueSend(s_requests, &request, 0) != pdTRUE) {
    atomic_store(&s_busy, false); report(sequence, "busy", -QM_EFULL);
  }
}
#else
esp_err_t hv_gesture_agent_init(void)
{
  esp_err_t diagnostic = hv_gesture_probe_init();
  if (diagnostic != ESP_OK) return diagnostic;
  printf("HG_AGENT {\"v\":1,\"id\":0,\"state\":\"not_configured\",\"code\":0}\n");
  return ESP_OK;
}
void hv_gesture_agent_submit(hv_hand_gate_event_t event, uint64_t captured_ms)
{ (void)event; (void)captured_ms; }
#endif

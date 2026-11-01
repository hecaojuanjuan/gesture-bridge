#include "hv_gesture_agent.h"
#include "hv_gesture_probe.h"
#include "headvoice_app.h"
#include <stdio.h>

/* Other vision/stage builds have no hand scan controller. The hand app's
 * strong definitions replace these without introducing new link dependencies. */
__attribute__((weak)) void headvoice_scan_status(headvoice_scan_status_t *out)
{
  if (out) *out = (headvoice_scan_status_t){.last_gesture = "none"};
}
__attribute__((weak)) bool headvoice_scan_arm(void) { return false; }

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
#include "nvs.h"
#include "qm.h"
#include "qm_cli.h"
#include "qm_http_client.h"

typedef struct {
  hv_hand_gate_event_t gesture;
  uint64_t captured_ms;
  unsigned sequence;
} gesture_request_t;
static QueueHandle_t s_requests;
static atomic_bool s_busy;
static atomic_uint s_sequence;
static atomic_uint s_active_sequence;
static char s_boot[17];
typedef struct {
  uint32_t version;
  char open_palm[HV_GESTURE_MEANING_BYTES];
  char v_sign[HV_GESTURE_MEANING_BYTES];
} dictionary_storage_t;
static dictionary_storage_t s_bindings = {
  .version = 1, .open_palm = HV_GESTURE_OPEN_PALM, .v_sign = HV_GESTURE_V_SIGN
};
static const hv_gesture_dictionary_t s_dictionary = {
  .open_palm = s_bindings.open_palm, .v_sign = s_bindings.v_sign
};
static bool s_dictionary_loaded, s_persisted;
static esp_err_t s_storage_error;

static uint64_t gesture_now(void) { return (uint64_t)(esp_timer_get_time() / 1000); }
static void report(unsigned sequence, const char *state, int code)
{
  printf("HG_AGENT {\"v\":1,\"boot\":\"%s\",\"id\":%u,\"state\":\"%s\",\"code\":%d}\n",
         s_boot, sequence, state, code);
}

static void report_failure(unsigned sequence, int code, const char *phase)
{
  if (!strcmp(phase, "connecting"))
    printf("HG_AGENT {\"v\":1,\"boot\":\"%s\",\"id\":%u,\"state\":\"failed\","
           "\"code\":%d,\"phase\":\"%s\",\"detail\":\"%s\"}\n",
           s_boot, sequence, code, phase, hv_gesture_agent_port_ready_detail());
  else printf("HG_AGENT {\"v\":1,\"boot\":\"%s\",\"id\":%u,\"state\":\"failed\","
              "\"code\":%d,\"phase\":\"%s\"}\n", s_boot, sequence, code, phase);
}

unsigned hv_gesture_agent_active_sequence(void)
{
  return atomic_load(&s_active_sequence);
}

void hv_gesture_agent_text(unsigned sequence, const char *text, bool truncated)
{
  if (!sequence || sequence != atomic_load(&s_active_sequence) ||
      !text || !text[0] || strlen(text) > 1024) return;
  cJSON *record = cJSON_CreateObject();
  if (!record) return;
  bool ok = cJSON_AddNumberToObject(record, "v", 1) &&
    cJSON_AddStringToObject(record, "boot", s_boot) &&
    cJSON_AddNumberToObject(record, "id", sequence) &&
    cJSON_AddStringToObject(record, "state", "reply") &&
    cJSON_AddNumberToObject(record, "code", 0) &&
    cJSON_AddBoolToObject(record, "truncated", truncated) &&
    cJSON_AddStringToObject(record, "text", text);
  char *json = ok ? cJSON_PrintUnformatted(record) : NULL;
  cJSON_Delete(record);
  if (json) { printf("HG_AGENT %s\n", json); cJSON_free(json); }
}

/* Strict UTF-8, no NUL/control characters or line separators. Empty disables
 * a binding; only the byte limit matters, not the number of code points. */
static bool dictionary_text_valid(const char *text, size_t length)
{
  if (length >= HV_GESTURE_MEANING_BYTES) return false;
  size_t i = 0;
  while (i < length) {
    unsigned char lead = (unsigned char)text[i++];
    uint32_t code; unsigned trailing; uint32_t minimum;
    if (lead < 0x80) { code = lead; trailing = 0; minimum = 0; }
    else if (lead >= 0xc2 && lead <= 0xdf) { code = lead & 0x1f; trailing = 1; minimum = 0x80; }
    else if (lead >= 0xe0 && lead <= 0xef) { code = lead & 0x0f; trailing = 2; minimum = 0x800; }
    else if (lead >= 0xf0 && lead <= 0xf4) { code = lead & 7; trailing = 3; minimum = 0x10000; }
    else return false;
    if (i + trailing > length) return false;
    for (unsigned j = 0; j < trailing; ++j) {
      unsigned char next = (unsigned char)text[i++];
      if ((next & 0xc0) != 0x80) return false;
      code = (code << 6) | (next & 0x3f);
    }
    if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff) ||
        code < 0x20 || (code >= 0x7f && code <= 0x9f) || code == 0x2028 || code == 0x2029)
      return false;
  }
  return true;
}

static bool dictionary_record_valid(const dictionary_storage_t *record)
{
  const char *palm_end = memchr(record->open_palm, 0, sizeof(record->open_palm));
  const char *v_end = memchr(record->v_sign, 0, sizeof(record->v_sign));
  return record->version == 1 && palm_end && v_end &&
    dictionary_text_valid(record->open_palm, (size_t)(palm_end - record->open_palm)) &&
    dictionary_text_valid(record->v_sign, (size_t)(v_end - record->v_sign));
}

static void dictionary_load(void)
{
  if (s_dictionary_loaded) return;
  s_dictionary_loaded = true;
  nvs_handle_t handle;
  esp_err_t result = nvs_open("hv_gesture", NVS_READONLY, &handle);
  if (result == ESP_ERR_NVS_NOT_FOUND) return;
  if (result != ESP_OK) { s_storage_error = result; return; }
  dictionary_storage_t stored = {0}; size_t length = sizeof(stored);
  result = nvs_get_blob(handle, "dictionary", &stored, &length);
  nvs_close(handle);
  if (result == ESP_ERR_NVS_NOT_FOUND) return;
  if (result != ESP_OK || length != sizeof(stored) || !dictionary_record_valid(&stored)) {
    s_storage_error = result == ESP_OK ? ESP_ERR_INVALID_ARG : result;
    return;
  }
  s_bindings = stored;
  s_persisted = true;
}

#if defined(CONFIG_QM_CLI_SUPPORT) && CONFIG_QM_CLI_SUPPORT
static portMUX_TYPE s_dictionary_guard = portMUX_INITIALIZER_UNLOCKED;
/* 360 hex bytes plus command, id, gesture and separators must fit together.
 * The prepared SDK sets this shared CLI buffer to 512; never silently truncate. */
_Static_assert(CONFIG_QM_CLI_INBUF_SIZE >= 400, "hg_dict requires a 400-byte CLI input buffer");
_Static_assert(CONFIG_QM_CLI_MAX_ARG_NUM >= 5, "hg_dict requires five CLI tokens");
static bool s_dictionary_cli_registered;

static void dictionary_report(unsigned id, const char *code)
{
  headvoice_scan_status_t scan;
  headvoice_scan_status(&scan);
  dictionary_storage_t current;
  bool persisted; esp_err_t storage_error;
  portENTER_CRITICAL(&s_dictionary_guard);
  current = s_bindings; persisted = s_persisted; storage_error = s_storage_error;
  portEXIT_CRITICAL(&s_dictionary_guard);
  /* JSON and its output live on the heap: the SDK CLI task has a 4 KiB stack. */
  cJSON *record = cJSON_CreateObject();
  cJSON *bindings = record ? cJSON_AddObjectToObject(record, "bindings") : NULL;
  bool ok = bindings && cJSON_AddStringToObject(bindings, "open_palm", current.open_palm) &&
    cJSON_AddStringToObject(bindings, "v_sign", current.v_sign) &&
    cJSON_AddNumberToObject(record, "v", 1) && cJSON_AddStringToObject(record, "boot", s_boot) &&
    cJSON_AddNumberToObject(record, "id", id) && cJSON_AddBoolToObject(record, "ok", !strcmp(code, "ok")) &&
    cJSON_AddStringToObject(record, "code", code) && cJSON_AddBoolToObject(record, "persisted", persisted) &&
    cJSON_AddNumberToObject(record, "storage_error", storage_error) &&
    cJSON_AddNumberToObject(record, "max_age_ms", HV_HAND_GATE_MAX_AGE_MS) &&
    cJSON_AddBoolToObject(record, "scan_supported", scan.supported) &&
    cJSON_AddBoolToObject(record, "scan_armed", scan.armed) &&
    cJSON_AddNumberToObject(record, "scan_generation", scan.generation) &&
    cJSON_AddStringToObject(record, "last_gesture", scan.last_gesture) &&
    cJSON_AddNumberToObject(record, "palm_count", scan.palm_count) &&
    cJSON_AddNumberToObject(record, "v_count", scan.v_count) &&
    cJSON_AddBoolToObject(record, "agent_busy", atomic_load(&s_busy));
  char *json = ok ? cJSON_PrintUnformatted(record) : NULL;
  cJSON_Delete(record);
  if (json) { printf("HGD %s\n", json); cJSON_free(json); }
  else printf("HGD {\"v\":1,\"boot\":\"%s\",\"id\":%u,\"ok\":false,\"code\":\"memory\"}\n", s_boot, id);
}

static unsigned dictionary_request_id(const char *text)
{
  if (!text || !text[0]) return 0;
  unsigned id = 0;
  for (; *text; ++text) {
    if (*text < '0' || *text > '9' || id > 99999999) return 0;
    id = id * 10 + (unsigned)(*text - '0');
  }
  return id;
}

static int dictionary_hex_digit(char value)
{
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

static bool dictionary_decode(const char *hex, char *text)
{
  if (!strcmp(hex, "-")) { text[0] = 0; return true; }
  size_t length = strlen(hex);
  if (!length || length % 2 || length / 2 >= HV_GESTURE_MEANING_BYTES) return false;
  for (size_t i = 0; i < length; i += 2) {
    int high = dictionary_hex_digit(hex[i]), low = dictionary_hex_digit(hex[i+1]);
    if (high < 0 || low < 0) return false;
    text[i/2] = (char)((high << 4) | low);
  }
  text[length/2] = 0;
  return dictionary_text_valid(text, length/2);
}

static void dictionary_command(char *buffer, int size, int argc, char **argv)
{
  (void)buffer; (void)size;
  unsigned id = argc > 1 ? dictionary_request_id(argv[1]) : 0;
  if (!id || argc < 3) { dictionary_report(id, "invalid"); return; }
  if (argc == 3 && !strcmp(argv[2], "get")) { dictionary_report(id, "ok"); return; }
  if (argc == 3 && !strcmp(argv[2], "arm")) {
    headvoice_scan_status_t scan;
    headvoice_scan_status(&scan);
    if (!scan.supported) { dictionary_report(id, "unsupported"); return; }
    /* Do not reserve the worker while arming: an already-confirmed event may
     * be between disarming and submit. The hand controller's dispatch guard
     * excludes that window without making the one real submit fail as busy. */
    if (atomic_load(&s_busy)) { dictionary_report(id, "busy"); return; }
    bool armed = headvoice_scan_arm();
    dictionary_report(id, armed ? "ok" : "busy");
    return;
  }
  char value[HV_GESTURE_MEANING_BYTES] = {0};
  if (argc != 5 || strcmp(argv[2], "set") ||
      (strcmp(argv[3], "open_palm") && strcmp(argv[3], "v_sign")) ||
      !dictionary_decode(argv[4], value)) { dictionary_report(id, "invalid"); return; }
  if (atomic_exchange(&s_busy, true)) { dictionary_report(id, "busy"); return; }
  /* Sharing the worker's single-transaction flag excludes queued/running
   * gestures and other mutations throughout durable storage and publication. */
  dictionary_storage_t next;
  portENTER_CRITICAL(&s_dictionary_guard); next = s_bindings; portEXIT_CRITICAL(&s_dictionary_guard);
  char *target = !strcmp(argv[3], "open_palm") ? next.open_palm : next.v_sign;
  memset(target, 0, HV_GESTURE_MEANING_BYTES); memcpy(target, value, strlen(value));
  nvs_handle_t handle;
  esp_err_t result = nvs_open("hv_gesture", NVS_READWRITE, &handle);
  if (result == ESP_OK) {
    result = nvs_set_blob(handle, "dictionary", &next, sizeof(next));
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
  }
  portENTER_CRITICAL(&s_dictionary_guard);
  if (result == ESP_OK) { s_bindings = next; s_persisted = true; }
  else s_persisted = false; /* A failed commit cannot promise reboot state. */
  s_storage_error = result;
  portEXIT_CRITICAL(&s_dictionary_guard);
  dictionary_report(id, result == ESP_OK ? "ok" : "storage_failed");
  atomic_store(&s_busy, false);
}

static esp_err_t dictionary_cli_init(void)
{
  if (s_dictionary_cli_registered) return ESP_OK;
  static const struct qm_cli_command command = {
    .name = "hg_dict", .help = "ID get|arm|set open_palm|v_sign UTF8_HEX|-", .function = dictionary_command
  };
  if (qm_cli_register_command(&command) != QM_EOK) return ESP_FAIL;
  s_dictionary_cli_registered = true;
  return ESP_OK;
}
#else
static esp_err_t dictionary_cli_init(void) { return ESP_OK; }
#endif

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
  const char *begin_detail = NULL;
  int ret = hv_gesture_agent_port_begin_detail(&begin_detail);
  if (ret != QM_EOK) {
    printf("HG_AGENT {\"v\":1,\"boot\":\"%s\",\"id\":%u,\"state\":\"unavailable\","
           "\"code\":%d,\"detail\":\"%s\"}\n", s_boot, event->sequence, ret, begin_detail);
    return;
  }
  atomic_store(&s_active_sequence, event->sequence);
  const char *phase = "connecting";
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
    phase = "sending";
    report(event->sequence, "sending", 0);
    ret = send_prompt(event, prompt);
  }
  if (ret == QM_EOK) {
    phase = "reply";
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
  if (ret != QM_EOK) report_failure(event->sequence, ret, phase);
  int cleanup = hv_gesture_agent_port_end();
  atomic_store(&s_active_sequence, 0);
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
  if (s_requests) return dictionary_cli_init();
  snprintf(s_boot, sizeof(s_boot), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
  dictionary_load();
  s_requests = xQueueCreate(1, sizeof(gesture_request_t));
  if (!s_requests) return ESP_ERR_NO_MEM;
  /* HTTPS/JSON run on an internal stack, never on the vision task or callbacks. */
  if (xTaskCreate(gesture_task, "hv_gesture_agent", 8192, NULL, 3, NULL) != pdPASS) {
    vQueueDelete(s_requests); s_requests = NULL; return ESP_ERR_NO_MEM;
  }
  report(0, "ready", 0);
  return dictionary_cli_init();
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
unsigned hv_gesture_agent_active_sequence(void) { return 0; }
void hv_gesture_agent_text(unsigned sequence, const char *text, bool truncated)
{ (void)sequence; (void)text; (void)truncated; }
#endif

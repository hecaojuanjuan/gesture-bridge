#include "hv_panel.h"
#include "hv_light.h"
#include "bsp_ws2812.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "ljyd_cloud.h"
#include "qm_cli.h"
#include "qm_config.h"
#include "qm_iot_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct {
  unsigned stage, people, inferenceMs, epoch;
  uint64_t captured;
  float tilt;
  bool tracking, eligible;
  uint8_t status[3];
} panel_input_t;
static panel_input_t s_input;
/* epoch() publishes under the producer guard, then this panel guard. Nothing
 * under the panel guard acquires a producer lock or performs I/O. */
static unsigned s_poseEpoch;
static portMUX_TYPE s_guard = portMUX_INITIALIZER_UNLOCKED;
static QueueHandle_t s_commands;

void hv_panel_status_light(uint8_t r, uint8_t g, uint8_t b)
{
  portENTER_CRITICAL(&s_guard);
  s_input.status[0] = r; s_input.status[1] = g; s_input.status[2] = b;
  portEXIT_CRITICAL(&s_guard);
}

void hv_panel_pose_epoch(unsigned epoch)
{
  portENTER_CRITICAL(&s_guard);
  s_poseEpoch = epoch;
  portEXIT_CRITICAL(&s_guard);
}

void hv_panel_pose(unsigned stage, uint64_t captured, unsigned people, float tilt,
                   bool tracking, bool eligible, unsigned inferenceMs, unsigned epoch)
{
  portENTER_CRITICAL(&s_guard);
  s_input.stage = stage; s_input.captured = captured; s_input.people = people;
  s_input.tilt = isfinite(tilt) ? tilt : 0;
  s_input.tracking = tracking && isfinite(tilt); s_input.inferenceMs = inferenceMs;
  s_input.eligible = eligible && s_input.tracking; s_input.epoch = epoch;
  portEXIT_CRITICAL(&s_guard);
}

static int submit(const char *text)
{
  hv_light_command_t command;
  if (!hv_light_parse(text, &command)) return -1;
  if (!s_commands || xQueueSend(s_commands, &command, 0) != pdTRUE) return -3;
  return 0;
}

bool hv_panel_on_property(qm_spec_property_t *property)
{
  if (!property || property->siid != HV_PANEL_SIID || property->piid != 1) return false;
  /* The upstream copying unpacker ignores its caller's capacity; borrow and
   * explicitly bound the bytes instead. Never trust a NUL from MQTT. */
  char *bytes = NULL, text[97]; int length = 0;
  if (property->value.property_format != QM_SPEC_PROPERTY_FORMAT_STRING ||
      qm_spec_property_unpack_string_direct(property, &bytes, &length) != QM_EOK ||
      !bytes || length < 1 || length >= (int)sizeof(text)) return true;
  memcpy(text, bytes, (size_t)length); text[length] = '\0';
  if (strlen(text) == (size_t)length) (void)submit(text);
  return true;
}

static void cloud_report(char *text)
{
  void *iot = ljyd_cloud_get_handle();
  if (!iot) return;
  qm_spec_property_operation_t *op = qm_spec_property_operation_creat();
  if (!op) return;
  qm_spec_property_t *prop = qm_spec_property_creat();
  if (!prop) { qm_spec_property_operation_delete(op); return; }
  qm_spec_property_pack_xiid(prop, HV_PANEL_SIID, 2);
  qm_spec_property_pack_string(prop, text, (int)strlen(text));
  /* Upstream pack_string discards pack_bytes' allocation error. */
  if (prop->value.len != (int)strlen(text)) {
    qm_spec_property_delete(prop); qm_spec_property_operation_delete(op); return;
  }
  qm_spec_property_add(op, prop);
  if (qm_iot_report(iot, op) != QM_EOK) qm_spec_property_operation_delete(op);
}

static void panel_task(void *argument)
{
  (void)argument;
  hv_light_t light; hv_light_init(&light);
  uint8_t previous[3] = {255,255,255};
  uint32_t boot = esp_random(), id = 0;
  uint64_t lastReport = 0;
  int result = bsp_ws2812_init();
  bool ready = result == QM_EOK;
  for (;;) {
    uint64_t now = (uint64_t)(esp_timer_get_time()/1000);
    panel_input_t input;
    portENTER_CRITICAL(&s_guard); input = s_input; portEXIT_CRITICAL(&s_guard);
    memcpy(light.status, input.status, 3);
    hv_light_command_t command;
    bool received = xQueueReceive(s_commands, &command, 0) == pdTRUE;
    if (received) {
      hv_light_apply(&light, &command, now);
      id = command.id;
    }
    uint8_t output[3]; hv_light_output(&light, now, output);
    if (ready && (memcmp(output, previous, 3) || received)) {
      result = bsp_ws2812_fill(output[0], output[1], output[2]);
      if (result == QM_EOK) memcpy(previous, output, 3);
    }
    if (received || now - lastReport >= 5000) {
      uint64_t age = input.captured && now >= input.captured ? now-input.captured : UINT32_MAX;
      unsigned poseEpoch;
      portENTER_CRITICAL(&s_guard); poseEpoch = s_poseEpoch; portEXIT_CRITICAL(&s_guard);
      char text[640];
      snprintf(text, sizeof(text),
        "{\"v\":1,\"boot\":%u,\"reset_reason\":%u,\"id\":%u,\"ok\":%s,\"uptime_ms\":%llu,"
        "\"mode\":%u,\"brightness\":%u,\"rgb\":[%u,%u,%u],\"output\":[%u,%u,%u],"
        "\"test_ms\":%u,\"stage\":%u,\"pose\":{\"age_ms\":%llu,\"people\":%u,"
        "\"tilt\":%.2f,\"tracking\":%s,\"valid\":%s,\"infer_ms\":%u}}",
        (unsigned)boot, (unsigned)esp_reset_reason(), (unsigned)id,
        ready && result == QM_EOK ? "true" : "false",
        (unsigned long long)now, light.mode, light.brightness,
        light.rgb[0], light.rgb[1], light.rgb[2], previous[0], previous[1], previous[2],
        (unsigned)(now < light.testUntil ? light.testUntil-now : 0), input.stage,
        (unsigned long long)age, input.people, (double)input.tilt,
        input.tracking ? "true" : "false",
        input.eligible && input.epoch == poseEpoch && age <= 400 ? "true" : "false",
        input.inferenceMs);
      printf("HP %s\n", text);
      cloud_report(text);
      lastReport = now;
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

#if defined(CONFIG_QM_CLI_SUPPORT) && CONFIG_QM_CLI_SUPPORT
static void panel_command(char *buffer, int length, int argc, char **argv)
{
  (void)buffer; (void)length;
  char text[97] = {0}; size_t used = 0;
  for (int i = 1; i < argc; ++i) {
    int n = snprintf(text+used, sizeof(text)-used, "%s%s", i == 1 ? "" : " ", argv[i]);
    if (n < 0 || (size_t)n >= sizeof(text)-used) return;
    used += (size_t)n;
  }
  int ret = submit(text);
  if (ret) qm_cli_printf("HP command rejected=%d; hv_panel ID get|test|set MODE BRIGHTNESS R G B\r\n", ret);
}
static const struct qm_cli_command panel_cli = {
  .name = "hv_panel", .help = "ID get|test|set MODE BRIGHTNESS R G B", .function = panel_command
};
#endif

int hv_panel_init(void)
{
  if (s_commands) return QM_EOK;
  s_commands = xQueueCreate(4, sizeof(hv_light_command_t));
  if (!s_commands) return -QM_ENOMEM;
  if (xTaskCreate(panel_task, "hv_panel", 4096, NULL, 2, NULL) != pdPASS) {
    vQueueDelete(s_commands); s_commands = NULL; return -QM_ENOMEM;
  }
#if defined(CONFIG_QM_CLI_SUPPORT) && CONFIG_QM_CLI_SUPPORT
  qm_cli_register_command(&panel_cli);
#endif
  return QM_EOK;
}

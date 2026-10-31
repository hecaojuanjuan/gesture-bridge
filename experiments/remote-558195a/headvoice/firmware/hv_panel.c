#include "hv_panel.h"

#include <stdlib.h>
#include <string.h>

#include "bsp_ws2812.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "ljyd_provision.h"
#include "qm_cli.h"

static SemaphoreHandle_t s_lock;
static const char * s_state = "starting";
static bool s_cloud, s_manual, s_expression, s_ready, s_renderOk;
static unsigned s_brightness = 20;
static uint8_t s_color[3], s_expressionColor[3], s_output[3];

void hv_panel_network(const char * state)
{
  if (!s_lock) return;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  if (strcmp(state, "online") == 0)
    s_cloud = true;
  else
    s_cloud = false;
  s_state = state;
  xSemaphoreGive(s_lock);
}

void hv_panel_expression(uint8_t r, uint8_t g, uint8_t b, bool active)
{
  if (!s_lock) return;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  s_expressionColor[0] = r;
  s_expressionColor[1] = g;
  s_expressionColor[2] = b;
  s_expression = active;
  xSemaphoreGive(s_lock);
}

static bool number(const char * text, unsigned * value)
{
  if (!text || !*text || strspn(text, "0123456789") != strlen(text)) return false;
  char * end;
  unsigned long parsed = strtoul(text, &end, 10);
  if (*end || strlen(text) > 6 || parsed > 999999) return false;
  *value = (unsigned)parsed;
  return true;
}

static void command(char * buffer, int length, int argc, char ** argv)
{
  (void)buffer;
  (void)length;
  unsigned id = 0, values[3] = {0};
  if (argc < 3 || !number(argv[1], &id)) return;
  xSemaphoreTake(s_lock, portMAX_DELAY);
  bool ok = true, restart = false;
  const char * action = argv[2];
  if (argc == 3 && strcmp(action, "status") == 0) {
    /* Read-only request. */
  } else if (argc == 3 && strcmp(action, "auto") == 0) {
    s_manual = false;
  } else if (argc == 3 && strcmp(action, "off") == 0) {
    memset(s_color, 0, sizeof(s_color));
    s_manual = true;
  } else if (argc == 3 && strcmp(action, "restart") == 0) {
    restart = true;
  } else if (
    argc == 4 && strcmp(action, "brightness") == 0 && number(argv[3], &values[0]) &&
    values[0] <= 100) {
    s_brightness = values[0];
  } else if (
    argc == 6 && strcmp(action, "color") == 0 && number(argv[3], &values[0]) && values[0] <= 255 &&
    number(argv[4], &values[1]) && values[1] <= 255 && number(argv[5], &values[2]) &&
    values[2] <= 255) {
    for (int i = 0; i < 3; ++i) s_color[i] = values[i];
    s_manual = true;
  } else {
    ok = false;
  }
  qm_cli_printf(
    "PANEL {\"id\":%u,\"ok\":%s,\"state\":\"%s\",\"mode\":\"%s\","
    "\"brightness\":%u,\"ready\":%s,\"render_ok\":%s,\"rgb\":[%u,%u,%u],"
    "\"uptime\":%u}\r\n",
    id, ok ? "true" : "false", s_state, s_manual ? "manual" : "auto", s_brightness,
    s_ready ? "true" : "false", s_renderOk ? "true" : "false", s_output[0], s_output[1],
    s_output[2], (unsigned)(esp_timer_get_time() / 1000000));
  xSemaphoreGive(s_lock);
  if (restart) {
    vTaskDelay(pdMS_TO_TICKS(100));
    ljyd_provision_clear_and_reboot();
  }
}

static void light_task(void * argument)
{
  (void)argument;
  bool ready = bsp_ws2812_init() == QM_EOK;
  unsigned tick = 0;
  for (;;) {
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_ready = ready;
    uint8_t color[3] = {0};
    if (s_manual)
      memcpy(color, s_color, sizeof(color));
    else if (s_expression)
      memcpy(color, s_expressionColor, sizeof(color));
    else if (s_cloud)
      color[1] = 255;
    else if (strcmp(s_state, "provisioning") == 0)
      color[2] = (tick % 10 < 5) ? 255 : 0;
    else if (strcmp(s_state, "connecting") == 0 || strcmp(s_state, "cloud_connecting") == 0)
      color[0] = color[1] = (tick % 4 < 2) ? 255 : 0;
    else if (strcmp(s_state, "disconnected") == 0 || strcmp(s_state, "error") == 0)
      color[0] = (tick % 10 < 5) ? 255 : 0;
    else
      color[0] = color[1] = color[2] = 64;
    /* Limit maximum channel output to the upstream example's 48/255. */
    for (int i = 0; i < 3; ++i) s_output[i] = color[i] * s_brightness * 48 / 255 / 100;
    s_renderOk = ready && bsp_ws2812_fill(s_output[0], s_output[1], s_output[2]) == QM_EOK;
    xSemaphoreGive(s_lock);
    ++tick;
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

void hv_panel_init(void)
{
  if (s_lock) return;
  s_lock = xSemaphoreCreateMutex();
  if (!s_lock) return;
  if (xTaskCreate(light_task, "hv_light", 3072, NULL, 2, NULL) != pdPASS) {
    hv_panel_network("error");
  }
  static const struct qm_cli_command cli = {
    .name = "hv_panel",
    .help = "<id> status|auto|off|color <r> <g> <b>|brightness <0..100>|restart",
    .function = command};
  qm_cli_register_command(&cli);
}

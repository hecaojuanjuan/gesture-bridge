#include "hv_camera_preview.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "hv_settings.h"
#include "qm_cli.h"
#include "yolo11_pose.h"

#define RAW_BYTES (240 * 320 * 2)
#define PREVIEW_WIDTH 120
#define PREVIEW_HEIGHT 160
#define PREVIEW_BYTES (PREVIEW_WIDTH * PREVIEW_HEIGHT * 2)

typedef enum {
  PREVIEW_IDLE,
  PREVIEW_PENDING,
  PREVIEW_COPYING,
  PREVIEW_READY,
  PREVIEW_EXPORTING
} PreviewState;

static portMUX_TYPE s_guard = portMUX_INITIALIZER_UNLOCKED;
static PreviewState s_state;
static uint8_t * s_raw;
static uint8_t * s_rgb;
static uint64_t s_requestedMs, s_capturedMs;

void hv_camera_preview_offer(const uint8_t * data, size_t length, uint64_t capturedMs)
{
  if (!data || length != RAW_BYTES) return;
  portENTER_CRITICAL(&s_guard);
  bool requested = s_state == PREVIEW_PENDING;
  if (requested) s_state = PREVIEW_COPYING;
  portEXIT_CRITICAL(&s_guard);
  if (!requested) return;
  /* The camera only copies a single borrowed frame; encoding runs elsewhere. */
  memcpy(s_raw, data, RAW_BYTES);
  portENTER_CRITICAL(&s_guard);
  s_capturedMs = capturedMs;
  s_state = PREVIEW_READY;
  portEXIT_CRITICAL(&s_guard);
}

static void preview_task(void * argument)
{
  (void)argument;
  static const char HEX[] = "0123456789abcdef";
  for (;;) {
    uint64_t now = esp_timer_get_time() / 1000;
    portENTER_CRITICAL(&s_guard);
    bool ready = s_state == PREVIEW_READY;
    bool expired = s_state == PREVIEW_PENDING && now - s_requestedMs > 10000;
    if (ready) s_state = PREVIEW_EXPORTING;
    if (expired) s_state = PREVIEW_IDLE;
    uint64_t capturedMs = s_capturedMs;
    portEXIT_CRITICAL(&s_guard);
    if (expired) printf("HVCAM ERROR no_complete_frame\n");
    if (ready) {
      esp_err_t ret = yolo11_pose_uyvy_to_rgb565(
        s_raw, RAW_BYTES, 240, 320, s_rgb, PREVIEW_WIDTH, PREVIEW_HEIGHT);
      if (ret == ESP_OK) {
        printf(
          "HVCAM BEGIN %u %u %u %u %u\n", PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_BYTES,
          (unsigned)capturedMs, HV_ROTATE_CW90);
        uint32_t checksum = 2166136261u;
        for (unsigned offset = 0; offset < PREVIEW_BYTES; offset += 128) {
          char hex[257];
          unsigned count = PREVIEW_BYTES - offset;
          if (count > 128) count = 128;
          for (unsigned i = 0; i < count; ++i) {
            unsigned value = s_rgb[offset + i];
            hex[i * 2] = HEX[value >> 4];
            hex[i * 2 + 1] = HEX[value & 15];
            checksum = (checksum ^ value) * 16777619u;
          }
          hex[count * 2] = '\0';
          printf("HVCAM DATA %u %s\n", offset, hex);
          /* Keep export work below camera, inference, and audio priorities. */
          vTaskDelay(pdMS_TO_TICKS(1));
        }
        printf("HVCAM END %08x\n", (unsigned)checksum);
        fflush(stdout);
      } else {
        printf("HVCAM ERROR conversion_%d\n", (int)ret);
      }
      portENTER_CRITICAL(&s_guard);
      s_state = PREVIEW_IDLE;
      portEXIT_CRITICAL(&s_guard);
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

static void preview_command(char * buffer, int length, int argc, char ** argv)
{
  (void)buffer;
  (void)length;
  if (argc != 2 || strcmp(argv[1], "snapshot") != 0) {
    qm_cli_printf("hv_camera snapshot: export one local camera preview\r\n");
    return;
  }
  portENTER_CRITICAL(&s_guard);
  bool busy = s_state != PREVIEW_IDLE;
  if (!busy) {
    s_requestedMs = esp_timer_get_time() / 1000;
    s_state = PREVIEW_PENDING;
  }
  portEXIT_CRITICAL(&s_guard);
  qm_cli_printf(busy ? "HVCAM BUSY\r\n" : "HVCAM WAIT\r\n");
}

esp_err_t hv_camera_preview_init(void)
{
  s_raw = heap_caps_malloc(RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  s_rgb = heap_caps_malloc(PREVIEW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!s_raw || !s_rgb) {
    heap_caps_free(s_raw);
    heap_caps_free(s_rgb);
    return ESP_ERR_NO_MEM;
  }
  if (
    xTaskCreateWithCaps(
      preview_task, "hv_preview", 4096, NULL, 2, NULL, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) !=
    pdPASS) {
    heap_caps_free(s_raw);
    heap_caps_free(s_rgb);
    return ESP_ERR_NO_MEM;
  }
  static const struct qm_cli_command command = {
    .name = "hv_camera",
    .help = "snapshot: export one RGB565 camera preview over serial",
    .function = preview_command,
  };
  int ret = qm_cli_register_command(&command);
  qm_cli_printf("HVCAM ready ret=%d\r\n", ret);
  return ret == 0 ? ESP_OK : ESP_FAIL;
}

#include "hv_camera_preview.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_jpeg_enc.h"
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
#define FULL_RGB_BYTES (240 * 320 * 3)
#define JPEG_MAX_BYTES (RAW_BYTES + 4096)
#define JPEG_QUALITY 75

typedef enum {
  PREVIEW_IDLE,
  PREVIEW_PREPARING,
  PREVIEW_PENDING,
  PREVIEW_COPYING,
  PREVIEW_READY,
  PREVIEW_EXPORTING
} PreviewState;

typedef enum {
  PREVIEW_CAMERA, PREVIEW_MODEL_INPUT, PREVIEW_JPEG, PREVIEW_MODEL_JPEG
} PreviewSource;

static portMUX_TYPE s_guard = portMUX_INITIALIZER_UNLOCKED;
static PreviewState s_state;
static PreviewSource s_source;
static uint8_t * s_raw;
static uint8_t * s_rgb;
/* Allocated only for an explicit inputjpeg request, never borrowed from inference. */
static uint8_t * s_jpegInput;
static uint64_t s_requestedMs, s_capturedMs;
static unsigned s_width, s_height, s_rotation;

void hv_camera_preview_offer(const uint8_t * data, size_t length, uint64_t capturedMs)
{
  if (!data || length != RAW_BYTES) return;
  portENTER_CRITICAL(&s_guard);
  bool requested = s_state == PREVIEW_PENDING &&
                   (s_source == PREVIEW_CAMERA || s_source == PREVIEW_JPEG);
  if (requested) s_state = PREVIEW_COPYING;
  portEXIT_CRITICAL(&s_guard);
  if (!requested) return;
  /* The camera only copies a single borrowed frame; encoding runs elsewhere. */
  memcpy(s_raw, data, RAW_BYTES);
  portENTER_CRITICAL(&s_guard);
  s_capturedMs = capturedMs;
  s_width = PREVIEW_WIDTH;
  s_height = PREVIEW_HEIGHT;
  s_rotation = HV_ROTATE_CW90;
  s_state = PREVIEW_READY;
  portEXIT_CRITICAL(&s_guard);
}

void hv_camera_preview_offer_model_input(
  const uint8_t * rgb, uint16_t width, uint16_t height, uint64_t capturedMs)
{
  /* These are the two full-resolution shapes emitted by our RGB converter. */
  if (HV_STAGE < 2 || !rgb ||
      !((width == 320 && height == 240) || (width == 240 && height == 320))) return;
  portENTER_CRITICAL(&s_guard);
  bool fullJpeg = s_source == PREVIEW_MODEL_JPEG;
  bool requested = s_state == PREVIEW_PENDING &&
                   (s_source == PREVIEW_MODEL_INPUT || fullJpeg);
  if (requested) s_state = PREVIEW_COPYING;
  portEXIT_CRITICAL(&s_guard);
  if (!requested) return;

  if (fullJpeg) {
    memcpy(s_jpegInput, rgb, FULL_RGB_BYTES);
    portENTER_CRITICAL(&s_guard);
    s_capturedMs = capturedMs;
    s_width = width; s_height = height;
    s_rotation = 0;
    s_state = PREVIEW_READY;
    portEXIT_CRITICAL(&s_guard);
    return;
  }

  /* Sample the actual, already-oriented RGB888 input in place. There is no
   * second full RGB frame and no second UYVY conversion or deferred borrow. */
  unsigned outWidth = width / 2, outHeight = height / 2;
  for (unsigned y = 0; y < outHeight; ++y) {
    for (unsigned x = 0; x < outWidth; ++x) {
      const uint8_t * pixel = rgb + ((size_t)(y * 2) * width + x * 2) * 3;
      uint16_t packed = ((uint16_t)(pixel[0] >> 3) << 11) |
                        ((uint16_t)(pixel[1] >> 2) << 5) | (pixel[2] >> 3);
      size_t offset = ((size_t)y * outWidth + x) * 2;
      s_rgb[offset] = packed & 0xff;
      s_rgb[offset + 1] = packed >> 8;
    }
  }
  portENTER_CRITICAL(&s_guard);
  s_capturedMs = capturedMs;
  s_width = outWidth;
  s_height = outHeight;
  s_rotation = 0; /* The RGB input already has the inference orientation. */
  s_state = PREVIEW_READY;
  portEXIT_CRITICAL(&s_guard);
}

static bool jpeg_source(PreviewSource source)
{
  return source == PREVIEW_JPEG || source == PREVIEW_MODEL_JPEG;
}

/* 192 input bytes produce at most 256 base64 characters, keeping every line
 * bounded even when unrelated device diagnostics share the console. */
static void base64_chunk(const uint8_t *data, unsigned length, char encoded[257])
{
  static const char ALPHABET[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  unsigned out = 0;
  for (unsigned i = 0; i < length; i += 3) {
    unsigned left = length - i;
    uint32_t value = (uint32_t)data[i] << 16;
    if (left > 1) value |= (uint32_t)data[i + 1] << 8;
    if (left > 2) value |= data[i + 2];
    encoded[out++] = ALPHABET[(value >> 18) & 63];
    encoded[out++] = ALPHABET[(value >> 12) & 63];
    encoded[out++] = left > 1 ? ALPHABET[(value >> 6) & 63] : '=';
    encoded[out++] = left > 2 ? ALPHABET[value & 63] : '=';
  }
  encoded[out] = 0;
}

static void export_jpeg(PreviewSource source, unsigned width, unsigned height,
                        uint64_t capturedMs)
{
  uint8_t *output = heap_caps_malloc(JPEG_MAX_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!output) {
    printf("HVJPEG ERROR no_output_memory\n");
    return;
  }
  jpeg_enc_config_t config = DEFAULT_JPEG_ENC_CONFIG();
  config.quality = JPEG_QUALITY;
  config.subsampling = JPEG_SUBSAMPLE_420;
  config.task_enable = false;
  const uint8_t *input;
  int inputBytes;
  if (source == PREVIEW_MODEL_JPEG) {
    config.width = width; config.height = height;
    config.src_type = JPEG_PIXEL_FORMAT_RGB888;
    config.rotate = JPEG_ROTATE_0D;
    input = s_jpegInput; inputBytes = FULL_RGB_BYTES;
  } else {
    /* BF3901 supplies U Y0 V Y1. Espressif's documented encoder rotation
     * supports Y0 U Y1 V + 4:2:0 and dimensions divisible by 16. This private
     * frame is no longer needed in UYVY form; never alter the camera buffer. */
    for (unsigned i = 0; i < RAW_BYTES; i += 4) {
      uint8_t u = s_raw[i], v = s_raw[i + 2];
      s_raw[i] = s_raw[i + 1]; s_raw[i + 1] = u;
      s_raw[i + 2] = s_raw[i + 3]; s_raw[i + 3] = v;
    }
    config.width = 240; config.height = 320;
    config.src_type = JPEG_PIXEL_FORMAT_YCbYCr;
    config.rotate = HV_ROTATE_CW90 ? JPEG_ROTATE_90D : JPEG_ROTATE_0D;
    width = HV_ROTATE_CW90 ? 320 : 240;
    height = HV_ROTATE_CW90 ? 240 : 320;
    input = s_raw; inputBytes = RAW_BYTES;
  }
  jpeg_enc_handle_t encoder = NULL;
  jpeg_error_t ret = jpeg_enc_open(&config, &encoder);
  int length = 0;
  if (ret == JPEG_ERR_OK)
    ret = jpeg_enc_process(encoder, input, inputBytes, output, JPEG_MAX_BYTES, &length);
  if (encoder) jpeg_enc_close(encoder);
  if (ret != JPEG_ERR_OK || length <= 0 || length > JPEG_MAX_BYTES) {
    printf("HVJPEG ERROR encode_%d\n", (int)ret);
  } else {
    printf("HVJPEG SOURCE %s\n", source == PREVIEW_MODEL_JPEG ? "model" : "camera");
    /* Pixels are already oriented; rotation is always zero. */
    printf("HVJPEG BEGIN 1 %u %u %u %llu 0 %u\n", width, height,
           (unsigned)length, (unsigned long long)capturedMs, JPEG_QUALITY);
    uint32_t checksum = 2166136261u;
    for (unsigned offset = 0; offset < (unsigned)length; offset += 192) {
      unsigned count = (unsigned)length - offset;
      if (count > 192) count = 192;
      char encoded[257];
      base64_chunk(output + offset, count, encoded);
      for (unsigned i = 0; i < count; ++i)
        checksum = (checksum ^ output[offset + i]) * 16777619u;
      printf("HVJPEG DATA %u %s\n", offset, encoded);
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    printf("HVJPEG END %08x\n", (unsigned)checksum);
    fflush(stdout);
  }
  heap_caps_free(output);
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
    uint8_t *expiredInput = NULL;
    if (expired) {
      expiredInput = s_jpegInput; s_jpegInput = NULL;
      s_state = PREVIEW_IDLE;
    }
    uint64_t capturedMs = s_capturedMs;
    PreviewSource source = s_source;
    unsigned width = s_width, height = s_height, rotation = s_rotation;
    portEXIT_CRITICAL(&s_guard);
    if (expired) {
      heap_caps_free(expiredInput);
      printf("%s ERROR %s\n", jpeg_source(source) ? "HVJPEG" : "HVCAM",
             source == PREVIEW_MODEL_INPUT || source == PREVIEW_MODEL_JPEG
               ? "no_model_input" : "no_complete_frame");
    }
    if (ready) {
      if (jpeg_source(source)) {
        export_jpeg(source, width, height, capturedMs);
        heap_caps_free(s_jpegInput); s_jpegInput = NULL;
        portENTER_CRITICAL(&s_guard);
        s_state = PREVIEW_IDLE;
        portEXIT_CRITICAL(&s_guard);
        vTaskDelay(pdMS_TO_TICKS(50));
        continue;
      }
      esp_err_t ret = ESP_OK;
      if (source == PREVIEW_CAMERA) {
        ret = yolo11_pose_uyvy_to_rgb565(
          s_raw, RAW_BYTES, 240, 320, s_rgb, PREVIEW_WIDTH, PREVIEW_HEIGHT);
      }
      if (ret == ESP_OK) {
        if (source == PREVIEW_MODEL_INPUT) printf("HVCAM SOURCE model\n");
        printf(
          "HVCAM BEGIN %u %u %u %u %u\n", width, height, PREVIEW_BYTES,
          (unsigned)capturedMs, rotation);
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
  bool modelInput = argc == 2 && strcmp(argv[1], "input") == 0;
  bool jpeg = argc == 2 && strcmp(argv[1], "jpeg") == 0;
  bool modelJpeg = argc == 2 && strcmp(argv[1], "inputjpeg") == 0;
  const char *prefix = jpeg || modelJpeg ? "HVJPEG" : "HVCAM";
  if (argc != 2 || (!modelInput && !jpeg && !modelJpeg && strcmp(argv[1], "snapshot") != 0)) {
    qm_cli_printf("hv_camera snapshot|input|jpeg|inputjpeg: export one local camera frame\r\n");
    return;
  }
  if ((modelInput || modelJpeg) && HV_STAGE < 2) {
    qm_cli_printf("%s ERROR model_input_requires_stage2\r\n", prefix);
    return;
  }
  portENTER_CRITICAL(&s_guard);
  bool busy = s_state != PREVIEW_IDLE;
  if (!busy) {
    s_source = modelJpeg ? PREVIEW_MODEL_JPEG : jpeg ? PREVIEW_JPEG :
               modelInput ? PREVIEW_MODEL_INPUT : PREVIEW_CAMERA;
    s_state = PREVIEW_PREPARING;
  }
  portEXIT_CRITICAL(&s_guard);
  if (busy) {
    qm_cli_printf("%s BUSY\r\n", prefix);
    return;
  }
  if (modelJpeg) {
    s_jpegInput = heap_caps_aligned_alloc(16, FULL_RGB_BYTES,
                                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_jpegInput) {
      portENTER_CRITICAL(&s_guard);
      s_state = PREVIEW_IDLE;
      portEXIT_CRITICAL(&s_guard);
      qm_cli_printf("HVJPEG ERROR no_input_memory\r\n");
      return;
    }
  }
  portENTER_CRITICAL(&s_guard);
  s_requestedMs = esp_timer_get_time() / 1000;
  s_state = PREVIEW_PENDING;
  portEXIT_CRITICAL(&s_guard);
  qm_cli_printf("%s WAIT\r\n", prefix);
}

esp_err_t hv_camera_preview_init(void)
{
  s_raw = heap_caps_aligned_alloc(16, RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
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
    .help = "snapshot|input|jpeg|inputjpeg: export one preview or full JPEG over serial",
    .function = preview_command,
  };
  int ret = qm_cli_register_command(&command);
  qm_cli_printf("HVCAM ready ret=%d\r\n", ret);
  return ret == 0 ? ESP_OK : ESP_FAIL;
}

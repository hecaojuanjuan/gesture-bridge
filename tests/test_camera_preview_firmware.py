"""Exercise the production preview state machine and RGB sampling on the host.

SDK calls are stubbed; these checks do not establish device timing or camera quality.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUBS = r"""
#ifndef PREVIEW_TEST_STUBS_H
#define PREVIEW_TEST_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
typedef int portMUX_TYPE;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM -2
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(guard) ((void)(guard))
#define portEXIT_CRITICAL(guard) ((void)(guard))
#define pdMS_TO_TICKS(ms) (ms)
#define pdPASS 1
#define xTaskCreateWithCaps(...) pdPASS
static bool fail_allocation;
static void *test_malloc(size_t size) { return fail_allocation ? NULL : malloc(size); }
#define heap_caps_malloc(size, caps) test_malloc(size)
#define heap_caps_aligned_alloc(alignment, size, caps) test_malloc(size)
#define heap_caps_free(ptr) free(ptr)
static uint64_t clock_ms;
static int conversion_calls;
typedef int jpeg_error_t;
typedef void *jpeg_enc_handle_t;
typedef struct {
  unsigned width, height;
  int src_type, subsampling, quality, rotate;
  bool task_enable;
} jpeg_enc_config_t;
#define JPEG_ERR_OK 0
#define JPEG_PIXEL_FORMAT_RGB888 1
#define JPEG_PIXEL_FORMAT_YCbYCr 2
#define JPEG_SUBSAMPLE_420 3
#define JPEG_ROTATE_0D 0
#define JPEG_ROTATE_90D 1
#define DEFAULT_JPEG_ENC_CONFIG() {0}
static jpeg_enc_config_t encoded_config;
static int jpeg_opens, jpeg_processes, jpeg_closes, jpeg_open_error, jpeg_process_error;
static jpeg_error_t jpeg_enc_open(jpeg_enc_config_t *config, jpeg_enc_handle_t *handle) {
  ++jpeg_opens;
  if (jpeg_open_error) return jpeg_open_error;
  encoded_config = *config; *handle = &encoded_config; return 0;
}
static jpeg_error_t jpeg_enc_process(jpeg_enc_handle_t handle, const uint8_t *input,
                                    int in_size, uint8_t *output, int capacity, int *length) {
  assert(handle == &encoded_config && input && output && capacity >= 197);
  assert(encoded_config.quality == 75 && encoded_config.subsampling == JPEG_SUBSAMPLE_420);
  assert(!encoded_config.task_enable);
  if (encoded_config.src_type == JPEG_PIXEL_FORMAT_YCbYCr) {
    assert(in_size == 153600 && encoded_config.width == 240 && encoded_config.height == 320);
    assert(encoded_config.rotate == HV_ROTATE_CW90);
    assert(input[0] == 0x22 && input[1] == 0x11 && input[2] == 0x44 && input[3] == 0x33);
  } else {
    assert(in_size == 230400 && encoded_config.src_type == JPEG_PIXEL_FORMAT_RGB888);
    assert(encoded_config.rotate == 0);
    assert(input[0] == 0x19 && input[1] == 0x29 && input[2] == 0x39);
  }
  ++jpeg_processes;
  if (jpeg_process_error) return jpeg_process_error;
  for (int i = 0; i < 197; ++i) output[i] = (uint8_t)i;
  *length = 197; return 0;
}
static jpeg_error_t jpeg_enc_close(jpeg_enc_handle_t handle) {
  assert(handle == &encoded_config); ++jpeg_closes; return 0;
}
static jmp_buf tick;
static char output[100000];
static size_t output_length;
static int capture_printf(const char *fmt, ...) {
  va_list args; va_start(args, fmt);
  int length = vsnprintf(output + output_length, sizeof(output) - output_length, fmt, args);
  va_end(args);
  assert(length >= 0 && (size_t)length < sizeof(output) - output_length);
  output_length += (size_t)length;
  return length;
}
#define printf capture_printf
#define qm_cli_printf capture_printf
static int64_t esp_timer_get_time(void) { return (int64_t)clock_ms * 1000; }
static void vTaskDelay(unsigned ms) { if (ms == 50) longjmp(tick, 1); }
struct qm_cli_command {
  const char *name, *help;
  void (*function)(char *, int, int, char **);
};
static int qm_cli_register_command(const struct qm_cli_command *cmd) {
  assert(cmd->function); return 0;
}
static esp_err_t yolo11_pose_uyvy_to_rgb565(
    const uint8_t *raw, size_t size, unsigned width, unsigned height,
    uint8_t *rgb, unsigned out_width, unsigned out_height) {
  assert(raw && size == 153600 && width == 240 && height == 320);
  assert(out_width == 120 && out_height == 160);
  ++conversion_calls;
  memset(rgb, 0x5a, out_width * out_height * 2);
  return ESP_OK;
}
#endif
"""

HARNESS = r"""
#include "hv_camera_preview.c"
static uint8_t raw[RAW_BYTES], guarded_rgb[PREVIEW_BYTES + 2], input[240 * 320 * 3];
static void clear_output(void) { output[0] = 0; output_length = 0; }
static void command(const char *verb) {
  char *argv[] = {"hv_camera", (char *)verb};
  preview_command(NULL, 0, 2, argv);
}
static void cycle(void) { if (setjmp(tick) == 0) preview_task(NULL); }
static void raw_jpeg_case(void) {
  clear_output(); command("jpeg");
  assert(s_state == PREVIEW_PENDING && s_source == PREVIEW_JPEG);
  assert(strstr(output, "HVJPEG WAIT"));
  command("snapshot");
  assert(strstr(output, "HVCAM BUSY") && s_source == PREVIEW_JPEG);
  raw[0] = 0x11; raw[1] = 0x22; raw[2] = 0x33; raw[3] = 0x44;
  hv_camera_preview_offer(raw, sizeof(raw), 91234);
  assert(s_state == PREVIEW_READY);
  cycle();
  assert(s_state == PREVIEW_IDLE && s_jpegInput == NULL);
  char header[100];
  snprintf(header, sizeof(header), "HVJPEG BEGIN 1 %u %u 197 91234 0 75\n",
           HV_ROTATE_CW90 ? 320 : 240, HV_ROTATE_CW90 ? 240 : 320);
  assert(strstr(output, "HVJPEG SOURCE camera\n") && strstr(output, header));
  assert(strstr(output, "HVJPEG DATA 0 AAECAwQF") && strstr(output, "HVJPEG DATA 192 wMHCw8Q=\n"));
  assert(!strstr(output, "HVCAM BEGIN"));
}
#if HV_STAGE >= 2
static uint32_t fnv(void) {
  uint32_t value = 2166136261u;
  for (unsigned i = 0; i < PREVIEW_BYTES; ++i) value = (value ^ s_rgb[i]) * 16777619u;
  return value;
}
static void model_case(unsigned width, unsigned height) {
  clear_output();
  command("input");
  assert(s_state == PREVIEW_PENDING && s_source == PREVIEW_MODEL_INPUT);
  assert(strstr(output, "HVCAM WAIT"));
  command("snapshot");
  assert(strstr(output, "HVCAM BUSY") && s_source == PREVIEW_MODEL_INPUT);
  hv_camera_preview_offer(raw, sizeof(raw), 999);
  assert(s_state == PREVIEW_PENDING);
  hv_camera_preview_offer_model_input(input, 320, 239, 999);
  assert(s_state == PREVIEW_PENDING);
  for (unsigned y = 0; y < height; ++y) {
    for (unsigned x = 0; x < width; ++x) {
      size_t at = ((size_t)y * width + x) * 3;
      input[at] = (uint8_t)x;
      input[at + 1] = (uint8_t)y;
      input[at + 2] = (uint8_t)(x + y);
    }
  }
  hv_camera_preview_offer_model_input(input, width, height, 12345);
  assert(s_state == PREVIEW_READY && s_capturedMs == 12345);
  assert(s_width == width / 2 && s_height == height / 2 && s_rotation == 0);
  assert(guarded_rgb[0] == 0xa5 && guarded_rgb[PREVIEW_BYTES + 1] == 0xa5);
  for (unsigned y = 0; y < height / 2; ++y) {
    for (unsigned x = 0; x < width / 2; ++x) {
      unsigned r = (x * 2) % 256, g = (y * 2) % 256, b = (x * 2 + y * 2) % 256;
      unsigned expected = (r / 8) * 2048 + (g / 4) * 32 + b / 8;
      size_t at = ((size_t)y * (width / 2) + x) * 2;
      assert(((unsigned)s_rgb[at] | ((unsigned)s_rgb[at + 1] << 8)) == expected);
    }
  }
  uint32_t expected_checksum = fnv();
  memset(input, 0, sizeof(input));
  hv_camera_preview_offer_model_input(input, width, height, 54321);
  assert(fnv() == expected_checksum && s_capturedMs == 12345);
  int conversions_before = conversion_calls;
  clear_output(); cycle();
  assert(s_state == PREVIEW_IDLE && conversion_calls == conversions_before);
  char header[100], end[100];
  snprintf(header, sizeof(header), "HVCAM SOURCE model\nHVCAM BEGIN %u %u 38400 12345 0\n",
           width / 2, height / 2);
  snprintf(end, sizeof(end), "HVCAM END %08x\n", expected_checksum);
  assert(strstr(output, header) && strstr(output, end));
  hv_camera_preview_offer_model_input(input, width, height, 88888);
  assert(s_state == PREVIEW_IDLE && fnv() == expected_checksum);
}
static void model_jpeg_case(unsigned width, unsigned height) {
  clear_output(); command("inputjpeg");
  assert(s_state == PREVIEW_PENDING && s_source == PREVIEW_MODEL_JPEG && s_jpegInput);
  assert(strstr(output, "HVJPEG WAIT"));
  command("jpeg"); assert(strstr(output, "HVJPEG BUSY"));
  hv_camera_preview_offer(raw, sizeof(raw), 9);
  assert(s_state == PREVIEW_PENDING);
  input[0] = 0x19; input[1] = 0x29; input[2] = 0x39;
  hv_camera_preview_offer_model_input(input, width, height, 92345);
  assert(s_state == PREVIEW_READY && s_rotation == 0);
  assert(s_jpegInput != input && memcmp(s_jpegInput, input, sizeof(input)) == 0);
  memset(input, 0, sizeof(input)); /* Consumer must have its own complete copy. */
  cycle();
  assert(s_state == PREVIEW_IDLE && s_jpegInput == NULL);
  char header[100];
  snprintf(header, sizeof(header), "HVJPEG BEGIN 1 %u %u 197 92345 0 75\n", width, height);
  assert(strstr(output, "HVJPEG SOURCE model\n") && strstr(output, header));
  assert(encoded_config.width == width && encoded_config.height == height);
}
#endif
int main(void) {
  s_raw = raw; s_rgb = guarded_rgb + 1;
  memset(guarded_rgb, 0xa5, sizeof(guarded_rgb));
#if HV_STAGE >= 2
  model_case(320, 240);
  model_case(240, 320);
  model_jpeg_case(320, 240);
  model_jpeg_case(240, 320);
  fail_allocation = true;
  clear_output(); command("inputjpeg");
  assert(s_state == PREVIEW_IDLE && !s_jpegInput && strstr(output, "HVJPEG ERROR no_input_memory"));
  fail_allocation = false;
  clear_output(); command("inputjpeg"); clock_ms += 10001; cycle();
  assert(s_state == PREVIEW_IDLE && !s_jpegInput && strstr(output, "HVJPEG ERROR no_model_input"));
  clear_output(); command("input"); clock_ms += 10001; cycle();
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVCAM ERROR no_model_input"));
#else
  command("input");
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVCAM ERROR model_input_requires_stage2"));
  hv_camera_preview_offer_model_input(input, 320, 240, 9);
  assert(s_state == PREVIEW_IDLE);
  clear_output(); command("inputjpeg");
  assert(s_state == PREVIEW_IDLE && !s_jpegInput && strstr(output, "HVJPEG ERROR model_input_requires_stage2"));
#endif
  raw_jpeg_case();
  assert(jpeg_opens == jpeg_processes && jpeg_processes == jpeg_closes);
  clear_output(); command("jpeg"); clock_ms += 10001; cycle();
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVJPEG ERROR no_complete_frame"));
  fail_allocation = true;
  clear_output(); command("jpeg"); hv_camera_preview_offer(raw, sizeof(raw), 99); cycle();
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVJPEG ERROR no_output_memory"));
  fail_allocation = false;
  jpeg_open_error = -5;
  clear_output(); command("jpeg"); hv_camera_preview_offer(raw, sizeof(raw), 99); cycle();
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVJPEG ERROR encode_-5"));
  jpeg_open_error = 0;
  raw[0] = 0x11; raw[1] = 0x22; raw[2] = 0x33; raw[3] = 0x44;
  jpeg_process_error = -6;
  int closed_before = jpeg_closes;
  clear_output(); command("jpeg"); hv_camera_preview_offer(raw, sizeof(raw), 99); cycle();
  assert(s_state == PREVIEW_IDLE && jpeg_closes == closed_before + 1);
  assert(strstr(output, "HVJPEG ERROR encode_-6"));
  jpeg_process_error = 0;
  clear_output(); command("snapshot");
  hv_camera_preview_offer_model_input(input, 320, 240, 9);
  assert(s_state == PREVIEW_PENDING && s_source == PREVIEW_CAMERA);
  hv_camera_preview_offer(raw, sizeof(raw), 777);
  assert(s_state == PREVIEW_READY);
  cycle();
  assert(conversion_calls == 1 && s_state == PREVIEW_IDLE);
  assert(strstr(output, HV_ROTATE_CW90 ? "HVCAM BEGIN 120 160 38400 777 1\n" :
                                      "HVCAM BEGIN 120 160 38400 777 0\n"));
  assert(!strstr(output, "HVCAM SOURCE model"));
  assert(guarded_rgb[0] == 0xa5 && guarded_rgb[PREVIEW_BYTES + 1] == 0xa5);
  clear_output(); command("snapshot"); clock_ms += 10001; cycle();
  assert(s_state == PREVIEW_IDLE && strstr(output, "HVCAM ERROR no_complete_frame"));
  return 0;
}
"""


class CameraPreviewFirmwareTest(unittest.TestCase):
    def test_production_preview_for_capture_and_inference_stages(self):
        compiler = shutil.which("cc") or shutil.which("clang")
        self.assertIsNotNone(compiler, "A C compiler is required for firmware host checks")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "preview_test_stubs.h").write_text(STUBS, encoding="utf-8")
            for name in ("esp_err.h", "esp_heap_caps.h", "esp_timer.h", "qm_cli.h", "esp_jpeg_enc.h",
                         "yolo11_pose.h", "freertos/FreeRTOS.h", "freertos/idf_additions.h",
                         "freertos/task.h"):
                header = folder / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('#include "preview_test_stubs.h"\n', encoding="utf-8")
            source = folder / "test_preview.c"
            source.write_text(HARNESS, encoding="utf-8")
            for stage, rotation in ((1, 0), (1, 1), (2, 0), (2, 1)):
                with self.subTest(stage=stage, rotation=rotation):
                    executable = folder / f"preview-stage{stage}-rotation{rotation}"
                    result = subprocess.run([
                        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                        f"-DHV_STAGE={stage}", f"-DHV_ROTATE_CW90={rotation}", "-I", str(folder),
                        "-I", str(ROOT / "headvoice/firmware"), str(source), "-o", str(executable),
                    ], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(executable)], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

"""Run the actual hand app, classifier and gate with SDK I/O stubbed on the host.

The synthetic bias-only model proves integration behavior, not gesture accuracy.
No device, serial port, trained user weights or firmware flash is involved.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADERS = (
    "linux/videodev2.h", "bsp_camera.h", "esp_heap_caps.h", "esp_log.h", "esp_timer.h",
    "esp_err.h", "qm_spec_api.h", "freertos/FreeRTOS.h", "freertos/idf_additions.h",
    "freertos/queue.h", "freertos/task.h", "yolo11_pose.h",
)
STUBS = r'''
#ifndef HAND_APP_TEST_STUBS_H
#define HAND_APP_TEST_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
typedef int portMUX_TYPE;
typedef void *QueueHandle_t;
typedef struct { int unused; } qm_spec_property_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM -2
#define ESP_ERR_INVALID_ARG -3
#define ESP_LOG_WARN 2
#define ESP_LOGW(...) ((void)0)
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_INTERNAL 4
#define V4L2_PIX_FMT_UYVY 1
#define portMUX_INITIALIZER_UNLOCKED 0
#define portMAX_DELAY 0xffffffffu
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(value) (value)
static unsigned lock_depth, allocations;
static void enter_guard(portMUX_TYPE *guard) { (void)guard; assert(lock_depth == 0); ++lock_depth; }
static void leave_guard(portMUX_TYPE *guard) { (void)guard; assert(lock_depth == 1); --lock_depth; }
#define portENTER_CRITICAL(guard) enter_guard(guard)
#define portEXIT_CRITICAL(guard) leave_guard(guard)
static uint64_t clock_ms;
static uint8_t rgb_pixels[320*240*3];
static int conversion_result;
static uint8_t displayed_rgb[3];
static void *heap_caps_malloc(size_t bytes, unsigned caps) {
  assert(caps == (MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)); ++allocations; return malloc(bytes);
}
static void heap_caps_free(void *pointer) { free(pointer); }
static size_t heap_caps_get_free_size(unsigned caps) { (void)caps; return 100000; }
static size_t heap_caps_get_largest_free_block(unsigned caps) { (void)caps; return 50000; }
static int64_t esp_timer_get_time(void) { return (int64_t)clock_ms * 1000; }
static QueueHandle_t xQueueCreate(unsigned capacity, unsigned bytes) { (void)capacity; (void)bytes; return (void*)1; }
static int xQueueReceive(QueueHandle_t queue, void *item, unsigned timeout) { (void)queue; (void)item; (void)timeout; return 0; }
static int xQueueSend(QueueHandle_t queue, const void *item, unsigned timeout) { (void)queue; (void)item; (void)timeout; return pdTRUE; }
static void vTaskDelay(unsigned ticks) { (void)ticks; }
static int xTaskCreateWithCaps(void (*task)(void *), const char *name, unsigned stack,
                              void *arg, unsigned priority, void *handle, unsigned caps) {
  (void)task; (void)name; (void)stack; (void)arg; (void)priority; (void)handle; (void)caps; return pdPASS;
}
static int xTaskCreatePinnedToCoreWithCaps(void (*task)(void *), const char *name, unsigned stack,
                              void *arg, unsigned priority, void *handle, unsigned core, unsigned caps) {
  (void)core; return xTaskCreateWithCaps(task, name, stack, arg, priority, handle, caps);
}
static void esp_log_level_set(const char *name, int level) { (void)name; (void)level; }
static esp_err_t bsp_camera_early_init(void) { return 0; }
static esp_err_t bsp_camera_stream_start(void) { return 0; }
static esp_err_t bsp_camera_set_frame_callback(void (*callback)(const uint8_t*,size_t,uint32_t,uint32_t,uint32_t,uint64_t)) { (void)callback; return 0; }
static esp_err_t yolo11_pose_uyvy_to_rgb888(const uint8_t *input, size_t length, unsigned w, unsigned h,
                                           uint8_t **output, uint16_t *width, uint16_t *height) {
  assert(lock_depth == 0 && input && length == 153600 && w == 240 && h == 320);
  clock_ms += 10; *output = rgb_pixels; *width = 320; *height = 240; return conversion_result;
}
#endif
'''
HARNESS = r'''
#include "headvoice/firmware/hv_hand_app.c"

static unsigned detected_count = 1;
static bool detector_fault, fault_during_detector;
static unsigned detector_calls, offered_inputs;
esp_err_t hv_hand_detect_init(void) { return 0; }
esp_err_t hv_hand_detect_analyze_rgb888(const uint8_t *rgb, uint16_t width,
                                       uint16_t height, hv_hand_detection_t *hand)
{
  assert(lock_depth == 0 && rgb == rgb_pixels && width == 320 && height == 240);
  ++detector_calls; clock_ms += 100;
  if (fault_during_detector) stream_epoch(true);
  memset(hand, 0, sizeof(*hand));
  hand->count = detected_count;
  hand->valid = detected_count == 1;
  hand->score = hand->valid ? .9f : 0;
  if (hand->valid) { hand->box[0] = 60; hand->box[1] = 20; hand->box[2] = 200; hand->box[3] = 200; }
  return detector_fault ? ESP_FAIL : ESP_OK;
}
esp_err_t hv_camera_preview_init(void) { return 0; }
void hv_camera_preview_offer(const uint8_t *data, size_t length, uint64_t captured) {
  (void)data; (void)length; (void)captured;
}
void hv_camera_preview_offer_model_input(const uint8_t *rgb, uint16_t width, uint16_t height, uint64_t captured) {
  (void)captured; assert(rgb == rgb_pixels && width == 320 && height == 240); ++offered_inputs;
}
void hv_panel_pose_epoch(unsigned epoch) { (void)epoch; }
void hv_panel_pose(unsigned stage, uint64_t captured, unsigned people, float tilt,
                   bool tracking, bool eligible, unsigned infer, unsigned epoch) {
  (void)stage; (void)captured; (void)people; (void)tilt; (void)tracking; (void)eligible; (void)infer; (void)epoch;
}
void hv_panel_status_light(uint8_t red, uint8_t green, uint8_t blue) {
  assert(lock_depth == 1); /* Publishing never races the epoch or output lease. */
  displayed_rgb[0] = red; displayed_rgb[1] = green; displayed_rgb[2] = blue;
}
static void frame(hand_inference_state_t *state, uint64_t capture, unsigned age, unsigned epoch)
{
  uint8_t dummy = 0;
  hand_frame_t input = {&dummy, capture, epoch};
  clock_ms = capture + age;
  process_frame(&input, state);
  assert(lock_depth == 0);
}
static bool dark(void) { return !displayed_rgb[0] && !displayed_rgb[1] && !displayed_rgb[2]; }
#ifdef HV_HAND_WEIGHTS_HEADER
static void predict_class(unsigned index)
{
  test_weights[HV_HAND_CLASSIFIER_WEIGHTS-3] = index == 0 ? 4 : 0;
  test_weights[HV_HAND_CLASSIFIER_WEIGHTS-2] = index == 1 ? 4 : 0;
  test_weights[HV_HAND_CLASSIFIER_WEIGHTS-1] = index == 2 ? 4 : 0;
}
#endif

int main(void)
{
  assert(classifier_init() == ESP_OK);
  hand_inference_state_t state;
  inference_state_init(&state);
#ifndef HV_HAND_WEIGHTS_HEADER
  assert(!s_classifierReady && !s_gray && !s_classifierWork && allocations == 0);
  for (uint64_t t = 1000; t < 3000; t += 300) frame(&state, t, 0, 0);
  assert(!state.palmCount && !state.fistCount && dark());
  assert(state.gate.latched == HV_HAND_GATE_UNKNOWN);
#else
  assert(s_classifierReady && s_gray && s_classifierWork && allocations == 2);
  predict_class(0);
  frame(&state, 1000, 0, 0); assert(dark());
  frame(&state, 1300, 0, 0); assert(dark());
  frame(&state, 1600, 0, 0);
  assert(state.palmCount == 1 && displayed_rgb[1] == 32 && !displayed_rgb[2]);
  for (uint64_t t = 1900; t <= 2800; t += 300) frame(&state, t, 0, 0);
  assert(state.palmCount == 1);
  predict_class(1);
  frame(&state, 3100, 0, 0); assert(dark());
  frame(&state, 3400, 0, 0); assert(dark());
  frame(&state, 3700, 0, 0);
  assert(state.fistCount == 1 && displayed_rgb[2] == 32 && !displayed_rgb[1]);
  feedback_tick(4300); assert(displayed_rgb[2] == 32);
  feedback_tick(4301); assert(dark()); /* No inference call is needed to expire light. */
  assert(state.gate.latched == HV_HAND_GATE_CLOSED_FIST);

  frame(&state, 4600, 0, 0); assert(dark()); /* Cross-gap frame cannot revive a window. */
  frame(&state, 4900, 0, 0); assert(displayed_rgb[2] == 32);
  assert(state.fistCount == 1);
  predict_class(9); /* Equal class scores: raw top exists, gate must reject it. */
  frame(&state, 5200, 0, 0); assert(dark());
  assert(state.gate.latched == HV_HAND_GATE_CLOSED_FIST);
  detected_count = 0;
  frame(&state, 5500, 0, 0); assert(dark());
  frame(&state, 6000, 0, 0);
  assert(state.gate.latched == HV_HAND_GATE_UNKNOWN);
  detected_count = 1; predict_class(1);
  frame(&state, 6300, 0, 0); frame(&state, 6600, 0, 0); frame(&state, 6900, 0, 0);
  assert(state.fistCount == 2 && displayed_rgb[2] == 32);

  stream_epoch(true); feedback_tick(7010); assert(dark());
  frame(&state, 7200, 0, 1); frame(&state, 7500, 0, 1); frame(&state, 7800, 0, 1);
  assert(state.fistCount == 2); /* A new epoch does not unlock the same held gesture. */
  predict_class(0);
  frame(&state, 8100, 0, 1); assert(dark());
  fault_during_detector = true;
  frame(&state, 8400, 0, 1); assert(dark());
  fault_during_detector = false;
  frame(&state, 8700, 0, 2); frame(&state, 9000, 0, 2);
  assert(state.palmCount == 1);
  frame(&state, 9300, 0, 2);
  assert(state.palmCount == 2 && displayed_rgb[1] == 32);
  frame(&state, 9600, 600, 2); assert(dark()); /* 710ms total age rejects classification. */
  detected_count = 2;
  frame(&state, 10300, 0, 2); assert(dark());
  detector_fault = true;
  frame(&state, 10600, 0, 2); assert(dark());
  assert(state.palmCount == 2 && state.fistCount == 2);
  heap_caps_free(s_gray); heap_caps_free(s_classifierWork);
#endif
  assert(offered_inputs == detector_calls);
  return 0;
}
'''


class HandAppIntegrationTests(unittest.TestCase):
    def compile_and_run(self, trained):
        with tempfile.TemporaryDirectory(prefix="hand-app-test-") as temp:
            directory = Path(temp)
            (directory/"stubs.h").write_text(STUBS, encoding="utf-8")
            for name in HEADERS:
                path = directory/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "stubs.h"\n', encoding="utf-8")
            (directory/"model.h").write_text(
                '#include "hv_hand_classifier.h"\n'
                'static float test_weights[HV_HAND_CLASSIFIER_WEIGHTS];\n'
                'static const hv_hand_classifier_model_t hv_hand_model = '
                '{test_weights,HV_HAND_CLASSIFIER_WEIGHTS,HV_HAND_CLASSIFIER_VERSION};\n'
                '#define HV_HAND_MODEL_SHA256 "synthetic-test-only-not-a-trained-model"\n', encoding="utf-8")
            harness = directory/"harness.c"
            harness.write_text(HARNESS, encoding="utf-8")
            binary = directory/"app-test"
            defines = ['-DHV_HAND_WEIGHTS_HEADER="model.h"'] if trained else []
            subprocess.run([shutil.which("cc") or "clang", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                            "-UNDEBUG", "-DHV_STAGE=2", *defines, "-I", str(directory), "-I", str(ROOT),
                            "-I", str(ROOT/"headvoice/core"), "-I", str(ROOT/"headvoice/firmware"),
                            str(harness), str(ROOT/"headvoice/core/hv_hand_classifier.c"),
                            str(ROOT/"headvoice/core/hv_hand_gate.c"), "-o", str(binary), "-lm"], check=True)
            completed = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            return [json.loads(line[3:]) for line in completed.stdout.splitlines() if line.startswith("HG ")]

    def test_default_detection_only_never_classifies(self):
        rows = self.compile_and_run(False)
        self.assertTrue(rows)
        self.assertFalse(any(row.get("event") == "gesture" for row in rows))
        observations = [row for row in rows if row["event"] == "observation"]
        self.assertTrue(all(row["classifier_ready"] is False and row["gesture"] == "untrained" for row in observations))
        self.assertTrue(all(row["valid"] is True and row["hands"] == 1 for row in observations))

    def test_actual_classifier_gate_and_watchdog_integration(self):
        rows = self.compile_and_run(True)
        events = [row for row in rows if row["event"] == "gesture"]
        self.assertEqual([row["gesture"] for row in events], ["open_palm", "closed_fist", "closed_fist", "open_palm"])
        self.assertEqual(events[-1]["palm_count"], 2)
        self.assertEqual(events[-1]["fist_count"], 2)
        observations = [row for row in rows if row["event"] == "observation"]
        self.assertTrue(all(row["classifier_ready"] is True for row in observations))
        uncertain = next(row for row in observations if row["captured_ms"] == 5200)
        self.assertEqual(uncertain["gesture"], "open_palm")
        self.assertTrue(uncertain["classification_valid"])
        self.assertFalse(uncertain["confirmed"])
        self.assertEqual(uncertain["gate_visible"], "unknown")
        self.assertTrue(all(row["valid"] is False for row in observations if row["captured_ms"] in (8400, 9600, 10300, 10600)))


if __name__ == "__main__":
    unittest.main()

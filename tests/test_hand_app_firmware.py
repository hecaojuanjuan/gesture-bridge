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
static void (*guard_hook)(void);
static void enter_guard(portMUX_TYPE *guard) {
  (void)guard; assert(lock_depth == 0);
  if (guard_hook) guard_hook();
  ++lock_depth;
}
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
static unsigned camera_init_calls, camera_start_calls, camera_callback_calls;
static esp_err_t bsp_camera_early_init(void) { ++camera_init_calls; return 0; }
static esp_err_t bsp_camera_stream_start(void) { ++camera_start_calls; return 0; }
static esp_err_t bsp_camera_set_frame_callback(void (*callback)(const uint8_t*,size_t,uint32_t,uint32_t,uint32_t,uint64_t)) { assert(callback); ++camera_callback_calls; return 0; }
static esp_err_t yolo11_pose_uyvy_to_rgb888(const uint8_t *input, size_t length, unsigned w, unsigned h,
                                           uint8_t **output, uint16_t *width, uint16_t *height) {
  assert(lock_depth == 0 && input && length == 153600 && w == 240 && h == 320);
  clock_ms += 10; *output = rgb_pixels; *width = 320; *height = 240; return conversion_result;
}
#endif
'''
HARNESS = r'''
#include "headvoice/firmware/hv_hand_app.c"

static unsigned agent_submissions;
esp_err_t hv_gesture_agent_init(void) { return ESP_OK; }
void hv_gesture_agent_submit(hv_hand_gate_event_t event, uint64_t captured) {
  assert(event != HV_HAND_GATE_EVENT_NONE && captured <= clock_ms);
  if (HV_HAND_SINGLE_SHOT) {
    headvoice_scan_status_t scan; headvoice_scan_status(&scan);
    assert(scan.supported && !scan.armed);
    assert(!headvoice_scan_arm()); /* Completion-to-agent handoff is exclusive. */
  }
  ++agent_submissions;
  printf("HG {\"event\":\"agent_submit\",\"kind\":%d}\n", (int)event);
}

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
  feedback_tick(3700 + HV_HAND_GATE_MAX_AGE_MS); assert(displayed_rgb[2] == 32);
  feedback_tick(3700 + HV_HAND_GATE_MAX_AGE_MS + 1); assert(dark()); /* No inference call is needed to expire light. */
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
  frame(&state, 9600, HV_HAND_GATE_MAX_AGE_MS + 1 - 110, 2); assert(dark()); /* 1001ms total age rejects classification. */
  detected_count = 2;
  frame(&state, 10900, 0, 2); assert(dark());
  detector_fault = true;
  frame(&state, 11200, 0, 2); assert(dark());
  assert(state.palmCount == 2 && state.fistCount == 2);
  heap_caps_free(s_gray); heap_caps_free(s_classifierWork);
#endif
  assert(offered_inputs == detector_calls);
  return 0;
}
'''


# Same detector/camera/SDK scaffolding, actual app and gate; only the native
# model boundary is replaced with deterministic labelled scores. These scores
# test routing and safety, not the official model's accuracy or board timing.
NATIVE_HARNESS = HARNESS.split("#ifdef HV_HAND_WEIGHTS_HEADER", 1)[0] + r'''
static hv_hand_native_status_t native_init_status = HV_HAND_NATIVE_OK;
static hv_hand_native_status_t native_infer_status = HV_HAND_NATIVE_OK;
static bool native_ready_value = true, native_valid = true, native_bad_score;
static bool native_fault, commit_fault, commit_expired;
static unsigned native_calls, native_deinits, native_delay = 30, guard_countdown;
static int native_top = HV_HAND_NATIVE_CLASS_FIVE;

hv_hand_native_status_t hv_hand_native_classifier_init(const char *partition, const char *hash) {
  assert(!strcmp(partition, "test_native_model"));
  assert(!strcmp(hash, HV_HAND_NATIVE_MODEL_SHA256));
  return native_init_status;
}
bool hv_hand_native_classifier_ready(void) { return native_ready_value; }
void hv_hand_native_classifier_deinit(void) { native_ready_value = false; ++native_deinits; }
const char *hv_hand_native_class_name(int index) {
  const char *names[] = {"one","two","three","four","five","like","ok",
                         "no_gesture","call","dislike","no_hand"};
  return index >= 0 && index < 11 ? names[index] : "unknown";
}
static void before_commit(void) {
  if (--guard_countdown) return;
  guard_hook = NULL;
  if (commit_fault) ++s_epoch;
  if (commit_expired) clock_ms += HV_HAND_GATE_MAX_AGE_MS + 1;
}
hv_hand_native_status_t hv_hand_native_classifier_analyze_rgb888(
    const uint8_t *rgb, size_t bytes, uint16_t width, uint16_t height,
    const hv_hand_detection_t *hand, hv_hand_native_result_t *out) {
  assert(lock_depth == 0 && rgb == rgb_pixels && bytes == sizeof(rgb_pixels));
  assert(width == 320 && height == 240 && hand->valid && hand->count == 1);
  ++native_calls; clock_ms += native_delay;
  memset(out, 0, sizeof(*out));
  out->valid = native_valid; out->top_index = native_top;
  for (unsigned i = 0; i < 11; ++i) out->scores[i] = i == (unsigned)native_top ? .9f : .01f;
  if (native_bad_score) out->scores[0] = NAN;
  out->top_score = .9f; out->second_score = .01f; out->margin = .89f;
  out->preprocess_ms = 3; out->model_ms = native_delay - 4; out->postprocess_ms = 1;
  if (native_fault) stream_epoch(true);
  if (commit_fault || commit_expired) {
    /* First lock is the post-inference epoch read; second is output commit.
     * This injects an interleaving after the final unlocked freshness test. */
    guard_countdown = 2; guard_hook = before_commit;
  }
  return native_infer_status;
}
static void hold(hand_inference_state_t *state, uint64_t start, unsigned epoch) {
  frame(state, start, 0, epoch); frame(state, start + 300, 0, epoch); frame(state, start + 600, 0, epoch);
}
int main(int argc, char **argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "missing")) native_init_status = HV_HAND_NATIVE_PARTITION_MISSING;
  if (!strcmp(argv[1], "not-ready")) native_ready_value = false;
  assert(headvoice_start() == ESP_OK);
  assert(camera_init_calls == 1 && camera_start_calls == 1 && camera_callback_calls == 1);
  assert(allocations == RAW_COUNT); /* Native adapter owns its own work memory. */
  hand_inference_state_t state; inference_state_init(&state);
  if (strcmp(argv[1], "ready")) {
    assert(!s_classifierReady && native_deinits == 1);
    hold(&state, 1000, 0);
    assert(native_calls == 0 && detector_calls == 3 && offered_inputs == 3);
    assert(state.palmCount == 0 && state.vCount == 0 && dark());
  } else {
    assert(s_classifierReady && native_deinits == 0);
    frame(&state, 1000, 0, 0); assert(dark());
    frame(&state, 1300, 0, 0); assert(dark());
    frame(&state, 1600, 0, 0);
    assert(state.palmCount == 1 && displayed_rgb[1] == 32 && !displayed_rgb[2]);
    frame(&state, 1900, 0, 0); frame(&state, 2200, 0, 0);
    assert(state.palmCount == 1);
    native_top = HV_HAND_NATIVE_CLASS_TWO;
    frame(&state, 2500, 0, 0); assert(dark());
    frame(&state, 2800, 0, 0); assert(dark());
    frame(&state, 3100, 0, 0);
    assert(state.vCount == 1 && displayed_rgb[2] == 32 && !displayed_rgb[1]);
    frame(&state, 3400, 0, 0); assert(state.vCount == 1);
    feedback_tick(4000); assert(displayed_rgb[2] == 32);
    feedback_tick(4001); assert(displayed_rgb[2] == 32); /* 601ms remains fresh. */
    frame(&state, 4100, 0, 0); assert(state.vCount == 1);

    /* All non-target classes stay OTHER, including model no_hand with hands=1. */
    uint64_t next = 4300;
    for (int i = 0; i < HV_HAND_NATIVE_CLASS_COUNT; ++i) {
      if (i == HV_HAND_NATIVE_CLASS_TWO || i == HV_HAND_NATIVE_CLASS_FIVE) continue;
      native_top = i; frame(&state, next, 0, 0); next += 300;
      assert(state.gate.visible == HV_HAND_GATE_OTHER && dark());
    }
    assert(state.palmCount == 1 && state.vCount == 1 && state.fistCount == 0);
    assert(state.gate.latched == HV_HAND_GATE_UNKNOWN);
    native_top = HV_HAND_NATIVE_CLASS_TWO;
    hold(&state, 7000, 0); assert(state.vCount == 2 && displayed_rgb[2] == 32);

    /* Native compute exceeding the lease is rejected AFTER inference. */
    native_top = HV_HAND_NATIVE_CLASS_FIVE; native_delay = HV_HAND_GATE_MAX_AGE_MS + 1 - 110;
    frame(&state, 7900, 0, 0); assert(dark() && state.palmCount == 1);
    native_delay = 30;
    /* Already stale input never calls the classifier at all. */
    unsigned calls = native_calls;
    frame(&state, 8600, HV_HAND_GATE_MAX_AGE_MS + 1 - 110, 0); assert(native_calls == calls && dark());
    native_fault = true;
    frame(&state, 9500, 0, 0); assert(dark() && s_epoch == 1);
    native_fault = false;
    frame(&state, 9800, 0, 1); frame(&state, 10100, 0, 1);
    assert(state.palmCount == 1 && dark());
    frame(&state, 10400, 0, 1); assert(state.palmCount == 2 && displayed_rgb[1] == 32);

    /* An epoch change right at commit cannot emit or latch the new V. */
    native_top = HV_HAND_NATIVE_CLASS_TWO;
    frame(&state, 10700, 0, 1); frame(&state, 11000, 0, 1);
    commit_fault = true; frame(&state, 11300, 0, 1); commit_fault = false;
    assert(state.vCount == 2 && dark() && s_epoch == 2);
    assert(state.gate.latched == HV_HAND_GATE_OPEN_PALM);
    frame(&state, 11600, 0, 2); frame(&state, 11900, 0, 2);
    assert(state.vCount == 2);
    frame(&state, 12200, 0, 2); assert(state.vCount == 3 && displayed_rgb[2] == 32);

    /* Same commit safeguard for clock expiry, not only epoch mutation. */
    native_top = HV_HAND_NATIVE_CLASS_FIVE;
    frame(&state, 12500, 0, 2); frame(&state, 12800, 0, 2);
    commit_expired = true; frame(&state, 13100, 0, 2); commit_expired = false;
    assert(state.palmCount == 2 && dark() && state.gate.latched == HV_HAND_GATE_V_SIGN);

    /* Failed/invalid native outputs cannot reach the gate or poison JSON. */
    native_infer_status = HV_HAND_NATIVE_INVALID_OUTPUT;
    frame(&state, 14000, 0, 2); assert(dark());
    native_infer_status = HV_HAND_NATIVE_OK; native_valid = false;
    frame(&state, 14300, 0, 2); assert(dark()); native_valid = true;
    native_top = 99; frame(&state, 14600, 0, 2); assert(dark());
    native_top = HV_HAND_NATIVE_CLASS_FIVE; native_bad_score = true;
    frame(&state, 14900, 0, 2); assert(dark()); native_bad_score = false;
    detected_count = 0; calls = native_calls;
    frame(&state, 15200, 0, 2); assert(native_calls == calls && dark());
    assert(state.gate.visible == HV_HAND_GATE_NO_HAND);
    detected_count = 2;
    frame(&state, 15500, 0, 2); assert(native_calls == calls && dark());
    assert(state.gate.visible == HV_HAND_GATE_UNKNOWN);
    detected_count = 1; detector_fault = true;
    frame(&state, 15800, 0, 2); assert(native_calls == calls && dark());
    detector_fault = false; native_top = HV_HAND_NATIVE_CLASS_ONE;
    frame(&state, 16100, 0, 2);
    commit_fault = true; frame(&state, 16600, 0, 2); commit_fault = false;
    assert(s_epoch == 3 && state.gate.latched == HV_HAND_GATE_V_SIGN && dark());
    /* Rejected release at commit must not unlock another copy of the same V. */
    native_top = HV_HAND_NATIVE_CLASS_TWO;
    hold(&state, 16900, 3);
    assert(state.palmCount == 2 && state.vCount == 3 && state.fistCount == 0);
    feedback_tick(17500 + HV_HAND_GATE_MAX_AGE_MS); assert(displayed_rgb[2] == 32);
    feedback_tick(17500 + HV_HAND_GATE_MAX_AGE_MS + 1); assert(dark());
  }
  for (unsigned i = 0; i < RAW_COUNT; ++i) heap_caps_free(s_frames[i].data);
  assert(offered_inputs == detector_calls && !guard_hook);
  return 0;
}
'''

SINGLE_SHOT_HARNESS = NATIVE_HARNESS.split("int main(int argc", 1)[0] + r'''
int main(int argc, char **argv) {
  (void)argc; (void)argv;
  assert(headvoice_start()==ESP_OK);
  assert(dark());
  headvoice_scan_status_t scan; headvoice_scan_status(&scan);
  assert(scan.supported && scan.armed && scan.generation==1);
  assert(headvoice_scan_arm()); headvoice_scan_status(&scan); assert(scan.generation==1);
  hand_inference_state_t state; inference_state_init(&state);
  hold(&state,1000,0);
  headvoice_scan_status(&scan);
  assert(!scan.armed && scan.palm_count==1 && !strcmp(scan.last_gesture,"open_palm"));
  assert(agent_submissions==1);
  unsigned detect_before=detector_calls,native_before=native_calls,preview_before=offered_inputs;
  native_top=HV_HAND_NATIVE_CLASS_TWO;
  for(uint64_t t=1900;t<=4000;t+=300) frame(&state,t,0,0);
  assert(detector_calls==detect_before && native_calls==native_before && offered_inputs>preview_before);
  assert(agent_submissions==1 && state.palmCount==1 && state.vCount==0);
  conversion_result=ESP_FAIL; frame(&state,4300,0,0); conversion_result=ESP_OK;
  assert(detector_calls==detect_before && native_calls==native_before);
  clock_ms=4500; assert(headvoice_scan_arm()); headvoice_scan_status(&scan);
  assert(scan.armed && scan.generation==2 && scan.palm_count==1);
  frame(&state,4400,100,0); /* Buffered frame predating explicit arm is ignored. */
  assert(detector_calls==detect_before);
  hold(&state,4600,0); headvoice_scan_status(&scan);
  assert(!scan.armed && scan.generation==2 && scan.palm_count==1 && scan.v_count==1);
  assert(!strcmp(scan.last_gesture,"v_sign") && agent_submissions==2);
  for(uint64_t t=5500;t<=6400;t+=300) frame(&state,t,0,0);
  assert(agent_submissions==2 && state.vCount==1);
  clock_ms=6600; assert(headvoice_scan_arm());
  hold(&state,6700,0); headvoice_scan_status(&scan);
  assert(!scan.armed && scan.generation==3 && scan.v_count==2 && agent_submissions==3);
  for(unsigned i=0;i<RAW_COUNT;i++) heap_caps_free(s_frames[i].data);
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
        self.assertEqual(len([row for row in rows if row["event"] == "agent_submit"]), len(events))
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
        self.assertTrue(all(row["valid"] is False for row in observations if row["captured_ms"] in (8400, 9600, 10900, 11200)))

    def compile_and_run_native(self, scenario):
        with tempfile.TemporaryDirectory(prefix="hand-native-app-test-") as temp:
            directory = Path(temp)
            (directory/"stubs.h").write_text(STUBS, encoding="utf-8")
            for name in HEADERS:
                path = directory/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "stubs.h"\n', encoding="utf-8")
            harness = directory/"harness.c"
            harness.write_text(SINGLE_SHOT_HARNESS if scenario == "oneshot" else NATIVE_HARNESS, encoding="utf-8")
            binary = directory/"app-native-test"
            subprocess.run([
                shutil.which("cc") or "clang", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                "-DHV_STAGE=2", "-DHV_HAND_NATIVE_CLASSIFIER=1", '-DHV_HAND_NATIVE_PARTITION="test_native_model"',
                *(["-DHV_HAND_SINGLE_SHOT=1"] if scenario == "oneshot" else []),
                "-I", str(directory), "-I", str(ROOT), "-I", str(ROOT/"headvoice/core"),
                "-I", str(ROOT/"headvoice/firmware"), str(harness),
                # No legacy classifier linked: native path must be self-contained.
                str(ROOT/"headvoice/core/hv_hand_gate.c"), "-o", str(binary), "-lm",
            ], check=True)
            completed = subprocess.run([str(binary), scenario], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout[-3000:])
            return [json.loads(line[3:]) for line in completed.stdout.splitlines() if line.startswith("HG ")]

    def test_single_shot_stops_both_models_keeps_preview_and_requires_explicit_arm(self):
        rows = self.compile_and_run_native("oneshot")
        events = [row for row in rows if row.get("event") == "gesture"]
        self.assertEqual([row["gesture"] for row in events], ["open_palm", "v_sign", "v_sign"])
        self.assertEqual([row["scan_generation"] for row in events], [1, 2, 3])
        self.assertTrue(all(row["scan_armed"] is False for row in events))
        observations = [row for row in rows if row.get("event") == "observation"]
        self.assertFalse(any(1900 <= row["captured_ms"] <= 4500 for row in observations))

    def test_native_official_names_gate_lifecycle_and_eleven_scores(self):
        rows = self.compile_and_run_native("ready")
        ready = next(row for row in rows if row["event"] == "ready")
        self.assertEqual(ready["classifier"], "espdl_gesture11")
        self.assertTrue(ready["classifier_ready"])
        self.assertFalse(ready["servo_control"])
        self.assertEqual(len(ready["model_sha256"]), 64)
        events = [row for row in rows if row["event"] == "gesture"]
        self.assertEqual(len([row for row in rows if row["event"] == "agent_submit"]), len(events))
        self.assertEqual([row["gesture"] for row in events], ["open_palm", "v_sign", "v_sign", "open_palm", "v_sign"])
        self.assertEqual((events[-1]["palm_count"], events[-1]["v_count"]), (2, 3))
        self.assertTrue(all(row["classifier"] == "espdl_gesture11" and "fist_count" not in row for row in events))
        observations = [row for row in rows if row["event"] == "observation"]
        self.assertTrue(all(len(row["scores"]) == 11 and row["classifier"] == "espdl_gesture11" for row in observations))
        self.assertTrue(all("v_count" in row and "fist_count" not in row for row in observations))
        at = {row["captured_ms"]: row for row in observations}
        self.assertEqual(at[1000]["gesture"], "five")
        self.assertTrue(at[1000]["classification_valid"])
        self.assertFalse(at[1000]["confirmed"])
        self.assertTrue(at[1600]["confirmed"])
        self.assertEqual(at[3100]["gesture"], "two")
        self.assertTrue(at[3100]["confirmed"])
        self.assertEqual(at[1000]["scores"].index(max(at[1000]["scores"])), 4)
        self.assertEqual(at[3100]["scores"].index(max(at[3100]["scores"])), 1)
        self.assertEqual(at[1000]["classifier_ms"], 30)
        other = [row for row in observations if 4300 <= row["captured_ms"] < 7000]
        self.assertEqual([row["gesture"] for row in other],
                         ["one", "three", "four", "like", "ok", "no_gesture", "call", "dislike", "no_hand"])
        self.assertTrue(all(row["gate_visible"] == "other" and row["hands"] == 1 and
                            row["classification_valid"] and not row["confirmed"] for row in other))
        for stamp in (7900, 8600, 9500, 11300, 13100, 16600):
            with self.subTest(stale_or_epoch=stamp):
                self.assertFalse(at[stamp]["valid"])
                self.assertFalse(at[stamp]["classification_valid"])
                self.assertFalse(at[stamp]["confirmed"])
                self.assertEqual(at[stamp]["gate_visible"], "unknown")
        self.assertGreater(at[13100]["age_ms"], 1000)
        self.assertEqual(at[16600]["gate_latched"], "v_sign")
        for stamp in (14000, 14300, 14600, 14900):
            with self.subTest(invalid_model_output=stamp):
                self.assertEqual(at[stamp]["classifier_status"], 10)
                self.assertEqual(at[stamp]["gesture"], "unknown")
                self.assertEqual(at[stamp]["scores"], [0] * 11)
                self.assertFalse(at[stamp]["classification_valid"])
                self.assertFalse(at[stamp]["confirmed"])
        self.assertEqual(at[15200]["hands"], 0)
        self.assertEqual(at[15200]["gate_visible"], "no_hand")
        self.assertFalse(at[15200]["classification_valid"])

    def test_native_missing_model_keeps_detection_and_camera_running(self):
        self.assert_native_unavailable(self.compile_and_run_native("missing"), 4)

    def test_native_false_readiness_is_not_reported_as_ready(self):
        self.assert_native_unavailable(self.compile_and_run_native("not-ready"), 1)

    def assert_native_unavailable(self, rows, status):
        diagnostic = next(row for row in rows if row["event"] == "classifier_init")
        self.assertEqual(diagnostic["classifier_status"], status)
        self.assertFalse(diagnostic["classifier_ready"])
        ready = next(row for row in rows if row["event"] == "ready")
        self.assertFalse(ready["classifier_ready"])
        self.assertEqual(ready["model_sha256"], "unavailable")
        observations = [row for row in rows if row["event"] == "observation"]
        self.assertEqual(len(observations), 3)
        self.assertTrue(all(row["valid"] and row["hands"] == 1 for row in observations))
        self.assertTrue(all(row["gesture"] == "unavailable" and row["scores"] == [0] * 11 and
                            not row["classification_valid"] and not row["classifier_ready"] and
                            not row["confirmed"] for row in observations))
        self.assertFalse(any(row["event"] == "gesture" for row in rows))


if __name__ == "__main__":
    unittest.main()

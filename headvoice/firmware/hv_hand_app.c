#include "headvoice_app.h"

#include <linux/videodev2.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "bsp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hv_camera_preview.h"
#include "hv_hand_detect.h"
#ifndef HV_HAND_NATIVE_CLASSIFIER
#define HV_HAND_NATIVE_CLASSIFIER 0
#endif
#if HV_HAND_NATIVE_CLASSIFIER
#include "hv_hand_native_classifier.h"
#ifndef HV_HAND_NATIVE_PARTITION
#error "Native hand classification requires an explicit model partition"
#endif
#define HAND_SECOND_TARGET HV_HAND_GATE_V_SIGN
#define HAND_CLASSIFIER_JSON "\"classifier\":\"espdl_gesture11\","
#define HAND_SECOND_COUNT_JSON "\"v_count\":%u,"
#else
#include "hv_hand_classifier.h"
#define HAND_SECOND_TARGET HV_HAND_GATE_CLOSED_FIST
#define HAND_CLASSIFIER_JSON ""
#define HAND_SECOND_COUNT_JSON "\"fist_count\":%u,"
#endif
#include "hv_hand_gate.h"
#include "hv_panel.h"
#include "hv_settings.h"
#include "yolo11_pose.h"

#if !HV_HAND_NATIVE_CLASSIFIER && defined(HV_HAND_WEIGHTS_HEADER)
#include HV_HAND_WEIGHTS_HEADER
#endif

/* Hand inference owns a separate application: no servo initialization,
 * head-tilt state machine, or expression/audio requests are linked here. */
#define RAW_BYTES (240 * 320 * 2)
#define RAW_COUNT 2
#define TAG "handvoice"

typedef struct {
  uint8_t *data;
  uint64_t capturedMs;
  unsigned epoch;
} hand_frame_t;

static QueueHandle_t s_free, s_pending;
static hand_frame_t s_frames[RAW_COUNT];
static portMUX_TYPE s_guard = portMUX_INITIALIZER_UNLOCKED;
static unsigned s_epoch;
static atomic_uint s_captured, s_dropped;
static bool s_classifierReady;
#if !HV_HAND_NATIVE_CLASSIFIER
static uint8_t *s_gray;
static float *s_classifierWork;
#endif
/* Only this tiny output snapshot is shared with the feedback watchdog. The
 * classifier and confirmation gate belong exclusively to inference_task. */
static struct {
  bool valid;
  uint64_t capturedMs;
  unsigned epoch;
  hv_hand_gate_kind_t kind;
} s_feedback;

typedef struct {
  hv_hand_gate_t gate;
  unsigned epoch, sequence, palmCount, fistCount, vCount;
  uint64_t lastMetrics;
} hand_inference_state_t;

static uint64_t now_ms(void) { return (uint64_t)(esp_timer_get_time() / 1000); }

static unsigned stream_epoch(bool invalid)
{
  portENTER_CRITICAL(&s_guard);
  if (invalid) {
    ++s_epoch;
    s_feedback.valid = false;
  }
  unsigned value = s_epoch;
  portEXIT_CRITICAL(&s_guard);
  return value;
}

#if !HV_HAND_NATIVE_CLASSIFIER
static const hv_hand_classifier_model_t *classifier_model(void)
{
#ifdef HV_HAND_WEIGHTS_HEADER
  return &hv_hand_model;
#else
  return NULL;
#endif
}
#endif

static const char *classifier_hash(void)
{
#if HV_HAND_NATIVE_CLASSIFIER
  return s_classifierReady ? HV_HAND_NATIVE_MODEL_SHA256 : "unavailable";
#elif defined(HV_HAND_MODEL_SHA256)
  return HV_HAND_MODEL_SHA256;
#else
  return "untrained";
#endif
}

static esp_err_t classifier_init(void)
{
#if HV_HAND_NATIVE_CLASSIFIER
  hv_hand_native_status_t status = hv_hand_native_classifier_init(
      HV_HAND_NATIVE_PARTITION, HV_HAND_NATIVE_MODEL_SHA256);
  s_classifierReady = status == HV_HAND_NATIVE_OK && hv_hand_native_classifier_ready();
  if (!s_classifierReady) {
    /* A missing/corrupt model disables classification, never camera or voice.
     * Also reject an init that reports OK without a usable model singleton. */
    hv_hand_native_classifier_deinit();
    printf("HG {\"v\":1,\"event\":\"classifier_init\","
           HAND_CLASSIFIER_JSON "\"classifier_ready\":false,\"classifier_status\":%d}\n",
           (int)(status == HV_HAND_NATIVE_OK ? HV_HAND_NATIVE_NOT_READY : status));
    ESP_LOGW(TAG, "Native classifier unavailable: %d", (int)status);
  }
  return ESP_OK;
#else
  const hv_hand_classifier_model_t *model = classifier_model();
  if (!model) return ESP_OK; /* A detection-only build allocates no classifier buffers. */
  if (!model->weights || model->count != HV_HAND_CLASSIFIER_WEIGHTS ||
      model->version != HV_HAND_CLASSIFIER_VERSION) return ESP_ERR_INVALID_ARG;
  s_gray = heap_caps_malloc(HV_HAND_CLASSIFIER_PIXELS, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  s_classifierWork = heap_caps_malloc(sizeof(float) * HV_HAND_CLASSIFIER_WORK_FLOATS,
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!s_gray || !s_classifierWork) {
    heap_caps_free(s_gray);
    heap_caps_free(s_classifierWork);
    s_gray = NULL;
    s_classifierWork = NULL;
    return ESP_ERR_NO_MEM;
  }
  s_classifierReady = true;
  return ESP_OK;
#endif
}

static bool is_target(hv_hand_gate_kind_t kind)
{
  return kind == HV_HAND_GATE_OPEN_PALM || kind == HAND_SECOND_TARGET;
}

static unsigned second_count(const hand_inference_state_t *state)
{
#if HV_HAND_NATIVE_CLASSIFIER
  return state->vCount;
#else
  return state->fistCount;
#endif
}

/* Caller holds s_guard. hv_panel_status_light only copies under its own short
 * guard; fixed lock order is hand guard -> panel guard, with no I/O or inference. */
static void feedback_light_locked(uint64_t now)
{
  uint8_t green = 0, blue = 0;
  bool live = s_feedback.valid && s_feedback.epoch == s_epoch &&
              now >= s_feedback.capturedMs &&
              now - s_feedback.capturedMs <= HV_HAND_GATE_MAX_AGE_MS;
  if (live && s_feedback.kind == HV_HAND_GATE_OPEN_PALM) green = 32;
  if (live && s_feedback.kind == HAND_SECOND_TARGET) blue = 32;
  hv_panel_status_light(0, green, blue);
}

static bool feedback_publish(const hv_hand_gate_t *gate, uint64_t captured,
                              unsigned epoch, uint64_t now)
{
  portENTER_CRITICAL(&s_guard);
  bool current = epoch == s_epoch && now >= captured &&
                 now - captured <= HV_HAND_GATE_MAX_AGE_MS;
  s_feedback.valid = current && s_classifierReady && gate->visible == gate->latched &&
                     is_target(gate->visible);
  s_feedback.capturedMs = captured;
  s_feedback.epoch = epoch;
  s_feedback.kind = gate->visible;
  feedback_light_locked(now);
  portEXIT_CRITICAL(&s_guard);
  return current;
}

static void feedback_tick(uint64_t now)
{
  portENTER_CRITICAL(&s_guard);
  feedback_light_locked(now);
  portEXIT_CRITICAL(&s_guard);
}

static void feedback_task(void *argument)
{
  (void)argument;
  for (;;) {
    feedback_tick(now_ms());
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

static void camera_frame(const uint8_t *bytes, size_t length, uint32_t width,
                         uint32_t height, uint32_t format, uint64_t capturedMs)
{
  if (!bytes || length != RAW_BYTES || width != 240 || height != 320 ||
      format != V4L2_PIX_FMT_UYVY) {
    stream_epoch(true);
    return;
  }
  hv_camera_preview_offer(bytes, length, capturedMs);
  hand_frame_t *frame = NULL;
  if (xQueueReceive(s_pending, &frame, 0) == pdTRUE) {
    ++s_dropped;
  } else if (xQueueReceive(s_free, &frame, 0) != pdTRUE) {
    ++s_dropped;
    return;
  }
  memcpy(frame->data, bytes, RAW_BYTES);
  frame->capturedMs = capturedMs;
  frame->epoch = stream_epoch(false);
  if (xQueueSend(s_pending, &frame, 0) != pdTRUE) {
    xQueueSend(s_free, &frame, 0);
    stream_epoch(true);
  }
  ++s_captured;
}

static void inference_state_init(hand_inference_state_t *state)
{
  memset(state, 0, sizeof(*state));
  hv_hand_gate_init(&state->gate);
  state->epoch = stream_epoch(false);
  state->lastMetrics = now_ms();
}

static void process_frame(hand_frame_t *frame, hand_inference_state_t *state)
{
    uint64_t captured = frame->capturedMs, started = now_ms();
    unsigned epoch = frame->epoch;
    unsigned currentEpoch = stream_epoch(false);
    if (state->epoch != currentEpoch) {
      hv_hand_gate_invalidate(&state->gate);
      state->epoch = currentEpoch;
    }
    uint8_t *rgb = NULL;
    uint16_t width = 0, height = 0;
#if HV_ROTATE_CW90
    esp_err_t ret = yolo11_pose_uyvy_to_rgb888_cw90(
#else
    esp_err_t ret = yolo11_pose_uyvy_to_rgb888(
#endif
      frame->data, RAW_BYTES, 240, 320, &rgb, &width, &height);
    uint32_t conversionMs = (uint32_t)(now_ms() - started);
    xQueueSend(s_free, &frame, 0);
    hv_hand_detection_t hand = {0};
    uint64_t detectStarted = now_ms();
    if (ret == ESP_OK) {
      hv_camera_preview_offer_model_input(rgb, width, height, captured);
      ret = hv_hand_detect_analyze_rgb888(rgb, width, height, &hand);
    }
    uint32_t detectMs = (uint32_t)(now_ms() - detectStarted);
    uint64_t now = now_ms();
    bool fresh = ret == ESP_OK && epoch == stream_epoch(false) && now >= captured &&
                 now - captured <= HV_HAND_GATE_MAX_AGE_MS;
    float scores[HV_HAND_CLASSIFIER_CLASSES] = {0};
    hv_hand_classifier_status_t classStatus = HV_HAND_CLASSIFIER_NOT_READY;
    uint32_t classifierMs = 0;
    unsigned top = HV_HAND_OTHER;
    float runnerUp = 0;
    const char *rawLabel = s_classifierReady ? "unknown" : "untrained";
    if (s_classifierReady && fresh && hand.count == 0) rawLabel = "no_hand";
    if (s_classifierReady && fresh && hand.valid) {
      uint64_t classifyStarted = now_ms();
      classStatus = hv_hand_classifier_preprocess_rgb888(rgb, (size_t)width * height * 3,
        width, height, hand.box[0], hand.box[1], hand.box[2], hand.box[3], s_gray);
      if (classStatus == HV_HAND_CLASSIFIER_OK)
        classStatus = hv_hand_classifier_predict(classifier_model(), s_gray, s_classifierWork,
                                                HV_HAND_CLASSIFIER_WORK_FLOATS, scores);
      classifierMs = (uint32_t)(now_ms() - classifyStarted);
      if (classStatus == HV_HAND_CLASSIFIER_OK) {
        top = 0;
        for (unsigned i = 1; i < HV_HAND_CLASSIFIER_CLASSES; ++i)
          if (scores[i] > scores[top]) top = i;
        for (unsigned i = 0; i < HV_HAND_CLASSIFIER_CLASSES; ++i)
          if (i != top && scores[i] > runnerUp) runnerUp = scores[i];
        rawLabel = hv_hand_classifier_label(top);
      }
    }
    now = now_ms();
    currentEpoch = stream_epoch(false);
    fresh = ret == ESP_OK && epoch == currentEpoch && now >= captured &&
            now - captured <= HV_HAND_GATE_MAX_AGE_MS;
    if (state->epoch != currentEpoch) {
      hv_hand_gate_invalidate(&state->gate);
      state->epoch = currentEpoch;
    }
    bool classified = classStatus == HV_HAND_CLASSIFIER_OK && fresh && hand.valid;
    hv_hand_gate_observation_t observation = {
      .captured_ms = captured, .valid = s_classifierReady && fresh,
      .hands = hand.count, .kind = HV_HAND_GATE_UNKNOWN, .score = scores[top], .runner_up = runnerUp};
    if (s_classifierReady && fresh && hand.count == 0) observation.kind = HV_HAND_GATE_NO_HAND;
    if (classified) observation.kind = top == HV_HAND_OPEN_PALM ? HV_HAND_GATE_OPEN_PALM :
                                     top == HV_HAND_CLOSED_FIST ? HV_HAND_GATE_CLOSED_FIST : HV_HAND_GATE_OTHER;
    hv_hand_gate_kind_t previousLatched = state->gate.latched;
    hv_hand_gate_event_t event = hv_hand_gate_observe(&state->gate, observation, now);
    /* A camera fault can occur while the classifier runs. Check the epoch once
     * more while committing the output snapshot; no old result may relight it. */
    if (!feedback_publish(&state->gate, captured, epoch, now)) {
      fresh = classified = false;
      hv_hand_gate_invalidate(&state->gate);
      if (event != HV_HAND_GATE_EVENT_NONE) state->gate.latched = previousLatched;
      event = HV_HAND_GATE_EVENT_NONE;
    }
    bool confirmed = classified && state->gate.visible == state->gate.latched &&
                     (state->gate.visible == HV_HAND_GATE_OPEN_PALM ||
                      state->gate.visible == HV_HAND_GATE_CLOSED_FIST);
    if (event != HV_HAND_GATE_EVENT_NONE) {
      if (event == HV_HAND_GATE_EVENT_OPEN_PALM) ++state->palmCount;
      else ++state->fistCount;
      printf("HG {\"v\":1,\"event\":\"gesture\",\"gesture\":\"%s\","
             "\"captured_ms\":%llu,\"at_ms\":%llu,\"epoch\":%u,"
             "\"classifier_ready\":true,\"palm_count\":%u,\"fist_count\":%u}\n",
             hv_hand_gate_kind_name(state->gate.latched), (unsigned long long)captured,
             (unsigned long long)now, epoch, state->palmCount, state->fistCount);
    }
    /* Keep detector fields unchanged for same-frame JPEG sample collection.
     * gesture/scores are raw classifier output; only the gesture event denotes
     * a completed hold. A detector-only build never assigns either hand class. */
    printf("HG {\"v\":1,\"event\":\"observation\",\"seq\":%u,\"captured_ms\":%llu,"
           "\"age_ms\":%llu,\"epoch\":%u,\"width\":%u,\"height\":%u,\"hands\":%u,"
           "\"box\":[%d,%d,%d,%d],\"detect_score\":%.5f,\"valid\":%s,"
           "\"classifier_ready\":%s,\"gesture\":\"%s\",\"scores\":[%.6f,%.6f,%.6f],"
           "\"classification_valid\":%s,\"classifier_status\":%d,\"confirmed\":%s,"
           "\"gate_visible\":\"%s\",\"gate_latched\":\"%s\",\"candidate_samples\":%u,"
           "\"palm_count\":%u,\"fist_count\":%u,"
           "\"infer_ms\":%u,\"conversion_ms\":%u,\"detect_ms\":%u,\"classifier_ms\":%u}\n",
           ++state->sequence, (unsigned long long)captured,
           (unsigned long long)(now >= captured ? now - captured : 0), epoch,
           width, height, (unsigned)hand.count, hand.box[0], hand.box[1], hand.box[2], hand.box[3],
           (double)hand.score, fresh && hand.valid ? "true" : "false",
           s_classifierReady ? "true" : "false", rawLabel,
           (double)scores[0], (double)scores[1], (double)scores[2],
           classified ? "true" : "false", (int)classStatus, confirmed ? "true" : "false",
           hv_hand_gate_kind_name(state->gate.visible), hv_hand_gate_kind_name(state->gate.latched),
           state->gate.samples, state->palmCount, state->fistCount,
           (unsigned)(now - started), (unsigned)conversionMs, (unsigned)detectMs,
           (unsigned)classifierMs);
    if (now - state->lastMetrics >= 5000) {
      printf("HG {\"v\":1,\"event\":\"metrics\",\"captured\":%u,\"dropped\":%u,"
             "\"internal_free\":%u,\"internal_largest\":%u,\"psram_free\":%u}\n",
             s_captured, s_dropped,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
      state->lastMetrics = now;
    }
}

static void inference_task(void *argument)
{
  (void)argument;
  hand_inference_state_t state;
  inference_state_init(&state);
  for (;;) {
    hand_frame_t *frame;
    if (xQueueReceive(s_pending, &frame, portMAX_DELAY) != pdTRUE) continue;
    process_frame(frame, &state);
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

esp_err_t headvoice_start(void)
{
  s_free = xQueueCreate(RAW_COUNT, sizeof(hand_frame_t *));
  s_pending = xQueueCreate(1, sizeof(hand_frame_t *));
  if (!s_free || !s_pending) return ESP_ERR_NO_MEM;
  for (unsigned i = 0; i < RAW_COUNT; ++i) {
    s_frames[i].data = heap_caps_malloc(RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_frames[i].data) return ESP_ERR_NO_MEM;
    hand_frame_t *frame = &s_frames[i];
    xQueueSend(s_free, &frame, 0);
  }
  /* Keep legacy head-pose fields explicitly ineligible in the RGB report. */
  hv_panel_pose_epoch(0);
  hv_panel_pose(2, 0, 0, 0, false, false, 0, 0);
  esp_err_t ret = classifier_init();
  if (ret != ESP_OK) return ret;
  ret = hv_hand_detect_init();
  if (ret != ESP_OK) return ret;
  esp_log_level_set("yolo11n-pose", ESP_LOG_WARN);
  ret = bsp_camera_early_init();
  if (ret != ESP_OK) return ret;
  if (hv_camera_preview_init() != ESP_OK) ESP_LOGW(TAG, "Camera preview unavailable");
  if (xTaskCreateWithCaps(feedback_task, "hv_hand_feedback", 2048, NULL, 3,
                         NULL, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS)
    return ESP_ERR_NO_MEM;
  if (xTaskCreatePinnedToCoreWithCaps(inference_task, "hv_hand", 16 * 1024, NULL, 3,
                                    NULL, 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS)
    return ESP_ERR_NO_MEM;
  ret = bsp_camera_set_frame_callback(camera_frame);
  if (ret != ESP_OK) return ret;
  printf("HG {\"v\":1,\"event\":\"ready\",\"backend\":\"hand\","
         "\"classifier_ready\":%s,\"model_sha256\":\"%s\",\"servo_control\":false}\n",
         s_classifierReady ? "true" : "false", classifier_hash());
  return bsp_camera_stream_start();
}

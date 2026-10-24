#include "headvoice_app.h"

#include <linux/videodev2.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "agent_app.h"
#include "bsp_camera.h"
#include "bsp_ws2812.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hv_core.h"
#include "hv_settings.h"
#include "qm_audio.h"
#include "qm_audio_control.h"
#include "qm_errno.h"
#include "yolo11_pose.h"

#define RAW_BYTES (240 * 320 * 2)
#define RAW_COUNT 2
#define TAG "headvoice"

typedef struct
{
  uint8_t * data;
  uint64_t capturedMs;
  unsigned epoch;
} hv_frame_t;
typedef struct
{
  hv_observation_t observation;
  unsigned epoch, people;
  uint32_t inferenceMs;
} hv_result_t;
typedef struct
{
  int phrase;
  uint32_t ticket;
  uint64_t confirmedMs;
  unsigned epoch;
} hv_audio_request_t;
typedef struct
{
  uint32_t ticket;
  bool started;
  int result;
  uint64_t confirmedMs, reportedMs;
} hv_audio_notice_t;

static QueueHandle_t s_free, s_pending, s_observations, s_audioRequests, s_audioNotices;
static hv_frame_t s_frames[RAW_COUNT];
static portMUX_TYPE s_guard = portMUX_INITIALIZER_UNLOCKED;
static unsigned s_epoch;
static atomic_uint s_dropped, s_captured;
static bool s_audioFault;
static bool s_ledReady;

#define AUDIO_SYMBOLS(code)                                                       \
  extern const uint8_t hv_##code##_start[] asm("_binary_hv_" #code "_pcm_start"); \
  extern const uint8_t hv_##code##_end[] asm("_binary_hv_" #code "_pcm_end")
AUDIO_SYMBOLS(AA);
AUDIO_SYMBOLS(AB);
AUDIO_SYMBOLS(BA);
AUDIO_SYMBOLS(BB);

static uint64_t now_ms(void) { return (uint64_t)(esp_timer_get_time() / 1000); }

static unsigned epoch(bool invalidate)
{
  portENTER_CRITICAL(&s_guard);
  if (invalidate) ++s_epoch;
  unsigned value = s_epoch;
  portEXIT_CRITICAL(&s_guard);
  return value;
}

/* Runs on the capture task. MMAP storage is borrowed until callback return.
 * The BSP QBUFs every driver buffer immediately after this bounded copy.
 * Only two application raw frames exist: one in inference, one latest pending.
 * Replacing the pending frame returns its slot here; no frame queue can grow. */
static void camera_frame(
  const uint8_t * bytes, size_t length, uint32_t width, uint32_t height, uint32_t format,
  uint64_t capturedMs)
{
  if (
    !bytes || length != RAW_BYTES || width != 240 || height != 320 || format != V4L2_PIX_FMT_UYVY) {
    epoch(true);
    return;
  }
  if (HV_STAGE == 1) {
    ++s_captured;
    return;
  }
  hv_frame_t * frame = NULL;
  if (xQueueReceive(s_free, &frame, 0) != pdTRUE) {
    if (xQueueReceive(s_pending, &frame, 0) != pdTRUE) {
      ++s_dropped;
      return;
    }
    ++s_dropped;
  }
  memcpy(frame->data, bytes, RAW_BYTES);
  frame->capturedMs = capturedMs;
  frame->epoch = epoch(false);
  if (xQueueSend(s_pending, &frame, 0) != pdTRUE) {
    xQueueSend(s_free, &frame, 0);
    epoch(true);
  }
  ++s_captured;
}

static void inference_task(void * argument)
{
  (void)argument;
  for (;;) {
    hv_frame_t * frame;
    if (xQueueReceive(s_pending, &frame, portMAX_DELAY) != pdTRUE) continue;
    hv_result_t result = {0};
    result.epoch = frame->epoch;
    result.observation.capturedMs = frame->capturedMs;
    uint64_t started = now_ms();
    uint8_t * rgb = NULL;
    uint16_t width = 0, height = 0;
    esp_err_t ret;
#if HV_ROTATE_CW90
    ret = yolo11_pose_uyvy_to_rgb888_cw90(
#else
    ret = yolo11_pose_uyvy_to_rgb888(
#endif
      frame->data, RAW_BYTES, 240, 320, &rgb, &width, &height);
    /* RGB is a separate resident model buffer, owned only by this task.
     * Raw input is no longer needed once conversion returns. */
    xQueueSend(s_free, &frame, 0);
    yolo11_pose_frame_result_t pose = {0};
    if (ret == ESP_OK) {
      ret = yolo11_pose_analyze_rgb888(rgb, width, height, "live", &pose);
    }
    result.people = pose.person_count;
    result.observation.valid =
      ret == ESP_OK && pose.person_count == 1 && pose.head_valid &&
      hv_eye_tilt(
        pose.eye_x1, pose.eye_y1, pose.eye_x2, pose.eye_y2, &result.observation.tiltDegrees);
    result.inferenceMs = (uint32_t)(now_ms() - started);
    if (HV_INVERT_TILT) result.observation.tiltDegrees *= -1;
    /* Invalid results must survive mailbox replacement by a later valid frame. */
    if (!result.observation.valid) result.epoch = epoch(true);
    xQueueOverwrite(s_observations, &result);
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

static void send_audio_notice(hv_audio_request_t request, bool started, int result)
{
  hv_audio_notice_t notice = {request.ticket, started, result, request.confirmedMs, now_ms()};
  if (xQueueSend(s_audioNotices, &notice, 0) != pdTRUE) {
    portENTER_CRITICAL(&s_guard);
    s_audioFault = true;
    portEXIT_CRITICAL(&s_guard);
  }
}

static void audio_task(void * argument)
{
  (void)argument;
  static const uint8_t * const AUDIO_START[] = {hv_AA_start, hv_AB_start, hv_BA_start, hv_BB_start};
  static const uint8_t * const AUDIO_END[] = {hv_AA_end, hv_AB_end, hv_BA_end, hv_BB_end};
  qm_audio_control_t * control = NULL;
  int initialized = qm_audio_control_create(&control);
  for (;;) {
    hv_audio_request_t request;
    xQueueReceive(s_audioRequests, &request, portMAX_DELAY);
    int ret = initialized;
    if (
      ret != QM_EOK || request.phrase < 0 || request.phrase >= 4 || request.epoch != epoch(false) ||
      now_ms() - request.confirmedMs > 1000) {
      send_audio_notice(request, false, ret == QM_EOK ? -QM_ETIMEOUT : ret);
      continue;
    }
    /* End an active dialog only after expression confirmation. Wi-Fi/MQTT
     * remain connected; a later wake word can start the official agent again.
     * A resource mode alone only gates upload and cannot exclude agent TTS. */
    if (agent_app_is_active()) ret = agent_app_leave();
    if (ret == QM_EOK) ret = agent_app_set_resource_mode(QM_TRUE);
    qm_audio_operation_id_t operation = 0;
    if (ret == QM_EOK && request.epoch != epoch(false)) ret = -QM_EINTR;
    if (ret == QM_EOK) {
      qm_audio_control_play_request_t play = {0};
      play.source.type = QM_AUDIO_SOURCE_MEMORY;
      play.source.value.memory.data = AUDIO_START[request.phrase];
      play.source.value.memory.size = AUDIO_END[request.phrase] - AUDIO_START[request.phrase];
      play.codec.codec = QM_AUDIO_CODEC_PCM;
      play.codec.framing = QM_AUDIO_CODEC_FRAMING_STREAM;
      play.codec.pcm.sample_rate_hz = 16000;
      play.codec.pcm.channels = 1;
      play.codec.pcm.sample = QM_AUDIO_PCM_S16;
      play.priority = QM_AUDIO_PRIORITY_NORMAL;
      play.admission = QM_AUDIO_ADMISSION_REJECT_IF_BUSY;
      ret = qm_audio_control_play(control, &play, &operation);
    }
    bool reportedStart = false;
    bool terminal = false;
    uint64_t deadline = now_ms() + 15000;
    while (ret == QM_EOK && !terminal && now_ms() < deadline) {
      qm_audio_control_snapshot_t snapshot;
      ret = qm_audio_control_get_snapshot(control, operation, &snapshot);
      if (ret != QM_EOK) break;
      if (
        !reportedStart && (snapshot.state == QM_AUDIO_CONTROL_PLAYING ||
                           snapshot.state == QM_AUDIO_CONTROL_DRAINING)) {
        reportedStart = true;
        send_audio_notice(request, true, QM_EOK);
      }
      if (snapshot.state >= QM_AUDIO_CONTROL_FINISHED) {
        terminal = true;
        ret = snapshot.state == QM_AUDIO_CONTROL_FINISHED ? QM_EOK : -QM_EIO;
      }
      if (!terminal) vTaskDelay(pdMS_TO_TICKS(20));
    }
    if (operation) {
      if (!terminal) {
        qm_audio_control_stop(control, operation, 1000);
        ret = -QM_ETIMEOUT;
      }
      int released = qm_audio_control_release(control, operation, 1000);
      if (released != QM_EOK) {
        /* Unknown speaker ownership is fail-closed. Require a reboot. */
        ESP_LOGE(TAG, "audio release failed=%d; reboot required", released);
        for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
      }
    }
    agent_app_set_resource_mode(QM_FALSE);
    send_audio_notice(request, false, ret);
  }
}

static void set_light(HvState state, bool blue)
{
  if (!s_ledReady) return;
  uint8_t r = 0, g = 0, b = 0;
  if (blue)
    b = 32;
  else if (state == HV_REVIEW_REARM || state == HV_REVIEW)
    r = g = 24;
  else if (state == HV_CALIBRATING)
    r = g = b = 8;
  bsp_ws2812_fill(r, g, b);
}

static void core_task(void * argument)
{
  (void)argument;
  hv_core_t core;
  hv_init(&core, NULL);
  unsigned seenEpoch = epoch(false), valid = 0, inferred = 0;
  uint32_t inferTotal = 0, inferMax = 0;
  uint64_t logStart = now_ms();
  bool blue = false;
  bool oldBlue = false;
  HvState oldState = HV_SPEAKING;
  ESP_LOGI(TAG, "HV stage=%d; stage 3 calibrates a comfortable neutral posture", HV_STAGE);
  for (;;) {
    uint64_t now = now_ms();
    unsigned currentEpoch = epoch(false);
    if (currentEpoch != seenEpoch) {
      hv_invalidate(&core, now);
      seenEpoch = currentEpoch;
      ESP_LOGW(TAG, "HV reset reason=invalid_frame_or_pose epoch=%u", currentEpoch);
    }
    hv_effect_t out = hv_tick(&core, now);
    hv_result_t result;
    if (xQueueReceive(s_observations, &result, 0) == pdTRUE) {
      inferred++;
      inferTotal += result.inferenceMs;
      if (result.inferenceMs > inferMax) inferMax = result.inferenceMs;
      bool fresh = result.epoch == seenEpoch && result.observation.valid &&
                   now >= result.observation.capturedMs &&
                   now - result.observation.capturedMs <= core.config.maxAgeMs;
      valid += fresh;
      printf(
        "HV {\"event\":\"pose\",\"captured_ms\":%llu,\"age_ms\":%llu,"
        "\"tilt\":%.2f,\"people\":%u,\"valid\":%s,\"infer_ms\":%u}\n",
        (unsigned long long)result.observation.capturedMs,
        (unsigned long long)(now >= result.observation.capturedMs
                               ? now - result.observation.capturedMs
                               : 0),
        result.observation.tiltDegrees, result.people, fresh ? "true" : "false",
        (unsigned)result.inferenceMs);
      if (fresh && HV_STAGE == 3)
        out = hv_observe(&core, result.observation, now);
      else
        out = hv_invalidate(&core, now);
    }
    if ((out.event == HV_PLAY || out.event == HV_CANDIDATE) && epoch(false) != seenEpoch) {
      out = hv_invalidate(&core, now);
      if (core.state == HV_SPEAKING) hv_playback_done(&core, core.ticket, now);
    }
    if (out.event == HV_CANDIDATE) {
      printf(
        "HV {\"event\":\"candidate\",\"code\":\"%s\",\"text\":\"%s\",\"at_ms\":%llu}\n",
        hv_code(out.phrase), hv_phrase(out.phrase), (unsigned long long)now);
      fflush(stdout);
    } else if (out.event == HV_PLAY) {
      hv_audio_request_t request = {out.phrase, out.ticket, now, seenEpoch};
      if (xQueueSend(s_audioRequests, &request, 0) != pdTRUE) {
        hv_playback_done(&core, out.ticket, now);
        ESP_LOGE(TAG, "audio queue full; expression discarded");
      }
    } else if (out.event != HV_NONE) {
      ESP_LOGI(
        TAG, "HV event=%d state=%d action=%c baseline=%.2f", out.event, core.state,
        out.action ? out.action : '-', core.baseline);
    }
    hv_audio_notice_t notice;
    while (xQueueReceive(s_audioNotices, &notice, 0) == pdTRUE) {
      if (core.state != HV_SPEAKING || notice.ticket != core.ticket) continue;
      if (notice.started)
        blue = true;
      else {
        blue = false;
        hv_playback_done(&core, notice.ticket, now);
      }
      printf(
        "HV {\"event\":\"audio_%s\",\"ticket\":%u,\"result\":%d,\"confirm_to_report_ms\":%llu}\n",
        notice.started ? "started_estimate" : "done", (unsigned)notice.ticket, notice.result,
        (unsigned long long)(notice.reportedMs - notice.confirmedMs));
    }
    portENTER_CRITICAL(&s_guard);
    bool audioFault = s_audioFault;
    portEXIT_CRITICAL(&s_guard);
    if (audioFault) {
      ESP_LOGE(TAG, "audio notice overflow; reboot required");
      for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (oldState != core.state || oldBlue != blue) {
      set_light(core.state, blue);
      oldState = core.state;
      oldBlue = blue;
    }
    if (now - logStart >= 5000) {
      printf(
        "HV {\"event\":\"metrics\",\"window_ms\":%llu,\"valid_hz\":%.2f,\"inferred\":%u,"
        "\"infer_mean_ms\":%u,\"infer_max_ms\":%u,\"captured\":%u,\"dropped\":%u,"
        "\"internal_free\":%u,\"internal_largest\":%u,\"psram_free\":%u}\n",
        (unsigned long long)(now - logStart), valid * 1000.0 / (now - logStart), inferred,
        (unsigned)(inferred ? inferTotal / inferred : 0), (unsigned)inferMax, s_captured, s_dropped,
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
      logStart = now;
      valid = inferred = inferTotal = inferMax = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

esp_err_t headvoice_start(void)
{
  s_free = xQueueCreate(RAW_COUNT, sizeof(hv_frame_t *));
  s_pending = xQueueCreate(1, sizeof(hv_frame_t *));
  s_observations = xQueueCreate(1, sizeof(hv_result_t));
  s_audioRequests = xQueueCreate(1, sizeof(hv_audio_request_t));
  s_audioNotices = xQueueCreate(4, sizeof(hv_audio_notice_t));
  if (!s_free || !s_pending || !s_observations || !s_audioRequests || !s_audioNotices)
    return ESP_ERR_NO_MEM;
  for (int i = 0; i < RAW_COUNT; ++i) {
    s_frames[i].data = heap_caps_malloc(RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_frames[i].data) return ESP_ERR_NO_MEM;
    hv_frame_t * frame = &s_frames[i];
    xQueueSend(s_free, &frame, 0);
  }
  /* Model initialization is deferred until the official voice/cloud startup. */
  esp_err_t ret = HV_STAGE >= 2 ? yolo11_pose_init() : ESP_OK;
  if (ret != ESP_OK) return ret;
  esp_log_level_set("yolo11n-pose", ESP_LOG_WARN);
  s_ledReady = bsp_ws2812_init() == QM_EOK;
  if (!s_ledReady) ESP_LOGW(TAG, "RGB unavailable");
  ret = bsp_camera_early_init();
  if (ret != ESP_OK) return ret;
  if (
    (HV_STAGE >= 2 && xTaskCreatePinnedToCoreWithCaps(
                        inference_task, "hv_infer", 16 * 1024, NULL, 3, NULL, 1,
                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS) ||
    (HV_STAGE == 3 && xTaskCreateWithCaps(
                        audio_task, "hv_audio", 12 * 1024, NULL, 5, NULL,
                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS) ||
    xTaskCreateWithCaps(
      core_task, "hv_core", 6 * 1024, NULL, 5, NULL, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS)
    return ESP_ERR_NO_MEM;
  ret = bsp_camera_set_frame_callback(camera_frame);
  if (ret != ESP_OK) return ret;
  return bsp_camera_stream_start();
}

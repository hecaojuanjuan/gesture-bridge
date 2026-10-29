#include <linux/videodev2.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsp_camera.h"
#include "driver/ledc.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "headvoice_app.h"
#include "hv_camera_preview.h"
#include "hv_gimbal_core.h"
#include "hv_settings.h"
#include "qm_cli.h"
#include "yolo11_pose.h"

#define RAW_BYTES (240 * 320 * 2)
static const int PINS[2] = {17, 18};
static uint8_t * s_raw;
static atomic_int s_frameState;
static uint64_t s_capturedMs;
static SemaphoreHandle_t s_lock;
static hv_gimbal_t s_core;
static bool s_armed[2], s_directionsReady, s_probe;

static uint64_t now_ms(void) { return esp_timer_get_time() / 1000; }
static void lock(void) { xSemaphoreTake(s_lock, portMAX_DELAY); }
static void unlock(void) { xSemaphoreGive(s_lock); }

static void stop_locked(void)
{
  s_core.active = s_probe = false;
  for (int i = 0; i < 2; ++i) {
    ledc_stop(LEDC_LOW_SPEED_MODE, (ledc_channel_t)i, 0);
    s_armed[i] = false;
  }
}

static bool write_pulse(int axis)
{
  uint32_t duty = (uint32_t)s_core.pulse[axis] * ((1u << 14) - 1) / 20000;
  if (
    ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, duty) != ESP_OK ||
    ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis) != ESP_OK) {
    stop_locked();
    printf("GIMBAL ERROR pwm_write\n");
    return false;
  }
  return true;
}

static void status_locked(void)
{
  printf(
    "GIMBAL {\"event\":\"status\",\"active\":%s,\"pan_us\":%d,\"tilt_us\":%d,"
    "\"pan_armed\":%s,\"tilt_armed\":%s,\"pan_dir\":%d,\"tilt_dir\":%d,"
    "\"directions_ready\":%s,\"steps\":%u}\n",
    s_core.active ? "true" : "false", s_core.pulse[0], s_core.pulse[1],
    s_armed[0] ? "true" : "false", s_armed[1] ? "true" : "false", s_core.direction[0],
    s_core.direction[1], s_directionsReady ? "true" : "false", s_core.steps);
}

static bool number(const char * text, int low, int high, int * out)
{
  char * end;
  long value = strtol(text, &end, 10);
  if (!*text || *end || value < low || value > high) return false;
  *out = (int)value;
  return true;
}

static void command(char * buffer, int length, int argc, char ** argv)
{
  (void)buffer;
  (void)length;
  lock();
  if (argc == 2 && strcmp(argv[1], "stop") == 0) {
    stop_locked();
  } else if (argc == 2 && strcmp(argv[1], "status") == 0) {
    /* Status never changes PWM output. */
  } else if (argc == 2 && strcmp(argv[1], "probe") == 0 && !s_core.active) {
    s_probe = true;
  } else if (argc == 2 && strcmp(argv[1], "start") == 0) {
    if (!s_armed[0] || !s_armed[1] || !s_directionsReady) {
      printf("GIMBAL ERROR arm_both_axes_and_verify_directions_first\n");
    } else {
      hv_gimbal_begin(&s_core, now_ms());
    }
  } else if (argc == 3 && strcmp(argv[1], "arm") == 0 && !s_core.active && !s_probe) {
    int axis = strcmp(argv[2], "pan") == 0 ? 0 : strcmp(argv[2], "tilt") == 0 ? 1 : -1;
    if (axis >= 0) {
      s_core.pulse[axis] = 1500;
      s_armed[axis] = true;
      write_pulse(axis);
      s_core.acceptAfterMs = now_ms() + 600;
    }
  } else if (argc == 4 && strcmp(argv[1], "jog") == 0 && !s_core.active && !s_probe) {
    int axis = strcmp(argv[2], "pan") == 0 ? 0 : strcmp(argv[2], "tilt") == 0 ? 1 : -1;
    int delta;
    if (
      axis >= 0 && s_armed[axis] && number(argv[3], -50, 50, &delta) &&
      s_core.pulse[axis] + delta >= 1300 && s_core.pulse[axis] + delta <= 1700) {
      s_core.pulse[axis] += delta;
      write_pulse(axis);
      s_core.acceptAfterMs = now_ms() + 600;
    } else
      printf("GIMBAL ERROR jog_requires_armed_axis_and_safe_range\n");
  } else if (argc == 4 && strcmp(argv[1], "dir") == 0 && !s_core.active && !s_probe) {
    int pan, tilt;
    if (number(argv[2], -1, 1, &pan) && number(argv[3], -1, 1, &tilt) && pan && tilt) {
      s_core.direction[0] = pan;
      s_core.direction[1] = tilt;
      s_directionsReady = true;
    } else
      printf("GIMBAL ERROR directions_must_be_plus_or_minus_one\n");
  } else {
    printf(
      "hv_gimbal status|probe|arm pan|arm tilt|jog pan <us>|jog tilt <us>|dir <pan_sign> "
      "<tilt_sign>|start|stop\n");
  }
  status_locked();
  unlock();
}

static void camera_frame(
  const uint8_t * data, size_t length, uint32_t width, uint32_t height, uint32_t format,
  uint64_t capturedMs)
{
  if (!data || length != RAW_BYTES || width != 240 || height != 320 || format != V4L2_PIX_FMT_UYVY)
    return;
  hv_camera_preview_offer(data, length, capturedMs);
  int expected = 1;
  if (atomic_compare_exchange_strong(&s_frameState, &expected, 2)) {
    memcpy(s_raw, data, RAW_BYTES);
    s_capturedMs = capturedMs;
    atomic_store(&s_frameState, 3);
  }
}

static void control_task(void * argument)
{
  (void)argument;
  for (;;) {
    lock();
    bool work = s_probe || s_core.active;
    if (s_core.active && now_ms() >= s_core.deadlineMs) {
      s_core.active = false;
      printf("GIMBAL STOP timeout\n");
      work = false;
    }
    uint64_t after = s_core.acceptAfterMs + 150;
    unlock();
    if (!work || now_ms() <= after) {
      vTaskDelay(pdMS_TO_TICKS(30));
      continue;
    }
    atomic_store(&s_frameState, 1);
    uint64_t waitUntil = now_ms() + 2500;
    while (atomic_load(&s_frameState) != 3 && now_ms() < waitUntil) vTaskDelay(pdMS_TO_TICKS(10));
    int expected = 1;
    if (atomic_compare_exchange_strong(&s_frameState, &expected, 0)) {
      lock();
      s_core.active = s_probe = false;
      unlock();
      printf("GIMBAL STOP no_camera_frame\n");
      continue;
    }
    while (atomic_load(&s_frameState) == 2) vTaskDelay(1);
    if (atomic_load(&s_frameState) != 3) continue;
    uint64_t captured = s_capturedMs, started = now_ms();
    uint8_t * rgb = NULL;
    uint16_t width = 0, height = 0;
#if HV_ROTATE_CW90
    esp_err_t ret =
      yolo11_pose_uyvy_to_rgb888_cw90(s_raw, RAW_BYTES, 240, 320, &rgb, &width, &height);
#else
    esp_err_t ret = yolo11_pose_uyvy_to_rgb888(s_raw, RAW_BYTES, 240, 320, &rgb, &width, &height);
#endif
    atomic_store(&s_frameState, 0);
    yolo11_pose_frame_result_t pose = {0};
    if (ret == ESP_OK) ret = yolo11_pose_analyze_rgb888(rgb, width, height, "gimbal", &pose);
    bool face = ret == ESP_OK && pose.person_count == 1 && pose.head_valid;
    float x = 0, y = 0;
    if (face && width && height) {
      x = (pose.eye_x1 + pose.eye_x2) * 0.5f / width;
      y = (pose.eye_y1 + pose.eye_y2) * 0.5f / height;
    }
    lock();
    s_probe = false;
    int before[2] = {s_core.pulse[0], s_core.pulse[1]};
    HvGimbalResult result =
      hv_gimbal_observe(&s_core, pose.person_count, face, x, y, captured, now_ms());
    if (result == HV_GIMBAL_MOVE) {
      for (int axis = 0; axis < 2; ++axis)
        if (before[axis] != s_core.pulse[axis]) write_pulse(axis);
      s_core.acceptAfterMs = now_ms() + 450;
    }
    printf(
      "GIMBAL {\"event\":\"observation\",\"people\":%u,\"face\":%s,"
      "\"x\":%.4f,\"y\":%.4f,\"captured_ms\":%u,\"infer_ms\":%u,"
      "\"result\":%d,\"pan_us\":%d,\"tilt_us\":%d,\"active\":%s}\n",
      pose.person_count, face ? "true" : "false", x, y, (unsigned)captured,
      (unsigned)(now_ms() - started), result, s_core.pulse[0], s_core.pulse[1],
      s_core.active ? "true" : "false");
    if (result == HV_GIMBAL_STALE) s_core.acceptAfterMs = now_ms() + 150;
    unlock();
    vTaskDelay(pdMS_TO_TICKS(30));
  }
}

esp_err_t headvoice_start(void)
{
  hv_gimbal_reset(&s_core);
  s_lock = xSemaphoreCreateMutex();
  s_raw = heap_caps_malloc(RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!s_lock || !s_raw) return ESP_ERR_NO_MEM;
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .duty_resolution = LEDC_TIMER_14_BIT,
    .timer_num = LEDC_TIMER_0,
    .freq_hz = 50,
    .clk_cfg = LEDC_AUTO_CLK};
  ESP_ERROR_CHECK(ledc_timer_config(&timer));
  for (int axis = 0; axis < 2; ++axis) {
    ledc_channel_config_t channel = {
      .gpio_num = PINS[axis],
      .speed_mode = LEDC_LOW_SPEED_MODE,
      .channel = (ledc_channel_t)axis,
      .intr_type = LEDC_INTR_DISABLE,
      .timer_sel = LEDC_TIMER_0,
      .duty = 0,
      .hpoint = 0};
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
  }
  esp_err_t ret = bsp_camera_early_init();
  if (ret != ESP_OK) return ret;
  ret = hv_camera_preview_init();
  if (ret != ESP_OK) return ret;
  if (xTaskCreatePinnedToCore(control_task, "hv_gimbal", 16384, NULL, 3, NULL, 1) != pdPASS)
    return ESP_ERR_NO_MEM;
  static const struct qm_cli_command cli = {
    .name = "hv_gimbal",
    .help = "status|probe|arm <axis>|jog <axis> <us>|dir <pan> <tilt>|start|stop",
    .function = command};
  if (qm_cli_register_command(&cli) != 0) return ESP_FAIL;
  ret = bsp_camera_set_frame_callback(camera_frame);
  if (ret != ESP_OK) return ret;
  printf("GIMBAL ready pan=17 tilt=18 PWM=off limits=1300..1700us\n");
  return bsp_camera_stream_start();
}

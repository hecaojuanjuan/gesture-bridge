#include "hv_face_gimbal.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "hv_gimbal_core.h"
#include "qm_cli.h"

/* This first mounted test stays within the user-observed small P18 motion.
 * These are pulse widths, not mechanically calibrated angles. */
enum {
  PULSE_MIN_US = 1475,
  PULSE_MID_US = 1500,
  PULSE_MAX_US = 1525,
  MAX_STEP_US = 25,
  MAX_FRAME_AGE_MS = 400,
#if HV_CENTERING
  LOST_TARGET_MS = 2000,
#else
  LOST_TARGET_MS = 1000,
#endif
  IDLE_ARM_LEASE_MS = 10000,
  CENTERED_HOLD_LEASE_MS = 60000,
};
static const int PINS[2] = {17, 18};
static SemaphoreHandle_t s_lock;
static hv_gimbal_t s_core;
static bool s_armed[2], s_directionsReady, s_initialized, s_outputFault, s_centeredHolding;
static uint64_t s_lastAcceptedMs, s_leaseUntilMs;
static const char *s_lastStopReason = "none";
static bool s_targetValid;
static unsigned s_targetPeople;
static float s_targetX, s_targetY;
static uint64_t s_targetCapturedMs;
static HvGimbalTarget s_targetSource;
static bool s_autoEnabled;
static unsigned s_acquireCount;
static uint64_t s_acquireCapturedMs;

static uint64_t now_ms(void) { return (uint64_t)(esp_timer_get_time() / 1000); }
static void lock(void) { xSemaphoreTake(s_lock, portMAX_DELAY); }
static void unlock(void) { xSemaphoreGive(s_lock); }

static void status_locked(void)
{
  uint64_t now = now_ms();
  uint64_t lease = s_leaseUntilMs > now ? s_leaseUntilMs - now : 0;
  printf("GIMBAL {\"event\":\"status\",\"active\":%s,\"pan_us\":%d,\"tilt_us\":%d,"
         "\"pan_armed\":%s,\"tilt_armed\":%s,\"pan_dir\":%d,\"tilt_dir\":%d,"
         "\"directions_ready\":%s,\"holding\":%s,\"output_fault\":%s,"
         "\"lease_remaining_ms\":%llu,\"last_stop_reason\":\"%s\",\"steps\":%u,"
         "\"auto_enabled\":%s,\"limits_us\":[%d,%d],"
         "\"max_step_us\":%d,\"max_age_ms\":%d,\"lost_after_ms\":%d}\n",
         s_core.active ? "true" : "false", s_core.pulse[0], s_core.pulse[1],
         s_armed[0] ? "true" : "false", s_armed[1] ? "true" : "false",
         s_core.direction[0], s_core.direction[1], s_directionsReady ? "true" : "false",
         s_centeredHolding ? "true" : "false", s_outputFault ? "true" : "false",
         (unsigned long long)lease, s_lastStopReason, s_core.steps,
         s_autoEnabled ? "true" : "false",
         PULSE_MIN_US, PULSE_MAX_US, MAX_STEP_US, MAX_FRAME_AGE_MS,
         LOST_TARGET_MS);
}

static bool target_fresh_locked(uint64_t now)
{
  return s_targetValid && s_targetPeople == 1 &&
         s_targetCapturedMs > s_core.acceptAfterMs &&
         now >= s_targetCapturedMs && now - s_targetCapturedMs <= MAX_FRAME_AGE_MS;
}

static void target_locked(void)
{
  uint64_t now = now_ms();
  uint64_t age = s_targetCapturedMs && now >= s_targetCapturedMs ? now - s_targetCapturedMs : 0;
  bool valid = target_fresh_locked(now);
  printf("GIMBAL {\"event\":\"target\",\"valid\":%s,\"people\":%u,"
         "\"source\":\"%s\",\"x\":%.4f,\"y\":%.4f,\"captured_ms\":%llu,\"age_ms\":%llu}\n",
         valid ? "true" : "false", s_targetPeople,
         s_targetSource == HV_GIMBAL_TARGET_HAND ? "hand" : "face",
         valid ? (double)s_targetX : 0.0, valid ? (double)s_targetY : 0.0,
         (unsigned long long)s_targetCapturedMs, (unsigned long long)age);
}

static void close_outputs_locked(const char *reason, bool unexpected)
{
  s_autoEnabled = false;
  s_acquireCount = 0;
  s_acquireCapturedMs = 0;
  s_core.active = false;
  s_centeredHolding = false;
  s_leaseUntilMs = 0;
  s_lastStopReason = reason ? reason : "unspecified";
  for (int axis = 0; axis < 2; ++axis) {
    esp_err_t stopped = ledc_stop(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, 0);
    if (stopped != ESP_OK) {
      esp_err_t fallback = ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, 0);
      if (fallback == ESP_OK)
        fallback = ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis);
      s_outputFault = true;
      printf("GIMBAL ERROR pwm_stop_failed axis=%d ret=%d zero_duty_ret=%d reboot_required\n",
             axis, stopped, fallback);
    }
    s_armed[axis] = false;
  }
  s_directionsReady = false;
  if (reason) {
    if (unexpected)
      printf("GIMBAL STOP %s\n", reason);
    else
      printf("GIMBAL {\"event\":\"stopped\",\"reason\":\"%s\"}\n", reason);
  }
}

static bool write_pulse_locked(int axis)
{
  uint32_t duty = (uint32_t)s_core.pulse[axis] * ((1u << 14) - 1) / 20000;
  if (ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, duty) != ESP_OK ||
      ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis) != ESP_OK) {
    close_outputs_locked("pwm_write_failed", true);
    return false;
  }
  return true;
}

static bool number(const char *text, int low, int high, int *out)
{
  char *end;
  long value = strtol(text, &end, 10);
  if (!*text || *end || value < low || value > high) return false;
  *out = (int)value;
  return true;
}

static int axis_name(const char *text)
{
  if (strcmp(text, "pan") == 0) return 0;
  if (strcmp(text, "tilt") == 0) return 1;
  return -1;
}

static void tick_locked(uint64_t nowMs);

static void command(char *buffer, int length, int argc, char **argv)
{
  (void)buffer;
  (void)length;
  if (!s_initialized) return;
  lock();
  tick_locked(now_ms());
  if (s_outputFault && !(argc == 2 &&
      (strcmp(argv[1], "status") == 0 || strcmp(argv[1], "target") == 0 ||
       strcmp(argv[1], "stop") == 0))) {
    printf("GIMBAL ERROR output_fault_reboot_required\n");
    status_locked();
    unlock();
    return;
  }
  if (argc == 2 && strcmp(argv[1], "status") == 0) {
    /* A status query never changes the output. */
  } else if (argc == 2 && strcmp(argv[1], "target") == 0) {
    target_locked();
  } else if (argc == 2 && strcmp(argv[1], "stop") == 0) {
    close_outputs_locked("operator", false);
  } else if (argc == 3 && strcmp(argv[1], "auto") == 0 &&
             strcmp(argv[2], "off") == 0) {
    close_outputs_locked("operator", false);
  } else if (argc == 3 && strcmp(argv[1], "auto") == 0 &&
             strcmp(argv[2], "on") == 0) {
    if (!s_armed[0] || !s_armed[1] || !s_directionsReady) {
      printf("GIMBAL ERROR arm_both_axes_and_verify_directions_first\n");
    } else {
      s_autoEnabled = true;
      s_acquireCount = 0;
      s_acquireCapturedMs = 0;
      s_lastAcceptedMs = now_ms();
      s_leaseUntilMs = 0;
      printf("GIMBAL {\"event\":\"auto_enabled\"}\n");
    }
  } else if (argc == 3 && strcmp(argv[1], "arm") == 0 && !s_core.active && !s_autoEnabled) {
    int axis = axis_name(argv[2]);
    if (axis < 0) {
      printf("GIMBAL ERROR arm_requires_pan_or_tilt\n");
    } else {
      s_core.pulse[axis] = PULSE_MID_US;
      s_directionsReady = false;
      if (write_pulse_locked(axis)) {
        s_armed[axis] = true;
        s_centeredHolding = false;
        uint64_t now = now_ms();
        s_core.acceptAfterMs = now + 450;
        s_leaseUntilMs = now + IDLE_ARM_LEASE_MS;
        s_lastStopReason = "none";
      }
    }
  } else if (argc == 4 && strcmp(argv[1], "jog") == 0 && !s_core.active && !s_autoEnabled) {
    int axis = axis_name(argv[2]);
    int delta;
    if (axis < 0 || !s_armed[axis] || !number(argv[3], -MAX_STEP_US, MAX_STEP_US, &delta) ||
        !delta || s_core.pulse[axis] + delta < PULSE_MIN_US ||
        s_core.pulse[axis] + delta > PULSE_MAX_US) {
      printf("GIMBAL ERROR jog_requires_armed_axis_and_1475_to_1525us\n");
    } else {
      s_core.pulse[axis] += delta;
      s_directionsReady = false;
      if (write_pulse_locked(axis)) {
        uint64_t now = now_ms();
        s_core.acceptAfterMs = now + 450;
        s_leaseUntilMs = now + IDLE_ARM_LEASE_MS;
      }
    }
  } else if (argc == 4 && strcmp(argv[1], "dir") == 0 && !s_core.active && !s_autoEnabled) {
    int pan, tilt;
    if (number(argv[2], -1, 1, &pan) && number(argv[3], -1, 1, &tilt) && pan && tilt &&
        s_armed[0] && s_armed[1]) {
      s_core.direction[0] = pan;
      s_core.direction[1] = tilt;
      s_directionsReady = true;
      s_leaseUntilMs = now_ms() + IDLE_ARM_LEASE_MS;
    } else {
      printf("GIMBAL ERROR dir_requires_armed_axes_and_two_verified_signs\n");
    }
  } else if (argc == 2 && strcmp(argv[1], "start") == 0) {
    if (s_core.active || !s_armed[0] || !s_armed[1] || !s_directionsReady) {
      printf("GIMBAL ERROR arm_both_axes_and_verify_directions_first\n");
    } else {
      uint64_t now = now_ms();
      if (!target_fresh_locked(now)) {
        printf("GIMBAL ERROR fresh_single_face_target_required\n");
      } else {
        hv_gimbal_begin(&s_core, now);
        s_lastAcceptedMs = now;
        s_leaseUntilMs = 0;
        s_centeredHolding = false;
        printf("GIMBAL {\"event\":\"started\",\"deadline_ms\":%llu,"
               "\"lost_after_ms\":%d}\n", (unsigned long long)s_core.deadlineMs,
               LOST_TARGET_MS);
      }
    }
  } else {
    printf("hv_gimbal status|target|arm pan|arm tilt|jog pan <signed_us>|jog tilt <signed_us>|"
           "dir <pan_sign> <tilt_sign>|start|auto on|auto off|stop\n");
  }
  status_locked();
  unlock();
}

static const struct qm_cli_command s_cli = {
  .name = "hv_gimbal",
  .help = "status|target|arm <axis>|jog <axis> <signed_us>|dir <pan> <tilt>|start|auto on|auto off|stop",
  .function = command};

static void tick_locked(uint64_t nowMs)
{
  if (s_autoEnabled && nowMs >= s_lastAcceptedMs &&
      nowMs - s_lastAcceptedMs > LOST_TARGET_MS && (s_armed[0] || s_armed[1])) {
    /* Normal loss releases PWM; reacquisition may resume at the last pulse.
     * Faults, limits, camera invalidation and stop disable automatic retries. */
    close_outputs_locked("auto_waiting_target", false);
    if (!s_outputFault) {
      s_autoEnabled = true;
      s_directionsReady = true;
    }
  }
  if (!s_core.active) {
    if ((s_armed[0] || s_armed[1]) && s_leaseUntilMs && nowMs >= s_leaseUntilMs)
      close_outputs_locked(s_centeredHolding ? "centered_hold_expired" :
                           "idle_arm_lease_expired", true);
    return;
  }
  if (nowMs < s_lastAcceptedMs) {
    close_outputs_locked("clock_reversed", true);
  } else if (nowMs >= s_core.deadlineMs) {
    close_outputs_locked("timeout", true);
  } else if (nowMs - s_lastAcceptedMs > LOST_TARGET_MS) {
    close_outputs_locked("lost_target_or_frame", true);
  }
}

bool hv_face_gimbal_active(void)
{
  if (!s_initialized) return false;
  lock();
  bool active = s_core.active;
  unlock();
  return active;
}

void hv_face_gimbal_tick(uint64_t nowMs)
{
  if (!s_initialized) return;
  lock();
  tick_locked(nowMs);
  unlock();
}

static void clear_target_locked(void)
{
  s_acquireCount = 0;
  s_acquireCapturedMs = 0;
  s_targetValid = false;
  s_targetPeople = 0;
  s_targetX = s_targetY = 0;
  s_targetCapturedMs = 0;
}

void hv_face_gimbal_clear_target(void)
{
  if (!s_initialized) return;
  lock();
  clear_target_locked();
  unlock();
}

void hv_face_gimbal_invalidate(void)
{
  if (!s_initialized) return;
  lock();
  clear_target_locked();
  if (s_core.active || s_armed[0] || s_armed[1] || s_autoEnabled)
    close_outputs_locked("stream_invalidated", true);
  unlock();
}

void hv_face_gimbal_observe(unsigned people, bool faceValid, float x, float y,
                            uint64_t capturedMs, uint64_t nowMs)
{
  hv_face_gimbal_observe_target(HV_GIMBAL_TARGET_FACE, people, faceValid,
                                x, y, capturedMs, nowMs);
}

void hv_face_gimbal_observe_target(HvGimbalTarget source, unsigned people, bool faceValid,
                                  float x, float y, uint64_t capturedMs, uint64_t nowMs)
{
  if (!s_initialized) return;
  lock();
  bool sourceChanged = source != s_targetSource;
  s_targetSource = source;
  if (sourceChanged) {
    s_acquireCount = 0;
    s_core.previousAxis = -1;
    s_core.centered = s_core.worsening = 0;
  }
  bool face = people == 1 && faceValid && isfinite(x) && isfinite(y) &&
              x >= 0 && x <= 1 && y >= 0 && y <= 1;
  s_targetPeople = people;
  s_targetCapturedMs = capturedMs;
  s_targetValid = face && capturedMs > s_core.acceptAfterMs && capturedMs <= nowMs &&
                  nowMs - capturedMs <= MAX_FRAME_AGE_MS;
  if (s_targetValid) {
    s_targetX = x;
    s_targetY = y;
  }
  tick_locked(nowMs);
  if (s_autoEnabled && s_targetValid && capturedMs > s_acquireCapturedMs) {
    s_acquireCapturedMs = capturedMs;
    s_lastAcceptedMs = nowMs;
    if (s_acquireCount < 3) ++s_acquireCount;
    bool outside = fabsf(x - 0.5f) > 0.12f || fabsf(y - 0.5f) > 0.12f;
    if (!s_core.active && s_acquireCount >= 3 &&
        (!s_centeredHolding || sourceChanged || outside)) {
      bool ready = true;
      for (int axis = 0; axis < 2 && ready; ++axis) {
        if (!s_armed[axis]) {
          ready = write_pulse_locked(axis);
          if (ready) s_armed[axis] = true;
        }
      }
      if (ready) {
        hv_gimbal_begin(&s_core, nowMs);
        s_centeredHolding = false;
        s_leaseUntilMs = 0;
        s_lastStopReason = "none";
        printf("GIMBAL {\"event\":\"auto_started\",\"source\":\"%s\"}\n",
               source == HV_GIMBAL_TARGET_HAND ? "hand" : "face");
      }
    }
  } else if (!s_targetValid) {
    s_acquireCount = 0;
    s_core.centered = 0;
  }
  if (!s_core.active) {
    unlock();
    return;
  }
  HvGimbalResult result = HV_GIMBAL_WAIT;
  if (face && capturedMs > s_core.acceptAfterMs && capturedMs <= nowMs &&
      nowMs - capturedMs <= MAX_FRAME_AGE_MS) {
    int before[2] = {s_core.pulse[0], s_core.pulse[1]};
    result = hv_gimbal_observe(&s_core, people, true, x, y, capturedMs, nowMs);
    if (result == HV_GIMBAL_MOVE) {
      for (int axis = 0; axis < 2; ++axis)
        if (before[axis] != s_core.pulse[axis] && !write_pulse_locked(axis)) {
          unlock();
          return;
        }
    }
    if (result == HV_GIMBAL_MOVE || result == HV_GIMBAL_WAIT || result == HV_GIMBAL_CENTERED)
      s_lastAcceptedMs = nowMs;
    if (result == HV_GIMBAL_CENTERED) {
      s_centeredHolding = true;
      s_leaseUntilMs = s_autoEnabled ? 0 : nowMs + CENTERED_HOLD_LEASE_MS;
      s_lastStopReason = "centered";
    }
  } else if (face) {
    result = HV_GIMBAL_STALE;
  }
  if (result == HV_GIMBAL_LIMIT || result == HV_GIMBAL_TIMEOUT ||
      result == HV_GIMBAL_WRONG_DIRECTION || result == HV_GIMBAL_NO_FACE)
    close_outputs_locked(result == HV_GIMBAL_LIMIT ? "pulse_limit" :
                         result == HV_GIMBAL_TIMEOUT ? "timeout" :
                         result == HV_GIMBAL_WRONG_DIRECTION ? "wrong_direction" :
                         "lost_target", true);
  float loggedX = isfinite(x) ? x : 0;
  float loggedY = isfinite(y) ? y : 0;
  printf("GIMBAL {\"event\":\"observation\",\"source\":\"%s\",\"people\":%u,\"face\":%s,"
         "\"x\":%.4f,\"y\":%.4f,\"captured_ms\":%llu,\"age_ms\":%llu,"
         "\"result\":%d,\"pan_us\":%d,\"tilt_us\":%d,\"active\":%s,"
         "\"holding\":%s}\n", source == HV_GIMBAL_TARGET_HAND ? "hand" : "face",
         people, face ? "true" : "false", (double)loggedX,
         (double)loggedY,
         (unsigned long long)capturedMs,
         (unsigned long long)(capturedMs <= nowMs ? nowMs - capturedMs : 0), result,
         s_core.pulse[0], s_core.pulse[1], s_core.active ? "true" : "false",
         s_centeredHolding ? "true" : "false");
  unlock();
}

esp_err_t hv_face_gimbal_init(void)
{
  if (s_initialized) return ESP_OK;
  if (s_outputFault) return ESP_FAIL;
  s_lock = xSemaphoreCreateMutex();
  if (!s_lock) return ESP_ERR_NO_MEM;
  hv_gimbal_reset(&s_core);
  s_core.minPulseUs = PULSE_MIN_US;
  s_core.maxPulseUs = PULSE_MAX_US;
  s_core.maxStepUs = MAX_STEP_US;
  s_core.maxAgeMs = MAX_FRAME_AGE_MS;
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .duty_resolution = LEDC_TIMER_14_BIT,
    .timer_num = LEDC_TIMER_0,
    .freq_hz = 50,
    .clk_cfg = LEDC_AUTO_CLK};
  esp_err_t ret = ledc_timer_config(&timer);
  int configured = 0;
  if (ret != ESP_OK) goto fail;
  for (int axis = 0; axis < 2; ++axis) {
    ledc_channel_config_t channel = {
      .gpio_num = PINS[axis],
      .speed_mode = LEDC_LOW_SPEED_MODE,
      .channel = (ledc_channel_t)axis,
      .intr_type = LEDC_INTR_DISABLE,
      .timer_sel = LEDC_TIMER_0,
      .duty = 0,
      .hpoint = 0};
    ret = ledc_channel_config(&channel);
    if (ret != ESP_OK) goto fail;
    ++configured;
    ret = ledc_stop(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, 0);
    if (ret != ESP_OK) goto fail;
  }
  s_initialized = true;
  if (qm_cli_register_command(&s_cli) != 0) {
    s_initialized = false;
    ret = ESP_FAIL;
    goto fail;
  }
  printf("GIMBAL ready pan=17 tilt=18 PWM=off limits=1475..1525us age<=400ms\n");
  return ESP_OK;
fail:
  for (int axis = 0; axis < configured; ++axis) {
    esp_err_t stopped = ledc_stop(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, 0);
    if (stopped != ESP_OK) {
      esp_err_t fallback = ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis, 0);
      if (fallback == ESP_OK)
        fallback = ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)axis);
      s_outputFault = true;
      printf("GIMBAL ERROR init_pwm_stop_failed axis=%d ret=%d zero_duty_ret=%d\n",
             axis, stopped, fallback);
    }
  }
  vSemaphoreDelete(s_lock);
  s_lock = NULL;
  return ret;
}

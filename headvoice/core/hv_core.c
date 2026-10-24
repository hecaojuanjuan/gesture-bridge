#include "hv_core.h"

#include <math.h>
#include <string.h>

static hv_effect_t effect(HvEvent event, const hv_core_t * core, char action)
{
  hv_effect_t out = {event, core->phrase, action, core->ticket};
  return out;
}

hv_config_t hv_default_config(void)
{
  hv_config_t config = {5, 14, 9, 45, 5, 2000, 600, 350, 400, 400, 5000, 8000, 10000, 3, 10};
  return config;
}

static void reset_motion(hv_core_t * core)
{
  core->phase = 0;
  core->direction = 0;
  core->held = false;
  core->haveNeutral = false;
  core->haveWindow = false;
  core->samples = core->neutralSamples = 0;
}

void hv_init(hv_core_t * core, const hv_config_t * config)
{
  memset(core, 0, sizeof(*core));
  core->config = config ? *config : hv_default_config();
  core->state = HV_CALIBRATING;
  core->first = core->phrase = -1;
}

void hv_recalibrate(hv_core_t * core)
{
  hv_config_t config = core->config;
  uint32_t ticket = core->ticket + 1;
  hv_init(core, &config);
  core->ticket = ticket;
}

hv_effect_t hv_invalidate(hv_core_t * core, uint64_t nowMs)
{
  bool hadInput = core->state != HV_REARM && core->state != HV_CALIBRATING;
  reset_motion(core);
  core->rejectThrough = nowMs;
  core->first = core->phrase = -1;
  core->deadline = 0;
  if (core->state != HV_CALIBRATING && core->state != HV_SPEAKING) {
    core->state = HV_REARM;
  }
  return effect(hadInput ? HV_RESET : HV_NONE, core, 0);
}

hv_effect_t hv_tick(hv_core_t * core, uint64_t nowMs)
{
  if (
    (core->deadline && nowMs >= core->deadline) ||
    (core->haveCapture && nowMs > core->lastCapture &&
     nowMs - core->lastCapture > core->config.maxGapMs &&
     (core->haveWindow || core->haveNeutral || core->phase || core->first >= 0 ||
      core->state == HV_REVIEW || core->state == HV_REVIEW_REARM))) {
    return hv_invalidate(core, nowMs);
  }
  return effect(HV_NONE, core, 0);
}

static bool neutral(hv_core_t * core, float delta, uint64_t capture)
{
  if (fabsf(delta) > core->config.neutralDegrees) {
    core->haveNeutral = false;
    core->neutralSamples = 0;
    return false;
  }
  if (!core->haveNeutral) {
    core->neutralStart = capture;
    core->haveNeutral = true;
  }
  core->neutralSamples++;
  return capture - core->neutralStart >= core->config.neutralMs &&
         core->neutralSamples >= core->config.minSamples;
}

hv_effect_t hv_observe(hv_core_t * core, hv_observation_t obs, uint64_t nowMs)
{
  hv_effect_t timeout = hv_tick(core, nowMs);
  if (timeout.event != HV_NONE) return timeout;
  if (
    !obs.valid || !isfinite(obs.tiltDegrees) || obs.capturedMs > nowMs ||
    nowMs - obs.capturedMs > core->config.maxAgeMs ||
    (core->haveCapture && obs.capturedMs <= core->lastCapture) ||
    obs.capturedMs <= core->rejectThrough) {
    return hv_invalidate(core, nowMs);
  }
  if (core->haveCapture && obs.capturedMs - core->lastCapture > core->config.maxGapMs) {
    core->lastCapture = obs.capturedMs;
    return hv_invalidate(core, nowMs);
  }
  core->lastCapture = obs.capturedMs;
  core->haveCapture = true;
  if (core->state == HV_SPEAKING) return effect(HV_NONE, core, 0);

  if (core->state == HV_CALIBRATING) {
    if (!core->haveWindow) {
      core->windowStart = obs.capturedMs;
      core->calibrationMin = core->calibrationMax = obs.tiltDegrees;
      core->calibrationSum = 0;
      core->samples = 0;
      core->haveWindow = true;
    }
    core->calibrationMin = fminf(core->calibrationMin, obs.tiltDegrees);
    core->calibrationMax = fmaxf(core->calibrationMax, obs.tiltDegrees);
    if (core->calibrationMax - core->calibrationMin > core->config.calibrationSpread) {
      reset_motion(core);
      return effect(HV_NONE, core, 0);
    }
    core->calibrationSum += obs.tiltDegrees;
    core->samples++;
    if (
      obs.capturedMs - core->windowStart >= core->config.calibrationMs &&
      core->samples >= core->config.calibrationSamples) {
      core->baseline = core->calibrationSum / (float)core->samples;
      core->state = HV_REARM;
      reset_motion(core);
      return effect(HV_CALIBRATED, core, 0);
    }
    return effect(HV_NONE, core, 0);
  }

  float delta = obs.tiltDegrees - core->baseline;
  if (fabsf(delta) > core->config.maxDegrees) return hv_invalidate(core, nowMs);
  if (core->state == HV_REARM || core->state == HV_REVIEW_REARM) {
    if (neutral(core, delta, obs.capturedMs)) {
      core->state = core->state == HV_REVIEW_REARM ? HV_REVIEW : HV_COLLECT;
      reset_motion(core);
      return effect(HV_READY, core, 0);
    }
    return effect(HV_NONE, core, 0);
  }

  int sign = delta >= core->config.actionDegrees    ? 1
             : delta <= -core->config.actionDegrees ? -1
                                                    : 0;
  if (core->phase == 0) {
    if (sign) {
      core->phase = 1;
      core->direction = sign;
      core->actionStart = core->windowStart = obs.capturedMs;
      core->samples = 1;
      core->held = false;
    }
    return effect(HV_NONE, core, 0);
  }
  if (obs.capturedMs - core->actionStart > core->config.actionTimeoutMs) {
    return hv_invalidate(core, nowMs);
  }
  if (core->phase == 1) {
    if (sign == core->direction) {
      core->samples++;
      if (
        obs.capturedMs - core->windowStart >= core->config.holdMs &&
        core->samples >= core->config.minSamples)
        core->held = true;
    } else if (core->held && fabsf(delta) <= core->config.releaseDegrees) {
      core->phase = 2;
    } else {
      return hv_invalidate(core, nowMs);
    }
  }
  if (core->phase == 2) {
    if (sign) return hv_invalidate(core, nowMs);
    if (neutral(core, delta, obs.capturedMs)) {
      int value = core->direction > 0 ? 0 : 1;
      char action = value ? 'B' : 'A';
      reset_motion(core);
      if (core->state == HV_REVIEW) {
        core->deadline = 0;
        if (value == 0) {
          core->state = HV_SPEAKING;
          core->ticket++;
          return effect(HV_PLAY, core, action);
        }
        core->state = HV_REARM;
        core->phrase = core->first = -1;
        return effect(HV_CANCELLED, core, action);
      }
      if (core->first < 0) {
        core->first = value;
        core->deadline = nowMs + core->config.comboTimeoutMs;
        return effect(HV_ACTION, core, action);
      }
      core->phrase = core->first * 2 + value;
      core->first = -1;
      core->state = HV_REVIEW_REARM;
      core->deadline = nowMs + core->config.confirmTimeoutMs;
      return effect(HV_CANDIDATE, core, action);
    }
  }
  return effect(HV_NONE, core, 0);
}

void hv_playback_done(hv_core_t * core, uint32_t ticket, uint64_t nowMs)
{
  if (core->state == HV_SPEAKING && core->ticket == ticket) {
    core->state = HV_REARM;
    hv_invalidate(core, nowMs);
  }
}

const char * hv_phrase(int phrase)
{
  static const char * const PHRASES[] = {
    "我想喝水。", "我想休息一下。", "请过来协助我。", "我想自己来。"};
  return phrase >= 0 && phrase < 4 ? PHRASES[phrase] : "";
}

const char * hv_code(int phrase)
{
  static const char * const CODES[] = {"AA", "AB", "BA", "BB"};
  return phrase >= 0 && phrase < 4 ? CODES[phrase] : "";
}

bool hv_eye_tilt(float x1, float y1, float x2, float y2, float * degrees)
{
  if (!degrees || !isfinite(x1) || !isfinite(y1) || !isfinite(x2) || !isfinite(y2)) return false;
  float dx = x2 - x1, dy = y2 - y1;
  if (dx * dx + dy * dy < 16.0f) return false;
  float angle = atan2f(dy, dx) * (180.0f / 3.14159265358979323846f);
  if (angle > 90) angle -= 180;
  if (angle < -90) angle += 180;
  *degrees = angle;
  return true;
}

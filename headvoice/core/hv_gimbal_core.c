#include "hv_gimbal_core.h"

#include <math.h>
#include <string.h>

void hv_gimbal_reset(hv_gimbal_t * core)
{
  memset(core, 0, sizeof(*core));
  core->pulse[0] = core->pulse[1] = 1500;
  core->direction[0] = core->direction[1] = 1;
  core->previousAxis = -1;
}

void hv_gimbal_begin(hv_gimbal_t * core, uint64_t nowMs)
{
  core->active = true;
  core->centered = core->steps = core->worsening = 0;
  core->previousAxis = -1;
  core->lastCaptureMs = 0;
  core->acceptAfterMs = nowMs + 450;
  core->deadlineMs = nowMs + 90000;
}

static HvGimbalResult stop(hv_gimbal_t * core, HvGimbalResult result)
{
  core->active = false;
  return result;
}

HvGimbalResult hv_gimbal_observe(
  hv_gimbal_t * core, unsigned people, bool headValid, float x, float y, uint64_t capturedMs,
  uint64_t nowMs)
{
  if (!core->active) return HV_GIMBAL_WAIT;
  if (nowMs >= core->deadlineMs) return stop(core, HV_GIMBAL_TIMEOUT);
  if (
    capturedMs <= core->lastCaptureMs || capturedMs <= core->acceptAfterMs || capturedMs > nowMs ||
    nowMs - capturedMs > 6000)
    return HV_GIMBAL_STALE;
  core->lastCaptureMs = capturedMs;
  if (people != 1 || !headValid || !isfinite(x) || !isfinite(y) || x < 0 || x > 1 || y < 0 || y > 1)
    return stop(core, HV_GIMBAL_NO_FACE);
  float error[2] = {x - 0.5f, y - 0.5f};
  if (core->previousAxis >= 0) {
    if (fabsf(error[core->previousAxis]) > core->previousError + 0.035f)
      ++core->worsening;
    else
      core->worsening = 0;
    if (core->worsening >= 2) return stop(core, HV_GIMBAL_WRONG_DIRECTION);
    core->previousAxis = -1;
  }
  if (fabsf(error[0]) <= 0.08f && fabsf(error[1]) <= 0.08f) {
    if (++core->centered >= 3) return stop(core, HV_GIMBAL_CENTERED);
    return HV_GIMBAL_WAIT;
  }
  core->centered = 0;
  if (core->steps >= 20) return stop(core, HV_GIMBAL_TIMEOUT);
  int axis = fabsf(error[0]) >= fabsf(error[1]) ? 0 : 1;
  if (core->direction[axis] != 1 && core->direction[axis] != -1)
    return stop(core, HV_GIMBAL_WRONG_DIRECTION);
  int step = (int)(fabsf(error[axis]) * 100);
  if (step < 10) step = 10;
  if (step > 35) step = 35;
  int target = core->pulse[axis] + (error[axis] > 0 ? step : -step) * core->direction[axis];
  if (target < 1300 || target > 1700) return stop(core, HV_GIMBAL_LIMIT);
  core->pulse[axis] = target;
  core->previousAxis = axis;
  core->previousError = fabsf(error[axis]);
  core->acceptAfterMs = nowMs + 450;
  ++core->steps;
  return HV_GIMBAL_MOVE;
}

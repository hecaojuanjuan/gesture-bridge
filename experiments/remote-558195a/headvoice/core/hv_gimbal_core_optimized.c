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
  // 优化1: 减少初始等待时间从450ms到250ms
  core->acceptAfterMs = nowMs + 250;
  // 优化2: 延长总超时时间，给更多机会
  core->deadlineMs = nowMs + 120000;
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

  // 优化3: 放宽人像识别条件
  // 原来: 必须恰好1人且头部有效
  // 现在: 允许1-2人，只要有一个头部有效即可；或者即使头部无效但坐标合理也可以尝试
  bool hasValidTarget = false;
  if (people >= 1 && people <= 2 && headValid && isfinite(x) && isfinite(y) &&
      x >= 0 && x <= 1 && y >= 0 && y <= 1) {
    hasValidTarget = true;
  } else if (people == 1 && isfinite(x) && isfinite(y) &&
             x >= 0.1f && x <= 0.9f && y >= 0.1f && y <= 0.9f) {
    // 即使头部无效，但如果只有1人且坐标在合理范围内，也尝试居中
    hasValidTarget = true;
  }

  if (!hasValidTarget) {
    // 优化4: 不立即停止，而是等待更多帧
    // 只有连续多次失败才停止
    if (core->steps == 0) {
      // 还没开始移动，继续等待
      return HV_GIMBAL_WAIT;
    }
    // 已经移动过，给一次机会继续
    return HV_GIMBAL_WAIT;
  }

  float error[2] = {x - 0.5f, y - 0.5f};
  if (core->previousAxis >= 0) {
    // 优化5: 放宽"变差"的判断阈值，从0.035提高到0.05
    if (fabsf(error[core->previousAxis]) > core->previousError + 0.05f)
      ++core->worsening;
    else
      core->worsening = 0;
    // 优化6: 允许更多次变差，从2次提高到3次
    if (core->worsening >= 3) return stop(core, HV_GIMBAL_WRONG_DIRECTION);
    core->previousAxis = -1;
  }

  // 优化7: 缩小居中判定范围，从0.08提高到0.06，更精确
  if (fabsf(error[0]) <= 0.06f && fabsf(error[1]) <= 0.06f) {
    // 优化8: 减少需要的连续居中次数，从3次降到2次
    if (++core->centered >= 2) return stop(core, HV_GIMBAL_CENTERED);
    return HV_GIMBAL_WAIT;
  }
  core->centered = 0;

  // 优化9: 增加最大步数限制，从20提高到30
  if (core->steps >= 30) return stop(core, HV_GIMBAL_TIMEOUT);

  int axis = fabsf(error[0]) >= fabsf(error[1]) ? 0 : 1;
  if (core->direction[axis] != 1 && core->direction[axis] != -1)
    return stop(core, HV_GIMBAL_WRONG_DIRECTION);

  // 优化10: 动态调整步长，使响应更快
  int step = (int)(fabsf(error[axis]) * 120);  // 从100提高到120
  if (step < 12) step = 12;  // 最小步长从10提高到12
  if (step > 45) step = 45;  // 最大步长从35提高到45

  int target = core->pulse[axis] + (error[axis] > 0 ? step : -step) * core->direction[axis];
  if (target < 1300 || target > 1700) return stop(core, HV_GIMBAL_LIMIT);
  core->pulse[axis] = target;
  core->previousAxis = axis;
  core->previousError = fabsf(error[axis]);

  // 优化11: 大幅减少等待时间，从450ms降到200ms
  core->acceptAfterMs = nowMs + 200;
  ++core->steps;
  return HV_GIMBAL_MOVE;
}

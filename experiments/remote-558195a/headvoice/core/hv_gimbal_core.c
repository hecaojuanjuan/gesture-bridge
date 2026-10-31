#include "hv_gimbal_core.h"

#include <math.h>
#include <string.h>

void hv_gimbal_reset(hv_gimbal_t * core)
{
  memset(core, 0, sizeof(*core));
  core->pulse[0] = core->pulse[1] = 1500;
  core->direction[0] = core->direction[1] = 1;
  core->previousAxis = -1;
  // 默认使用自动模式（优先人脸，无人脸时用手掌）
  core->target_mode = HV_GIMBAL_TARGET_AUTO;
  core->current_target.type = HV_GIMBAL_TARGET_NONE;
}

void hv_gimbal_begin(hv_gimbal_t * core, uint64_t nowMs)
{
  core->active = true;
  core->centered = core->steps = core->worsening = 0;
  core->previousAxis = -1;
  core->lastCaptureMs = 0;
  core->acceptAfterMs = nowMs + 250;
  core->deadlineMs = nowMs + 120000;
  core->current_target.lost_frames = 0;
}

void hv_gimbal_set_target_mode(hv_gimbal_t * core, HvGimbalTargetType mode)
{
  core->target_mode = mode;
  core->current_target.type = HV_GIMBAL_TARGET_NONE;
  core->current_target.lost_frames = 0;
}

static HvGimbalResult stop(hv_gimbal_t * core, HvGimbalResult result)
{
  core->active = false;
  return result;
}

// 原有API，保持向后兼容
HvGimbalResult hv_gimbal_observe(
  hv_gimbal_t * core, unsigned people, bool headValid, float x, float y, uint64_t capturedMs,
  uint64_t nowMs)
{
  // 转发到扩展API，不提供手部信息
  return hv_gimbal_observe_extended(core, people, headValid, x, y,
                                     false, 0, 0, 0,
                                     capturedMs, nowMs);
}

// 新增：扩展观察API，支持手部跟踪
HvGimbalResult hv_gimbal_observe_extended(
  hv_gimbal_t * core,
  // 人脸信息
  unsigned people, bool headValid, float face_x, float face_y,
  // 手部信息
  bool handValid, float hand_x, float hand_y, float hand_confidence,
  // 其他
  uint64_t capturedMs, uint64_t nowMs)
{
  if (!core->active) return HV_GIMBAL_WAIT;
  if (nowMs >= core->deadlineMs) return stop(core, HV_GIMBAL_TIMEOUT);
  if (
    capturedMs <= core->lastCaptureMs || capturedMs <= core->acceptAfterMs || capturedMs > nowMs ||
    nowMs - capturedMs > 6000)
    return HV_GIMBAL_STALE;
  core->lastCaptureMs = capturedMs;

  // ========== 目标选择逻辑 ==========
  bool hasFaceTarget = false;
  bool hasHandTarget = false;

  // 检查人脸目标有效性
  if (people >= 1 && people <= 2 && headValid && isfinite(face_x) && isfinite(face_y) &&
      face_x >= 0 && face_x <= 1 && face_y >= 0 && face_y <= 1) {
    hasFaceTarget = true;
  } else if (people == 1 && isfinite(face_x) && isfinite(face_y) &&
             face_x >= 0.1f && face_x <= 0.9f && face_y >= 0.1f && face_y <= 0.9f) {
    hasFaceTarget = true;
  }

  // 检查手掌目标有效性
  if (handValid && isfinite(hand_x) && isfinite(hand_y) &&
      hand_x >= 0.1f && hand_x <= 0.9f && hand_y >= 0.1f && hand_y <= 0.9f &&
      hand_confidence >= 0.3f) {  // 置信度阈值
    hasHandTarget = true;
  }

  // 根据模式选择目标
  float target_x = 0, target_y = 0;
  HvGimbalTargetType selected_type = HV_GIMBAL_TARGET_NONE;

  switch (core->target_mode) {
    case HV_GIMBAL_TARGET_FACE:
      // 仅人脸模式
      if (hasFaceTarget) {
        target_x = face_x;
        target_y = face_y;
        selected_type = HV_GIMBAL_TARGET_FACE;
      }
      break;

    case HV_GIMBAL_TARGET_HAND:
      // 仅手掌模式
      if (hasHandTarget) {
        target_x = hand_x;
        target_y = hand_y;
        selected_type = HV_GIMBAL_TARGET_HAND;
      }
      break;

    case HV_GIMBAL_TARGET_AUTO:
    default:
      // 自动模式：优先人脸，无人脸时使用手掌
      if (hasFaceTarget) {
        target_x = face_x;
        target_y = face_y;
        selected_type = HV_GIMBAL_TARGET_FACE;
      } else if (hasHandTarget) {
        target_x = hand_x;
        target_y = hand_y;
        selected_type = HV_GIMBAL_TARGET_HAND;
      }
      break;
  }

  // 没有有效目标
  if (selected_type == HV_GIMBAL_TARGET_NONE) {
    core->current_target.lost_frames++;

    // 连续丢失处理
    if (core->steps == 0) {
      // 还没开始移动，继续等待
      return HV_GIMBAL_WAIT;
    }

    // 已经移动过，允许短暂丢失（最多3帧）
    if (core->current_target.lost_frames <= 3) {
      return HV_GIMBAL_WAIT;
    }

    // 丢失过久，停止
    return stop(core, HV_GIMBAL_NO_FACE);
  }

  // 更新当前目标状态
  core->current_target.type = selected_type;
  core->current_target.valid = true;
  core->current_target.x = target_x;
  core->current_target.y = target_y;
  core->current_target.confidence = (selected_type == HV_GIMBAL_TARGET_HAND) ? hand_confidence : 1.0f;
  core->current_target.lost_frames = 0;

  // ========== 居中控制逻辑 ==========
  float error[2] = {target_x - 0.5f, target_y - 0.5f};

  if (core->previousAxis >= 0) {
    // 变差判断
    if (fabsf(error[core->previousAxis]) > core->previousError + 0.05f)
      ++core->worsening;
    else
      core->worsening = 0;
    if (core->worsening >= 3) return stop(core, HV_GIMBAL_WRONG_DIRECTION);
    core->previousAxis = -1;
  }

  // 居中判定（手掌模式使用稍宽松的阈值）
  float center_threshold = (selected_type == HV_GIMBAL_TARGET_HAND) ? 0.08f : 0.06f;

  if (fabsf(error[0]) <= center_threshold && fabsf(error[1]) <= center_threshold) {
    if (++core->centered >= 2) return stop(core, HV_GIMBAL_CENTERED);
    return HV_GIMBAL_WAIT;
  }
  core->centered = 0;

  if (core->steps >= 30) return stop(core, HV_GIMBAL_TIMEOUT);

  int axis = fabsf(error[0]) >= fabsf(error[1]) ? 0 : 1;
  if (core->direction[axis] != 1 && core->direction[axis] != -1)
    return stop(core, HV_GIMBAL_WRONG_DIRECTION);

  // 动态步长（手掌模式响应更快）
  int step_multiplier = (selected_type == HV_GIMBAL_TARGET_HAND) ? 130 : 120;
  int step = (int)(fabsf(error[axis]) * step_multiplier);

  if (selected_type == HV_GIMBAL_TARGET_HAND) {
    // 手掌模式：更快响应
    if (step < 15) step = 15;
    if (step > 50) step = 50;
  } else {
    // 人脸模式
    if (step < 12) step = 12;
    if (step > 45) step = 45;
  }

  int target = core->pulse[axis] + (error[axis] > 0 ? step : -step) * core->direction[axis];
  if (target < 1300 || target > 1700) return stop(core, HV_GIMBAL_LIMIT);
  core->pulse[axis] = target;
  core->previousAxis = axis;
  core->previousError = fabsf(error[axis]);

  // 手掌模式等待时间更短
  int wait_time = (selected_type == HV_GIMBAL_TARGET_HAND) ? 180 : 200;
  core->acceptAfterMs = nowMs + wait_time;
  ++core->steps;
  return HV_GIMBAL_MOVE;
}

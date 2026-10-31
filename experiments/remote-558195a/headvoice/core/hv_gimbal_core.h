#ifndef HV_GIMBAL_CORE_H
#define HV_GIMBAL_CORE_H
#include <stdbool.h>
#include <stdint.h>

typedef enum {
  HV_GIMBAL_WAIT,
  HV_GIMBAL_MOVE,
  HV_GIMBAL_CENTERED,
  HV_GIMBAL_NO_FACE,
  HV_GIMBAL_STALE,
  HV_GIMBAL_LIMIT,
  HV_GIMBAL_TIMEOUT,
  HV_GIMBAL_WRONG_DIRECTION
} HvGimbalResult;

// 新增：目标类型枚举
typedef enum {
  HV_GIMBAL_TARGET_NONE = 0,
  HV_GIMBAL_TARGET_FACE = 1,    // 人脸（默认）
  HV_GIMBAL_TARGET_HAND = 2,    // 手掌
  HV_GIMBAL_TARGET_AUTO = 3     // 自动选择（优先人脸，无人脸时用手掌）
} HvGimbalTargetType;

// 新增：跟踪目标信息
typedef struct {
  HvGimbalTargetType type;      // 当前跟踪的目标类型
  bool valid;                   // 目标是否有效
  float x, y;                   // 目标中心坐标 (0-1)
  float confidence;             // 置信度 (0-1)
  unsigned int lost_frames;     // 连续丢失帧数
} hv_gimbal_target_t;

typedef struct
{
  int pulse[2], direction[2];
  bool active;
  unsigned centered, steps, worsening;
  int previousAxis;
  float previousError;
  uint64_t acceptAfterMs, lastCaptureMs, deadlineMs;

  // 新增：目标跟踪状态
  HvGimbalTargetType target_mode;   // 目标模式设置
  hv_gimbal_target_t current_target; // 当前跟踪目标
} hv_gimbal_t;

void hv_gimbal_reset(hv_gimbal_t * core);
void hv_gimbal_begin(hv_gimbal_t * core, uint64_t nowMs);

// 原有API（保持兼容）
HvGimbalResult hv_gimbal_observe(
  hv_gimbal_t * core, unsigned people, bool headValid, float x, float y, uint64_t capturedMs,
  uint64_t nowMs);

// 新增：设置目标模式
void hv_gimbal_set_target_mode(hv_gimbal_t * core, HvGimbalTargetType mode);

// 新增：扩展观察API，支持手部跟踪
HvGimbalResult hv_gimbal_observe_extended(
  hv_gimbal_t * core,
  // 人脸信息
  unsigned people, bool headValid, float face_x, float face_y,
  // 手部信息
  bool handValid, float hand_x, float hand_y, float hand_confidence,
  // 其他
  uint64_t capturedMs, uint64_t nowMs);

#endif

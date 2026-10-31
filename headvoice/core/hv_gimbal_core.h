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

typedef struct
{
  int pulse[2], direction[2];
  int minPulseUs, maxPulseUs, maxStepUs;
  uint32_t maxAgeMs;
  bool active;
  unsigned centered, steps, worsening;
  int previousAxis;
  float previousError;
  uint64_t acceptAfterMs, lastCaptureMs, deadlineMs;
} hv_gimbal_t;

void hv_gimbal_reset(hv_gimbal_t * core);
void hv_gimbal_begin(hv_gimbal_t * core, uint64_t nowMs);
HvGimbalResult hv_gimbal_observe(
  hv_gimbal_t * core, unsigned people, bool headValid, float x, float y, uint64_t capturedMs,
  uint64_t nowMs);
#endif

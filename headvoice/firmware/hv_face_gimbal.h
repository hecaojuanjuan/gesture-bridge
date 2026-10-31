#ifndef HV_FACE_GIMBAL_H
#define HV_FACE_GIMBAL_H

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* Face stage 2 only. PWM remains off until an explicit arm command. */
esp_err_t hv_face_gimbal_init(void);
bool hv_face_gimbal_active(void);
void hv_face_gimbal_observe(unsigned people, bool faceValid, float x, float y,
                            uint64_t capturedMs, uint64_t nowMs);
/* Discard cached face target only; keep manual PWM arm and its existing lease. */
void hv_face_gimbal_clear_target(void);
void hv_face_gimbal_invalidate(void);
void hv_face_gimbal_tick(uint64_t nowMs);

#endif

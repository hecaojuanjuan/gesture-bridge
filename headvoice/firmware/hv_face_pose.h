#ifndef HV_FACE_POSE_H
#define HV_FACE_POSE_H
#include <stdbool.h>
#include "yolo11_pose.h"

typedef struct {
  bool valid;
  float x, y; /* Whole-face box center, normalized to the rotated input. */
} hv_face_target_t;

#ifdef __cplusplus
extern "C" {
#endif
esp_err_t hv_face_pose_init(void);
#if HV_FACE_SELFTEST
/* Diagnostic-only; invoke on the sole inference task before receiving frames. */
void hv_face_pose_selftest(void);
#endif
esp_err_t hv_face_pose_analyze_rgb888(const uint8_t *rgb, uint16_t width,
                                     uint16_t height,
                                     yolo11_pose_frame_result_t *result,
                                     hv_face_target_t *target);
#ifdef __cplusplus
}
#endif
#endif

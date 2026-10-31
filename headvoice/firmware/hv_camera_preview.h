#ifndef HV_CAMERA_PREVIEW_H
#define HV_CAMERA_PREVIEW_H

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t hv_camera_preview_init(void);
void hv_camera_preview_offer(const uint8_t * data, size_t length, uint64_t capturedMs);
/* Called only by inference_task while it owns the converted model input.
 * input copies a bounded RGB565 preview; inputjpeg copies the complete RGB888
 * frame into request-owned storage before returning. JPEG encoding runs in
 * preview_task, and its captured_ms identifies this exact model input. */
void hv_camera_preview_offer_model_input(
  const uint8_t * rgb, uint16_t width, uint16_t height, uint64_t capturedMs);

#endif

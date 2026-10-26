#ifndef HV_CAMERA_PREVIEW_H
#define HV_CAMERA_PREVIEW_H

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t hv_camera_preview_init(void);
void hv_camera_preview_offer(const uint8_t * data, size_t length, uint64_t capturedMs);

#endif

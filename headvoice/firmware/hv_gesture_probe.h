#ifndef HV_GESTURE_PROBE_H
#define HV_GESTURE_PROBE_H
#include "esp_err.h"
#if defined(HV_GESTURE_AGENT_DIAGNOSTICS)
esp_err_t hv_gesture_probe_init(void);
#else
static inline esp_err_t hv_gesture_probe_init(void) { return ESP_OK; }
#endif
#endif

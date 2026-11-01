#ifndef HV_GESTURE_AGENT_H
#define HV_GESTURE_AGENT_H
#include <stdint.h>
#include "esp_err.h"
#include "hv_hand_gate.h"

esp_err_t hv_gesture_agent_init(void);
/* Zero wait, bounded single transaction. Only invoke for a completed gate event. */
void hv_gesture_agent_submit(hv_hand_gate_event_t event, uint64_t captured_ms);
#endif

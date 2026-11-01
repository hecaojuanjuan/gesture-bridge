#ifndef HV_GESTURE_AGENT_H
#define HV_GESTURE_AGENT_H
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "hv_hand_gate.h"

esp_err_t hv_gesture_agent_init(void);
/* Zero wait, bounded single transaction. Only invoke for a completed gate event. */
void hv_gesture_agent_submit(hv_hand_gate_event_t event, uint64_t captured_ms);
/* Observed agent TTS text for the currently owned automatic transaction.
 * This is not evidence of physical playback or hardware completion. */
unsigned hv_gesture_agent_active_sequence(void);
void hv_gesture_agent_text(unsigned sequence, const char *text, bool truncated);
#endif

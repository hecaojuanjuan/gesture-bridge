#ifndef HV_GESTURE_AGENT_PORT_H
#define HV_GESTURE_AGENT_PORT_H
#include <stdbool.h>
#include "qm_agent_event.h"

int hv_gesture_agent_port_init(void);
void hv_gesture_agent_port_cancel(void);
void hv_gesture_agent_port_resource_mode(bool active);
void hv_gesture_agent_port_notice(int32_t id, const qm_agent_event_notice_t *notice);
int hv_gesture_agent_port_begin(void);
int hv_gesture_agent_port_ready(void);
int hv_gesture_agent_port_arm(void);
/* Terminal handoff without a hardware playback-complete acknowledgement. */
#define HV_GESTURE_PORT_COMPLETION_UNSUPPORTED 3
/* 0=pending, 1=started, 2=confirmed complete, 3=completion unsupported,
 * negative=failed. Unsupported must never be reported as playback complete. */
int hv_gesture_agent_port_poll(void);
bool hv_gesture_agent_port_cancelled(void *unused);
int hv_gesture_agent_port_end(void);
#endif

#ifndef HV_GESTURE_AGENT_PORT_H
#define HV_GESTURE_AGENT_PORT_H
#include <stdbool.h>
#include "qm_agent_event.h"

int hv_gesture_agent_port_init(void);
void hv_gesture_agent_port_cancel(void);
void hv_gesture_agent_port_resource_mode(bool active);
void hv_gesture_agent_port_notice(int32_t id, const qm_agent_event_notice_t *notice);
int hv_gesture_agent_port_begin(void);
/* Returns a static reason captured by this begin call, never a later snapshot. */
int hv_gesture_agent_port_begin_detail(const char **detail);
/* Read only: inspect the local start gate without starting/stopping a session. */
int hv_gesture_agent_port_status(const char **detail);
int hv_gesture_agent_port_ready(void);
/* Credential-free snapshot of the readiness barrier, for timeout diagnosis. */
const char *hv_gesture_agent_port_ready_detail(void);
int hv_gesture_agent_port_arm(void);
/* Terminal handoff without a hardware playback-complete acknowledgement. */
#define HV_GESTURE_PORT_COMPLETION_UNSUPPORTED 3
/* 0=pending, 1=started, 2=confirmed complete, 3=completion unsupported,
 * negative=failed. Unsupported must never be reported as playback complete. */
int hv_gesture_agent_port_poll(void);
bool hv_gesture_agent_port_cancelled(void *unused);
int hv_gesture_agent_port_end(void);
/* Owned automatic transaction only; diagnostics have no active request ID. */
unsigned hv_gesture_agent_active_sequence(void);
void hv_gesture_agent_text(unsigned sequence, const char *text, bool truncated);
#endif

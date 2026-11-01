#ifndef HV_GESTURE_REPLY_H
#define HV_GESTURE_REPLY_H
#include <stdbool.h>
#include <stdint.h>

typedef enum {
  HV_REPLY_TEXT, HV_REPLY_SPEAKING, HV_REPLY_SILENT, HV_REPLY_STARTED,
  HV_REPLY_COMPLETE, HV_REPLY_FAILED
} hv_reply_event_t;
typedef struct {
  bool text, speaking, silent, started, input_closed, complete, failed;
  uint32_t generation;
} hv_gesture_reply_t;

/* Returns true exactly once when the transport input must be closed so the
 * local audio engine can drain. COMPLETE is not inferred from HTTP or text. */
bool hv_gesture_reply_observe(hv_gesture_reply_t *reply, hv_reply_event_t event,
                              uint32_t generation);
#endif

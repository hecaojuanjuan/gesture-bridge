#include "hv_gesture_reply.h"

bool hv_gesture_reply_observe(hv_gesture_reply_t *r, hv_reply_event_t event,
                              uint32_t generation)
{
  if (!r || r->complete || r->failed) return false;
  switch (event) {
  case HV_REPLY_TEXT: r->text = true; break;
  case HV_REPLY_SPEAKING: r->speaking = true; r->silent = false; break;
  case HV_REPLY_SILENT: r->silent = true; break;
  case HV_REPLY_STARTED:
    if (r->started && r->generation != generation) { r->failed = true; break; }
    r->started = true; r->generation = generation; break;
  case HV_REPLY_FAILED:
    if (!r->started || r->generation == generation) r->failed = true;
    break;
  case HV_REPLY_COMPLETE:
    if (r->started && r->input_closed && r->generation == generation) r->complete = true;
    break;
  }
  if (!r->failed && !r->input_closed && r->text && r->speaking && r->silent && r->started) {
    r->input_closed = true;
    return true;
  }
  return false;
}

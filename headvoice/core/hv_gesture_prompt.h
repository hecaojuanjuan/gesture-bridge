#ifndef HV_GESTURE_PROMPT_H
#define HV_GESTURE_PROMPT_H

#include <stddef.h>
#include "hv_hand_gate.h"

#define HV_GESTURE_MEANING_BYTES 181
#define HV_GESTURE_PROMPT_BYTES 1024

/* Meanings are explicitly provisioned by the caregiver, never inferred from
 * the model class name. Empty bindings disable that gesture. */
typedef struct {
  const char *open_palm;
  const char *v_sign;
} hv_gesture_dictionary_t;

/* Returns UTF-8 bytes excluding NUL, or 0 for unbound/invalid/too-long input.
 * Only completed gate events may be passed here, not raw classifications. */
size_t hv_gesture_prompt(hv_hand_gate_event_t event,
                         const hv_gesture_dictionary_t *dictionary,
                         char *output, size_t capacity);

#endif

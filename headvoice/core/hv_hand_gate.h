#ifndef HV_HAND_GATE_H
#define HV_HAND_GATE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  HV_HAND_GATE_UNKNOWN = 0,
  HV_HAND_GATE_NO_HAND,
  HV_HAND_GATE_OPEN_PALM,
  HV_HAND_GATE_CLOSED_FIST,
  HV_HAND_GATE_OTHER,
  /* Append to retain legacy palm/fist numeric values. */
  HV_HAND_GATE_V_SIGN
} hv_hand_gate_kind_t;

typedef enum {
  HV_HAND_GATE_EVENT_NONE = 0,
  HV_HAND_GATE_EVENT_OPEN_PALM,
  HV_HAND_GATE_EVENT_CLOSED_FIST,
  HV_HAND_GATE_EVENT_V_SIGN
} hv_hand_gate_event_t;

enum {
  HV_HAND_GATE_MIN_SAMPLES = 3,
  HV_HAND_GATE_HOLD_MS = 600,
  HV_HAND_GATE_RELEASE_MS = 500,
  HV_HAND_GATE_MAX_AGE_MS = 1000,
  HV_HAND_GATE_MAX_GAP_MS = 800
};

typedef struct {
  uint64_t captured_ms;
  /* The producer's freshness/epoch decision. No hand still requires a valid
   * inference result; an unavailable detector is UNKNOWN, not NO_HAND. */
  bool valid;
  unsigned hands;
  hv_hand_gate_kind_t kind;
  float score;
  float runner_up;
} hv_hand_gate_observation_t;

typedef struct {
  hv_hand_gate_kind_t visible, candidate, latched;
  unsigned samples;
  uint64_t candidate_start_ms, release_start_ms, last_capture_ms, last_now_ms;
  /* Arrival time is separate: tick updates the clock, never this timestamp. */
  uint64_t last_received_ms;
  bool have_release, have_capture, have_clock, have_received;
} hv_hand_gate_t;

/* Defaults are provisional operating thresholds, not an accuracy guarantee.
 * Scores must be >= .80 and at least .20 above the runner-up. */
void hv_hand_gate_init(hv_hand_gate_t *gate);
hv_hand_gate_event_t hv_hand_gate_observe(
  hv_hand_gate_t *gate, hv_hand_gate_observation_t observation, uint64_t now_ms);
void hv_hand_gate_tick(hv_hand_gate_t *gate, uint64_t now_ms);

/* Epoch change, lost stream or explicit invalidation cancels display/progress,
 * but retains the last emitted class. Releasing requires fresh NO_HAND or
 * reliable OTHER for >=500ms; init is the explicit full reset. Timestamp
 * ordering remains in force across invalidation. */
void hv_hand_gate_invalidate(hv_hand_gate_t *gate);
const char *hv_hand_gate_kind_name(hv_hand_gate_kind_t kind);

#ifdef __cplusplus
}
#endif
#endif

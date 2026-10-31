#include "hv_hand_gate.h"

#include <math.h>
#include <string.h>

const char *hv_hand_gate_kind_name(hv_hand_gate_kind_t kind)
{
  switch (kind) {
    case HV_HAND_GATE_NO_HAND: return "no_hand";
    case HV_HAND_GATE_OPEN_PALM: return "open_palm";
    case HV_HAND_GATE_CLOSED_FIST: return "closed_fist";
    case HV_HAND_GATE_V_SIGN: return "v_sign";
    case HV_HAND_GATE_OTHER: return "other";
    default: return "unknown";
  }
}

static void clear_candidate(hv_hand_gate_t *gate)
{
  gate->candidate = HV_HAND_GATE_UNKNOWN;
  gate->samples = 0;
  gate->candidate_start_ms = 0;
}

void hv_hand_gate_invalidate(hv_hand_gate_t *gate)
{
  if (!gate) return;
  gate->visible = HV_HAND_GATE_UNKNOWN;
  clear_candidate(gate);
  gate->have_release = false;
  gate->release_start_ms = 0;
}

void hv_hand_gate_init(hv_hand_gate_t *gate)
{
  if (gate) memset(gate, 0, sizeof(*gate));
}

static bool advance_clock(hv_hand_gate_t *gate, uint64_t now_ms)
{
  if (gate->have_clock && now_ms < gate->last_now_ms) {
    hv_hand_gate_invalidate(gate);
    return false;
  }
  gate->have_clock = true;
  gate->last_now_ms = now_ms;
  if (gate->have_received && now_ms >= gate->last_received_ms &&
      now_ms - gate->last_received_ms > HV_HAND_GATE_MAX_GAP_MS)
    hv_hand_gate_invalidate(gate);
  return true;
}

void hv_hand_gate_tick(hv_hand_gate_t *gate, uint64_t now_ms)
{
  if (gate) (void)advance_clock(gate, now_ms);
}

static bool reliable_class(hv_hand_gate_observation_t observation)
{
  return observation.hands == 1 &&
         (observation.kind == HV_HAND_GATE_OPEN_PALM ||
          observation.kind == HV_HAND_GATE_CLOSED_FIST ||
          observation.kind == HV_HAND_GATE_V_SIGN || observation.kind == HV_HAND_GATE_OTHER) &&
         isfinite(observation.score) && isfinite(observation.runner_up) &&
         observation.score >= .80f && observation.score <= 1.0f &&
         observation.runner_up >= 0.0f && observation.runner_up <= 1.0f &&
         observation.score >= observation.runner_up + .20f;
}

hv_hand_gate_event_t hv_hand_gate_observe(
  hv_hand_gate_t *gate, hv_hand_gate_observation_t observation, uint64_t now_ms)
{
  if (!gate) return HV_HAND_GATE_EVENT_NONE;
  if (!advance_clock(gate, now_ms)) return HV_HAND_GATE_EVENT_NONE;
  if (observation.captured_ms > now_ms ||
      now_ms - observation.captured_ms > HV_HAND_GATE_MAX_AGE_MS ||
      (gate->have_capture && observation.captured_ms <= gate->last_capture_ms)) {
    hv_hand_gate_invalidate(gate);
    return HV_HAND_GATE_EVENT_NONE;
  }
  /* Compare two capture times, not arrival minus capture: the latter adds
   * the current inference latency to the true interval between frames. */
  bool gap = gate->have_capture &&
             observation.captured_ms - gate->last_capture_ms > HV_HAND_GATE_MAX_GAP_MS;
  gate->last_capture_ms = observation.captured_ms;
  gate->have_capture = true;
  if (gap || !observation.valid ||
      !((observation.hands == 0 && observation.kind == HV_HAND_GATE_NO_HAND) ||
        reliable_class(observation))) {
    hv_hand_gate_invalidate(gate);
    return HV_HAND_GATE_EVENT_NONE;
  }

  gate->last_received_ms = now_ms;
  gate->have_received = true;
  gate->visible = observation.kind;
  if (observation.kind == HV_HAND_GATE_NO_HAND || observation.kind == HV_HAND_GATE_OTHER) {
    clear_candidate(gate);
    if (!gate->have_release) {
      gate->release_start_ms = observation.captured_ms;
      gate->have_release = true;
    }
    if (observation.captured_ms - gate->release_start_ms >= HV_HAND_GATE_RELEASE_MS)
      gate->latched = HV_HAND_GATE_UNKNOWN;
    return HV_HAND_GATE_EVENT_NONE;
  }
  gate->have_release = false;
  gate->release_start_ms = 0;
  if (observation.kind == gate->latched) {
    clear_candidate(gate);
    return HV_HAND_GATE_EVENT_NONE;
  }
  if (observation.kind != gate->candidate) {
    gate->candidate = observation.kind;
    gate->candidate_start_ms = observation.captured_ms;
    gate->samples = 1;
  } else {
    /* Only the small minimum matters; a saturated counter cannot wrap. */
    if (gate->samples < HV_HAND_GATE_MIN_SAMPLES) ++gate->samples;
  }
  if (gate->samples < HV_HAND_GATE_MIN_SAMPLES ||
      observation.captured_ms - gate->candidate_start_ms < HV_HAND_GATE_HOLD_MS)
    return HV_HAND_GATE_EVENT_NONE;
  gate->latched = observation.kind;
  clear_candidate(gate);
  switch (observation.kind) {
    case HV_HAND_GATE_OPEN_PALM: return HV_HAND_GATE_EVENT_OPEN_PALM;
    case HV_HAND_GATE_CLOSED_FIST: return HV_HAND_GATE_EVENT_CLOSED_FIST;
    case HV_HAND_GATE_V_SIGN: return HV_HAND_GATE_EVENT_V_SIGN;
    default: return HV_HAND_GATE_EVENT_NONE;
  }
}

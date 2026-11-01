"""Exercise production hand confirmation gates; synthetic inputs are not accuracy evidence."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "hv_hand_gate.h"

static hv_hand_gate_t gate;
static unsigned palm_events, fist_events, v_events;
static hv_hand_gate_event_t send(hv_hand_gate_kind_t kind, uint64_t capture, uint64_t now,
                                  bool valid, unsigned hands, float score, float second)
{
  hv_hand_gate_observation_t observation = {capture, valid, hands, kind, score, second};
  hv_hand_gate_event_t event = hv_hand_gate_observe(&gate, observation, now);
  palm_events += event == HV_HAND_GATE_EVENT_OPEN_PALM;
  fist_events += event == HV_HAND_GATE_EVENT_CLOSED_FIST;
  v_events += event == HV_HAND_GATE_EVENT_V_SIGN;
  return event;
}
static hv_hand_gate_event_t sample(hv_hand_gate_kind_t kind, uint64_t time)
{
  return send(kind, time, time + 100, true, kind == HV_HAND_GATE_NO_HAND ? 0 : 1, .9f, .1f);
}
static void reset(void)
{
  hv_hand_gate_init(&gate);
  palm_events = fist_events = v_events = 0;
}
static void palm(uint64_t start)
{
  sample(HV_HAND_GATE_OPEN_PALM, start);
  sample(HV_HAND_GATE_OPEN_PALM, start + 300);
  sample(HV_HAND_GATE_OPEN_PALM, start + 600);
}
static void fist(uint64_t start)
{
  sample(HV_HAND_GATE_CLOSED_FIST, start);
  sample(HV_HAND_GATE_CLOSED_FIST, start + 300);
  sample(HV_HAND_GATE_CLOSED_FIST, start + 600);
}
static void v_sign(uint64_t start)
{
  sample(HV_HAND_GATE_V_SIGN, start);
  sample(HV_HAND_GATE_V_SIGN, start + 300);
  sample(HV_HAND_GATE_V_SIGN, start + 600);
}
int main(void)
{
  reset();
  sample(HV_HAND_GATE_OPEN_PALM, 1000);
  sample(HV_HAND_GATE_OPEN_PALM, 1100);
  sample(HV_HAND_GATE_OPEN_PALM, 1200);
  assert(!palm_events); /* Three quick observations do not prove a hold. */
  sample(HV_HAND_GATE_OPEN_PALM, 1600);
  assert(palm_events == 1 && gate.latched == HV_HAND_GATE_OPEN_PALM);
  for (uint64_t t = 1800; t < 10000; t += 200) sample(HV_HAND_GATE_OPEN_PALM, t);
  assert(palm_events == 1);
  puts("PASS minimum samples/span and no repeats during a long hold");

  reset();
  sample(HV_HAND_GATE_OPEN_PALM, 1000);
  sample(HV_HAND_GATE_OPEN_PALM, 1600);
  assert(!palm_events); /* Enough time but only two observations. */
  sample(HV_HAND_GATE_OPEN_PALM, 1700);
  assert(palm_events == 1);
  fist(1900);
  assert(fist_events == 1 && gate.latched == HV_HAND_GATE_CLOSED_FIST);
  palm(2700);
  assert(palm_events == 2 && gate.latched == HV_HAND_GATE_OPEN_PALM);
  puts("PASS another stable class can trigger once without a no-hand gap");

  reset();
  palm(1000);
  sample(HV_HAND_GATE_NO_HAND, 1800);
  sample(HV_HAND_GATE_NO_HAND, 2200);
  assert(gate.latched == HV_HAND_GATE_OPEN_PALM);
  sample(HV_HAND_GATE_NO_HAND, 2300);
  assert(gate.latched == HV_HAND_GATE_UNKNOWN);
  palm(2500);
  assert(palm_events == 2);
  sample(HV_HAND_GATE_OTHER, 3300);
  sample(HV_HAND_GATE_OTHER, 3800);
  assert(gate.latched == HV_HAND_GATE_UNKNOWN);
  palm(4000);
  assert(palm_events == 3);
  puts("PASS fresh no-hand and reliable other release only after 500ms");

  reset();
  palm(1000);
  sample(HV_HAND_GATE_NO_HAND, 1800);
  send(HV_HAND_GATE_NO_HAND, 2100, 2200, false, 0, 0, 0);
  sample(HV_HAND_GATE_NO_HAND, 2400);
  assert(gate.latched == HV_HAND_GATE_OPEN_PALM);
  palm(2600);
  assert(palm_events == 1);
  send(HV_HAND_GATE_OTHER, 3400, 3500, true, 1, .79f, .1f);
  send(HV_HAND_GATE_OTHER, 3900, 4000, true, 1, .79f, .1f);
  assert(gate.latched == HV_HAND_GATE_OPEN_PALM);
  puts("PASS invalid or low-confidence observations cannot bridge a release");

  reset();
  sample(HV_HAND_GATE_OPEN_PALM, 1000);
  sample(HV_HAND_GATE_OPEN_PALM, 1300);
  send(HV_HAND_GATE_OPEN_PALM, 1300, 1450, true, 1, .9f, .1f);
  assert(gate.candidate == HV_HAND_GATE_UNKNOWN);
  sample(HV_HAND_GATE_OPEN_PALM, 1600);
  sample(HV_HAND_GATE_OPEN_PALM, 1900);
  assert(!palm_events);
  sample(HV_HAND_GATE_OPEN_PALM, 2200);
  assert(palm_events == 1);
  hv_hand_gate_invalidate(&gate); /* Producer epoch change. */
  assert(gate.visible == HV_HAND_GATE_UNKNOWN && gate.latched == HV_HAND_GATE_OPEN_PALM);
  palm(2400);
  assert(palm_events == 1);
  puts("PASS duplicate frames cancel candidates; epoch changes retain the latch");

  reset();
  sample(HV_HAND_GATE_OPEN_PALM, 1000);
  send(HV_HAND_GATE_OPEN_PALM, 1300, 1400, false, 1, .9f, .1f);
  palm(1600);
  assert(palm_events == 1);
  send(HV_HAND_GATE_NO_HAND, 2400, 2500, true, 2, 0, 0);
  send(HV_HAND_GATE_NO_HAND, 2900, 3000, true, 2, 0, 0);
  palm(3200);
  assert(palm_events == 1);
  puts("PASS tracking loss cancels a candidate and multiple hands cannot release");

  reset();
  sample(HV_HAND_GATE_OPEN_PALM, 1000);
  hv_hand_gate_tick(&gate, 1900);
  assert(gate.candidate == HV_HAND_GATE_OPEN_PALM);
  hv_hand_gate_tick(&gate, 1901);
  assert(gate.visible == HV_HAND_GATE_UNKNOWN && gate.candidate == HV_HAND_GATE_UNKNOWN);
  sample(HV_HAND_GATE_OPEN_PALM, 1900); /* First post-gap frame is rejected. */
  assert(gate.candidate == HV_HAND_GATE_UNKNOWN);
  palm(2100);
  assert(palm_events == 1);
  hv_hand_gate_tick(&gate, 3601);
  assert(gate.visible == HV_HAND_GATE_UNKNOWN && gate.latched == HV_HAND_GATE_OPEN_PALM);
  sample(HV_HAND_GATE_OPEN_PALM, 3600);
  palm(3800);
  assert(palm_events == 1);
  puts("PASS silence expires display/progress without unlocking or inventing events");

  reset();
  assert(HV_HAND_GATE_MAX_AGE_MS == 1000);
  send(HV_HAND_GATE_OPEN_PALM, 1000, 1000 + HV_HAND_GATE_MAX_AGE_MS, true, 1, .8f, .6f);
  assert(gate.candidate == HV_HAND_GATE_OPEN_PALM); /* Inclusive age/score/margin boundary. */
  send(HV_HAND_GATE_OPEN_PALM, 1400, 1400 + HV_HAND_GATE_MAX_AGE_MS + 1, true, 1, .9f, .1f);
  assert(gate.candidate == HV_HAND_GATE_UNKNOWN); /* 1001ms is stale. */
  send(HV_HAND_GATE_OPEN_PALM, 3001, 3000, true, 1, .9f, .1f);
  assert(gate.visible == HV_HAND_GATE_UNKNOWN);
  send(HV_HAND_GATE_OPEN_PALM, 3100, 3200, true, 1, NAN, .1f);
  send(HV_HAND_GATE_OPEN_PALM, 3400, 3500, true, 1, .9f, NAN);
  send(HV_HAND_GATE_OPEN_PALM, 3700, 3800, true, 1, 1.1f, .1f);
  send(HV_HAND_GATE_OPEN_PALM, 4000, 4100, true, 1, .9f, .71f);
  assert(!palm_events && gate.visible == HV_HAND_GATE_UNKNOWN);
  puts("PASS stale/future timestamps, non-finite scores and insufficient margins reject");

  reset();
  sample(HV_HAND_GATE_CLOSED_FIST, 1000);
  sample(HV_HAND_GATE_CLOSED_FIST, 1300);
  hv_hand_gate_tick(&gate, 1350); /* Clock reversed from last result at 1400. */
  assert(gate.candidate == HV_HAND_GATE_UNKNOWN);
  sample(HV_HAND_GATE_CLOSED_FIST, 1600);
  sample(HV_HAND_GATE_CLOSED_FIST, 1900);
  assert(!fist_events);
  sample(HV_HAND_GATE_CLOSED_FIST, 2200);
  assert(fist_events == 1);
  hv_hand_gate_init(&gate); /* Only an explicit full reset clears the latch. */
  assert(gate.latched == HV_HAND_GATE_UNKNOWN && !gate.have_capture);
  puts("PASS reverse clocks cancel progress; explicit reset clears state");
  reset();
  assert(HV_HAND_GATE_OPEN_PALM == 2 && HV_HAND_GATE_CLOSED_FIST == 3 && HV_HAND_GATE_OTHER == 4);
  assert(HV_HAND_GATE_EVENT_OPEN_PALM == 1 && HV_HAND_GATE_EVENT_CLOSED_FIST == 2);
  assert(strcmp(hv_hand_gate_kind_name(HV_HAND_GATE_V_SIGN), "v_sign") == 0);
  sample(HV_HAND_GATE_V_SIGN, 1000);
  sample(HV_HAND_GATE_V_SIGN, 1100);
  sample(HV_HAND_GATE_V_SIGN, 1200);
  assert(!v_events);
  sample(HV_HAND_GATE_V_SIGN, 1600);
  assert(v_events == 1 && !fist_events && gate.latched == HV_HAND_GATE_V_SIGN);
  for (uint64_t t = 1800; t <= 2400; t += 200) sample(HV_HAND_GATE_V_SIGN, t);
  assert(v_events == 1);
  fist(2600); palm(3400); v_sign(4200);
  assert(fist_events == 1 && palm_events == 1 && v_events == 2);
  puts("PASS V sign has its own event, stable hold and retained legacy palm/fist values");

  reset();
  sample(HV_HAND_GATE_V_SIGN, 1000);
  sample(HV_HAND_GATE_V_SIGN, 1300);
  send(HV_HAND_GATE_V_SIGN, 1600, 1700, true, 2, .9f, .1f);
  assert(!v_events && gate.candidate == HV_HAND_GATE_UNKNOWN);
  send(HV_HAND_GATE_V_SIGN, 1900, 2000, true, 1, .79f, .1f);
  send(HV_HAND_GATE_V_SIGN, 2200, 2300, true, 1, .9f, .71f);
  send(HV_HAND_GATE_V_SIGN, 2500, 2500 + HV_HAND_GATE_MAX_AGE_MS + 1, true, 1, .9f, .1f);
  assert(!v_events && gate.candidate == HV_HAND_GATE_UNKNOWN);
  sample(HV_HAND_GATE_V_SIGN, 3600); /* First post-gap frame only advances capture. */
  v_sign(3700);
  assert(v_events == 1 && gate.latched == HV_HAND_GATE_V_SIGN);
  puts("PASS V sign shares multi-hand, score, margin and freshness rejection rules");

  hv_hand_gate_invalidate(&gate);
  assert(gate.visible == HV_HAND_GATE_UNKNOWN && gate.latched == HV_HAND_GATE_V_SIGN);
  v_sign(4500);
  assert(v_events == 1);
  sample(HV_HAND_GATE_OTHER, 5300);
  sample(HV_HAND_GATE_OTHER, 5800);
  assert(gate.latched == HV_HAND_GATE_UNKNOWN);
  v_sign(6000);
  assert(v_events == 2);
  sample(HV_HAND_GATE_NO_HAND, 6800);
  sample(HV_HAND_GATE_NO_HAND, 7300);
  v_sign(7500);
  assert(v_events == 3 && !fist_events && !palm_events);
  puts("PASS V sign survives epoch invalidation and requires reliable release before repetition");
  reset();
  send(HV_HAND_GATE_V_SIGN, 1000, 1450, true, 1, .9f, .1f);
  send(HV_HAND_GATE_V_SIGN, 1450, 1900, true, 1, .9f, .1f);
  assert(!v_events && gate.samples == 2);
  send(HV_HAND_GATE_V_SIGN, 1900, 2350, true, 1, .9f, .1f);
  assert(v_events == 1 && gate.latched == HV_HAND_GATE_V_SIGN);
  assert(gate.last_capture_ms == 1900 && gate.last_received_ms == 2350);
  hv_hand_gate_tick(&gate, 2400);
  hv_hand_gate_tick(&gate, 2800);
  hv_hand_gate_tick(&gate, 3150);
  assert(gate.visible == HV_HAND_GATE_V_SIGN && gate.last_received_ms == 2350);
  hv_hand_gate_tick(&gate, 3151);
  assert(gate.visible == HV_HAND_GATE_UNKNOWN && gate.latched == HV_HAND_GATE_V_SIGN);
  puts("PASS 450ms inference and frame spacing confirm; periodic ticks do not extend arrival freshness");

  reset();
  send(HV_HAND_GATE_V_SIGN, 1000, 1450, true, 1, .9f, .1f);
  send(HV_HAND_GATE_V_SIGN, 1450, 1900, true, 1, .9f, .1f);
  send(HV_HAND_GATE_V_SIGN, 2301, 2751, true, 1, .9f, .1f);
  assert(!v_events && gate.candidate == HV_HAND_GATE_UNKNOWN);
  assert(gate.last_capture_ms == 2301 && gate.last_received_ms == 1900);
  send(HV_HAND_GATE_V_SIGN, 2601, 3051, true, 1, .9f, .1f);
  send(HV_HAND_GATE_V_SIGN, 2901, 3351, true, 1, .9f, .1f);
  assert(!v_events);
  send(HV_HAND_GATE_V_SIGN, 3201, 3651, true, 1, .9f, .1f);
  assert(v_events == 1);
  send(HV_HAND_GATE_NO_HAND, 3501, 3951, false, 0, 0, 0);
  assert(gate.last_received_ms == 3651 && gate.last_now_ms == 3951);
  puts("PASS capture gaps above 800ms restart confirmation and invalid input does not refresh arrival");
  return 0;
}
'''


class HandGateTests(unittest.TestCase):
    def test_production_gate(self):
        with tempfile.TemporaryDirectory(prefix="hand-gate-test-") as temp:
            directory = Path(temp)
            harness = directory/"test.c"
            harness.write_text(HARNESS, encoding="utf-8")
            binary = directory/"test"
            subprocess.run([shutil.which("cc") or "clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                            "-Werror", "-UNDEBUG", "-I", str(ROOT/"headvoice/core"), str(harness),
                            str(ROOT/"headvoice/core/hv_hand_gate.c"), "-o", str(binary), "-lm"], check=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.count("PASS "), 14)


if __name__ == "__main__":
    unittest.main()

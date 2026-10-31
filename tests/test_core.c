#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "hv_core.h"
#ifdef NDEBUG
#error "Tests require enabled assertions"
#endif

static hv_core_t core;
static uint64_t now;
static unsigned plays, candidates, actions;
static int lastPhrase;

static hv_effect_t sample(float tilt, bool valid)
{
  now += 100;
  hv_observation_t observation = {now, tilt, valid};
  hv_effect_t out = hv_observe(&core, observation, now);
  plays += out.event == HV_PLAY;
  candidates += out.event == HV_CANDIDATE;
  actions += out.event == HV_ACTION || out.event == HV_CANDIDATE;
  if (out.event == HV_CANDIDATE) lastPhrase = out.phrase;
  return out;
}

static void frames(float tilt, unsigned count)
{
  for (unsigned i = 0; i < count; i++) sample(tilt, true);
}

static void setup(void)
{
  hv_init(&core, NULL);
  now = 1000;
  plays = candidates = actions = 0;
  lastPhrase = -1;
  frames(3, 30);
  assert(core.state == HV_COLLECT);
  assert(fabsf(core.baseline - 3) < 0.001f);
}

static void gesture(char action)
{
  frames(action == 'A' ? 23 : -17, 8);
  frames(3, 5);
}

static void candidate(char a, char b)
{
  gesture(a);
  gesture(b);
  assert(candidates == 1 && core.state == HV_REVIEW_REARM);
  assert(plays == 0);
}

int main(void)
{
  float angle;
  assert(hv_eye_tilt(10, 10, 30, 20, &angle) && angle > 26 && angle < 27);
  assert(hv_eye_tilt(30, 20, 10, 10, &angle) && angle > 26 && angle < 27);
  assert(hv_eye_tilt(10, 20, 30, 10, &angle) && angle < -26);
  assert(!hv_eye_tilt(1, 1, 1, 1, &angle));
  assert(!hv_eye_tilt(NAN, 1, 4, 5, &angle));
  for (int phrase = 0; phrase < 4; phrase++) {
    setup();
    candidate(phrase < 2 ? 'A' : 'B', phrase % 2 ? 'B' : 'A');
    assert(lastPhrase == phrase && strlen(hv_phrase(phrase)) > 0);
    assert(strcmp(hv_code(phrase), (const char *[]){"AA", "AB", "BA", "BB"}[phrase]) == 0);
    frames(23, 9); /* Last code action cannot become a confirmation. */
    frames(3, 5);
    assert(plays == 0 && core.state == HV_REVIEW);
    gesture('A');
    assert(plays == 1 && core.state == HV_SPEAKING);
    gesture('A');
    assert(plays == 1);
    hv_playback_done(&core, core.ticket + 1, now);
    assert(core.state == HV_SPEAKING);
    hv_playback_done(&core, core.ticket, now);
    frames(23, 10);
    assert(core.state == HV_REARM);
    frames(3, 5);
    assert(core.state == HV_COLLECT);
  }
  puts("PASS four mappings, confirmation barrier, playback rearm, stale completion");
  setup();
  frames(23, 40);
  assert(actions == 0 && candidates == 0 && plays == 0);
  frames(3, 5);
  assert(actions == 1);
  puts("PASS sustained tilt is consumed once only after return");
  for (int direction = -1; direction <= 1; direction += 2) {
    setup();
    frames(3 + direction * 20, 8);
    frames(3 + direction * 12, 4);
    frames(3 + direction * 10, 3);
    frames(3 + direction * 8, 3);
    assert(actions == 0);
    frames(3, 5);
    assert(actions == 1 && core.first == (direction < 0));
    frames(3, 10);
    assert(actions == 1);
    setup();
    frames(3 + direction * 20, 3); /* An incomplete hold cannot be rescued. */
    frames(3 + direction * 12, 4);
    frames(3, 5);
    assert(actions == 0);
    setup();
    frames(3 + direction * 20, 8);
    frames(3 + direction * 12, 51); /* The return must still finish in time. */
    frames(3, 5);
    assert(actions == 0);
    setup();
    frames(3 + direction * 20, 8);
    frames(3 + direction * 12, 3);
    sample(3, false);
    frames(3, 6);
    assert(actions == 0);
  }
  puts("PASS gradual return, incomplete hold, return timeout and tracking loss");
  setup();
  candidate('A', 'A');
  frames(3, 5);
  gesture('B');
  assert(plays == 0 && core.state == HV_REARM);
  frames(3, 5);
  gesture('B');
  assert(candidates == 1 && core.first == 1);
  puts("PASS cancellation clears candidate");
  setup();
  gesture('A');
  sample(0, false); /* Covers occlusion, multiple people and invalid keypoints. */
  frames(3, 6);
  gesture('B');
  assert(candidates == 0 && core.first == 1);
  puts("PASS invalid tracking never joins pre-loss and post-loss input");
  setup();
  candidate('A', 'A');
  sample(0, false);
  frames(3, 6);
  gesture('A');
  assert(plays == 0 && candidates == 1 && core.first == 0);
  puts("PASS occlusion revokes pending confirmation");
  setup();
  candidate('A', 'A');
  now += 500;
  hv_tick(&core, now);
  assert(core.state == HV_REARM && core.phrase == -1);
  frames(3, 6);
  gesture('A');
  assert(plays == 0 && core.first == 0);
  puts("PASS camera silence immediately after candidate revokes review rearm");
  setup();
  gesture('A');
  frames(3, 85);
  gesture('B');
  assert(candidates == 0 && core.first == 1);
  setup();
  candidate('A', 'A');
  frames(3, 105);
  gesture('A');
  assert(plays == 0);
  puts("PASS combination and confirmation timeouts");
  setup();
  frames(23, 2);
  now += 700;
  hv_tick(&core, now);
  frames(23, 8);
  frames(3, 6);
  assert(actions == 0);
  setup();
  gesture('A');
  now += 700;
  hv_observation_t old = {now - 500, -17, true};
  hv_observe(&core, old, now);
  frames(3, 6);
  gesture('B');
  assert(candidates == 0);
  puts("PASS watchdog and aged observations clear partial input");
  setup();
  frames(23, 3);
  hv_observation_t duplicate = {now, 23, true};
  hv_observe(&core, duplicate, now);
  frames(23, 8);
  frames(3, 6);
  assert(actions == 0);
  setup();
  frames(23, 2);
  frames(-17, 8);
  frames(3, 6);
  assert(actions == 0);
  puts("PASS duplicate frames and direction switches cannot complete gestures");
  hv_init(&core, NULL);
  frames(0, 8);
  sample(20, true);
  frames(0, 8);
  assert(core.state == HV_CALIBRATING);
  now += 3000;
  hv_tick(&core, now);
  assert(core.state == HV_CALIBRATING);
  frames(0, 30);
  assert(core.state == HV_COLLECT);
  puts("PASS calibration requires continuous stable observations");
  puts("All production-core tests passed (synthetic observations, no hardware claim).");
  return 0;
}

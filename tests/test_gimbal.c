#include <assert.h>
#include <math.h>
#include <stdio.h>

#include "hv_gimbal_core.h"

static HvGimbalResult observe(hv_gimbal_t * c, float x, float y, uint64_t time)
{
  return hv_gimbal_observe(c, 1, true, x, y, time, time + 2700);
}

int main(void)
{
  hv_gimbal_t c;
  hv_gimbal_reset(&c);
  assert(observe(&c, 0.9f, 0.5f, 1000) == HV_GIMBAL_WAIT);
  assert(c.pulse[0] == 1500);
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, 0.9f, 0.5f, 1000) == HV_GIMBAL_MOVE);
  assert(c.pulse[0] == 1535 && c.pulse[1] == 1500);
  assert(observe(&c, 0.9f, 0.5f, 1100) == HV_GIMBAL_STALE);
  assert(c.pulse[0] == 1535);
  hv_gimbal_reset(&c);
  c.direction[1] = -1;
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, 0.5f, 0.9f, 1000) == HV_GIMBAL_MOVE);
  assert(c.pulse[1] == 1465);
  for (unsigned people = 0; people <= 2; people += 2) {
    hv_gimbal_reset(&c);
    hv_gimbal_begin(&c, 0);
    assert(hv_gimbal_observe(&c, people, true, 0.9f, 0.5f, 1000, 3700) == HV_GIMBAL_NO_FACE);
    assert(!c.active && c.pulse[0] == 1500);
  }
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, NAN, 0.5f, 1000) == HV_GIMBAL_NO_FACE);
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, 0.5f, 0.5f, 1000) == HV_GIMBAL_WAIT);
  assert(observe(&c, 0.5f, 0.5f, 1000) == HV_GIMBAL_STALE);
  assert(observe(&c, 0.5f, 0.5f, 5000) == HV_GIMBAL_WAIT);
  assert(observe(&c, 0.5f, 0.5f, 9000) == HV_GIMBAL_CENTERED);
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  c.pulse[0] = 1690;
  assert(observe(&c, 0.9f, 0.5f, 1000) == HV_GIMBAL_LIMIT);
  assert(c.pulse[0] == 1690);
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, 0.65f, 0.5f, 1000) == HV_GIMBAL_MOVE);
  assert(observe(&c, 0.72f, 0.5f, 5000) == HV_GIMBAL_MOVE);
  assert(observe(&c, 0.79f, 0.5f, 9000) == HV_GIMBAL_WRONG_DIRECTION);
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  assert(observe(&c, 0.9f, 0.5f, 90000) == HV_GIMBAL_TIMEOUT);
  hv_gimbal_reset(&c);
  hv_gimbal_begin(&c, 0);
  uint64_t time = 1000;
  while (c.active) {
    float x = 0.7f - 0.002f * (c.pulse[0] - 1500);
    float y = 0.3f - 0.002f * (c.pulse[1] - 1500);
    HvGimbalResult result = observe(&c, x, y, time);
    assert(result == HV_GIMBAL_MOVE || result == HV_GIMBAL_WAIT || result == HV_GIMBAL_CENTERED);
    time += 4000;
  }
  assert(c.centered == 3 && c.steps <= 20);
  hv_gimbal_reset(&c);
  c.minPulseUs = 1475;
  c.maxPulseUs = 1525;
  c.maxStepUs = 25;
  c.maxAgeMs = 400;
  hv_gimbal_begin(&c, 0);
  assert(hv_gimbal_observe(&c, 1, true, 0.9f, 0.5f, 1000, 1401) == HV_GIMBAL_STALE);
  assert(c.pulse[0] == 1500);
  assert(hv_gimbal_observe(&c, 1, true, 0.9f, 0.5f, 1500, 1700) == HV_GIMBAL_MOVE);
  assert(c.pulse[0] == 1525 && c.steps == 1);
  assert(hv_gimbal_observe(&c, 1, true, 0.9f, 0.5f, 2000, 2200) == HV_GIMBAL_STALE);
  assert(c.pulse[0] == 1525);
  assert(hv_gimbal_observe(&c, 1, true, 0.9f, 0.5f, 2300, 2500) == HV_GIMBAL_LIMIT);
  assert(!c.active && c.pulse[0] == 1525);
  hv_gimbal_reset(&c);
  c.minPulseUs = 1475;
  c.maxPulseUs = 1525;
  c.maxStepUs = 25;
  c.maxAgeMs = 400;
  hv_gimbal_begin(&c, 0);
  assert(hv_gimbal_observe(&c, 1, true, 0.5f, 0.5f, 1000, 1200) == HV_GIMBAL_WAIT);
  assert(hv_gimbal_observe(&c, 1, true, 0.5f, 0.5f, 1100, 1300) == HV_GIMBAL_WAIT);
  assert(hv_gimbal_observe(&c, 1, true, 0.5f, 0.5f, 1200, 1400) == HV_GIMBAL_CENTERED);
  puts("Gimbal core: limits, stale data, target loss, direction, and convergence passed");
  return 0;
}

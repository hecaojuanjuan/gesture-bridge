"""Exercise automatic reacquisition and stop behavior with real controller C."""
from test_face_gimbal_firmware import HARNESS, run_harness


SCENARIOS = r'''
static void observe(uint64_t t, HvGimbalTarget source, unsigned count,
                    bool valid, float x, float y) {
  now_ms = t;
  hv_face_gimbal_observe_target(source, count, valid, x, y, t - 50, t);
}

int main(void) {
  now_ms = 1000;
  assert(hv_face_gimbal_init() == 0);
  send("auto", "on", NULL);
  observe(1100, HV_GIMBAL_TARGET_HAND, 1, true, .8f, .5f);
  assert(!active[0] && !active[1]);
  send("arm", "pan", NULL);
  send("arm", "tilt", NULL);
  send("dir", "1", "1");
  send("auto", "on", NULL);
  observe(1700, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  observe(1900, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(!hv_face_gimbal_active());
  observe(2100, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(hv_face_gimbal_active());
  observe(2700, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  observe(2900, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  observe(3100, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  observe(3400, HV_GIMBAL_TARGET_HAND, 1, true, .64f, .5f);
  assert(hv_face_gimbal_active());
  observe(4000, HV_GIMBAL_TARGET_HAND, 1, true, .64f, .5f);
  int moved_duty = duty[0];
  assert(moved_duty > 1500 * 16383 / 20000);
  now_ms = 6001;
  hv_face_gimbal_tick(now_ms);
  assert(!active[0] && !active[1] && !hv_face_gimbal_active());
  observe(6200, HV_GIMBAL_TARGET_FACE, 1, true, .5f, .5f);
  observe(6400, HV_GIMBAL_TARGET_FACE, 1, true, .5f, .5f);
  assert(!active[0] && !active[1]);
  observe(6600, HV_GIMBAL_TARGET_FACE, 1, true, .5f, .5f);
  assert(active[0] && active[1] && duty[0] == moved_duty);
  observe(7200, HV_GIMBAL_TARGET_FACE, 1, true, .5f, .5f);
  observe(7400, HV_GIMBAL_TARGET_HAND, 2, false, 0, 0);
  observe(7600, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(hv_face_gimbal_active()); /* Invalid/source change resets centered streak. */
  observe(7800, HV_GIMBAL_TARGET_HAND, 1, true, .9f, .5f);
  assert(!hv_face_gimbal_active() && !active[0] && !active[1]);
  for (int i = 0; i < 6; ++i)
    observe(8100 + i * 200, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(!active[0] && !active[1]); /* A pulse limit never retries automatically. */
  send("arm", "pan", NULL); send("arm", "tilt", NULL);
  send("dir", "1", "-1"); send("auto", "on", NULL);
  send("stop", NULL, NULL);
  for (int i = 0; i < 6; ++i)
    observe(10000 + i * 200, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(!active[0] && !active[1]);
  send("arm", "pan", NULL); send("arm", "tilt", NULL);
  send("dir", "1", "-1"); send("auto", "on", NULL);
  hv_face_gimbal_invalidate();
  for (int i = 0; i < 6; ++i)
    observe(12000 + i * 200, HV_GIMBAL_TARGET_HAND, 1, true, .5f, .5f);
  assert(!active[0] && !active[1]);
  puts("Automatic gimbal scenarios passed");
  return 0;
}
'''


def main():
    output = run_harness(HARNESS.split("int main(void)")[0] + SCENARIOS,
                         ["-DHV_CENTERING=1"])
    assert '"source":"hand"' in output
    assert '"source":"face"' in output
    assert "GIMBAL STOP pulse_limit" in output
    assert "Automatic gimbal scenarios passed" in output
    print("PASS automatic acquire, hold, drift, loss/reacquire, limits, stop, camera fault")


if __name__ == "__main__":
    main()

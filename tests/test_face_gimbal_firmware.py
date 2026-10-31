"""Host-simulate the face gimbal's PWM lease and stop behavior."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    "esp_err.h": """typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM -2
""",
    "esp_timer.h": """#include <stdint.h>
int64_t esp_timer_get_time(void);
""",
    "freertos/FreeRTOS.h": """#define portMAX_DELAY 0xffffffffu
""",
    "freertos/semphr.h": """typedef void *SemaphoreHandle_t;
SemaphoreHandle_t xSemaphoreCreateMutex(void);
int xSemaphoreTake(SemaphoreHandle_t, unsigned);
int xSemaphoreGive(SemaphoreHandle_t);
void vSemaphoreDelete(SemaphoreHandle_t);
""",
    "driver/ledc.h": """#include "esp_err.h"
typedef int ledc_channel_t;
#define LEDC_LOW_SPEED_MODE 0
#define LEDC_TIMER_14_BIT 14
#define LEDC_TIMER_0 0
#define LEDC_AUTO_CLK 0
#define LEDC_INTR_DISABLE 0
typedef struct {int speed_mode, duty_resolution, timer_num, freq_hz, clk_cfg;} ledc_timer_config_t;
typedef struct {int gpio_num, speed_mode, channel, intr_type, timer_sel, duty, hpoint;}
    ledc_channel_config_t;
esp_err_t ledc_timer_config(const ledc_timer_config_t *);
esp_err_t ledc_channel_config(const ledc_channel_config_t *);
esp_err_t ledc_set_duty(int, ledc_channel_t, unsigned);
esp_err_t ledc_update_duty(int, ledc_channel_t);
esp_err_t ledc_stop(int, ledc_channel_t, unsigned);
""",
    "qm_cli.h": """struct qm_cli_command {
  const char *name, *help;
  void (*function)(char *, int, int, char **);
};
int qm_cli_register_command(const struct qm_cli_command *);
""",
}
HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/semphr.h"
#include "hv_face_gimbal.h"
#include "qm_cli.h"

static uint64_t now_ms;
static int active[2], duty[2], stops[2];
static const struct qm_cli_command *cli;
int64_t esp_timer_get_time(void) { return (int64_t)now_ms * 1000; }
SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(SemaphoreHandle_t s, unsigned timeout) { (void)s; (void)timeout; return 1; }
int xSemaphoreGive(SemaphoreHandle_t s) { (void)s; return 1; }
void vSemaphoreDelete(SemaphoreHandle_t s) { (void)s; }
esp_err_t ledc_timer_config(const ledc_timer_config_t *c) { assert(c->freq_hz == 50); return 0; }
esp_err_t ledc_channel_config(const ledc_channel_config_t *c) {
  assert(c->gpio_num == 17 + c->channel && c->duty == 0); return 0;
}
esp_err_t ledc_set_duty(int mode, ledc_channel_t channel, unsigned value) {
  (void)mode; duty[channel] = (int)value; return 0;
}
esp_err_t ledc_update_duty(int mode, ledc_channel_t channel) {
  (void)mode; active[channel] = duty[channel] > 0; return 0;
}
esp_err_t ledc_stop(int mode, ledc_channel_t channel, unsigned idle) {
  (void)mode; (void)idle; active[channel] = 0; ++stops[channel]; return 0;
}
int qm_cli_register_command(const struct qm_cli_command *command) { cli = command; return 0; }

static void send(const char *one, const char *two, const char *three)
{
  char *args[4] = {"hv_gimbal", (char *)one, (char *)two, (char *)three};
  cli->function(NULL, 0, two ? (three ? 4 : 3) : 2, args);
}

int main(void)
{
  now_ms = 1000;
  assert(hv_face_gimbal_init() == 0 && cli);
  assert(!active[0] && !active[1] && stops[0] && stops[1]);
  send("start", NULL, NULL);
  assert(!hv_face_gimbal_active());
  hv_face_gimbal_observe(1, true, 0.5f, 0.5f, 900, 1000);
  send("target", NULL, NULL);
  now_ms = 1500;
  send("target", NULL, NULL);

  now_ms = 2000;
  send("arm", "pan", NULL);
  assert(active[0] && !active[1]);
  now_ms = 2100;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 2050, 2100);
  send("target", NULL, NULL); /* Old image during servo settling is rejected. */
  now_ms = 2600;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 2550, 2600);
  send("target", NULL, NULL);
  hv_face_gimbal_tick(12001);
  assert(!active[0] && !active[1]);

  now_ms = 13000;
  send("arm", "pan", NULL);
  send("arm", "tilt", NULL);
  send("dir", "1", "1");
  send("start", NULL, NULL); /* Firmware must reject missing target, even without host guard. */
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  now_ms = 13100;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 13050, 13100);
  send("target", NULL, NULL); /* Fresh frame taken before servo settle is unusable. */
  send("start", NULL, NULL);
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  now_ms = 13600;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 13550, 13600);
  send("target", NULL, NULL);
  int pan_stops = stops[0], tilt_stops = stops[1];
  hv_face_gimbal_clear_target(); /* Epoch change drops only the cached target. */
  send("target", NULL, NULL);
  assert(active[0] && active[1] && stops[0] == pan_stops && stops[1] == tilt_stops);
  send("start", NULL, NULL); /* Cleared target cannot start with stale coordinates. */
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  now_ms = 13700;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 13650, 13700);
  now_ms = 14101;
  send("start", NULL, NULL); /* Cached face expires before start. */
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  now_ms = 14200;
  hv_face_gimbal_observe(1, true, 0.4f, 0.6f, 14150, 14200);
  send("start", NULL, NULL);
  assert(hv_face_gimbal_active());
  now_ms = 14800;
  hv_face_gimbal_observe(0, false, 0, 0, 14700, 14800);
  assert(hv_face_gimbal_active() && active[0] && active[1]);
  hv_face_gimbal_tick(15201);
  assert(!hv_face_gimbal_active() && !active[0] && !active[1]);

  now_ms = 20000;
  send("arm", "pan", NULL);
  send("arm", "tilt", NULL);
  send("dir", "1", "1");
  now_ms = 20500;
  hv_face_gimbal_observe(1, true, 0.5f, 0.5f, 20480, 20500);
  send("start", NULL, NULL);
  for (int i = 0; i < 3; ++i) {
    now_ms = 21100 + (uint64_t)i * 100;
    hv_face_gimbal_observe(1, true, 0.5f, 0.5f, now_ms - 100, now_ms);
  }
  assert(!hv_face_gimbal_active() && active[0] && active[1]);
  hv_face_gimbal_tick(81299);
  assert(active[0] && active[1]);
  hv_face_gimbal_tick(81301);
  assert(!active[0] && !active[1]);
  puts("Face gimbal host simulation passed");
  return 0;
}
"""


def run_harness(source=HARNESS, extra_flags=()):
    with tempfile.TemporaryDirectory(prefix="face-gimbal-") as directory:
        temp = Path(directory)
        for name, header in HEADERS.items():
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(header, encoding="utf-8")
        harness = temp / "harness.c"
        harness.write_text(source, encoding="utf-8")
        binary = temp / "test_face_gimbal.exe"
        subprocess.run([
            shutil.which("cc") or shutil.which("gcc") or "cc",
            "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG", *extra_flags,
            "-I", str(temp), "-I", str(ROOT / "headvoice/firmware"),
            "-I", str(ROOT / "headvoice/core"),
            str(ROOT / "headvoice/firmware/hv_face_gimbal.c"),
            str(ROOT / "headvoice/core/hv_gimbal_core.c"), str(harness),
            "-lm", "-o", str(binary)], check=True)
        output = subprocess.check_output([str(binary)], text=True)
    return output


def main():
    output = run_harness()
    targets = [json.loads(line[7:]) for line in output.splitlines()
               if line.startswith("GIMBAL {\"event\":\"target\"")]
    assert [item["valid"] for item in targets] == [True, False, False, True, False, True, False], targets
    assert output.count("GIMBAL ERROR fresh_single_face_target_required") == 4
    assert "GIMBAL STOP idle_arm_lease_expired" in output
    assert "GIMBAL STOP lost_target_or_frame" in output
    assert "GIMBAL STOP centered_hold_expired" in output
    assert "Face gimbal host simulation passed" in output
    print("Face gimbal: default off, target TTL/epoch clear, start guard, PWM lease/stop passed")


if __name__ == "__main__":
    main()

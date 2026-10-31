"""Exercise production HP/cloud pose reports with task and SDK calls stubbed.

This checks the firmware's reporting contract, not camera timing or cloud delivery.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUBS = r"""
#ifndef PANEL_TEST_STUBS_H
#define PANEL_TEST_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
typedef int portMUX_TYPE;
typedef void *QueueHandle_t;
#define portMUX_INITIALIZER_UNLOCKED 0
void test_enter(portMUX_TYPE *);
void test_exit(portMUX_TYPE *);
#define portENTER_CRITICAL(p) test_enter(p)
#define portEXIT_CRITICAL(p) test_exit(p)
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(ms) (ms)
#define QM_EOK 0
#define QM_ENOMEM 12
#define QM_SPEC_PROPERTY_FORMAT_STRING 1
typedef struct { int siid, piid; struct {int property_format, len;} value; } qm_spec_property_t;
typedef struct { int unused; } qm_spec_property_operation_t;
int qm_spec_property_unpack_string_direct(qm_spec_property_t *, char **, int *);
qm_spec_property_operation_t *qm_spec_property_operation_creat(void);
void qm_spec_property_operation_delete(qm_spec_property_operation_t *);
qm_spec_property_t *qm_spec_property_creat(void);
void qm_spec_property_delete(qm_spec_property_t *);
void qm_spec_property_pack_xiid(qm_spec_property_t *, int, int);
void qm_spec_property_pack_string(qm_spec_property_t *, const char *, int);
void qm_spec_property_add(qm_spec_property_operation_t *, qm_spec_property_t *);
void *ljyd_cloud_get_handle(void);
int qm_iot_report(void *, qm_spec_property_operation_t *);
int bsp_ws2812_init(void);
int bsp_ws2812_fill(uint8_t, uint8_t, uint8_t);
uint32_t esp_random(void);
unsigned esp_reset_reason(void);
int64_t esp_timer_get_time(void);
QueueHandle_t xQueueCreate(unsigned, unsigned);
int xQueueSend(QueueHandle_t, const void *, unsigned);
int xQueueReceive(QueueHandle_t, void *, unsigned);
void vQueueDelete(QueueHandle_t);
int xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, void *);
void vTaskDelay(unsigned);
int capture_printf(const char *, ...);
#define printf capture_printf
struct qm_cli_command { const char *name, *help; void (*function)(char *, int, int, char **); };
int qm_cli_register_command(const struct qm_cli_command *);
#define qm_cli_printf capture_printf
#endif
"""

HARNESS = r"""
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "hv_panel.c"

static uint64_t clock_ms;
static int critical_depth, max_critical_depth, invalidate_on_fill;
static portMUX_TYPE *outer_guard;
static unsigned s_epoch;
static portMUX_TYPE app_guard;
static jmp_buf cycle_end;
static char serial_output[2048], cloud_output[2048];
static size_t output_length;
static unsigned reports;

/* APP_EPOCH_FUNCTION */

static void app_report(uint64_t captured, unsigned result_epoch, bool tracking, bool fresh) {
  struct {
    unsigned people, inferenceMs, epoch;
    struct { uint64_t capturedMs; float tiltDegrees; bool valid; } observation;
  } result = {1, 100, result_epoch, {captured, 13, tracking}};
  /* APP_POSE_CALL */
}

void test_enter(portMUX_TYPE *guard) {
  if (critical_depth == 0) outer_guard = guard;
  else assert(critical_depth == 1 && outer_guard == &app_guard && guard == &s_guard);
  ++critical_depth;
  if (critical_depth > max_critical_depth) max_critical_depth = critical_depth;
}
void test_exit(portMUX_TYPE *guard) {
  assert(critical_depth > 0 && guard == (critical_depth == 2 ? &s_guard : outer_guard));
  --critical_depth;
}
int capture_printf(const char *format, ...) {
  va_list args; va_start(args, format);
  int n = vsnprintf(serial_output + output_length, sizeof(serial_output) - output_length, format, args);
  va_end(args);
  assert(n >= 0 && (size_t)n < sizeof(serial_output) - output_length);
  output_length += (size_t)n; return n;
}
uint32_t esp_random(void) { return 1234; }
unsigned esp_reset_reason(void) { return 1; }
int64_t esp_timer_get_time(void) { return (int64_t)clock_ms * 1000; }
int bsp_ws2812_init(void) { return 0; }
int bsp_ws2812_fill(uint8_t r, uint8_t g, uint8_t b) {
  (void)r; (void)g; (void)b;
  if (invalidate_on_fill) {
    invalidate_on_fill = 0;
    app_epoch(true); /* After panel_task copied the old input, before its HP JSON. */
  }
  return 0;
}
QueueHandle_t xQueueCreate(unsigned count, unsigned size) {
  assert(count == 4 && size == sizeof(hv_light_command_t)); return (void *)1;
}
int xQueueSend(QueueHandle_t queue, const void *data, unsigned wait) {
  (void)queue; (void)data; (void)wait; return 1;
}
int xQueueReceive(QueueHandle_t queue, void *data, unsigned wait) {
  (void)queue; (void)wait;
  hv_light_command_t *command = data;
  memset(command, 0, sizeof(*command)); command->id = ++reports;
  command->operation = HV_LIGHT_QUERY; return 1;
}
void vQueueDelete(QueueHandle_t queue) { (void)queue; }
int xTaskCreate(void (*task)(void *), const char *name, unsigned size, void *arg,
                unsigned priority, void *handle) {
  (void)name; (void)size; (void)arg; (void)priority; (void)handle;
  assert(task == panel_task); return pdPASS;
}
void vTaskDelay(unsigned delay) {
  assert(delay == 50 && critical_depth == 0); longjmp(cycle_end, 1);
}
int qm_cli_register_command(const struct qm_cli_command *command) {
  assert(strcmp(command->name, "hv_panel") == 0); return 0;
}
int qm_spec_property_unpack_string_direct(qm_spec_property_t *p, char **bytes, int *length) {
  (void)p; (void)bytes; (void)length; return -1;
}
qm_spec_property_operation_t *qm_spec_property_operation_creat(void) {
  static qm_spec_property_operation_t operation; return &operation;
}
void qm_spec_property_operation_delete(qm_spec_property_operation_t *op) { (void)op; }
qm_spec_property_t *qm_spec_property_creat(void) { static qm_spec_property_t property; return &property; }
void qm_spec_property_delete(qm_spec_property_t *property) { (void)property; }
void qm_spec_property_pack_xiid(qm_spec_property_t *property, int siid, int piid) {
  assert(siid == 12 && piid == 2); property->siid = siid; property->piid = piid;
}
void qm_spec_property_pack_string(qm_spec_property_t *property, const char *text, int length) {
  assert(length > 0 && (size_t)length < sizeof(cloud_output));
  memcpy(cloud_output, text, (size_t)length); cloud_output[length] = 0;
  property->value.len = length;
}
void qm_spec_property_add(qm_spec_property_operation_t *op, qm_spec_property_t *property) {
  assert(op && property->siid == 12 && property->piid == 2);
}
void *ljyd_cloud_get_handle(void) { return (void *)1; }
int qm_iot_report(void *handle, qm_spec_property_operation_t *op) {
  assert(handle && op && critical_depth == 0); return 0;
}
static void cycle(uint64_t now) {
  clock_ms = now; output_length = 0; serial_output[0] = cloud_output[0] = 0;
  if (setjmp(cycle_end) == 0) panel_task(NULL);
  assert(output_length > 4 && serial_output[output_length - 1] == '\n');
  serial_output[output_length - 1] = 0;
  assert(strcmp(serial_output + 3, cloud_output) == 0); /* Both transports use the same JSON. */
  puts(serial_output);
}
int main(void) {
  assert(hv_panel_init() == 0);
  cycle(100); /* Baseline has no pose producer. */
  hv_panel_pose(1, 0, 0, 0, false, false, 0, app_epoch(false)); cycle(500);
  hv_panel_pose(2, 1000, 1, 12, true, true, 100, 0); cycle(1100);
  /* Eye points are sound but the core rejected this result despite age 100. */
  app_report(1100, 0, true, false); cycle(1200);
  hv_panel_pose(2, 1200, 1, 14, true, true, 100, 0); cycle(1300);
  invalidate_on_fill = 1; cycle(1301);
  assert(app_epoch(false) == 1 && max_critical_depth == 2);
  hv_panel_pose(2, 1250, 1, 15, true, true, 100, 0); cycle(1350); /* Late old epoch. */
  app_report(1350, 1, true, true); cycle(1450); /* Fresh recovery. */
  cycle(1750); cycle(1751); /* The 400 ms boundary is unchanged. */
  hv_panel_pose(2, 2000, 1, 17, true, true, 100, 1); cycle(1900); /* Future capture. */
  hv_panel_pose(2, 2000, 1, NAN, true, true, 100, 1); cycle(2100);
  hv_panel_pose(2, 2100, 0, 0, false, true, 100, 1); cycle(2200);
  unsigned superseded = app_epoch(true);
  unsigned current = app_epoch(true);
  hv_panel_pose(2, 2200, 1, 18, true, true, 100, superseded); cycle(2300);
  hv_panel_pose(2, 2300, 1, 19, true, true, 100, current); cycle(2400);
  {
    /* The core read seenEpoch, then invalidation raced with receiving its
     * queued result. Compile the real fresh decision, not a test imitation. */
    unsigned seenEpoch = app_epoch(false);
    uint64_t now = 2500;
    struct { struct { unsigned maxAgeMs; } config; } core = {{400}};
    struct {
      unsigned people, inferenceMs, epoch;
      struct { uint64_t capturedMs; float tiltDegrees; bool valid; } observation;
    } result = {1, 100, seenEpoch, {2400, 20, true}};
    app_epoch(true);
    /* APP_FRESH_DECISION */
    assert(!fresh);
    /* APP_POSE_CALL */
    cycle(now);
  }
  assert(max_critical_depth == 2 && critical_depth == 0);
  return 0;
}
"""


def production_app_fragments():
    """Compile the actual invalidation producer without unrelated camera/audio SDK code."""
    text = (ROOT / "headvoice/firmware/headvoice_app.c").read_text(encoding="utf-8")
    start = text.index("static unsigned epoch(bool invalidate)")
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    epoch_function = text[start:end].replace("epoch(bool", "app_epoch(bool").replace("&s_guard", "&app_guard")
    call_start = text.index("hv_panel_pose(HV_STAGE, result.")
    call_end = text.index(";", call_start) + 1
    fresh_start = text.index("bool fresh = result.epoch")
    fresh_end = text.index(";", fresh_start) + 1
    fresh_decision = text[fresh_start:fresh_end].replace("epoch(false)", "app_epoch(false)")
    return epoch_function, text[call_start:call_end], fresh_decision


class PanelFirmwareTest(unittest.TestCase):
    def test_quality_and_epoch_eligibility_remain_distinct_in_hp_and_cloud_reports(self):
        compiler = shutil.which("cc") or shutil.which("clang")
        self.assertIsNotNone(compiler, "A C compiler is required for firmware host checks")
        with tempfile.TemporaryDirectory(prefix="panel-firmware-") as directory:
            folder = Path(directory)
            (folder / "panel_test_stubs.h").write_text(STUBS, encoding="utf-8")
            for name in ("qm_spec_api.h", "bsp_ws2812.h", "esp_random.h", "esp_system.h",
                         "esp_timer.h", "freertos/FreeRTOS.h", "freertos/queue.h",
                         "freertos/task.h", "ljyd_cloud.h", "qm_cli.h", "qm_config.h",
                         "qm_iot_api.h"):
                header = folder / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('#include "panel_test_stubs.h"\n', encoding="utf-8")
            epoch_function, pose_call, fresh_decision = production_app_fragments()
            harness = HARNESS.replace("/* APP_EPOCH_FUNCTION */", epoch_function)
            harness = harness.replace("/* APP_POSE_CALL */", pose_call)
            harness = harness.replace("/* APP_FRESH_DECISION */", fresh_decision)
            source = folder / "test_panel.c"
            source.write_text(harness, encoding="utf-8")
            binary = folder / "test_panel"
            build = subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                "-DCONFIG_QM_CLI_SUPPORT=1", "-DHV_STAGE=2", "-I", str(folder),
                "-I", str(ROOT / "headvoice/firmware"), "-I", str(ROOT / "headvoice/core"),
                str(source), str(ROOT / "headvoice/core/hv_light.c"), "-lm", "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
        reports = [json.loads(line[3:]) for line in run.stdout.splitlines() if line.startswith("HP ")]
        self.assertEqual(len(reports), 16)
        baseline = reports.pop(0)
        self.assertEqual(baseline["stage"], 0)
        self.assertFalse(baseline["pose"]["valid"])
        self.assertEqual([r["pose"]["valid"] for r in reports],
                         [False, True, False, True, False, False, True, True,
                          False, False, False, False, False, True, False])
        for index in (2, 4, 5, 12, 14):
            self.assertTrue(reports[index]["pose"]["tracking"])
            self.assertLessEqual(reports[index]["pose"]["age_ms"], 400)
            self.assertFalse(reports[index]["pose"]["valid"])
        self.assertEqual(reports[7]["pose"]["age_ms"], 400)
        self.assertEqual(reports[8]["pose"]["age_ms"], 401)
        self.assertEqual(reports[0]["stage"], 1)
        self.assertFalse(reports[0]["pose"]["tracking"])
        self.assertFalse(reports[10]["pose"]["tracking"])
        self.assertTrue(all(r["v"] == 1 and r["ok"] for r in reports))


if __name__ == "__main__":
    unittest.main()

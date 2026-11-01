/* Explicit, credential-free diagnostic session for a host-sent text request. */
#include "hv_gesture_probe.h"
#if defined(HV_GESTURE_AGENT_DIAGNOSTICS)
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hv_gesture_agent_port.h"
#include "qm.h"
#include "qm_cli.h"

static portMUX_TYPE s_probe_guard = portMUX_INITIALIZER_UNLOCKED;
static bool s_probe_busy, s_probe_abort, s_probe_registered;
static char s_probe_marker[11];

static uint64_t probe_now(void) { return (uint64_t)(esp_timer_get_time() / 1000); }
static void probe_report(const char *marker, const char *state, int code)
{
  printf("HG_PROBE {\"v\":1,\"marker\":\"%s\",\"state\":\"%s\",\"code\":%d}\n",
         marker, state, code);
}
static bool probe_aborted(void)
{
  portENTER_CRITICAL(&s_probe_guard);
  bool aborted = s_probe_abort;
  portEXIT_CRITICAL(&s_probe_guard);
  return aborted;
}

static void probe_run(const char *marker)
{
  /* begin() is the only session reservation. A busy voice/gesture is untouched. */
  const char *begin_detail = "cancelled";
  int ret = probe_aborted() ? -QM_EINTR : hv_gesture_agent_port_begin_detail(&begin_detail);
  if (ret != QM_EOK) {
    printf("HG_PROBE {\"v\":1,\"marker\":\"%s\",\"state\":\"unavailable\","
           "\"code\":%d,\"detail\":\"%s\"}\n", marker, ret, begin_detail);
    return;
  }
  probe_report(marker, "connecting", 0);
  uint64_t deadline = probe_now() + 15000, quiet_since = 0;
  for (;;) {
    uint64_t now = probe_now();
    if (probe_aborted()) { ret = -QM_EINTR; break; }
    ret = hv_gesture_agent_port_ready();
    if (ret < 0) break;
    if (now >= deadline) { ret = -QM_ETIMEOUT; break; }
    if (ret == 1) {
      if (!quiet_since) quiet_since = now;
      if (now - quiet_since >= 600) { ret = QM_EOK; break; }
    } else quiet_since = 0;
    vTaskDelay(pdMS_TO_TICKS(20));
  }
  if (ret == QM_EOK) ret = probe_aborted() ? -QM_EINTR : hv_gesture_agent_port_arm();
  if (ret == QM_EOK) {
    probe_report(marker, "ready", 0);
    deadline = probe_now() + 90000;
    bool started = false;
    for (;;) {
      if (probe_aborted()) { ret = -QM_EINTR; break; }
      int state = hv_gesture_agent_port_poll();
      if (state < 0) { ret = state; break; }
      if (state >= 1 && !started) { probe_report(marker, "speaking", 0); started = true; }
      if (state == 2) { probe_report(marker, "playback_complete", 0); break; }
      if (state == HV_GESTURE_PORT_COMPLETION_UNSUPPORTED) {
        probe_report(marker, "playback_completion_unsupported", -QM_ENOSYS);
        break;
      }
      if (probe_now() >= deadline) { ret = -QM_ETIMEOUT; break; }
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
  if (ret != QM_EOK) probe_report(marker, "failed", ret);
  /* Local abort is not port_cancel(): that means ownership handed to someone
     else. end() retains ownership after a failed stop, as production does. */
  int cleanup = hv_gesture_agent_port_end();
  probe_report(marker, cleanup == QM_EOK ? "ended" : "cleanup_failed", cleanup);
}

static void probe_task(void *unused)
{
  (void)unused;
  char marker[sizeof(s_probe_marker)];
  portENTER_CRITICAL(&s_probe_guard);
  memcpy(marker, s_probe_marker, sizeof(marker));
  portEXIT_CRITICAL(&s_probe_guard);
  probe_run(marker);
  portENTER_CRITICAL(&s_probe_guard);
  s_probe_busy = false;
  portEXIT_CRITICAL(&s_probe_guard);
  vTaskDelete(NULL);
}

static bool probe_marker_valid(const char *marker)
{
  if (strlen(marker) != 10 || marker[0] != 'G' || marker[1] != 'B') return false;
  for (unsigned i = 2; i < 10; ++i)
    if (!((marker[i] >= '0' && marker[i] <= '9') || (marker[i] >= 'A' && marker[i] <= 'F'))) return false;
  return true;
}

static void probe_command(char *buffer, int size, int argc, char **argv)
{
  (void)buffer; (void)size;
  if (argc == 2 && !strcmp(argv[1], "status")) {
    const char *detail = NULL;
    int ret = hv_gesture_agent_port_status(&detail);
    qm_cli_printf("HG_AGENT_STATUS {\"v\":1,\"code\":%d,\"detail\":\"%s\"}\r\n", ret, detail);
    return;
  }
  if (argc != 3 || !probe_marker_valid(argv[2]) ||
      (strcmp(argv[1], "probe") && strcmp(argv[1], "abort"))) {
    qm_cli_printf("hg_agent status | probe|abort GB<8 uppercase hex digits>\r\n");
    return;
  }
  const char *marker = argv[2];
  bool abort = !strcmp(argv[1], "abort");
  portENTER_CRITICAL(&s_probe_guard);
  bool allowed = abort ? s_probe_busy && !strcmp(s_probe_marker, marker) : !s_probe_busy;
  if (allowed) {
    if (abort) s_probe_abort = true;
    else {
      memcpy(s_probe_marker, marker, sizeof(s_probe_marker));
      s_probe_busy = true;
      s_probe_abort = false;
    }
  }
  portEXIT_CRITICAL(&s_probe_guard);
  if (!allowed) { probe_report(marker, abort ? "not_owned" : "busy", -QM_EBUSY); return; }
  if (abort) { probe_report(marker, "aborting", 0); return; }
  if (xTaskCreate(probe_task, "hg_probe", 8192, NULL, 3, NULL) != pdPASS) {
    portENTER_CRITICAL(&s_probe_guard);
    s_probe_busy = false;
    portEXIT_CRITICAL(&s_probe_guard);
    probe_report(marker, "unavailable", -QM_ENOMEM);
  }
}

esp_err_t hv_gesture_probe_init(void)
{
  if (s_probe_registered) return ESP_OK;
  static const struct qm_cli_command command = {
    .name = "hg_agent", .help = "status | probe|abort GB<8 hex>: session diagnostics",
    .function = probe_command,
  };
  int ret = qm_cli_register_command(&command);
  if (ret != QM_EOK) return ESP_FAIL;
  s_probe_registered = true;
  return ESP_OK;
}
#endif

#include "hv_voice_probe.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "qm_agent_log.h"
#include "qm_cli.h"

static atomic_uint mic_packets, mic_bytes, mic_nonzero, mic_peak, mic_last;
static atomic_uint tx_packets, tx_bytes, tx_errors, tx_last;
static atomic_int tx_result;

static unsigned now_ms(void) { return (unsigned)(esp_timer_get_time() / 1000); }

static unsigned age_ms(const atomic_uint *last)
{
  /* Load the producer timestamp before sampling the clock. The CLI can be
     preempted while scanning stack watermarks or formatting earlier fields. */
  unsigned stamp = atomic_load(last);
  return now_ms() - stamp;
}

void hv_voice_probe_mic(const uint8_t * data, uint16_t length)
{
  unsigned peak = 0, nonzero = 0;
  if (!data) return;
  for (unsigned i = 0; i + 1 < length; i += 2) {
    int value = (int16_t)((uint16_t)data[i] | ((uint16_t)data[i + 1] << 8));
    unsigned magnitude = (unsigned)(value < 0 ? -value : value);
    if (magnitude > peak) peak = magnitude;
    if (value) nonzero++;
  }
  atomic_fetch_add(&mic_packets, 1);
  atomic_fetch_add(&mic_bytes, length);
  atomic_fetch_add(&mic_nonzero, nonzero);
  /* Only the UART receive task writes the peak; readers never reset it. */
  if (peak > atomic_load(&mic_peak)) atomic_store(&mic_peak, peak);
  atomic_store(&mic_last, now_ms());
}

void hv_voice_probe_tx(uint32_t length, int result)
{
  if (result == 0) {
    atomic_fetch_add(&tx_packets, 1);
    atomic_fetch_add(&tx_bytes, length);
  } else
    atomic_fetch_add(&tx_errors, 1);
  atomic_store(&tx_result, result);
  atomic_store(&tx_last, now_ms());
}

static void voice_command(char * buffer, int size, int argc, char ** argv)
{
  (void)buffer;
  (void)size;
  if (argc == 2 && strcmp(argv[1], "stats") == 0) {
    /* The app keeps its agent for the device lifetime. ESP-IDF reports bytes. */
    TaskHandle_t control = xTaskGetHandle("qm_agent_ctl");
    unsigned stack_free = control ? (unsigned)uxTaskGetStackHighWaterMark(control) : 0;
    /* qm_cli_printf has a 256-byte buffer. Keep each record bounded even
       when all counters reach UINT32_MAX; never silently truncate JSON. */
    qm_cli_printf(
      "HVVOICE {\"mic_packets\":%u,\"mic_bytes\":%u,\"mic_nonzero\":%u,"
      "\"mic_peak\":%u,\"mic_age_ms\":%u}\r\n",
      atomic_load(&mic_packets), atomic_load(&mic_bytes), atomic_load(&mic_nonzero),
      atomic_load(&mic_peak), age_ms(&mic_last));
    qm_cli_printf(
      "HVVOICETX {\"tx_packets\":%u,\"tx_bytes\":%u,\"tx_errors\":%u,"
      "\"tx_last_result\":%d,\"tx_age_ms\":%u}\r\n",
      atomic_load(&tx_packets), atomic_load(&tx_bytes), atomic_load(&tx_errors),
      atomic_load(&tx_result), age_ms(&tx_last));
    qm_cli_printf(
      "HVVOICECTRL {\"control_task_found\":%s,\"control_stack_free_min_bytes\":%u,"
      "\"internal_free\":%u,\"internal_largest\":%u}\r\n",
      control ? "true" : "false", stack_free,
      (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
      (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    return;
  }
  if (argc == 2 && strcmp(argv[1], "net") == 0) {
    wifi_ap_record_t ap = {0};
    esp_netif_ip_info_t ip = {0};
    int ap_result = esp_wifi_sta_get_ap_info(&ap);
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    int ip_result = netif ? esp_netif_get_ip_info(netif, &ip) : ESP_ERR_NOT_FOUND;
    qm_cli_printf(
      "HVVOICENET {\"ap_associated\":%s,\"ap_result\":%d,\"rssi\":%d,"
      "\"has_ip\":%s,\"ip_result\":%d}\r\n",
      ap_result == ESP_OK ? "true" : "false", ap_result,
      ap_result == ESP_OK ? ap.rssi : 0,
      ip_result == ESP_OK && ip.ip.addr ? "true" : "false", ip_result);
    return;
  }
  if (argc == 2 && strcmp(argv[1], "debug") == 0) {
    uint32_t flags = qm_agent_get_log_flags() | QM_AGENT_LOG_UPLINK | QM_AGENT_LOG_DOWNLINK |
                     QM_AGENT_LOG_STATS | QM_AGENT_LOG_CONTROL;
    qm_cli_printf("Voice lifecycle diagnostics ret=%d\r\n", qm_agent_set_log_flags(flags));
    return;
  }
  qm_cli_printf("hv_voice stats|net|debug; counters reset on reboot, raw audio is not retained\r\n");
}

void hv_voice_probe_cli_init(void)
{
  static const struct qm_cli_command command = {
    .name = "hv_voice",
    .help = "stats|net|debug: inspect microphone and actual RTC send counters",
    .function = voice_command,
  };
  qm_cli_printf("Voice diagnostics CLI ready ret=%d\r\n", qm_cli_register_command(&command));
}

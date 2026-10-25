#include "hv_voice_probe.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_timer.h"
#include "qm_agent_log.h"
#include "qm_cli.h"

static atomic_uint mic_packets, mic_bytes, mic_nonzero, mic_peak, mic_last;
static atomic_uint tx_packets, tx_bytes, tx_errors, tx_last;
static atomic_int tx_result;

static unsigned now_ms(void) { return (unsigned)(esp_timer_get_time() / 1000); }

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
    unsigned now = now_ms();
    qm_cli_printf(
      "HVVOICE {\"mic_packets\":%u,\"mic_bytes\":%u,\"mic_nonzero\":%u,"
      "\"mic_peak\":%u,\"mic_age_ms\":%u,\"tx_packets\":%u,\"tx_bytes\":%u,"
      "\"tx_errors\":%u,\"tx_last_result\":%d,\"tx_age_ms\":%u}\r\n",
      atomic_load(&mic_packets), atomic_load(&mic_bytes), atomic_load(&mic_nonzero),
      atomic_load(&mic_peak), now - atomic_load(&mic_last), atomic_load(&tx_packets),
      atomic_load(&tx_bytes), atomic_load(&tx_errors), atomic_load(&tx_result),
      now - atomic_load(&tx_last));
    return;
  }
  if (argc == 2 && strcmp(argv[1], "debug") == 0) {
    uint32_t flags = qm_agent_get_log_flags() | QM_AGENT_LOG_UPLINK | QM_AGENT_LOG_DOWNLINK |
                     QM_AGENT_LOG_STATS | QM_AGENT_LOG_CONTROL;
    qm_cli_printf("Voice lifecycle diagnostics ret=%d\r\n", qm_agent_set_log_flags(flags));
    return;
  }
  qm_cli_printf("hv_voice stats|debug; counters reset on reboot, raw audio is not retained\r\n");
}

void hv_voice_probe_cli_init(void)
{
  static const struct qm_cli_command command = {
    .name = "hv_voice",
    .help = "stats|debug: inspect microphone and actual RTC send counters",
    .function = voice_command,
  };
  qm_cli_printf("Voice diagnostics CLI ready ret=%d\r\n", qm_cli_register_command(&command));
}

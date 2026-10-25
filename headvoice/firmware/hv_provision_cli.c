#include "hv_provision_cli.h"

#include <string.h>

#include "hv_voice_probe.h"
#include "ljyd_cloud.h"
#include "ljyd_provision.h"
#include "qm_cli.h"
#include "qm_config.h"

#if defined(CONFIG_QM_CLI_SUPPORT) && CONFIG_QM_CLI_SUPPORT
static void provision_command(char * buffer, int length, int argc, char ** argv)
{
  (void)buffer;
  (void)length;
  if (argc == 2 && strcmp(argv[1], "status") == 0) {
    qm_cli_printf(
      "HeadVoice product PID=%u; secret omitted\r\n", (unsigned)CONFIG_XJIANG_CLOUD_PID);
    return;
  }
  if (argc == 2 && strcmp(argv[1], "restart") == 0) {
    qm_cli_printf(
      "Clear saved Wi-Fi and provisioning environment; reboot into BLE provisioning\r\n");
    /* The official path resets only binding/environment/Wi-Fi keys. */
    ljyd_provision_clear_and_reboot();
    return;
  }
  qm_cli_printf("hv_provision status|restart (restart clears saved Wi-Fi)\r\n");
}

static const struct qm_cli_command provision_cli = {
  .name = "hv_provision",
  .help = "status|restart: inspect product or clear Wi-Fi and restart BLE provisioning",
  .function = provision_command,
};
#endif

void hv_provision_cli_init(void)
{
#if defined(CONFIG_QM_CLI_SUPPORT) && CONFIG_QM_CLI_SUPPORT
  int result = qm_cli_register_command(&provision_cli);
  qm_cli_printf("HeadVoice provisioning CLI ready ret=%d\r\n", result);
  hv_voice_probe_cli_init();
#endif
}

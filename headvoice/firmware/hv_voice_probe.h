#ifndef HV_VOICE_PROBE_H
#define HV_VOICE_PROBE_H

#include <stdint.h>

void hv_voice_probe_mic(const uint8_t * data, uint16_t length);
void hv_voice_probe_tx(uint32_t length, int result);
void hv_voice_probe_cli_init(void);

#endif

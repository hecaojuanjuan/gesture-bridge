#ifndef HV_PANEL_H
#define HV_PANEL_H

#include <stdbool.h>
#include <stdint.h>

void hv_panel_init(void);
void hv_panel_network(const char * state);
void hv_panel_expression(uint8_t r, uint8_t g, uint8_t b, bool active);

#endif

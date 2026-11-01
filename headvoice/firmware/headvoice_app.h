#ifndef HEADVOICE_APP_H
#define HEADVOICE_APP_H
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
esp_err_t headvoice_start(void);
typedef struct {
  bool supported, armed;
  uint32_t generation, palm_count, v_count;
  const char *last_gesture;
} headvoice_scan_status_t;
void headvoice_scan_status(headvoice_scan_status_t *out);
/* Caller excludes an active agent transaction. False while a completed
 * event is being handed over, or when this backend has no single-shot mode. */
bool headvoice_scan_arm(void);
#endif

#ifndef HV_LIGHT_H
#define HV_LIGHT_H
#include <stdbool.h>
#include <stdint.h>

enum { HV_LIGHT_STATUS, HV_LIGHT_MANUAL, HV_LIGHT_OFF };
enum { HV_LIGHT_QUERY, HV_LIGHT_SET, HV_LIGHT_TEST };
typedef struct {
  uint32_t id;
  unsigned operation, mode, brightness;
  uint8_t rgb[3];
} hv_light_command_t;
typedef struct {
  unsigned mode, brightness;
  uint8_t rgb[3], status[3];
  uint64_t testUntil;
  uint32_t recentWrites[8];
  unsigned nextWrite;
} hv_light_t;
void hv_light_init(hv_light_t *light);
/* Wire grammar: ID get | ID set MODE BRIGHTNESS R G B | ID test. */
bool hv_light_parse(const char *text, hv_light_command_t *command);
void hv_light_apply(hv_light_t *light, const hv_light_command_t *command, uint64_t now);
void hv_light_output(const hv_light_t *light, uint64_t now, uint8_t rgb[3]);
#endif

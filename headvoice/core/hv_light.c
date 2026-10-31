#include "hv_light.h"
#include <stdio.h>
#include <string.h>

void hv_light_init(hv_light_t *light)
{
  memset(light, 0, sizeof(*light));
  light->brightness = 20;
  light->rgb[0] = 80;
  light->rgb[1] = 190;
  light->rgb[2] = 255;
}

bool hv_light_parse(const char *text, hv_light_command_t *command)
{
  if (!text || !command || strlen(text) > 96) return false;
  /* Restrict integer tokens before sscanf to avoid overflow conversions. */
  unsigned digits = 0;
  for (const char *p = text; *p; ++p) {
    if (*p >= '0' && *p <= '9') { if (++digits > 9) return false; }
    else { digits = 0; if (*p != ' ' && (*p < 'a' || *p > 'z')) return false; }
  }
  unsigned id, mode, brightness, r, g, b;
  char verb[8], extra;
  if (sscanf(text, "%u %7s", &id, verb) != 2 || id == 0) return false;
  memset(command, 0, sizeof(*command));
  command->id = id;
  if (strcmp(verb, "get") == 0 || strcmp(verb, "test") == 0) {
    if (sscanf(text, "%u %7s %c", &id, verb, &extra) != 2) return false;
    command->operation = strcmp(verb, "get") == 0 ? HV_LIGHT_QUERY : HV_LIGHT_TEST;
    return true;
  }
  if (strcmp(verb, "set") != 0 ||
      sscanf(text, "%u %7s %u %u %u %u %u %c", &id, verb, &mode, &brightness,
             &r, &g, &b, &extra) != 7 ||
      mode > HV_LIGHT_OFF || brightness > 100 || r > 255 || g > 255 || b > 255)
    return false;
  command->operation = HV_LIGHT_SET;
  command->mode = mode;
  command->brightness = brightness;
  command->rgb[0] = r; command->rgb[1] = g; command->rgb[2] = b;
  return true;
}

void hv_light_apply(hv_light_t *light, const hv_light_command_t *command, uint64_t now)
{
  if (command->operation == HV_LIGHT_QUERY) return;
  /* Polling from a second panel must not make a retried test restart. */
  for (unsigned i = 0; i < 8; ++i)
    if (light->recentWrites[i] == command->id) return;
  light->recentWrites[light->nextWrite++ % 8] = command->id;
  if (command->operation == HV_LIGHT_SET) {
    light->mode = command->mode;
    light->brightness = command->brightness;
    memcpy(light->rgb, command->rgb, 3);
    light->testUntil = 0;
  } else if (command->operation == HV_LIGHT_TEST) {
    light->testUntil = now + 5000;
  }
}

void hv_light_output(const hv_light_t *light, uint64_t now, uint8_t rgb[3])
{
  memset(rgb, 0, 3);
  if (now < light->testUntil) {
    /* Dim R/G/B/white/off, one second each; expires on device, even offline. */
    unsigned phase = (unsigned)((5000 - (light->testUntil - now)) / 1000);
    if (phase < 3) rgb[phase] = 32;
    else if (phase == 3) rgb[0] = rgb[1] = rgb[2] = 16;
    return;
  }
  if (light->mode == HV_LIGHT_STATUS) { memcpy(rgb, light->status, 3); return; }
  if (light->mode == HV_LIGHT_OFF) return;
  /* Panel 100% is a conservative PWM ceiling of 48, not unrestricted white. */
  for (unsigned i = 0; i < 3; ++i)
    rgb[i] = (uint8_t)((unsigned)light->rgb[i] * light->brightness * 48 / 25500);
}

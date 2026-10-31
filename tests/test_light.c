#include "hv_light.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
  hv_light_t light; hv_light_command_t command; uint8_t rgb[3];
  hv_light_init(&light);
  const char *bad[] = {"0 get", "1 set 9 20 1 2 3", "1 set 1 101 1 2 3",
    "1 set 1 20 256 2 3", "1 set 1 -1 1 2 3", "1 set 1 20 1 2",
    "1 test ignored", "1 get x", "99999999999999999999999 get", "1 get\n2 test"};
  for (unsigned i=0; i<sizeof(bad)/sizeof(*bad); ++i) assert(!hv_light_parse(bad[i], &command));
  assert(hv_light_parse("123 set 1 100 255 128 0", &command));
  hv_light_apply(&light, &command, 1000);
  hv_light_output(&light, 1000, rgb);
  assert(rgb[0] == 48 && rgb[1] == 24 && rgb[2] == 0);
  assert(hv_light_parse("124 test", &command));
  hv_light_apply(&light, &command, 2000);
  assert(hv_light_parse("900 get", &command));
  hv_light_apply(&light, &command, 2500);
  assert(hv_light_parse("124 test", &command));
  hv_light_apply(&light, &command, 3200);
  assert(light.testUntil == 7000); /* Interleaved polling cannot restart it. */
  for (unsigned phase=0; phase<5; ++phase) {
    hv_light_output(&light, 2000 + phase*1000, rgb);
    if (phase<3) assert(rgb[phase] == 32);
    if (phase==3) assert(rgb[0]==16 && rgb[1]==16 && rgb[2]==16);
    if (phase==4) assert(rgb[0]==0 && rgb[1]==0 && rgb[2]==0);
  }
  hv_light_output(&light, 7000, rgb);
  assert(rgb[0]==48 && rgb[1]==24); /* Restores without a browser connection. */
  assert(hv_light_parse("125 set 2 100 255 255 255", &command));
  hv_light_apply(&light, &command, 7100);
  hv_light_output(&light, 7100, rgb); assert(rgb[0]==0 && rgb[1]==0 && rgb[2]==0);
  assert(hv_light_parse("124 test", &command));
  hv_light_apply(&light, &command, 7150);
  assert(light.testUntil == 0); /* An old retry cannot undo a newer off command. */
  assert(hv_light_parse("126 set 0 100 255 255 255", &command));
  hv_light_apply(&light, &command, 7100); light.status[2] = 32;
  hv_light_output(&light, 7100, rgb); assert(rgb[0]==0 && rgb[2]==32);
  assert(hv_light_parse("127 get", &command));
  hv_light_t before = light; hv_light_apply(&light, &command, 7200);
  assert(memcmp(&before, &light, sizeof(light))==0);
  puts("PASS RGB parsing, brightness limit, modes, device test expiry and read-only query");
}

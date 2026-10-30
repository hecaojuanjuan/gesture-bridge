"""Run the real MQTT topic validator with an outer tokenizer in progress."""
import os
import subprocess
import sys

from prepare_sdk import ROOT, SDK

source = (SDK / 'qumios-dev/components/mqtt/iot_mqtt_client.c').read_text(
    encoding='utf-8')
if '--upstream' not in sys.argv:
    from prepare_sdk import reentrant_mqtt
    source = reentrant_mqtt(source)
start = source.index('static int iot_mc_check_rule(')
end = source.index('/* Send keepalive packet */', start)
header = '''#include <stdio.h>
#include <string.h>
#define SUCCESS_RETURN 0
#define FAIL_RETURN -1
#define IOT_MC_TOPIC_NAME_MAX_LEN 64
#define mqtt_log_err(...) ((void)0)
#ifdef _WIN32
#define strtok_r strtok_s
#endif
typedef enum {TOPIC_FILTER_TYPE, TOPIC_NAME_TYPE} iot_mc_topic_type_t;
'''
test = '''
int main(void) {
  char outer[] = "first/second";
  if (strcmp(strtok(outer, "/"), "first")) return 1;
  if (iot_mc_check_topic("device/info", TOPIC_NAME_TYPE)) return 2;
  char *next = strtok(NULL, "/");
  if (!next || strcmp(next, "second")) {
    puts("FAIL MQTT validation destroyed caller tokenizer state");
    return 3;
  }
  if (iot_mc_check_topic("device/+/info", TOPIC_FILTER_TYPE)) return 4;
  if (!iot_mc_check_topic("device/+/info", TOPIC_NAME_TYPE)) return 5;
  if (!iot_mc_check_topic("device/#/info", TOPIC_FILTER_TYPE)) return 6;
  if (!iot_mc_check_topic(NULL, TOPIC_NAME_TYPE)) return 7;
  puts("PASS MQTT validation preserves caller state and topic rules");
  return 0;
}
'''
output = ROOT / '.work/host'
output.mkdir(parents=True, exist_ok=True)
path = output / 'test_mqtt.c'
path.write_text(header + source[start:end] + test, encoding='utf-8')
env = os.environ.copy()
env['ZIG_GLOBAL_CACHE_DIR'] = str(output / 'zig-cache')
env['ZIG_LOCAL_CACHE_DIR'] = str(output / 'zig-local')
binary = output / 'test_mqtt.exe'
subprocess.run([str(ROOT / '.tools/host/ziglang/zig.exe'), 'cc', '-std=c11',
                '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)],
               check=True, env=env, cwd=output)
sys.exit(subprocess.call([str(binary)]))

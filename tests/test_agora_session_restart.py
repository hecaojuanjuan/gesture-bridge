"""Exercise the isolated Agora adapter's real C lifecycle and callbacks."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_sdk import restart_agora_session  # noqa: E402

SDK = Path(os.environ.get("HEADVOICE_SDK", ROOT.parent / "ljyd_xjwb03_agent_public_developer"))
SOURCE = SDK / "qumios-dev/components/qm_agent/src/transport/qm_agent_transport_agora.c"


def function(source, name):
    start = source.index("static ", source.rfind("\n", 0, source.index(name + "(")))
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define CONFIG_QM_AGENT_TRANSPORT_AGORA 1
#define CONFIG_QM_AGENT_AGORA_AUDIO_CODEC_SUP 1
#define CONFIG_QM_AGENT_AGORA_SDK_LOG_DISABLE 1
#define QM_EOK 0
#define QM_EINVAL 1
#define QM_ENOMEM 2
#define QM_ENOSYS 3
#define QM_EIO 4
#define QM_TRUE 1
#define QM_FALSE 0
#define QM_UNUSED_ARG(x) ((void)(x))
#define QM_AGENT_LOGI(...) ((void)0)
#define QM_AGENT_LOGW(...) ((void)0)
#define QM_AGENT_LOGE(...) ((void)0)
#define LOG_TAG "test"
#define QM_AGENT_AGORA_SDK_LOG_PATH "test"
#define QM_AGENT_AGORA_PCM_DURATION_MS 40
#define AREA_CODE_GLOB 0
#define RTC_LOG_ERROR 1
#define qm_malloc malloc
#define qm_free free
#define qm_memset memset
#define qm_strncpy strncpy
typedef bool qm_bool;
typedef unsigned connection_id_t;
typedef struct { int codec, sample_rate, channel_num, frame_ms; } qm_agent_audio_format_t;
typedef struct { int data_type; } audio_frame_info_t;
typedef struct { int unused; } agora_rtc_event_handler_t;
typedef struct {
 int area_code;
 struct { bool log_disable; int log_level; const char *log_path; int (*log_printf)(const char *,...); } log_cfg;
 bool domain_limit; char license_value[128];
} rtc_service_option_t;
typedef struct {
 bool auto_subscribe_audio, auto_subscribe_video;
 struct { int audio_codec_type, pcm_sample_rate, pcm_channel_num, pcm_duration; } audio_codec_opt;
} rtc_channel_options_t;
enum { QM_AGENT_EVENT_CONNECTED=1, QM_AGENT_EVENT_DISCONNECTED,
 QM_AGENT_EVENT_REMOTE_USER_JOINED, QM_AGENT_EVENT_REMOTE_USER_LEFT,
 QM_AGENT_EVENT_REMOTE_AUDIO_MUTED, QM_AGENT_EVENT_REMOTE_AUDIO_UNMUTED,
 QM_AGENT_EVENT_ERROR, QM_AGENT_EVENT_AUDIO, QM_AGENT_EVENT_SOURCE_TRANSPORT };
typedef struct {
 int id, source, code;
 union {
  struct { unsigned uid; int reason; bool muted; } remote_user;
  struct { const char *message; } error;
  struct { const uint8_t *data; uint32_t len; qm_agent_audio_format_t format; } audio;
 } data;
} qm_agent_event_t;
typedef struct {
 struct { struct { struct {
  const char *license, *app_id, *channel_name, *token;
  unsigned uid; bool audio_enable, video_enable;
 } agora; } data; } config;
 qm_agent_audio_format_t input_format;
 connection_id_t conn_id;
 agora_rtc_event_handler_t event_handler;
 void *stream;
 bool sdk_inited, connected, joined, callbacks_enabled;
} qm_agent_agora_ctx_t;
static void (*s_agora_event_cb)(const qm_agent_event_t *, void *);
static void *s_agora_user_ctx, *s_agora_stream;
static qm_agent_agora_ctx_t *s_agora_ctx;
static qm_agent_audio_format_t s_agora_output_format;
static bool s_agora_connected_emitted, s_agora_uplink_log_emitted, s_agora_downlink_log_emitted;
static unsigned counts[20], stream_inputs, resets, connection_counter;
static int join_result, leave_result, destroy_result, emit_leave_notice=1;
static void agora_on_connection_lost(connection_id_t conn_id);
static void capture(const qm_agent_event_t *event, void *unused) { ++counts[event->id]; }
static int agora_log_printf(const char *fmt,...) { return 0; }
static void agora_init_event_handler(agora_rtc_event_handler_t *handler) {}
static int agora_rtc_init(const char *appid, agora_rtc_event_handler_t *handler, rtc_service_option_t *opts) { return 0; }
static int agora_rtc_create_connection(connection_id_t *id) { *id=++connection_counter; return 0; }
static int agora_rtc_join_channel(connection_id_t id, const char *channel, unsigned uid, const char *token, rtc_channel_options_t *opts) { return join_result; }
static int agora_rtc_leave_channel(connection_id_t id) {
 /* Some SDKs deliver synchronous teardown events. They belong to the old turn. */
 if (emit_leave_notice) agora_on_connection_lost(id); return leave_result;
}
static int agora_rtc_destroy_connection(connection_id_t id) { return destroy_result; }
static void qm_agent_agora_stream_reset(void *stream) { ++resets; }
static int qm_agent_agora_stream_input(void *stream, const char *data, uint32_t len) { ++stream_inputs; return 0; }
static int agora_audio_codec_type(int codec) { return codec; }
static qm_agent_audio_format_t agora_audio_format_from_data_type(int type, const qm_agent_audio_format_t *fallback) { return *fallback; }
'''

HARNESS = r'''
static void late_callbacks(connection_id_t old) {
 agora_on_join_channel_success(old,1,0);
 agora_on_reconnecting(old);
 agora_on_connection_lost(old);
 agora_on_rejoin_channel_success(old,1,0);
 agora_on_user_joined(old,100,0);
 agora_on_user_offline(old,100,0);
 agora_on_user_mute_audio(old,100,true);
 agora_on_error(old,-1,"old");
 audio_frame_info_t info={0};
 agora_on_audio_data(old,100,0,"a",1,&info);
 agora_on_stream_message(old,100,1,"{}",2,0);
}
int main(void) {
 qm_agent_agora_ctx_t ctx={0};
 s_agora_ctx=&ctx; s_agora_event_cb=capture; s_agora_stream=&ctx;
 assert(agora_start(&ctx)==0);
 connection_id_t first=ctx.conn_id;
 agora_on_join_channel_success(first,1,0);
 agora_on_join_channel_success(first,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==1);
 agora_on_user_joined(first,100,0);
 assert(counts[QM_AGENT_EVENT_REMOTE_USER_JOINED]==1);
 assert(agora_stop(&ctx)==0);
 unsigned saved[20]; memcpy(saved,counts,sizeof(saved));
 late_callbacks(first);
 assert(!memcmp(saved,counts,sizeof(saved)) && !stream_inputs);
 assert(!ctx.callbacks_enabled && !ctx.connected && !ctx.joined && resets==1);
 /* Same adapter, no deinit/init: second join must publish CONNECTED again. */
 assert(agora_start(&ctx)==0 && ctx.conn_id!=first);
 connection_id_t second=ctx.conn_id;
 late_callbacks(first);
 assert(!memcmp(saved,counts,sizeof(saved)) && !stream_inputs);
 agora_on_join_channel_success(second,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==2);
 agora_on_rejoin_channel_success(second,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==2);
 agora_on_user_joined(second,100,0);
 assert(counts[QM_AGENT_EVENT_REMOTE_USER_JOINED]==2);
 agora_on_stream_message(second,100,1,"{}",2,0); assert(stream_inputs==1);
 audio_frame_info_t info={0};
 agora_on_audio_data(second,100,0,"a",1,&info);
 assert(counts[QM_AGENT_EVENT_AUDIO]==1);
 /* A real reconnect on the current connection still forwards loss/rejoin. */
 agora_on_connection_lost(second);
 assert(counts[QM_AGENT_EVENT_DISCONNECTED]==1);
 agora_on_rejoin_channel_success(second,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==3);
 assert(agora_stop(&ctx)==0 && counts[QM_AGENT_EVENT_DISCONNECTED]==1);
 /* Partial failures must never admit late callbacks. */
 join_result=-1; assert(agora_start(&ctx)==-1 && !ctx.callbacks_enabled);
 memcpy(saved,counts,sizeof(saved)); late_callbacks(ctx.conn_id);
 assert(!memcmp(saved,counts,sizeof(saved)) && stream_inputs==1);
 assert(agora_stop(&ctx)==0);
 join_result=0; assert(agora_start(&ctx)==0);
 agora_on_join_channel_success(ctx.conn_id,1,0);
 leave_result=-1; assert(agora_stop(&ctx)==-QM_EIO && !ctx.callbacks_enabled);
 memcpy(saved,counts,sizeof(saved)); late_callbacks(ctx.conn_id);
 assert(!memcmp(saved,counts,sizeof(saved)) && stream_inputs==1);
 leave_result=0; assert(agora_stop(&ctx)==0);
 assert(!ctx.callbacks_enabled && !ctx.connected && !ctx.joined);
 return 0;
}
'''


class AgoraRestartTests(unittest.TestCase):
    def run_adapter(self, source, harness):
        names = ("agora_is_agent_uid", "agora_emit_event",
                 "agora_emit_connected_once", "agora_emit_disconnected",
                 "agora_on_join_channel_success", "agora_on_reconnecting",
                 "agora_on_connection_lost", "agora_on_rejoin_channel_success",
                 "agora_on_user_joined", "agora_on_user_offline",
                 "agora_on_user_mute_audio", "agora_on_error", "agora_on_audio_data",
                 "agora_on_stream_message", "agora_start", "agora_stop")
        if "static qm_bool agora_callback_current(" in source:
            names = ("agora_callback_current",) + names
        code = STUBS + "\n".join(function(source, name) for name in names) + harness
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "test.c").write_text(code, encoding="utf-8")
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-Wno-unused-variable",
                            "-Wno-unused-function", "-UNDEBUG",
                            str(path / "test.c"), "-o", str(path / "test")], check=True)
            subprocess.run([str(path / "test")], check=True)

    def test_actual_adapter_restarts_and_rejects_old_callbacks(self):
        patched = restart_agora_session(SOURCE.read_text(encoding="utf-8"))
        with self.assertRaises(RuntimeError):
            restart_agora_session(patched)
        self.run_adapter(patched, HARNESS)

    def test_original_drops_second_connected_when_leave_has_no_notice(self):
        original = SOURCE.read_text(encoding="utf-8")
        harness = r'''
int main(void) {
 qm_agent_agora_ctx_t ctx={0};
 s_agora_ctx=&ctx; s_agora_event_cb=capture; emit_leave_notice=0;
 assert(agora_start(&ctx)==0);
 agora_on_join_channel_success(ctx.conn_id,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==1);
 assert(agora_stop(&ctx)==0);
 assert(agora_start(&ctx)==0);
 agora_on_join_channel_success(ctx.conn_id,1,0);
 assert(counts[QM_AGENT_EVENT_CONNECTED]==EXPECTED_CONNECTED);
 return 0;
}
'''
        for source, expected in ((original, 1), (restart_agora_session(original), 2)):
            with self.subTest(expected_connected=expected):
                self.run_adapter(source, harness.replace("EXPECTED_CONNECTED", str(expected)))


if __name__ == "__main__":
    unittest.main()

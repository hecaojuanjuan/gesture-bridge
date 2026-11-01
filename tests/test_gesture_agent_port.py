"""Run the production session adapter with deterministic SDK events."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUBS = r'''
#ifndef PORT_STUBS_H
#define PORT_STUBS_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define QM_EOK 0
#define QM_ENOMEM 5
#define QM_ENOSYS 6
#define QM_EBUSY 7
#define QM_EIO 8
#define QM_EINTR 9
#define QM_EINIT 11
#define QM_TRUE 1
#define QM_FALSE 0
#define pdTRUE 1
#define portMAX_DELAY 0xffffffffu
typedef int portMUX_TYPE;
typedef int *SemaphoreHandle_t;
static int lock_taken, deny_lock;
static SemaphoreHandle_t xSemaphoreCreateRecursiveMutex(void) { return &lock_taken; }
static int xSemaphoreTakeRecursive(SemaphoreHandle_t s, unsigned wait) {
  assert(s); if (deny_lock && !wait) return 0; ++*s; return 1;
}
static void xSemaphoreGiveRecursive(SemaphoreHandle_t s) { assert(*s); --*s; }
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) do { assert(!*(p)); *(p)=1; } while(0)
#define portEXIT_CRITICAL(p) do { assert(*(p)); *(p)=0; } while(0)
#define qm_memset memset
#define qm_malloc malloc
typedef enum {
  QM_AGENT_EVENT_REMOTE_USER_JOINED, QM_AGENT_EVENT_REMOTE_USER_LEFT,
  QM_AGENT_EVENT_DISCONNECTED, QM_AGENT_EVENT_AGENT_ABORTED, QM_AGENT_EVENT_ERROR,
  QM_AGENT_EVENT_AGENT_STATE, QM_AGENT_EVENT_TTS, QM_AGENT_EVENT_AGENT_TEXT,
  QM_AGENT_EVENT_TTS_PLAYBACK_STARTED, QM_AGENT_EVENT_TTS_PLAYBACK_COMPLETE,
  QM_AGENT_EVENT_TTS_PLAYBACK_FAILED, QM_AGENT_EVENT_TTS_INPUT_COMPLETE
} qm_agent_event_id_t;
enum { QM_AGENT_DIALOG_STATE_NONE, QM_AGENT_DIALOG_STATE_THINKING,
  QM_AGENT_DIALOG_STATE_SPEAKING, QM_AGENT_DIALOG_STATE_SILENT, QM_AGENT_DIALOG_STATE_LISTENING };
enum { QM_AGENT_STATE_RUNNING = 10, QM_AGENT_EVENT_SOURCE_TRANSPORT = 11 };
typedef struct { uint32_t generation; int code; union {
  struct { char text[64]; bool truncated; } text;
  struct { int state; } agent_state;
} data; } qm_agent_event_notice_t;
typedef struct { int id, source; } qm_agent_event_t;
typedef int ljyd_cloud_event_t;
enum { LJYD_CLOUD_EVENT_DISCONNECTED, LJYD_CLOUD_EVENT_CONNECTED };
static int agent, *s_agent = &agent, s_cloud_connected = 1, s_agent_started, s_waiting_tts_complete;
static int starts, stops, wakes, state, post_count, post_result, start_result, stop_result;
static bool upload = true, stream_active;
static unsigned forwarded_texts;
unsigned hv_gesture_agent_active_sequence(void) { return 17; }
void hv_gesture_agent_text(unsigned sequence, const char *text, bool truncated) {
  assert(sequence==17 && !strcmp(text,"reply") && !truncated); ++forwarded_texts;
}
#define QM_AUDIO_CAP_DRAIN 16u
typedef struct { unsigned flags; } qm_audio_caps_t;
static unsigned audio_caps = QM_AUDIO_CAP_DRAIN;
static int qm_audio_get_caps(qm_audio_caps_t *caps) { caps->flags=audio_caps; return 0; }
static int qm_agent_start(int *p) { assert(p); ++starts; state=QM_AGENT_STATE_RUNNING; return start_result; }
static void qm_agent_set_upload_enabled(int *p, int value) { assert(p); upload=value; }
static int qm_agent_get_state(int *p) { assert(p); return state; }
static bool qm_agent_audio_engine_stream_active(int *p) { assert(p); return stream_active; }
static int qm_agent_control_post_event(int *p, qm_agent_event_t *event) {
  assert(p && event->id==QM_AGENT_EVENT_TTS_INPUT_COMPLETE); ++post_count; free(event); return post_result;
}
static int agent_app_leave_unlocked(void) { ++stops; if (!stop_result) s_agent_started=0; return stop_result; }
static void on_wakeup_unlocked(void) { ++wakes; upload=false; }
static void on_cloud_event_unlocked(ljyd_cloud_event_t event, void *handle, void *userdata) {
  (void)handle; (void)userdata;
  s_cloud_connected=event==LJYD_CLOUD_EVENT_CONNECTED;
  if (!s_cloud_connected) agent_app_leave_unlocked();
}
#endif
'''
HARNESS = r'''
#include "stubs.h"
#include "hv_gesture_agent_port.h"
#include "hv_gesture_agent_port.inc"
static void notice(int id, int generation) {
  qm_agent_event_notice_t n = {.generation=generation};
  if (id==QM_AGENT_EVENT_TTS) strcpy(n.data.text.text,"reply");
  hv_gesture_agent_port_notice(id,&n);
}
static void dialog(int value) {
  qm_agent_event_notice_t n = {0}; n.data.agent_state.state=value;
  hv_gesture_agent_port_notice(QM_AGENT_EVENT_AGENT_STATE,&n);
}
static void failure(int generation, int code) {
  qm_agent_event_notice_t n = {.generation=generation,.code=code};
  hv_gesture_agent_port_notice(QM_AGENT_EVENT_TTS_PLAYBACK_FAILED,&n);
}
static void reply_input(int generation) {
  notice(QM_AGENT_EVENT_TTS,0); dialog(QM_AGENT_DIALOG_STATE_SPEAKING);
  notice(QM_AGENT_EVENT_TTS_PLAYBACK_STARTED,generation);
  dialog(QM_AGENT_DIALOG_STATE_SILENT);
}
static void start_ready(void) {
  assert(hv_gesture_agent_port_begin()==0);
  assert(!upload && hv_gesture_agent_port_ready()==0);
  assert(!strcmp(hv_gesture_agent_port_ready_detail(),"waiting_remote"));
  notice(QM_AGENT_EVENT_REMOTE_USER_JOINED,0);
  dialog(QM_AGENT_DIALOG_STATE_LISTENING);
  assert(hv_gesture_agent_port_ready()==1);
  assert(!strcmp(hv_gesture_agent_port_ready_detail(),"ready"));
  assert(hv_gesture_agent_port_arm()==0);
}
int main(void) {
  const char *detail = NULL, *other = NULL;
  assert(hv_gesture_agent_port_status(&detail)==-QM_EINIT && !strcmp(detail,"not_initialized"));
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EINIT && !strcmp(detail,"not_initialized"));
  assert(hv_gesture_agent_port_init()==0);
  deny_lock=1;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"lifecycle_busy"));
  assert(hv_gesture_agent_port_status(&detail)==-QM_EBUSY && !strcmp(detail,"lifecycle_busy"));
  deny_lock=0;
  s_agent=NULL;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"no_session"));
  s_agent=&agent; s_cloud_connected=0;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"cloud_disconnected"));
  s_cloud_connected=1;
  assert(hv_gesture_agent_port_status(&other)==0 && !strcmp(other,"ready"));
  assert(!strcmp(detail,"cloud_disconnected")); /* preserved across a later snapshot */
  s_agent_started=1;
  assert(hv_gesture_agent_port_begin_detail(&other)==-QM_EBUSY && !strcmp(other,"voice_session_active"));
  assert(!strcmp(detail,"cloud_disconnected")); /* preserved across a competing begin */
  s_agent_started=0; s_waiting_tts_complete=1;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"tts_pending"));
  s_waiting_tts_complete=0; atomic_store(&s_gesture_resource,true);
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"resource_active"));
  atomic_store(&s_gesture_resource,false); atomic_store(&s_gesture_owned,true);
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && !strcmp(detail,"gesture_session_active"));
  atomic_store(&s_gesture_owned,false);
  assert(!starts && !stops && upload && !lock_taken);
  assert(hv_gesture_agent_port_status(&detail)==0 && !strcmp(detail,"ready"));
  assert(!starts && !stops && upload && !s_agent_started && !atomic_load(&s_gesture_owned));
  notice(QM_AGENT_EVENT_TTS,0); assert(forwarded_texts==0);
  s_cloud_connected=0; assert(hv_gesture_agent_port_begin()==-QM_EBUSY && !starts);
  s_cloud_connected=1; s_agent_started=1;
  assert(hv_gesture_agent_port_begin()==-QM_EBUSY && !starts); s_agent_started=0;
  hv_gesture_agent_port_resource_mode(true);
  assert(hv_gesture_agent_port_begin()==-QM_EBUSY && !starts);
  hv_gesture_agent_port_resource_mode(false);
  start_ready();
  stream_active=true;
  assert(!hv_gesture_agent_port_ready() && !strcmp(hv_gesture_agent_port_ready_detail(),"audio_active"));
  stream_active=false;
  dialog(QM_AGENT_DIALOG_STATE_THINKING);
  assert(!hv_gesture_agent_port_ready() && !strcmp(hv_gesture_agent_port_ready_detail(),"thinking"));
  dialog(QM_AGENT_DIALOG_STATE_SPEAKING);
  assert(!hv_gesture_agent_port_ready() && !strcmp(hv_gesture_agent_port_ready_detail(),"speaking"));
  dialog(QM_AGENT_DIALOG_STATE_LISTENING);
  assert(hv_gesture_agent_port_begin()==-QM_EBUSY);
  notice(QM_AGENT_EVENT_TTS,0); dialog(QM_AGENT_DIALOG_STATE_SPEAKING);
#if defined(HV_GESTURE_AGENT_CONFIG_HEADER)
  assert(forwarded_texts==1);
#else
  assert(forwarded_texts==0);
#endif
  unsigned before_text=forwarded_texts;
  qm_agent_event_notice_t text_notice={0}; strcpy(text_notice.data.text.text,"reply");
  hv_gesture_agent_port_notice(QM_AGENT_EVENT_AGENT_TEXT,&text_notice);
  assert(forwarded_texts==before_text);
  upload=true; dialog(QM_AGENT_DIALOG_STATE_SPEAKING); assert(!upload);
  notice(QM_AGENT_EVENT_TTS_PLAYBACK_STARTED,3);
  assert(hv_gesture_agent_port_poll()==1);
  dialog(QM_AGENT_DIALOG_STATE_SILENT); assert(post_count==1);
  notice(QM_AGENT_EVENT_TTS_PLAYBACK_COMPLETE,2); assert(hv_gesture_agent_port_poll()==1);
  notice(QM_AGENT_EVENT_TTS_PLAYBACK_COMPLETE,3); assert(hv_gesture_agent_port_poll()==2);
  assert(hv_gesture_agent_port_end()==0 && stops==1 && upload && !s_agent_started);
  notice(QM_AGENT_EVENT_TTS,0); assert(forwarded_texts==before_text);
  /* Wake-up takes ownership. Worker cleanup must not stop the new conversation. */
  start_ready(); on_wakeup();
  notice(QM_AGENT_EVENT_TTS,0); assert(forwarded_texts==before_text);
  assert(hv_gesture_agent_port_poll()==-QM_EINTR && upload && wakes==1);
  assert(hv_gesture_agent_port_end()==0 && stops==1 && s_agent_started);
  assert(agent_app_leave()==0 && stops==2);
  /* Explicit resource ownership retains its microphone policy on cleanup. */
  start_ready(); hv_gesture_agent_port_cancel(); upload=false;
  assert(hv_gesture_agent_port_end()==0 && stops==2 && !upload);
  agent_app_leave();
  /* SDK error cancels the request but still requires worker-owned stop. */
  start_ready(); notice(QM_AGENT_EVENT_ERROR,0);
  assert(hv_gesture_agent_port_poll()==-QM_EINTR);
  assert(hv_gesture_agent_port_end()==0 && stops==4);
  start_ready(); on_cloud_event(LJYD_CLOUD_EVENT_DISCONNECTED,0,0);
  assert(hv_gesture_agent_port_end()==0 && stops==5);
  on_cloud_event(LJYD_CLOUD_EVENT_CONNECTED,0,0);
  start_result=-QM_EIO;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EIO && upload);
  assert(!strcmp(detail,"start_failed") && !atomic_load(&s_gesture_owned));
  start_result=-QM_EBUSY;
  assert(hv_gesture_agent_port_begin_detail(&detail)==-QM_EBUSY && upload);
  assert(!strcmp(detail,"start_failed") && !atomic_load(&s_gesture_owned));
  start_result=0; start_ready();
  notice(QM_AGENT_EVENT_TTS,0); dialog(QM_AGENT_DIALOG_STATE_SPEAKING);
  notice(QM_AGENT_EVENT_TTS_PLAYBACK_STARTED,4);
  post_result=-QM_EIO; dialog(QM_AGENT_DIALOG_STATE_SILENT);
  assert(hv_gesture_agent_port_poll()==-QM_EIO);
  assert(hv_gesture_agent_port_end()==0);
  start_ready(); stop_result=-QM_EIO;
  assert(hv_gesture_agent_port_end()==-QM_EIO && !upload);
  assert(hv_gesture_agent_port_begin()==-QM_EBUSY);
  stop_result=0; assert(agent_app_leave()==0);
  start_ready(); assert(hv_gesture_agent_port_end()==0);
  /* Unsupported physical completion is distinct from confirmed completion. */
  post_result=0; audio_caps=0; start_ready(); reply_input(10);
  failure(9,-QM_ENOSYS); assert(hv_gesture_agent_port_poll()==1);
  failure(10,-QM_ENOSYS);
  assert(hv_gesture_agent_port_poll()==HV_GESTURE_PORT_COMPLETION_UNSUPPORTED);
  assert(!s_gesture_reply.complete && !s_gesture_reply.failed);
  assert(hv_gesture_agent_port_end()==0);
  /* ENOSYS before a closed reply, or on a DRAIN-capable backend, stays failure. */
  start_ready(); notice(QM_AGENT_EVENT_TTS_PLAYBACK_STARTED,11); failure(11,-QM_ENOSYS);
  assert(hv_gesture_agent_port_poll()==-QM_ENOSYS); assert(hv_gesture_agent_port_end()==0);
  audio_caps=QM_AUDIO_CAP_DRAIN; start_ready(); reply_input(12); failure(12,-QM_ENOSYS);
  assert(hv_gesture_agent_port_poll()==-QM_ENOSYS); assert(hv_gesture_agent_port_end()==0);
  audio_caps=0; start_ready(); reply_input(13); failure(13,-2);
  assert(hv_gesture_agent_port_poll()==-2); assert(hv_gesture_agent_port_end()==0);
  assert(lock_taken==0);
  return 0;
}
'''


class PortTests(unittest.TestCase):
    def test_owned_session_reply_and_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "stubs.h").write_text(STUBS)
            for name in ("freertos/FreeRTOS.h", "freertos/semphr.h", "qm_agent_event.h"):
                path = temp / name; path.parent.mkdir(exist_ok=True)
                path.write_text('#include "stubs.h"\n')
            (temp / "test.c").write_text(HARNESS)
            for macro in ("HV_GESTURE_AGENT_CONFIG_HEADER", "HV_GESTURE_AGENT_DIAGNOSTICS"):
                with self.subTest(macro=macro):
                    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                                    "-D" + macro + "=1", "-I", str(temp),
                                    "-I", str(ROOT / "headvoice/firmware"), "-I", str(ROOT / "headvoice/core"),
                                    str(temp / "test.c"), str(ROOT / "headvoice/core/hv_gesture_reply.c"),
                                    "-o", str(temp / "test")], check=True)
                    subprocess.run([str(temp / "test")], check=True)


if __name__ == "__main__": unittest.main()

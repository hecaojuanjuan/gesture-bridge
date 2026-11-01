/* Included only in the prepared hand app's agent_app.c. This keeps access to
 * the SDK's private session app-local and leaves the pinned SDK untouched. */
#if defined(HV_GESTURE_AGENT_CONFIG_HEADER) || defined(HV_GESTURE_AGENT_DIAGNOSTICS)
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "hv_gesture_reply.h"

static SemaphoreHandle_t s_gesture_lifecycle;
static atomic_bool s_gesture_owned, s_gesture_cancelled, s_gesture_remote, s_gesture_handoff;
static atomic_bool s_gesture_resource;
static atomic_int s_gesture_dialog;
static portMUX_TYPE s_gesture_guard = portMUX_INITIALIZER_UNLOCKED;
static hv_gesture_reply_t s_gesture_reply;
static bool s_gesture_armed;
static bool s_gesture_completion_unsupported, s_gesture_drain_unavailable;
static int s_gesture_reply_error;

int hv_gesture_agent_port_init(void)
{
    if (!s_gesture_lifecycle) s_gesture_lifecycle = xSemaphoreCreateRecursiveMutex();
    return s_gesture_lifecycle ? QM_EOK : -QM_ENOMEM;
}

void hv_gesture_agent_port_cancel(void)
{
    if (!s_gesture_lifecycle) return;
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    if (atomic_load(&s_gesture_owned)) {
        atomic_store(&s_gesture_handoff, true);
        atomic_store(&s_gesture_cancelled, true);
    }
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
}

void hv_gesture_agent_port_resource_mode(bool active)
{
    if (!s_gesture_lifecycle) return;
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    atomic_store(&s_gesture_resource, active);
    if (active) hv_gesture_agent_port_cancel();
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
}

bool hv_gesture_agent_port_cancelled(void *unused)
{
    (void)unused;
    return atomic_load(&s_gesture_cancelled);
}

void hv_gesture_agent_port_notice(int32_t id, const qm_agent_event_notice_t *notice)
{
    if (id == QM_AGENT_EVENT_AGENT_STATE && atomic_load(&s_gesture_owned) &&
        !atomic_load(&s_gesture_handoff))
        qm_agent_set_upload_enabled(s_agent, QM_FALSE);
    if (id == QM_AGENT_EVENT_REMOTE_USER_JOINED) atomic_store(&s_gesture_remote, true);
    if (id == QM_AGENT_EVENT_REMOTE_USER_LEFT || id == QM_AGENT_EVENT_DISCONNECTED ||
        id == QM_AGENT_EVENT_AGENT_ABORTED || id == QM_AGENT_EVENT_ERROR)
        atomic_store(&s_gesture_cancelled, true);
    if (id == QM_AGENT_EVENT_AGENT_STATE)
        atomic_store(&s_gesture_dialog, notice->data.agent_state.state);
    hv_reply_event_t event;
    switch (id) {
    case QM_AGENT_EVENT_TTS: case QM_AGENT_EVENT_AGENT_TEXT:
        if (!notice->data.text.text[0]) return;
        event = HV_REPLY_TEXT; break;
    case QM_AGENT_EVENT_AGENT_STATE:
        if (notice->data.agent_state.state == QM_AGENT_DIALOG_STATE_SPEAKING) event = HV_REPLY_SPEAKING;
        else if (notice->data.agent_state.state == QM_AGENT_DIALOG_STATE_SILENT) event = HV_REPLY_SILENT;
        else return;
        break;
    case QM_AGENT_EVENT_TTS_PLAYBACK_STARTED: event = HV_REPLY_STARTED; break;
    case QM_AGENT_EVENT_TTS_PLAYBACK_COMPLETE: event = HV_REPLY_COMPLETE; break;
    case QM_AGENT_EVENT_TTS_PLAYBACK_FAILED: event = HV_REPLY_FAILED; break;
    default: return;
    }
    portENTER_CRITICAL(&s_gesture_guard);
    bool close = false;
    if (s_gesture_armed && !atomic_load(&s_gesture_cancelled) &&
        !s_gesture_completion_unsupported) {
        /* With the isolated queue-drain fix, this exact terminal condition
         * confirms local handoff only. Never turn arbitrary ENOSYS into success. */
        if (event == HV_REPLY_FAILED && notice->code == -QM_ENOSYS &&
            s_gesture_drain_unavailable && !s_gesture_reply.failed &&
            s_gesture_reply.started && s_gesture_reply.input_closed &&
            notice->generation == s_gesture_reply.generation) {
            s_gesture_completion_unsupported = true;
        } else {
            bool was_failed = s_gesture_reply.failed;
            close = hv_gesture_reply_observe(&s_gesture_reply, event, notice->generation);
            if (!was_failed && s_gesture_reply.failed && event == HV_REPLY_FAILED)
                s_gesture_reply_error = notice->code != QM_EOK ? notice->code : -QM_EIO;
        }
    }
    portEXIT_CRITICAL(&s_gesture_guard);
    if (close) {
        qm_agent_event_t *boundary = qm_malloc(sizeof(*boundary));
        int ret = -QM_ENOMEM;
        if (boundary) {
            qm_memset(boundary, 0, sizeof(*boundary));
            boundary->id = QM_AGENT_EVENT_TTS_INPUT_COMPLETE;
            boundary->source = QM_AGENT_EVENT_SOURCE_TRANSPORT;
            ret = qm_agent_control_post_event(s_agent, boundary);
        }
        if (ret != QM_EOK) {
            portENTER_CRITICAL(&s_gesture_guard);
            s_gesture_reply.failed = true;
            s_gesture_reply_error = ret;
            portEXIT_CRITICAL(&s_gesture_guard);
        }
    }
}

int hv_gesture_agent_port_begin(void)
{
    if (!s_gesture_lifecycle) return -QM_EINIT;
    if (xSemaphoreTakeRecursive(s_gesture_lifecycle, 0) != pdTRUE) return -QM_EBUSY;
    int ret = -QM_EBUSY;
    if (s_agent && s_cloud_connected && !s_agent_started && !s_waiting_tts_complete &&
        !atomic_load(&s_gesture_resource) &&
        !atomic_load(&s_gesture_owned)) {
        atomic_store(&s_gesture_cancelled, false);
        atomic_store(&s_gesture_handoff, false);
        atomic_store(&s_gesture_remote, false);
        atomic_store(&s_gesture_dialog, QM_AGENT_DIALOG_STATE_NONE);
        qm_audio_caps_t caps = {0};
        s_gesture_drain_unavailable = qm_audio_get_caps(&caps) == QM_EOK &&
            (caps.flags & QM_AUDIO_CAP_DRAIN) == 0;
        atomic_store(&s_gesture_owned, true);
        qm_agent_set_upload_enabled(s_agent, QM_FALSE);
        ret = qm_agent_start(s_agent);
        if (ret == QM_EOK) s_agent_started = 1;
        else {
            atomic_store(&s_gesture_owned, false);
            qm_agent_set_upload_enabled(s_agent, QM_TRUE);
        }
    }
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
    return ret;
}

int hv_gesture_agent_port_ready(void)
{
    if (atomic_load(&s_gesture_cancelled)) return -QM_EINTR;
    int dialog = atomic_load(&s_gesture_dialog);
    return s_agent && atomic_load(&s_gesture_remote) &&
        qm_agent_get_state(s_agent) == QM_AGENT_STATE_RUNNING &&
        !qm_agent_audio_engine_stream_active(s_agent) &&
        dialog != QM_AGENT_DIALOG_STATE_THINKING && dialog != QM_AGENT_DIALOG_STATE_SPEAKING;
}

int hv_gesture_agent_port_arm(void)
{
    if (atomic_load(&s_gesture_cancelled) || !atomic_load(&s_gesture_owned)) return -QM_EINTR;
    portENTER_CRITICAL(&s_gesture_guard);
    qm_memset(&s_gesture_reply, 0, sizeof(s_gesture_reply));
    s_gesture_completion_unsupported = false;
    s_gesture_reply_error = -QM_EIO;
    s_gesture_armed = true;
    portEXIT_CRITICAL(&s_gesture_guard);
    return QM_EOK;
}

int hv_gesture_agent_port_poll(void)
{
    if (atomic_load(&s_gesture_cancelled)) return -QM_EINTR;
    portENTER_CRITICAL(&s_gesture_guard);
    int ret = s_gesture_reply.failed ? s_gesture_reply_error :
              s_gesture_completion_unsupported ? HV_GESTURE_PORT_COMPLETION_UNSUPPORTED :
              s_gesture_reply.complete ? 2 :
              s_gesture_reply.started ? 1 : 0;
    portEXIT_CRITICAL(&s_gesture_guard);
    return ret;
}

int hv_gesture_agent_port_end(void)
{
    portENTER_CRITICAL(&s_gesture_guard);
    s_gesture_armed = false;
    portEXIT_CRITICAL(&s_gesture_guard);
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    int ret = QM_EOK;
    if (atomic_load(&s_gesture_owned)) {
        /* A wake word/resource/cloud shutdown has taken ownership on cancel. */
        if (!atomic_load(&s_gesture_handoff)) {
            ret = agent_app_leave_unlocked();
            if (ret == QM_EOK) qm_agent_set_upload_enabled(s_agent, QM_TRUE);
        }
        if (ret == QM_EOK) atomic_store(&s_gesture_owned, false);
    }
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
    return ret;
}

static void on_wakeup(void)
{
    hv_gesture_agent_port_cancel();
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    /* Wake words restore ordinary microphone conversation after text input. */
    on_wakeup_unlocked();
    if (s_agent) qm_agent_set_upload_enabled(s_agent, QM_TRUE);
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
}

static void on_cloud_event(ljyd_cloud_event_t event, void *handle, void *userdata)
{
    if (event == LJYD_CLOUD_EVENT_DISCONNECTED) hv_gesture_agent_port_cancel();
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    on_cloud_event_unlocked(event, handle, userdata);
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
}

int agent_app_leave(void)
{
    if (!s_gesture_lifecycle) return -QM_EINIT;
    hv_gesture_agent_port_cancel();
    xSemaphoreTakeRecursive(s_gesture_lifecycle, portMAX_DELAY);
    int ret = agent_app_leave_unlocked();
    if (ret == QM_EOK) atomic_store(&s_gesture_owned, false);
    xSemaphoreGiveRecursive(s_gesture_lifecycle);
    return ret;
}
#else
int hv_gesture_agent_port_init(void) { return QM_EOK; }
void hv_gesture_agent_port_cancel(void) {}
void hv_gesture_agent_port_resource_mode(bool active) { (void)active; }
void hv_gesture_agent_port_notice(int32_t id, const qm_agent_event_notice_t *notice)
{ (void)id; (void)notice; }
static void on_wakeup(void) { on_wakeup_unlocked(); }
static void on_cloud_event(ljyd_cloud_event_t event, void *handle, void *userdata)
{ on_cloud_event_unlocked(event, handle, userdata); }
int agent_app_leave(void) { return agent_app_leave_unlocked(); }
#endif

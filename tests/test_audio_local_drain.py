"""Run the patched production Engine with the SDK's real worker test backend."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_sdk import drain_local_audio_before_unsupported, replace

EXTRA = r'''
typedef struct {
    stream_call_t call;
    atomic_int returned;
} local_drain_call_t;

static void *local_drain_thread(void *context)
{
    local_drain_call_t *call = context;
    call->call.result = qm_audio_engine_render_drain(call->call.stream, TEST_WAIT_MS);
    atomic_store(&call->returned, 1);
    return NULL;
}

static void await_local_drain(local_drain_call_t *call)
{
    qm_utils_time_t deadline;
    qm_utils_time_countdown_ms(&deadline, TEST_WAIT_MS);
    for (;;) {
        qm_audio_engine_t *engine = call->call.stream->engine;
        qm_mutex_lock(&engine->lock, QM_WAIT_FOREVER);
        qm_bool active = call->call.stream->drain_active;
        qm_mutex_unlock(&engine->lock);
        assert(!atomic_load(&call->returned));
        if (active) return;
        assert(qm_utils_time_left(&deadline) != 0U);
        sched_yield();
    }
}

static void test_local_drain(qm_bool unsupported, qm_bool cancel, int write_error)
{
    atomic_store(&without_drain, unsupported);
    atomic_store(&forced_write_error, 0);
    qm_audio_engine_t *engine = create_engine(QM_FALSE);
    qm_audio_render_stream_t *stream = open_stream(engine);
    uint8_t bytes[TEST_PACKET_BYTES] = {17U};
    qm_audio_data_t input = {.data=bytes,.size=sizeof(bytes)};
    uint32_t written = 0U;
    local_drain_call_t call = {.call={.stream=stream,.result=-QM_ERROR}};

    atomic_store(&device.block_write, 1);
    assert(qm_audio_engine_render_write(stream,&input,TEST_WAIT_MS,&written)==QM_EOK);
    take(&device.write_entered);
    /* The second packet is still queued while the last device write blocks. */
    assert(qm_audio_engine_render_write(stream,&input,TEST_WAIT_MS,&written)==QM_EOK);
    assert(pthread_create(&call.call.thread,NULL,local_drain_thread,&call)==0);
    await_local_drain(&call);
    assert(atomic_load(&device.drains)==0 && !atomic_load(&call.returned));
    if (cancel) {
        assert(qm_audio_engine_render_stop(stream)==QM_EOK);
    } else {
        atomic_store(&forced_write_error, write_error);
        atomic_store(&device.block_write, 0);
        give(&device.write_release);
    }
    assert(pthread_join(call.call.thread,NULL)==0);
    if (cancel) assert(call.call.result==-QM_EINTR);
    else if (write_error) assert(call.call.result==write_error);
    else {
        assert(call.call.result==(unsupported ? -QM_ENOSYS : QM_EOK));
        assert(atomic_load(&device.writes)==2);
        assert(atomic_load(&device.aborts)==0);
        assert(atomic_load(&device.drains)==(unsupported ? 0 : 1));
        qm_mutex_lock(&engine->lock,QM_WAIT_FOREVER);
        assert(!stream->pending_packets && !engine->render_inflight);
        assert(stream->state==(unsupported ? QM_AUDIO_RENDER_STATE_SEALED : QM_AUDIO_RENDER_STATE_DRAINED));
        qm_mutex_unlock(&engine->lock);
    }
    assert(qm_audio_engine_render_stop(stream)==QM_EOK);
    assert(qm_audio_engine_render_close(stream)==QM_EOK);
    destroy_engine(engine);
    atomic_store(&forced_write_error, 0);
    atomic_store(&without_drain, 0);
}

static void test_local_drain_deadline(void)
{
    atomic_store(&without_drain, 1);
    qm_audio_engine_t *engine=create_engine(QM_FALSE);
    qm_audio_render_stream_t *stream=open_stream(engine);
    uint8_t bytes[TEST_PACKET_BYTES]={25U};
    qm_audio_data_t input={.data=bytes,.size=sizeof(bytes)};
    uint32_t written=0;
    atomic_store(&device.block_write,1);
    assert(qm_audio_engine_render_write(stream,&input,TEST_WAIT_MS,&written)==QM_EOK);
    take(&device.write_entered);
    assert(qm_audio_engine_render_drain(stream,10)==-QM_ETIMEOUT);
    assert(atomic_load(&device.drains)==0);
    atomic_store(&device.block_write,0); give(&device.write_release);
    assert(qm_audio_engine_render_drain(stream,TEST_WAIT_MS)==-QM_ENOSYS);
    assert(qm_audio_engine_render_stop(stream)==QM_EOK);
    assert(qm_audio_engine_render_close(stream)==QM_EOK);
    destroy_engine(engine);
    atomic_store(&without_drain,0);
}

int main(void)
{
    /* Existing supported-drain, ownership, cancellation and Service cases. */
    assert(sdk_engine_regressions()==0);
    test_local_drain(QM_TRUE,QM_FALSE,0);
    test_local_drain(QM_TRUE,QM_TRUE,0);
    test_local_drain(QM_TRUE,QM_FALSE,-QM_EIO);
    test_local_drain(QM_FALSE,QM_FALSE,0);
    test_local_drain_deadline();
    puts("local queue drain without hardware completion ACK passed");
    return 0;
}
'''


class LocalDrainTests(unittest.TestCase):
    def test_production_engine_waits_for_tail_without_faking_completion(self):
        sdk = Path(os.environ.get("HEADVOICE_SDK", ROOT.parent / "ljyd_xjwb03_agent_public_developer"))
        qumi = sdk / "qumios-dev"
        audio = qumi / "components/qm_audio"
        original = (audio / "src/engine/qm_audio_engine.c").read_text()
        patched = drain_local_audio_before_unsupported(original)
        with self.assertRaises(RuntimeError):
            drain_local_audio_before_unsupported(patched)
        backend = (audio / "tests/test_engine.c").read_text()
        backend = replace(backend, 'static device_t device;',
                          'static device_t device;\nstatic atomic_int without_drain, forced_write_error;')
        backend = replace(backend, '    if (qm_audio_stream_format_valid(&ctx->config.input_format)) {',
                          '    if (atomic_load(&without_drain)) caps->flags &= ~QM_AUDIO_DEVICE_CAP_DRAIN;\n'
                          '    if (qm_audio_stream_format_valid(&ctx->config.input_format)) {')
        backend = replace(backend,
                          '    normal_leave(ctx);\n    return ret;\n}\n\nint qm_audio_device_playback_drain',
                          '    if (atomic_load(&forced_write_error)) ret=atomic_load(&forced_write_error);\n'
                          '    normal_leave(ctx);\n    return ret;\n}\n\nint qm_audio_device_playback_drain')
        backend = replace(backend, 'int main(void)', 'static int sdk_engine_regressions(void)')
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "engine.c").write_text(patched)
            (temp / "test.c").write_text(backend + EXTRA)
            includes = (audio / "tests", qumi / "include/common", qumi / "include/qmos",
                        qumi / "utility/timer", qumi / "utility/string", audio / "include",
                        audio / "priv_include")
            command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                       "-Wno-sign-compare", "-Wno-unused-parameter", "-pthread"]
            for path in includes: command += ["-I", str(path)]
            command += [str(temp / "test.c"), str(temp / "engine.c"),
                        str(audio / "src/service/qm_audio_service.c"),
                        str(qumi / "platform/mcu/macos/qmos/qm_os.c"),
                        str(qumi / "utility/timer/qm_utils_timer.c"),
                        str(qumi / "utility/string/qm_string.c"), "-o", str(temp / "test")]
            subprocess.run(command, check=True)
            result = subprocess.run([str(temp / "test")], check=True, capture_output=True,
                                    text=True, timeout=30)
            self.assertIn("local queue drain without hardware completion ACK passed", result.stdout)
        self.assertEqual((audio / "src/engine/qm_audio_engine.c").read_text(), original)


if __name__ == "__main__": unittest.main()

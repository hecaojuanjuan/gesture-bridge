"""Run the actual mixed detector pipeline with deterministic SDK stubs."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_hand_app_firmware import HEADERS, NATIVE_HARNESS, ROOT, STUBS


ROUTING = r'''
static unsigned face_calls, centered_calls, centered_count, native_at_center;
static bool centered_valid;
static HvGimbalTarget centered_source;
static float centered_x, centered_y;
esp_err_t hv_face_pose_init(void) { return ESP_OK; }
esp_err_t hv_face_pose_analyze_rgb888(const uint8_t *rgb, uint16_t width, uint16_t height,
                                    yolo11_pose_frame_result_t *pose, hv_face_target_t *target) {
  (void)rgb; (void)width; (void)height;
  ++face_calls; clock_ms += 70;
  pose->person_count = 1; target->valid = true; target->x = .6f; target->y = .4f;
  return ESP_OK;
}
esp_err_t hv_face_gimbal_init(void) { return ESP_OK; }
void hv_face_gimbal_tick(uint64_t now) { (void)now; }
void hv_face_gimbal_invalidate(void) {}
void hv_face_gimbal_observe_target(HvGimbalTarget source, unsigned count, bool valid,
                                  float x, float y, uint64_t captured, uint64_t now) {
  assert(now >= captured);
  ++centered_calls; centered_source = source; centered_count = count;
  centered_valid = valid; centered_x = x; centered_y = y; native_at_center = native_calls;
}
int main(void) {
  assert(headvoice_start() == ESP_OK);
  hand_inference_state_t state; inference_state_init(&state);
  native_delay = 500;
  frame(&state, 1000, 0, 0);
  assert(centered_source == HV_GIMBAL_TARGET_HAND && centered_valid && centered_count == 1);
  assert(face_calls == 0 && native_at_center == 0 && native_calls == 1);
  assert(fabsf(centered_x - 130.0f / 320) < .001f);
  assert(fabsf(centered_y - 110.0f / 240) < .001f);
  detected_count = 0;
  frame(&state, 2000, 0, 0);
  assert(face_calls == 1 && centered_source == HV_GIMBAL_TARGET_FACE && centered_valid);
  detected_count = 2;
  frame(&state, 3000, 0, 0);
  assert(face_calls == 1 && !centered_valid && centered_count == 2);
  detected_count = 0; detector_fault = true;
  frame(&state, 4000, 0, 0);
  assert(face_calls == 1 && !centered_valid);
  detector_fault = false; detected_count = 1; fault_during_detector = true;
  frame(&state, 5000, 0, 0);
  assert(!centered_valid && centered_calls == 5);
  puts("Mixed centering pipeline passed");
  return 0;
}
'''


def main():
    stubs = STUBS.replace(
        "#endif", "typedef struct { unsigned person_count; } "
        "yolo11_pose_frame_result_t;\n#endif")
    source = NATIVE_HARNESS.split("int main(int argc, char **argv)")[0]
    source = source.replace(
        "hand->score = hand->valid ? .9f : 0;",
        "hand->score = hand->valid ? .9f : 0;\n"
        "hand->normalized_box[0] = 60.0f / 320;\n"
        "hand->normalized_box[1] = 20.0f / 240;\n"
        "hand->normalized_box[2] = 200.0f / 320;\n"
        "hand->normalized_box[3] = 200.0f / 240;")
    with tempfile.TemporaryDirectory(prefix="centering-pipeline-") as temp:
        directory = Path(temp)
        (directory / "stubs.h").write_text(stubs, encoding="utf-8")
        for name in HEADERS:
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "stubs.h"\n', encoding="utf-8")
        harness = directory / "harness.c"
        harness.write_text(source + ROUTING, encoding="utf-8")
        binary = directory / "pipeline.exe"
        subprocess.run([
            shutil.which("cc") or shutil.which("gcc") or "cc",
            "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
            "-UNDEBUG", "-DHV_STAGE=2", "-DHV_CENTERING=1",
            "-DHV_HAND_NATIVE_CLASSIFIER=1",
            '-DHV_HAND_NATIVE_PARTITION="test_native_model"',
            "-I", str(directory), "-I", str(ROOT),
            "-I", str(ROOT / "headvoice/core"),
            "-I", str(ROOT / "headvoice/firmware"), str(harness),
            str(ROOT / "headvoice/core/hv_hand_gate.c"),
            "-o", str(binary), "-lm"], check=True)
        output = subprocess.check_output([str(binary)], text=True)
    assert "Mixed centering pipeline passed" in output
    print("PASS hand priority, zero-hand face fallback, ambiguity/fault rejection, early control")


if __name__ == "__main__":
    main()

#include "hv_face_pose.h"
#include "hv_face_landmarks.h"
#include "human_face_detect.hpp"
#include "esp_log.h"
#include <cstring>
#include <new>

#if HV_FACE_SELFTEST
#include "dl_image_jpeg.hpp"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include <cstdio>
extern const uint8_t hv_face_selftest_jpg_start[] asm("_binary_hv_face_selftest_jpg_start");
extern const uint8_t hv_face_selftest_jpg_end[] asm("_binary_hv_face_selftest_jpg_end");
#endif

#if !CONFIG_HUMAN_FACE_DETECT_MODEL_IN_FLASH_RODATA
#error "HeadVoice face models must be embedded in the application; no partition changes"
#endif

static HumanFaceDetect *s_face;

#if HV_FACE_SELFTEST
extern "C" void hv_face_pose_selftest(void)
{
    /* Called once by the sole inference task before it receives camera frames.
     * Keep this result out of the camera observation mailbox and all timings. */
    static bool ran;
    if (ran) return;
    ran = true;
    if (!s_face) {
        std::printf("HV_SELFTEST {\"event\":\"error\",\"reason\":\"model_not_ready\"}\n");
        return;
    }
    std::printf("HV_SELFTEST {\"event\":\"begin\",\"fixture\":\"espressif_human_face\","
                "\"sha256\":\"65d23c18bd5d75370d3eff48130ac441b99f9ffd75bbfd6eff4c9ae0d8b4d68a\","
                "\"expected_faces\":1,\"diagnostic_only\":true}\n");
    int64_t started = esp_timer_get_time();
    dl::image::jpeg_img_t jpeg = {
        .data = const_cast<uint8_t *>(hv_face_selftest_jpg_start),
        .data_len = static_cast<size_t>(hv_face_selftest_jpg_end - hv_face_selftest_jpg_start)};
    auto image = dl::image::sw_decode_jpeg(jpeg, dl::image::DL_IMAGE_PIX_TYPE_RGB888);
    int64_t decoded = esp_timer_get_time();
    if (!image.data || image.width != 320 || image.height != 240) {
        std::printf("HV_SELFTEST {\"event\":\"error\",\"reason\":\"decode_failed_or_wrong_dimensions\","
                    "\"width\":%u,\"height\":%u}\n", (unsigned)image.width, (unsigned)image.height);
        if (image.data) heap_caps_free(image.data);
        return;
    }
    /* The official example is already upright RGB888. No UYVY conversion,
     * rotation or channel swap here; the detector owns model preprocessing. */
    const auto &faces = s_face->run(image);
    int64_t finished = esp_timer_get_time();
    std::printf("HV_SELFTEST {\"event\":\"result\",\"faces\":%u,\"expected_faces\":1,"
                "\"decode_ms\":%u,\"model_ms\":%u,\"width\":320,\"height\":240}\n",
                (unsigned)faces.size(), (unsigned)((decoded - started) / 1000),
                (unsigned)((finished - decoded) / 1000));
    unsigned index = 0;
    for (const auto &face : faces) {
        if (index >= 8) break;  // Bound diagnostic output, even for corrupt results.
        hv_face_eyes_t eyes;
        bool valid = hv_face_eye_points(face.keypoint.data(), face.keypoint.size(),
                                       faces.size(), image.width, image.height, face.score, &eyes);
        if (face.box.size() >= 4 && face.keypoint.size() >= 10) {
            std::printf("HV_SELFTEST {\"event\":\"face\",\"index\":%u,\"score\":%.6f,"
                        "\"box\":[%d,%d,%d,%d],\"keypoints\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d],"
                        "\"head_valid\":%s}\n", index, (double)face.score,
                        face.box[0], face.box[1], face.box[2], face.box[3],
                        face.keypoint[0], face.keypoint[1], face.keypoint[2], face.keypoint[3],
                        face.keypoint[4], face.keypoint[5], face.keypoint[6], face.keypoint[7],
                        face.keypoint[8], face.keypoint[9], valid ? "true" : "false");
        }
        ++index;
    }
    heap_caps_free(image.data);
    std::printf("HV_SELFTEST {\"event\":\"end\",\"camera_inference_follows\":true}\n");
}
#endif

extern "C" esp_err_t hv_face_pose_init(void)
{
    if (s_face) return ESP_OK;
    /* Eager initialization happens once at startup. Only the inference task
     * subsequently accesses the detector and its resident result buffers. */
    s_face = new (std::nothrow) HumanFaceDetect(HumanFaceDetect::MSRMNP_S8_V1, false);
    if (!s_face) return ESP_ERR_NO_MEM;
    if (!s_face->get_raw_model(0) || !s_face->get_raw_model(1)) {
        delete s_face; s_face = nullptr;
        return ESP_FAIL;
    }
    ESP_LOGI("hv_face", "MSR/MNP v1 ready; visible-face count, eye-line tilt only");
    return ESP_OK;
}

extern "C" esp_err_t hv_face_pose_analyze_rgb888(const uint8_t *rgb, uint16_t width,
                                                uint16_t height,
                                                yolo11_pose_frame_result_t *out,
                                                hv_face_target_t *target)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    std::memset(out, 0, sizeof(*out));
    if (target) std::memset(target, 0, sizeof(*target));
    out->status = YOLO11_POSE_FRAME_NO_PERSON;
    if (!rgb || !width || !height) return ESP_ERR_INVALID_ARG;
    if (!s_face) return ESP_ERR_INVALID_STATE;
    dl::image::img_t image = {.data = const_cast<uint8_t *>(rgb),
        .width = width, .height = height, .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888};
    const auto &faces = s_face->run(image);
    out->person_count = (unsigned)faces.size();
    if (faces.empty()) return ESP_OK;
    out->status = YOLO11_POSE_FRAME_UNKNOWN;
    if (faces.size() != 1) return ESP_OK;
    const auto &face = faces.front();
    hv_face_eyes_t eyes;
    if (!hv_face_eye_points(face.keypoint.data(), face.keypoint.size(), out->person_count,
                           width, height, face.score, &eyes)) return ESP_OK;
    if (target) {
        target->valid = hv_face_box_center(face.box.data(), face.box.size(), width, height,
                                           &target->x, &target->y);
    }
    out->eye_x1 = eyes.x1; out->eye_y1 = eyes.y1;
    out->eye_x2 = eyes.x2; out->eye_y2 = eyes.y2;
    out->head_valid = true;
    out->status = YOLO11_POSE_FRAME_OK;
    return ESP_OK;
}

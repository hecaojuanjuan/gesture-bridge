#include "headvoice_app.h"

#include <linux/videodev2.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <new>

#include "bsp_camera.h"
#include "dl_detect_espdet_postprocessor.hpp"
#include "dl_image_preprocessor.hpp"
#include "dl_model_base.hpp"
#include "esp_heap_caps.h"
#include "esp_partition.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include "yolo11_pose.h"

namespace {
constexpr size_t RAW_BYTES = 240 * 320 * 2;
struct Frame { uint8_t *bytes; uint64_t captured_ms; };
Frame frames[2]{};
QueueHandle_t free_queue, pending_queue;
dl::Model *model;
dl::image::ImagePreprocessor *preprocessor;
dl::detect::ESPDetPostProcessor *postprocessor;
uint32_t captured, dropped, inferred;

const char *gesture(int category)
{
    static constexpr const char *names[] = {
        "closed_fist", "ok_sign", "one_finger", "open_palm",
        "six_sign", "thumbs_up", "v_sign"};
    return category >= 0 && category < 7 ? names[category] : "other";
}

bool verify_partition(const esp_partition_t *partition)
{
    if (!partition || partition->size < HV_ESPDET_MODEL_BYTES) return false;
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    int error = mbedtls_sha256_starts(&ctx, 0);
    uint8_t buffer[1024], digest[32];
    for (size_t offset = 0; !error && offset < HV_ESPDET_MODEL_BYTES; offset += sizeof(buffer)) {
        size_t count = std::min(sizeof(buffer), size_t(HV_ESPDET_MODEL_BYTES) - offset);
        if (esp_partition_read(partition, offset, buffer, count) != ESP_OK) { error = -1; break; }
        error = mbedtls_sha256_update(&ctx, buffer, count);
    }
    if (!error) error = mbedtls_sha256_finish(&ctx, digest);
    mbedtls_sha256_free(&ctx);
    if (error) return false;
    constexpr char digits[] = "0123456789abcdef";
    char hex[65];
    for (int i = 0; i < 32; ++i) {
        hex[i * 2] = digits[digest[i] >> 4];
        hex[i * 2 + 1] = digits[digest[i] & 15];
    }
    hex[64] = 0;
    return strcmp(hex, HV_ESPDET_MODEL_SHA) == 0;
}

bool init_model()
{
    const auto *partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, HV_ESPDET_PARTITION);
    if (!verify_partition(partition)) return false;
    const void *mapped = nullptr;
    esp_partition_mmap_handle_t handle = 0;
    if (esp_partition_mmap(partition, 0, HV_ESPDET_MODEL_BYTES,
                           ESP_PARTITION_MMAP_DATA, &mapped, &handle) != ESP_OK || !mapped) return false;
    model = new (std::nothrow) dl::Model(static_cast<const char *>(mapped),
        fbs::MODEL_LOCATION_IN_FLASH_RODATA, 0, dl::MEMORY_MANAGER_GREEDY, nullptr, false);
    if (!model || !model->get_input() || !model->get_input()->data) return false;
    const char *outputs[] = {"box0", "score0", "box1", "score1", "box2", "score2"};
    for (const char *name : outputs)
        if (!model->get_output(name)) return false;
    model->minimize();
    preprocessor = new (std::nothrow) dl::image::ImagePreprocessor(
        model, {0, 0, 0}, {255, 255, 255});
    if (!preprocessor) return false;
    preprocessor->enable_letterbox({114, 114, 114});
    postprocessor = new (std::nothrow) dl::detect::ESPDetPostProcessor(
        model, preprocessor, .25f, .5f, 10,
        {{8, 8, 4, 4}, {16, 16, 8, 8}, {32, 32, 16, 16}});
    return postprocessor != nullptr;
}

struct BenchStats {
    uint32_t minimum;
    uint32_t median;
    uint32_t p95;
    uint32_t maximum;
    uint64_t mean;
};

template <size_t N>
BenchStats summarize(std::array<uint32_t, N> values)
{
    std::sort(values.begin(), values.end());
    uint64_t sum = 0;
    for (uint32_t value : values) sum += value;
    return {
        values.front(),
        uint32_t((uint64_t(values[N / 2 - 1]) + values[N / 2]) / 2),
        values[(N * 95 + 99) / 100 - 1],
        values.back(),
        sum / N,
    };
}

void run_synthetic_benchmark()
{
    constexpr uint32_t WARMUP = 3;
    constexpr size_t SAMPLES = 20;
    constexpr size_t RGB_BYTES = 320 * 240 * 3;
    auto *pixels = static_cast<uint8_t *>(heap_caps_malloc(
        RGB_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!pixels) {
        printf("HG {\"event\":\"espdet_benchmark\",\"status\":\"no_memory\"}\n");
        return;
    }
    for (size_t i = 0; i < RGB_BYTES; ++i)
        pixels[i] = uint8_t((i * 37 + i / 320) & 0xff);

    const dl::image::img_t image = {.data = pixels, .width = 320, .height = 240,
                                    .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888};
    std::array<uint32_t, SAMPLES> preprocess_us{}, model_us{}, postprocess_us{}, pipeline_us{};
    uint32_t detection_total = 0;
    for (uint32_t i = 0; i < WARMUP + SAMPLES; ++i) {
        const int64_t pipeline_started = esp_timer_get_time();
        int64_t tick = pipeline_started;
        preprocessor->preprocess(image);
        const uint32_t prep = uint32_t(esp_timer_get_time() - tick);
        tick = esp_timer_get_time();
        model->run();
        const uint32_t inference = uint32_t(esp_timer_get_time() - tick);
        tick = esp_timer_get_time();
        postprocessor->clear_result();
        postprocessor->postprocess();
        const auto &results = postprocessor->get_result(320, 240);
        const uint32_t post = uint32_t(esp_timer_get_time() - tick);
        if (i >= WARMUP) {
            const size_t sample = i - WARMUP;
            preprocess_us[sample] = prep;
            model_us[sample] = inference;
            postprocess_us[sample] = post;
            pipeline_us[sample] = uint32_t(esp_timer_get_time() - pipeline_started);
            detection_total += results.size();
        }
    }
    heap_caps_free(pixels);

    const BenchStats prep = summarize(preprocess_us);
    const BenchStats inference = summarize(model_us);
    const BenchStats post = summarize(postprocess_us);
    const BenchStats pipeline = summarize(pipeline_us);
    printf("HG {\"event\":\"espdet_benchmark\",\"status\":\"ok\","
           "\"input\":\"synthetic_rgb_320x240\",\"warmup\":%u,\"samples\":%u,"
           "\"preprocess_median_ms\":%.3f,\"model_median_ms\":%.3f,"
           "\"model_p95_ms\":%.3f,\"postprocess_median_ms\":%.3f,"
           "\"pipeline_mean_ms\":%.3f,\"pipeline_median_ms\":%.3f,"
           "\"pipeline_p95_ms\":%.3f,\"pipeline_min_ms\":%.3f,"
           "\"pipeline_max_ms\":%.3f,\"mean_detections\":%.2f}\n",
           (unsigned)WARMUP, (unsigned)SAMPLES,
           prep.median / 1000.0, inference.median / 1000.0, inference.p95 / 1000.0,
           post.median / 1000.0, pipeline.mean / 1000.0, pipeline.median / 1000.0,
           pipeline.p95 / 1000.0, pipeline.minimum / 1000.0, pipeline.maximum / 1000.0,
           detection_total / double(SAMPLES));
}

void camera_frame(const uint8_t *bytes, size_t length, uint32_t width,
                  uint32_t height, uint32_t format, uint64_t captured_ms)
{
    if (!bytes || length != RAW_BYTES || width != 240 || height != 320 ||
        format != V4L2_PIX_FMT_UYVY) return;
    ++captured;
    if (!model) return;
    Frame *frame = nullptr;
    if (xQueueReceive(pending_queue, &frame, 0) == pdTRUE) ++dropped;
    else if (xQueueReceive(free_queue, &frame, 0) != pdTRUE) { ++dropped; return; }
    memcpy(frame->bytes, bytes, RAW_BYTES);
    frame->captured_ms = captured_ms;
    if (xQueueSend(pending_queue, &frame, 0) != pdTRUE)
        xQueueSend(free_queue, &frame, 0);
}

void inference_task(void *)
{
    for (;;) {
        Frame *frame = nullptr;
        if (xQueueReceive(pending_queue, &frame, portMAX_DELAY) != pdTRUE) continue;
        const int64_t started = esp_timer_get_time();
        uint8_t *rgb = nullptr;
        uint16_t width = 0, height = 0;
#if HV_ROTATE_CW90
        const esp_err_t result = yolo11_pose_uyvy_to_rgb888_cw90(
#else
        const esp_err_t result = yolo11_pose_uyvy_to_rgb888(
#endif
            frame->bytes, RAW_BYTES, 240, 320, &rgb, &width, &height);
        const uint64_t timestamp = frame->captured_ms;
        xQueueSend(free_queue, &frame, 0);
        if (result != ESP_OK || width != 320 || height != 240) continue;
        const uint32_t conversion_ms = uint32_t((esp_timer_get_time() - started) / 1000);
        dl::image::img_t image = {.data = rgb, .width = width, .height = height,
                                  .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888};
        int64_t tick = esp_timer_get_time();
        preprocessor->preprocess(image);
        const uint32_t preprocess_ms = uint32_t((esp_timer_get_time() - tick) / 1000);
        tick = esp_timer_get_time();
        model->run();
        const uint32_t model_ms = uint32_t((esp_timer_get_time() - tick) / 1000);
        tick = esp_timer_get_time();
        postprocessor->clear_result();
        postprocessor->postprocess();
        const auto &results = postprocessor->get_result(width, height);
        const uint32_t postprocess_ms = uint32_t((esp_timer_get_time() - tick) / 1000);
        const uint32_t total_ms = uint32_t((esp_timer_get_time() - started) / 1000);
        if (results.empty()) {
            printf("HG {\"event\":\"espdet\",\"seq\":%u,\"captured_ms\":%llu,"
                   "\"gesture\":\"none\",\"score\":0,\"total_ms\":%u,"
                   "\"conversion_ms\":%u,\"preprocess_ms\":%u,\"model_ms\":%u,\"postprocess_ms\":%u}\n",
                   (unsigned)++inferred, (unsigned long long)timestamp, (unsigned)total_ms,
                   (unsigned)conversion_ms, (unsigned)preprocess_ms,
                   (unsigned)model_ms, (unsigned)postprocess_ms);
        } else {
            const auto &top = results.front();
            printf("HG {\"event\":\"espdet\",\"seq\":%u,\"captured_ms\":%llu,"
                   "\"gesture\":\"%s\",\"score\":%.4f,\"box\":[%d,%d,%d,%d],"
                   "\"total_ms\":%u,\"conversion_ms\":%u,\"preprocess_ms\":%u,"
                   "\"model_ms\":%u,\"postprocess_ms\":%u}\n",
                   (unsigned)++inferred, (unsigned long long)timestamp, gesture(top.category),
                   double(top.score), top.box[0], top.box[1], top.box[2], top.box[3],
                   (unsigned)total_ms, (unsigned)conversion_ms, (unsigned)preprocess_ms,
                   (unsigned)model_ms, (unsigned)postprocess_ms);
        }
        if (inferred % 20 == 0)
            printf("HG {\"event\":\"espdet_metrics\",\"captured\":%u,"
                   "\"dropped\":%u,\"psram_free\":%u}\n", (unsigned)captured, (unsigned)dropped,
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    }
}
} // namespace

extern "C" esp_err_t headvoice_start(void)
{
    free_queue = xQueueCreate(2, sizeof(Frame *));
    pending_queue = xQueueCreate(1, sizeof(Frame *));
    if (!free_queue || !pending_queue) return ESP_ERR_NO_MEM;
    for (auto &frame : frames) {
        frame.bytes = static_cast<uint8_t *>(heap_caps_malloc(
            RAW_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (!frame.bytes) return ESP_ERR_NO_MEM;
        Frame *pointer = &frame;
        xQueueSend(free_queue, &pointer, 0);
    }
    esp_err_t result = bsp_camera_early_init();
    if (result != ESP_OK) return result;
    if (!init_model()) {
        printf("HG {\"event\":\"espdet_init\",\"status\":\"failed\"}\n");
        return ESP_FAIL;
    }
    run_synthetic_benchmark();
    if (xTaskCreatePinnedToCoreWithCaps(inference_task, "hv_espdet", 16 * 1024,
            nullptr, 3, nullptr, 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS)
        return ESP_ERR_NO_MEM;
    result = bsp_camera_set_frame_callback(camera_frame);
    if (result != ESP_OK) return result;
    printf("HG {\"event\":\"ready\",\"backend\":\"espdet_pico_7\","
           "\"model_ready\":true}\n");
    return bsp_camera_stream_start();
}

#include "headvoice_app.h"

#include <linux/videodev2.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>

#include "bsp_camera.h"
#include "dl_model_base.hpp"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hv_camera_preview.h"
#include "mbedtls/sha256.h"
#include "yolo11_pose.h"

namespace {
constexpr size_t MODEL_BYTES = 2530192;
constexpr char MODEL_SHA[] = "7da8b50b8877383ba2561e37105364df2403a1dea870607a3578163d8a3f8e09";
constexpr size_t RAW_BYTES = 240 * 320 * 2;
struct Frame { uint8_t *bytes; uint64_t captured_ms; };
Frame frames[2]{};
QueueHandle_t free_queue, pending_queue;
dl::Model *model;
dl::TensorBase *input, *heads[3];
uint32_t captured, dropped, inferred;

const char *gesture(int cls)
{
  switch (cls) {
    case 20: return "open_palm";
    case 21: case 22: case 28: case 29: return "v_sign";
    case 18: return "ok_sign";
    case 4: return "six_sign";
    case 13: case 16: return "thumbs_up";
    case 14: return "closed_fist";
    case 3: case 11: case 19: return "one_finger";
    default: return "other";
  }
}

bool verify_partition(const esp_partition_t *partition)
{
  if (!partition || partition->size < MODEL_BYTES) return false;
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  int error = mbedtls_sha256_starts(&ctx, 0);
  uint8_t buffer[1024], digest[32];
  for (size_t offset = 0; !error && offset < MODEL_BYTES; offset += sizeof(buffer)) {
    const size_t count = std::min(sizeof(buffer), MODEL_BYTES - offset);
    if (esp_partition_read(partition, offset, buffer, count) != ESP_OK) { error = -1; break; }
    error = mbedtls_sha256_update(&ctx, buffer, count);
  }
  if (!error) error = mbedtls_sha256_finish(&ctx, digest);
  mbedtls_sha256_free(&ctx);
  if (error) return false;
  char hex[65];
  constexpr char digits[] = "0123456789abcdef";
  for (int i = 0; i < 32; ++i) {
    hex[i * 2] = digits[digest[i] >> 4];
    hex[i * 2 + 1] = digits[digest[i] & 15];
  }
  hex[64] = 0;
  return std::strcmp(hex, MODEL_SHA) == 0;
}

void init_model()
{
  const auto *partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, HV_YOLO_PARTITION);
  if (!verify_partition(partition)) {
    printf("HG {\"event\":\"yolo_init\",\"status\":\"model_missing_or_hash_mismatch\"}\n");
    return;
  }
  const void *mapped = nullptr;
  esp_partition_mmap_handle_t handle = 0;
  if (esp_partition_mmap(partition, 0, MODEL_BYTES, ESP_PARTITION_MMAP_DATA,
                         &mapped, &handle) != ESP_OK || !mapped) {
    printf("HG {\"event\":\"yolo_init\",\"status\":\"mmap_failed\"}\n");
    return;
  }
  model = new (std::nothrow) dl::Model(static_cast<const char *>(mapped),
      fbs::MODEL_LOCATION_IN_FLASH_RODATA, 0, dl::MEMORY_MANAGER_GREEDY,
      nullptr, false);
  if (!model) return;
  input = model->get_input();
  const char *names[3] = {"p3", "p4", "p5"};
  for (int i = 0; i < 3; ++i) heads[i] = model->get_output(names[i]);
  bool valid = input && input->data && input->dtype == dl::DATA_TYPE_INT8 &&
      input->shape == std::vector<int>({1, 320, 320, 3}) && input->exponent == -7;
  for (int i = 0; i < 3; ++i) {
    const int side = 40 >> i;
    valid = valid && heads[i] && heads[i]->data &&
        heads[i]->dtype == dl::DATA_TYPE_INT8 &&
        heads[i]->shape == std::vector<int>({1, side, side, 98});
  }
  if (!valid) {
    printf("HG {\"event\":\"yolo_init\",\"status\":\"bad_shape\"}\n");
    model = nullptr;
    return;
  }
  model->minimize();
  printf("HG {\"event\":\"yolo_init\",\"status\":\"ready\","
         "\"psram_free\":%u,\"internal_free\":%u}\n",
         (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
         (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}

float value(const dl::TensorBase *head, int y, int x, int c)
{
  const int side = head->shape[1];
  const auto *bytes = static_cast<const int8_t *>(head->data);
  return std::ldexp(float(bytes[(y * side + x) * 98 + c]), head->exponent);
}

void infer(const uint8_t *rgb, uint64_t captured_ms)
{
  auto *pixels = static_cast<int8_t *>(input->data);
  std::memset(pixels, 57, 320 * 320 * 3);
  for (int y = 0; y < 240; ++y)
    for (int x = 0; x < 320 * 3; ++x) {
      int q = (int(rgb[y * 320 * 3 + x]) * 128 + 127) / 255;
      pixels[((y + 40) * 320 * 3) + x] = int8_t(std::min(q, 127));
    }
  int64_t before = esp_timer_get_time();
  model->run();
  const uint32_t model_ms = uint32_t((esp_timer_get_time() - before) / 1000);
  float best = 0;
  int best_head = 0, best_x = 0, best_y = 0, best_class = -1;
  for (int level = 0; level < 3; ++level) {
    const int side = heads[level]->shape[1];
    for (int y = 0; y < side; ++y)
      for (int x = 0; x < side; ++x)
        for (int cls = 0; cls < 34; ++cls) {
          const float logit = value(heads[level], y, x, 64 + cls);
          if (logit > best || best_class < 0) {
            best = logit; best_class = cls; best_head = level;
            best_x = x; best_y = y;
          }
        }
  }
  const float score = 1.f / (1.f + std::exp(-best));
  float box[4]{};
  if (best_class >= 0) {
    const auto *head = heads[best_head];
    const int stride = 8 << best_head;
    float distance[4]{};
    for (int edge = 0; edge < 4; ++edge) {
      float peak = -INFINITY, sum = 0, weighted = 0;
      for (int bin = 0; bin < 16; ++bin)
        peak = std::max(peak, value(head, best_y, best_x, edge * 16 + bin));
      for (int bin = 0; bin < 16; ++bin) {
        float weight = std::exp(value(head, best_y, best_x, edge * 16 + bin) - peak);
        sum += weight; weighted += weight * bin;
      }
      distance[edge] = weighted / sum;
    }
    box[0] = std::clamp((best_x + .5f - distance[0]) * stride, 0.f, 320.f);
    box[1] = std::clamp((best_y + .5f - distance[1]) * stride - 40.f, 0.f, 240.f);
    box[2] = std::clamp((best_x + .5f + distance[2]) * stride, 0.f, 320.f);
    box[3] = std::clamp((best_y + .5f + distance[3]) * stride - 40.f, 0.f, 240.f);
  }
  printf("HG {\"event\":\"yolo\",\"seq\":%u,\"captured_ms\":%llu,"
         "\"model_ms\":%u,\"class_id\":%d,\"gesture\":\"%s\","
         "\"score\":%.4f,\"box\":[%.1f,%.1f,%.1f,%.1f]}\n",
         (unsigned)++inferred, (unsigned long long)captured_ms, (unsigned)model_ms, best_class,
         score >= .3f ? gesture(best_class) : "none", double(score),
         double(box[0]), double(box[1]), double(box[2]), double(box[3]));
}

void camera_frame(const uint8_t *bytes, size_t length, uint32_t width,
                  uint32_t height, uint32_t format, uint64_t captured_ms)
{
  if (!bytes || length != RAW_BYTES || width != 240 || height != 320 ||
      format != V4L2_PIX_FMT_UYVY) return;
  hv_camera_preview_offer(bytes, length, captured_ms);
  ++captured;
  if (!model) return;
  Frame *frame = nullptr;
  if (xQueueReceive(pending_queue, &frame, 0) == pdTRUE) ++dropped;
  else if (xQueueReceive(free_queue, &frame, 0) != pdTRUE) { ++dropped; return; }
  std::memcpy(frame->bytes, bytes, RAW_BYTES);
  frame->captured_ms = captured_ms;
  if (xQueueSend(pending_queue, &frame, 0) != pdTRUE)
    xQueueSend(free_queue, &frame, 0);
}

void inference_task(void *)
{
  std::memset(input->data, 57, 320 * 320 * 3);
  const int64_t probe_started = esp_timer_get_time();
  model->run();
  printf("HG {\"event\":\"model_probe\",\"model_ms\":%u}\n",
         (unsigned)((esp_timer_get_time() - probe_started) / 1000));
  for (;;) {
    Frame *frame;
    if (xQueueReceive(pending_queue, &frame, portMAX_DELAY) != pdTRUE) continue;
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
    hv_camera_preview_offer_model_input(rgb, width, height, timestamp);
    infer(rgb, timestamp);
    if (inferred % 5 == 0)
      printf("HG {\"event\":\"yolo_metrics\",\"captured\":%u,\"dropped\":%u,"
             "\"psram_free\":%u,\"internal_free\":%u}\n", (unsigned)captured, (unsigned)dropped,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  }
}
}  // namespace

extern "C" esp_err_t headvoice_start(void)
{
  free_queue = xQueueCreate(2, sizeof(Frame *));
  pending_queue = xQueueCreate(1, sizeof(Frame *));
  if (!free_queue || !pending_queue) return ESP_ERR_NO_MEM;
  for (auto &frame : frames) {
    frame.bytes = static_cast<uint8_t *>(heap_caps_malloc(RAW_BYTES,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!frame.bytes) return ESP_ERR_NO_MEM;
    Frame *pointer = &frame;
    xQueueSend(free_queue, &pointer, 0);
  }
  esp_err_t result = bsp_camera_early_init();
  if (result != ESP_OK) return result;
  if (hv_camera_preview_init() != ESP_OK) ESP_LOGW("hv_yolo", "preview unavailable");
  init_model();
  if (model && xTaskCreatePinnedToCoreWithCaps(inference_task, "hv_yolo", 16 * 1024,
            nullptr, 3, nullptr, 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) != pdPASS)
    return ESP_ERR_NO_MEM;
  result = bsp_camera_set_frame_callback(camera_frame);
  if (result != ESP_OK) return result;
  printf("HG {\"event\":\"ready\",\"backend\":\"yolov10n_int8\","
         "\"model_ready\":%s}\n", model ? "true" : "false");
  return bsp_camera_stream_start();
}

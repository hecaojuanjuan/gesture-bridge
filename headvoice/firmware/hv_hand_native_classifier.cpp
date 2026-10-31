#include "hv_hand_native_classifier.h"

#include "dl_image_preprocessor.hpp"
#include "dl_model_base.hpp"
#include "hand_gesture_cls_postprocessor.hpp"
#include "esp_partition.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

/* Matches the fixed official 0.1.0 RGB classifier pipeline. See
 * third_party/hand_gesture_recognition/UPSTREAM.json. We do not compile that
 * component's CMake or use ClsWrapper: this adapter owns the explicit partition
 * label, integrity check, eleven-class output and lifecycle. */
namespace {
dl::Model *s_model;
dl::image::ImagePreprocessor *s_preprocessor;
dl::cls::HandGestureClsPostprocessor *s_postprocessor;
char s_partition[17];

const char *const CLASS_NAMES[HV_HAND_NATIVE_CLASS_COUNT] = {
    "one", "two", "three", "four", "five", "like", "ok", "no_gesture",
    "call", "dislike", "no_hand"};

bool label_valid(const char *label)
{
  if (!label) return false;
  const size_t count = strnlen(label, sizeof(s_partition));
  return count > 0 && count < sizeof(s_partition);
}

hv_hand_native_status_t verify_model(const esp_partition_t *partition)
{
  uint8_t bytes[1024], digest[32];
  mbedtls_sha256_context context;
  mbedtls_sha256_init(&context);
  int result = mbedtls_sha256_starts(&context, 0);
  for (size_t offset = 0; !result && offset < HV_HAND_NATIVE_MODEL_BYTES;) {
    const size_t count = std::min(sizeof(bytes), size_t(HV_HAND_NATIVE_MODEL_BYTES) - offset);
    if (esp_partition_read(partition, offset, bytes, count) != ESP_OK) {
      mbedtls_sha256_free(&context);
      return HV_HAND_NATIVE_IO_ERROR;
    }
    result = mbedtls_sha256_update(&context, bytes, count);
    offset += count;
  }
  if (!result) result = mbedtls_sha256_finish(&context, digest);
  mbedtls_sha256_free(&context);
  if (result) return HV_HAND_NATIVE_IO_ERROR;

  static const char hex[] = "0123456789abcdef";
  char actual[65];
  for (size_t i = 0; i < sizeof(digest); ++i) {
    actual[i * 2] = hex[digest[i] >> 4];
    actual[i * 2 + 1] = hex[digest[i] & 15];
  }
  actual[64] = '\0';
  return std::strcmp(actual, HV_HAND_NATIVE_MODEL_SHA256) == 0
      ? HV_HAND_NATIVE_OK : HV_HAND_NATIVE_MODEL_HASH_MISMATCH;
}

int class_index(const char *name)
{
  if (name) {
    for (int i = 0; i < HV_HAND_NATIVE_CLASS_COUNT; ++i)
      if (std::strcmp(name, CLASS_NAMES[i]) == 0) return i;
  }
  return HV_HAND_NATIVE_CLASS_UNKNOWN;
}

uint32_t elapsed_ms(int64_t start, int64_t end)
{
  if (end <= start) return 0;
  const uint64_t duration = uint64_t(end - start) / 1000;
  return duration > UINT32_MAX ? UINT32_MAX : uint32_t(duration);
}

void clear_result(hv_hand_native_result_t *out)
{
  std::memset(out, 0, sizeof(*out));
  out->top_index = HV_HAND_NATIVE_CLASS_UNKNOWN;
}
} // namespace

extern "C" bool hv_hand_native_classifier_ready(void)
{
  return s_model && s_preprocessor && s_postprocessor;
}

extern "C" void hv_hand_native_classifier_deinit(void)
{
  delete s_postprocessor;
  delete s_preprocessor;
  delete s_model;
  s_postprocessor = nullptr;
  s_preprocessor = nullptr;
  s_model = nullptr;
  s_partition[0] = '\0';
}

extern "C" hv_hand_native_status_t hv_hand_native_classifier_init(
    const char *partition_label, const char *expected_sha256)
{
  if (!label_valid(partition_label) || !expected_sha256)
    return HV_HAND_NATIVE_INVALID_ARG;
  if (std::strcmp(expected_sha256, HV_HAND_NATIVE_MODEL_SHA256) != 0)
    return HV_HAND_NATIVE_MODEL_HASH_MISMATCH;
  if (hv_hand_native_classifier_ready())
    return std::strcmp(s_partition, partition_label) == 0
        ? HV_HAND_NATIVE_OK : HV_HAND_NATIVE_ALREADY_INITIALIZED;

  const esp_partition_t *partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, partition_label);
  if (!partition) return HV_HAND_NATIVE_PARTITION_MISSING;
  if (partition->size < HV_HAND_NATIVE_MODEL_BYTES)
    return HV_HAND_NATIVE_PARTITION_TOO_SMALL;
  const auto verified = verify_model(partition);
  if (verified != HV_HAND_NATIVE_OK) return verified;

  s_model = new (std::nothrow) dl::Model(
      partition_label, fbs::MODEL_LOCATION_IN_FLASH_PARTITION);
  if (!s_model) return HV_HAND_NATIVE_NO_MEMORY;
  auto *input = s_model->get_inputs().size() == 1 ? s_model->get_input() : nullptr;
  auto *output = s_model->get_outputs().size() == 1 ? s_model->get_output() : nullptr;
  if (!input || !output || !input->data || !output->data ||
      input->shape != std::vector<int>({1, 128, 128, 3}) ||
      input->dtype != dl::DATA_TYPE_INT8 || output->dtype != dl::DATA_TYPE_INT8 ||
      output->get_size() != HV_HAND_NATIVE_CLASS_COUNT) {
    hv_hand_native_classifier_deinit();
    return HV_HAND_NATIVE_BAD_MODEL;
  }
  s_model->minimize();
  s_preprocessor = new (std::nothrow) dl::image::ImagePreprocessor(
      s_model, {123.675f, 116.28f, 103.53f}, {58.395f, 57.12f, 57.375f},
      dl::image::DL_IMAGE_CAP_RGB565_BIG_ENDIAN);
  if (!s_preprocessor) {
    hv_hand_native_classifier_deinit();
    return HV_HAND_NATIVE_NO_MEMORY;
  }
  s_postprocessor = new (std::nothrow) dl::cls::HandGestureClsPostprocessor(
      s_model, HV_HAND_NATIVE_CLASS_COUNT, std::numeric_limits<float>::lowest(), true);
  if (!s_postprocessor) {
    hv_hand_native_classifier_deinit();
    return HV_HAND_NATIVE_NO_MEMORY;
  }
  std::memcpy(s_partition, partition_label, std::strlen(partition_label) + 1);
  return HV_HAND_NATIVE_OK;
}

extern "C" hv_hand_native_status_t hv_hand_native_classifier_analyze_rgb888(
    const uint8_t *rgb, size_t bytes, uint16_t width, uint16_t height,
    const hv_hand_detection_t *detection, hv_hand_native_result_t *out)
{
  if (!out) return HV_HAND_NATIVE_INVALID_ARG;
  clear_result(out);
  if (!rgb || !detection || !width || !height || width > 4096 || height > 4096 ||
      bytes != size_t(width) * size_t(height) * 3)
    return HV_HAND_NATIVE_INVALID_ARG;
  if (!detection->valid || detection->count != 1 || !std::isfinite(detection->score) ||
      detection->score < .5f || detection->score > 1.f ||
      detection->box[0] < 0 || detection->box[1] < 0 ||
      detection->box[0] >= detection->box[2] || detection->box[1] >= detection->box[3] ||
      detection->box[2] > width || detection->box[3] > height)
    return HV_HAND_NATIVE_INVALID_DETECTION;
  if (!hv_hand_native_classifier_ready()) return HV_HAND_NATIVE_NOT_READY;

  dl::image::img_t image = {.data = const_cast<uint8_t *>(rgb), .width = width,
      .height = height, .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888};
  const std::vector<int> crop(detection->box, detection->box + 4);
  const int64_t before_preprocess = esp_timer_get_time();
  s_preprocessor->preprocess(image, crop);
  const int64_t before_model = esp_timer_get_time();
  s_model->run();
  const int64_t before_postprocess = esp_timer_get_time();
  const auto &results = s_postprocessor->postprocess();
  const int64_t after_postprocess = esp_timer_get_time();
  if (results.size() != HV_HAND_NATIVE_CLASS_COUNT) return HV_HAND_NATIVE_INVALID_OUTPUT;

  hv_hand_native_result_t candidate{};
  bool seen[HV_HAND_NATIVE_CLASS_COUNT]{};
  float sum = 0;
  for (const auto &result : results) {
    const int index = class_index(result.cat_name);
    if (index < 0 || seen[index] || !std::isfinite(result.score) ||
        result.score < 0.f || result.score > 1.f)
      return HV_HAND_NATIVE_INVALID_OUTPUT;
    seen[index] = true;
    candidate.scores[index] = result.score;
    sum += result.score;
  }
  if (std::fabs(sum - 1.f) > .001f) return HV_HAND_NATIVE_INVALID_OUTPUT;
  candidate.top_index = 0;
  for (int i = 1; i < HV_HAND_NATIVE_CLASS_COUNT; ++i)
    if (candidate.scores[i] > candidate.scores[candidate.top_index]) candidate.top_index = i;
  candidate.top_score = candidate.scores[candidate.top_index];
  for (int i = 0; i < HV_HAND_NATIVE_CLASS_COUNT; ++i)
    if (i != candidate.top_index) candidate.second_score = std::max(candidate.second_score, candidate.scores[i]);
  candidate.margin = candidate.top_score - candidate.second_score;
  candidate.preprocess_ms = elapsed_ms(before_preprocess, before_model);
  candidate.model_ms = elapsed_ms(before_model, before_postprocess);
  candidate.postprocess_ms = elapsed_ms(before_postprocess, after_postprocess);
  candidate.valid = true;
  *out = candidate;
  return HV_HAND_NATIVE_OK;
}

extern "C" const char *hv_hand_native_class_name(int class_id)
{
  return class_id >= 0 && class_id < HV_HAND_NATIVE_CLASS_COUNT
      ? CLASS_NAMES[class_id] : "unknown";
}

extern "C" const char *hv_hand_native_status_name(hv_hand_native_status_t status)
{
  switch (status) {
    case HV_HAND_NATIVE_OK: return "ok";
    case HV_HAND_NATIVE_NOT_READY: return "not_ready";
    case HV_HAND_NATIVE_INVALID_ARG: return "invalid_arg";
    case HV_HAND_NATIVE_INVALID_DETECTION: return "invalid_detection";
    case HV_HAND_NATIVE_PARTITION_MISSING: return "partition_missing";
    case HV_HAND_NATIVE_PARTITION_TOO_SMALL: return "partition_too_small";
    case HV_HAND_NATIVE_MODEL_HASH_MISMATCH: return "model_hash_mismatch";
    case HV_HAND_NATIVE_IO_ERROR: return "io_error";
    case HV_HAND_NATIVE_NO_MEMORY: return "no_memory";
    case HV_HAND_NATIVE_BAD_MODEL: return "bad_model";
    case HV_HAND_NATIVE_INVALID_OUTPUT: return "invalid_output";
    case HV_HAND_NATIVE_ALREADY_INITIALIZED: return "already_initialized";
    default: return "unknown_status";
  }
}

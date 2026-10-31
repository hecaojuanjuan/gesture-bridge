#ifndef HV_HAND_NATIVE_CLASSIFIER_H
#define HV_HAND_NATIVE_CLASSIFIER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "hv_hand_detect.h"

#define HV_HAND_NATIVE_CLASS_COUNT 11
#define HV_HAND_NATIVE_MODEL_BYTES 788608u
#define HV_HAND_NATIVE_MODEL_SHA256 \
  "52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0"

typedef enum {
  HV_HAND_NATIVE_OK = 0,
  HV_HAND_NATIVE_NOT_READY = 1,
  HV_HAND_NATIVE_INVALID_ARG = 2,
  HV_HAND_NATIVE_INVALID_DETECTION = 3,
  HV_HAND_NATIVE_PARTITION_MISSING = 4,
  HV_HAND_NATIVE_PARTITION_TOO_SMALL = 5,
  HV_HAND_NATIVE_MODEL_HASH_MISMATCH = 6,
  HV_HAND_NATIVE_IO_ERROR = 7,
  HV_HAND_NATIVE_NO_MEMORY = 8,
  HV_HAND_NATIVE_BAD_MODEL = 9,
  HV_HAND_NATIVE_INVALID_OUTPUT = 10,
  HV_HAND_NATIVE_ALREADY_INITIALIZED = 11
} hv_hand_native_status_t;

/* Exact upstream order. Names are never aliases for different gestures. */
typedef enum {
  HV_HAND_NATIVE_CLASS_UNKNOWN = -1,
  HV_HAND_NATIVE_CLASS_ONE = 0,
  HV_HAND_NATIVE_CLASS_TWO = 1,
  HV_HAND_NATIVE_CLASS_THREE = 2,
  HV_HAND_NATIVE_CLASS_FOUR = 3,
  HV_HAND_NATIVE_CLASS_FIVE = 4,
  HV_HAND_NATIVE_CLASS_LIKE = 5,
  HV_HAND_NATIVE_CLASS_OK = 6,
  HV_HAND_NATIVE_CLASS_NO_GESTURE = 7,
  HV_HAND_NATIVE_CLASS_CALL = 8,
  HV_HAND_NATIVE_CLASS_DISLIKE = 9,
  HV_HAND_NATIVE_CLASS_NO_HAND = 10
} hv_hand_native_class_t;

typedef struct {
  /* Valid distribution for one accepted detection; NOT a completed gesture. */
  bool valid;
  int top_index;
  float scores[HV_HAND_NATIVE_CLASS_COUNT];
  float top_score;
  float second_score;
  float margin;
  uint32_t preprocess_ms;
  uint32_t model_ms;
  uint32_t postprocess_ms;
} hv_hand_native_result_t;

#ifdef __cplusplus
extern "C" {
#endif

/* Read-only initialization. No default partition is selected and nothing is
 * written or erased. The data partition must contain the unmodified pinned
 * EDL2 model at byte zero; only its first MODEL_BYTES are hashed. The remaining
 * partition bytes may contain padding. Only the verified model prefix is
 * mapped; its handle is released after all model objects are destroyed.
 * expected_sha256 must match the pinned
 * MODEL_SHA256: changing a model also requires an explicit adapter review.
 * Same-label repeated init is idempotent. A different label requires deinit.
 * Call init/deinit and inference only while other users of this singleton are
 * stopped. ESP-DL's internal allocation/assert failures are not all recoverable
 * through its public API; device memory and latency still need measurement. */
hv_hand_native_status_t hv_hand_native_classifier_init(
    const char *partition_label, const char *expected_sha256);
bool hv_hand_native_classifier_ready(void);
void hv_hand_native_classifier_deinit(void);

/* Use the exact RGB888 frame and detection box from the same inference epoch.
 * This function checks buffer size, single-hand validity, score, and bounds.
 * Caller owns freshness/epoch checks BOTH before and after this synchronous
 * call, as well as confidence/margin thresholds, hold/release logic and output
 * actions. The singleton and ESP-DL buffers are not reentrant.
 * On any failure out is cleared, valid=false and top_index=UNKNOWN. */
hv_hand_native_status_t hv_hand_native_classifier_analyze_rgb888(
    const uint8_t *rgb, size_t bytes, uint16_t width, uint16_t height,
    const hv_hand_detection_t *detection, hv_hand_native_result_t *out);
const char *hv_hand_native_class_name(int class_id);
const char *hv_hand_native_status_name(hv_hand_native_status_t status);

#ifdef __cplusplus
}
#endif
#endif

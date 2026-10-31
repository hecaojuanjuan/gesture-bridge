#ifndef HV_HAND_CLASSIFIER_H
#define HV_HAND_CLASSIFIER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
  HV_HAND_CLASSIFIER_VERSION = 1,
  HV_HAND_CLASSIFIER_SIZE = 64,
  HV_HAND_CLASSIFIER_PIXELS = 64 * 64,
  HV_HAND_CLASSIFIER_CLASSES = 3,
  HV_HAND_CLASSIFIER_WEIGHTS = 54011,
  HV_HAND_CLASSIFIER_WORK_FLOATS = 4096 + 8192 + 4096 + 1536 + 32
};

typedef enum {
  HV_HAND_CLASSIFIER_OK = 0,
  HV_HAND_CLASSIFIER_NOT_READY,
  HV_HAND_CLASSIFIER_BAD_INPUT,
  HV_HAND_CLASSIFIER_BAD_MODEL
} hv_hand_classifier_status_t;

typedef enum {
  HV_HAND_OPEN_PALM = 0,
  HV_HAND_CLOSED_FIST = 1,
  HV_HAND_OTHER = 2
} hv_hand_class_t;

typedef struct {
  const float *weights;
  size_t count;
  uint32_t version;
} hv_hand_classifier_model_t;

/* Integer pixel box: x1/y1 inclusive, x2/y2 exclusive. Expand each side by
 * floor(extent/10), clamp, center-nearest resize (stretch), integer RGB gray.
 * This is identical to tools/train_hand_classifier.py::preprocess_rgb888. */
hv_hand_classifier_status_t hv_hand_classifier_preprocess_rgb888(
  const uint8_t *rgb, size_t bytes, unsigned width, unsigned height,
  int x1, int y1, int x2, int y2, uint8_t gray[HV_HAND_CLASSIFIER_PIXELS]);

/* No allocation, static model or default/random weights. Allocate workspace on
 * the heap (PSRAM on the board), not on a task stack. CHW layers and flattened
 * weights follow the PyTorch module's parameter order; see training exporter.
 * The output is a score distribution, not a calibrated probability or an
 * acceptance decision. The application must reject low confidence/other/no hand. */
hv_hand_classifier_status_t hv_hand_classifier_predict(
  const hv_hand_classifier_model_t *model,
  const uint8_t gray[HV_HAND_CLASSIFIER_PIXELS],
  float *workspace, size_t workspace_floats,
  float scores[HV_HAND_CLASSIFIER_CLASSES]);

const char *hv_hand_classifier_label(unsigned index);

#ifdef __cplusplus
}
#endif
#endif

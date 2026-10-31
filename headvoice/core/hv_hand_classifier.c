#include "hv_hand_classifier.h"

#include <math.h>

const char *hv_hand_classifier_label(unsigned index)
{
  static const char *const labels[] = {"open_palm", "closed_fist", "other"};
  return index < HV_HAND_CLASSIFIER_CLASSES ? labels[index] : "unknown";
}

hv_hand_classifier_status_t hv_hand_classifier_preprocess_rgb888(
  const uint8_t *rgb, size_t bytes, unsigned width, unsigned height,
  int x1, int y1, int x2, int y2, uint8_t gray[HV_HAND_CLASSIFIER_PIXELS])
{
  if (!rgb || !gray || !width || !height || width > 4096 || height > 4096 ||
      bytes < (size_t)width * height * 3 || x1 < 0 || y1 < 0 ||
      x2 <= x1 || y2 <= y1 || x2 > (int)width || y2 > (int)height)
    return HV_HAND_CLASSIFIER_BAD_INPUT;
  int pad_x = (x2 - x1) / 10, pad_y = (y2 - y1) / 10;
  x1 = x1 > pad_x ? x1 - pad_x : 0;
  y1 = y1 > pad_y ? y1 - pad_y : 0;
  x2 = x2 + pad_x < (int)width ? x2 + pad_x : (int)width;
  y2 = y2 + pad_y < (int)height ? y2 + pad_y : (int)height;
  for (unsigned y = 0; y < HV_HAND_CLASSIFIER_SIZE; ++y) {
    unsigned source_y = (unsigned)y1 + (2 * y + 1) * (unsigned)(y2 - y1) / 128;
    for (unsigned x = 0; x < HV_HAND_CLASSIFIER_SIZE; ++x) {
      unsigned source_x = (unsigned)x1 + (2 * x + 1) * (unsigned)(x2 - x1) / 128;
      const uint8_t *pixel = rgb + ((size_t)source_y * width + source_x) * 3;
      gray[y * HV_HAND_CLASSIFIER_SIZE + x] =
        (uint8_t)((77u * pixel[0] + 150u * pixel[1] + 29u * pixel[2] + 128u) >> 8);
    }
  }
  return HV_HAND_CLASSIFIER_OK;
}

/* 3x3 convolution, stride 2, zero padding 1, ReLU. Input and output are CHW. */
static const float *conv(const float *input, unsigned size, unsigned channels,
                         unsigned out_channels, const float *weights, float *output)
{
  const float *bias = weights + out_channels * channels * 9;
  unsigned out_size = size / 2;
  for (unsigned oc = 0; oc < out_channels; ++oc) {
    for (unsigned oy = 0; oy < out_size; ++oy) {
      for (unsigned ox = 0; ox < out_size; ++ox) {
        float sum = bias[oc];
        for (unsigned ic = 0; ic < channels; ++ic) {
          const float *kernel = weights + (oc * channels + ic) * 9;
          for (unsigned ky = 0; ky < 3; ++ky) {
            int iy = (int)(oy * 2 + ky) - 1;
            if (iy < 0 || iy >= (int)size) continue;
            for (unsigned kx = 0; kx < 3; ++kx) {
              int ix = (int)(ox * 2 + kx) - 1;
              if (ix >= 0 && ix < (int)size)
                sum += input[(ic * size + (unsigned)iy) * size + (unsigned)ix] *
                       kernel[ky * 3 + kx];
            }
          }
        }
        /* Do not turn NaNs into plausible zero activations. */
        output[(oc * out_size + oy) * out_size + ox] = sum < 0 ? 0 : sum;
      }
    }
  }
  return bias + out_channels;
}

static const float *dense(const float *input, unsigned count, unsigned out_count,
                          const float *weights, float *output, int relu)
{
  const float *bias = weights + count * out_count;
  for (unsigned row = 0; row < out_count; ++row) {
    float sum = bias[row];
    for (unsigned i = 0; i < count; ++i) sum += input[i] * weights[row * count + i];
    output[row] = relu && sum < 0 ? 0 : sum;
  }
  return bias + out_count;
}

hv_hand_classifier_status_t hv_hand_classifier_predict(
  const hv_hand_classifier_model_t *model, const uint8_t gray[HV_HAND_CLASSIFIER_PIXELS],
  float *workspace, size_t workspace_floats, float scores[HV_HAND_CLASSIFIER_CLASSES])
{
  if (scores) for (unsigned i = 0; i < HV_HAND_CLASSIFIER_CLASSES; ++i) scores[i] = 0;
  if (!model || !model->weights) return HV_HAND_CLASSIFIER_NOT_READY;
  if (model->version != HV_HAND_CLASSIFIER_VERSION || model->count != HV_HAND_CLASSIFIER_WEIGHTS)
    return HV_HAND_CLASSIFIER_BAD_MODEL;
  if (!gray || !workspace || workspace_floats < HV_HAND_CLASSIFIER_WORK_FLOATS || !scores)
    return HV_HAND_CLASSIFIER_BAD_INPUT;
  float *first = workspace + HV_HAND_CLASSIFIER_PIXELS;
  float *second = first + 8192;
  float *third = second + 4096;
  float *hidden = third + 1536;
  for (unsigned i = 0; i < HV_HAND_CLASSIFIER_PIXELS; ++i) workspace[i] = gray[i] / 255.0f;
  const float *weights = conv(workspace, 64, 1, 8, model->weights, first);
  weights = conv(first, 32, 8, 16, weights, second);
  weights = conv(second, 16, 16, 24, weights, third);
  weights = dense(third, 1536, 32, weights, hidden, 1);
  float logits[HV_HAND_CLASSIFIER_CLASSES];
  weights = dense(hidden, 32, 3, weights, logits, 0);
  if ((size_t)(weights - model->weights) != model->count) return HV_HAND_CLASSIFIER_BAD_MODEL;
  float maximum = logits[0];
  for (unsigned i = 0; i < HV_HAND_CLASSIFIER_CLASSES; ++i) {
    if (!isfinite(logits[i])) return HV_HAND_CLASSIFIER_BAD_MODEL;
    if (logits[i] > maximum) maximum = logits[i];
  }
  float denominator = 0;
  for (unsigned i = 0; i < HV_HAND_CLASSIFIER_CLASSES; ++i) {
    scores[i] = expf(logits[i] - maximum);
    denominator += scores[i];
  }
  for (unsigned i = 0; i < HV_HAND_CLASSIFIER_CLASSES; ++i) scores[i] /= denominator;
  return HV_HAND_CLASSIFIER_OK;
}

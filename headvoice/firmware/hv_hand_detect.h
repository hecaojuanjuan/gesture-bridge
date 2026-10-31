#ifndef HV_HAND_DETECT_H
#define HV_HAND_DETECT_H

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* Detection only: this type never assigns open-palm or fist labels.
 * count is the detector's returned hand count, including rejected boxes.
 * A valid result contains exactly one finite, in-frame hand box with score
 * >= 0.5. Pixels use the SDK crop convention [x1, y1, x2, y2), without an
 * added endpoint pixel. normalized_box has the same order, divided by
 * input width/height. Rejected results keep both boxes and score zero. */
typedef struct {
    uint32_t count;
    bool valid;
    float score;
    int box[4];
    float normalized_box[4];
} hv_hand_detection_t;

#ifdef __cplusplus
extern "C" {
#endif

/* Call once during startup, then call analyze only from the single inference
 * task. The resident detector and its result buffers are not reentrant. */
esp_err_t hv_hand_detect_init(void);
esp_err_t hv_hand_detect_analyze_rgb888(const uint8_t *rgb, uint16_t width,
                                       uint16_t height, hv_hand_detection_t *out);

#ifdef __cplusplus
}
#endif
#endif

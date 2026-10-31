#include "hv_hand_detect.h"
#include "hand_detect.hpp"
#include "esp_log.h"

#include <cmath>
#include <cstring>
#include <limits>
#include <new>

#if !CONFIG_HAND_DETECT_MODEL_IN_FLASH_RODATA || !CONFIG_FLASH_ESPDET_PICO_224_224_HAND
#error "HeadVoice hand detection requires the pinned S3 model embedded in application rodata"
#endif

static HandDetect *s_hand;

extern "C" esp_err_t hv_hand_detect_init(void)
{
    if (s_hand) return ESP_OK;
    /* Eager initialization isolates loading from the first live frame. Keep
     * the upstream 0.25 proposal threshold so an additional detected hand
     * vetoes a supposedly single-hand observation even below our 0.5 gate. */
    HandDetect *candidate = new (std::nothrow) HandDetect(HandDetect::ESPDET_PICO_224_224_HAND, false);
    if (!candidate) return ESP_ERR_NO_MEM;
    dl::Model *model = candidate->get_raw_model();
    if (!model || model->get_inputs().empty() || model->get_outputs().empty()) {
        delete candidate;
        return ESP_FAIL;
    }
    s_hand = candidate;
    ESP_LOGI("hv_hand", "ESPDet-Pico 224 hand detector ready; boxes only, no gesture classification");
    return ESP_OK;
}

extern "C" esp_err_t hv_hand_detect_analyze_rgb888(const uint8_t *rgb, uint16_t width,
                                                  uint16_t height, hv_hand_detection_t *out)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    std::memset(out, 0, sizeof(*out));
    if (!rgb || !width || !height) return ESP_ERR_INVALID_ARG;
    if (!s_hand) return ESP_ERR_INVALID_STATE;
    dl::image::img_t image = {.data = const_cast<uint8_t *>(rgb),
        .width = width, .height = height, .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888};
    const auto &hands = s_hand->run(image);
    out->count = hands.size() > std::numeric_limits<uint32_t>::max()
        ? std::numeric_limits<uint32_t>::max() : static_cast<uint32_t>(hands.size());
    if (hands.size() != 1) return ESP_OK;
    const auto &hand = hands.front();
    if (hand.category != 0 || !std::isfinite(hand.score) || hand.score < 0.5f ||
        hand.score > 1.0f || hand.box.size() != 4) return ESP_OK;
    const auto &box = hand.box;
    if (box[0] < 0 || box[1] < 0 || box[2] <= box[0] || box[3] <= box[1] ||
        box[2] > width || box[3] > height) return ESP_OK;
    for (unsigned i = 0; i < 4; ++i) {
        out->box[i] = box[i];
        out->normalized_box[i] = static_cast<float>(box[i]) / (i % 2 ? height : width);
    }
    out->score = hand.score;
    out->valid = true;
    return ESP_OK;
}

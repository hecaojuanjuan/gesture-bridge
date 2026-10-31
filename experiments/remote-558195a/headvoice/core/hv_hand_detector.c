#include "hv_hand_detector.h"
#include "esp_err.h"
#include <math.h>
#include <string.h>

// 肤色检测参数（YCbCr色彩空间）
#define SKIN_Y_MIN 80
#define SKIN_Y_MAX 255
#define SKIN_CB_MIN 77
#define SKIN_CB_MAX 127
#define SKIN_CR_MIN 133
#define SKIN_CR_MAX 173

// RGB转YCbCr
static void rgb_to_ycbcr(uint8_t r, uint8_t g, uint8_t b, uint8_t *y, uint8_t *cb, uint8_t *cr)
{
  *y = (uint8_t)(0.299f * r + 0.587f * g + 0.114f * b);
  *cb = (uint8_t)(128 - 0.168736f * r - 0.331264f * g + 0.5f * b);
  *cr = (uint8_t)(128 + 0.5f * r - 0.418688f * g - 0.081312f * b);
}

// 判断是否为肤色
static bool is_skin_color(uint8_t r, uint8_t g, uint8_t b)
{
  uint8_t y, cb, cr;
  rgb_to_ycbcr(r, g, b, &y, &cb, &cr);

  return (y >= SKIN_Y_MIN && y <= SKIN_Y_MAX &&
          cb >= SKIN_CB_MIN && cb <= SKIN_CB_MAX &&
          cr >= SKIN_CR_MIN && cr <= SKIN_CR_MAX);
}

/**
 * 基于手腕关键点的手掌检测
 * 在手腕周围搜索肤色区域
 */
esp_err_t hv_hand_detect_from_wrists(
  const uint8_t *rgb888,
  uint16_t width, uint16_t height,
  float wrist_left_x, float wrist_left_y,
  float wrist_right_x, float wrist_right_y,
  bool wrists_valid,
  hv_hand_detection_t *out)
{
  if (!rgb888 || !out) return ESP_ERR_INVALID_ARG;

  memset(out, 0, sizeof(*out));

  if (!wrists_valid) return ESP_OK;

  // 搜索范围：手腕周围60x60像素区域
  int search_radius = 30;

  // 检测左手
  int left_wrist_px = (int)(wrist_left_x);
  int left_wrist_py = (int)(wrist_left_y);

  // 检测右手
  int right_wrist_px = (int)(wrist_right_x);
  int right_wrist_py = (int)(wrist_right_y);

  // 计算两只手的肤色像素
  int left_skin_pixels = 0;
  int right_skin_pixels = 0;
  float left_cx = 0, left_cy = 0;
  float right_cx = 0, right_cy = 0;

  // 左手区域
  for (int dy = -search_radius; dy <= search_radius; dy += 2) {
    for (int dx = -search_radius; dx <= search_radius; dx += 2) {
      int px = left_wrist_px + dx;
      int py = left_wrist_py + dy;

      if (px >= 0 && px < width && py >= 0 && py < height) {
        int offset = (py * width + px) * 3;
        uint8_t r = rgb888[offset];
        uint8_t g = rgb888[offset + 1];
        uint8_t b = rgb888[offset + 2];

        if (is_skin_color(r, g, b)) {
          left_skin_pixels++;
          left_cx += px;
          left_cy += py;
        }
      }
    }
  }

  // 右手区域
  for (int dy = -search_radius; dy <= search_radius; dy += 2) {
    for (int dx = -search_radius; dx <= search_radius; dx += 2) {
      int px = right_wrist_px + dx;
      int py = right_wrist_py + dy;

      if (px >= 0 && px < width && py >= 0 && py < height) {
        int offset = (py * width + px) * 3;
        uint8_t r = rgb888[offset];
        uint8_t g = rgb888[offset + 1];
        uint8_t b = rgb888[offset + 2];

        if (is_skin_color(r, g, b)) {
          right_skin_pixels++;
          right_cx += px;
          right_cy += py;
        }
      }
    }
  }

  // 选择检测到更多肤色像素的手
  int min_pixels = 50;  // 最小像素阈值

  if (left_skin_pixels > min_pixels || right_skin_pixels > min_pixels) {
    out->detected = true;

    if (left_skin_pixels > right_skin_pixels) {
      out->is_left = true;
      out->center_x = (left_cx / left_skin_pixels) / width;
      out->center_y = (left_cy / left_skin_pixels) / height;
      out->confidence = fminf(1.0f, left_skin_pixels / 200.0f);
      out->wrist_x = wrist_left_x / width;
      out->wrist_y = wrist_left_y / height;
    } else {
      out->is_right = true;
      out->center_x = (right_cx / right_skin_pixels) / width;
      out->center_y = (right_cy / right_skin_pixels) / height;
      out->confidence = fminf(1.0f, right_skin_pixels / 200.0f);
      out->wrist_x = wrist_right_x / width;
      out->wrist_y = wrist_right_y / height;
    }
  }

  return ESP_OK;
}

/**
 * 简化版：基于颜色的手掌检测
 * 扫描整个图像，找到最大的肤色区域
 */
esp_err_t hv_hand_detect_color_based(
  const uint8_t *rgb888,
  uint16_t width, uint16_t height,
  hv_hand_detection_t *out)
{
  if (!rgb888 || !out) return ESP_ERR_INVALID_ARG;

  memset(out, 0, sizeof(*out));

  // 分块统计肤色（16x16块）
  int block_size = 16;
  int blocks_x = (width + block_size - 1) / block_size;
  int blocks_y = (height + block_size - 1) / block_size;

  int max_skin_pixels = 0;
  int best_block_x = 0, best_block_y = 0;

  for (int by = 0; by < blocks_y; by++) {
    for (int bx = 0; bx < blocks_x; bx++) {
      int skin_pixels = 0;

      for (int py = by * block_size; py < (by + 1) * block_size && py < height; py += 2) {
        for (int px = bx * block_size; px < (bx + 1) * block_size && px < width; px += 2) {
          int offset = (py * width + px) * 3;
          uint8_t r = rgb888[offset];
          uint8_t g = rgb888[offset + 1];
          uint8_t b = rgb888[offset + 2];

          if (is_skin_color(r, g, b)) {
            skin_pixels++;
          }
        }
      }

      if (skin_pixels > max_skin_pixels) {
        max_skin_pixels = skin_pixels;
        best_block_x = bx;
        best_block_y = by;
      }
    }
  }

  // 如果找到足够的肤色像素
  if (max_skin_pixels > 20) {
    out->detected = true;
    out->center_x = (best_block_x * block_size + block_size / 2.0f) / width;
    out->center_y = (best_block_y * block_size + block_size / 2.0f) / height;
    out->confidence = fminf(1.0f, max_skin_pixels / 64.0f);
  }

  return ESP_OK;
}

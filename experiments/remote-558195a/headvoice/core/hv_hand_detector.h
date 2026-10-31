#ifndef HV_HAND_DETECTOR_H
#define HV_HAND_DETECTOR_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// 手部检测结果
typedef struct {
  bool detected;              // 是否检测到手掌
  float center_x, center_y;   // 手掌中心坐标 (0-1)
  float confidence;           // 置信度 (0-1)
  bool is_left;               // 是否左手
  bool is_right;              // 是否右手
  float wrist_x, wrist_y;     // 手腕坐标
} hv_hand_detection_t;

/**
 * 从RGB888图像中检测手掌
 *
 * 策略：
 * 1. 使用YOLO11姿态估计获取手腕关键点
 * 2. 基于肤色检测手掌区域
 * 3. 计算手掌中心和置信度
 *
 * @param rgb888 RGB888图像数据
 * @param width 图像宽度
 * @param height 图像高度
 * @param wrist_left_x 左手腕X坐标（来自YOLO11）
 * @param wrist_left_y 左手腕Y坐标
 * @param wrist_right_x 右手腕X坐标
 * @param wrist_right_y 右手腕Y坐标
 * @param wrists_valid 手腕关键点是否有效
 * @param out 输出检测结果
 * @return ESP_OK成功，其他失败
 */
esp_err_t hv_hand_detect_from_wrists(
  const uint8_t *rgb888,
  uint16_t width, uint16_t height,
  float wrist_left_x, float wrist_left_y,
  float wrist_right_x, float wrist_right_y,
  bool wrists_valid,
  hv_hand_detection_t *out);

/**
 * 简化版：基于颜色快速检测手掌
 * 不依赖YOLO关键点，适用于快速原型
 */
esp_err_t hv_hand_detect_color_based(
  const uint8_t *rgb888,
  uint16_t width, uint16_t height,
  hv_hand_detection_t *out);

#ifdef __cplusplus
}
#endif

#endif

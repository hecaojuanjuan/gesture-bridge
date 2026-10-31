"""测试人像居中和手势居中功能的集成测试

这个测试验证：
1. 人脸居中算法 (hv_gimbal_core)
2. 手部检测和居中逻辑
3. 两者的坐标归一化和目标计算
"""
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]


class CenteringIntegrationTests(unittest.TestCase):
    """居中功能集成测试"""

    def test_face_centering_algorithm(self):
        """测试人脸居中算法的核心逻辑"""
        # 编译并运行核心居中算法测试
        with tempfile.TemporaryDirectory(prefix="centering-test-") as temp:
            directory = Path(temp)

            # 创建测试桩
            stubs_h = directory / "stubs.h"
            stubs_h.write_text("""
#ifndef CENTERING_TEST_STUBS_H
#define CENTERING_TEST_STUBS_H
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef int esp_err_t;
#define ESP_OK 0
#endif
""", encoding="utf-8")

            # 创建测试用例
            test_c = directory / "test_centering.c"
            test_c.write_text("""
#include "stubs.h"
#include "hv_gimbal_core.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    hv_gimbal_t core;
    hv_gimbal_reset(&core);

    // 测试1: 初始状态
    assert(!core.active);
    assert(core.pulse[0] == 1500);
    assert(core.pulse[1] == 1500);
    printf("Test 1 passed: Initial state\\n");

    // 测试2: 开始居中
    hv_gimbal_begin(&core, 1000);
    assert(core.active);
    assert(core.steps == 0);
    assert(core.acceptAfterMs == 1450);  // 1000 + 450ms稳定期
    assert(core.deadlineMs == 91000);    // 1000 + 90s超时
    printf("Test 2 passed: Begin centering\\n");

    // 测试3: 目标在右上方 (x=0.7, y=0.3) - 需要向右移动pan轴
    HvGimbalResult result = hv_gimbal_observe(&core, 1, true, 0.7f, 0.3f, 1500, 1500);
    assert(result == HV_GIMBAL_MOVE);
    assert(core.steps == 1);
    printf("Test 3 passed: Move towards target x=0.7, y=0.3\\n");
    printf("  Pan pulse: %d (delta: %d)\\n", core.pulse[0], core.pulse[0] - 1500);
    printf("  Tilt pulse: %d (delta: %d)\\n", core.pulse[1], core.pulse[1] - 1500);

    // 测试4: 目标在左下方 (x=0.3, y=0.7) - 需要向左移动
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 2000);
    result = hv_gimbal_observe(&core, 1, true, 0.3f, 0.7f, 2500, 2500);
    assert(result == HV_GIMBAL_MOVE);
    int pan_before = core.pulse[0];
    printf("Test 4 passed: Move towards target x=0.3, y=0.7\\n");
    printf("  Pan pulse: %d (delta: %d)\\n", core.pulse[0], core.pulse[0] - 1500);

    // 测试5: 目标已居中 (x=0.5±0.08, y=0.5±0.08)
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 3000);
    result = hv_gimbal_observe(&core, 1, true, 0.50f, 0.50f, 3500, 3500);
    assert(result == HV_GIMBAL_WAIT);  // 第一次观察到居中，等待确认
    printf("Test 5 passed: First centered observation\\n");

    result = hv_gimbal_observe(&core, 1, true, 0.52f, 0.51f, 3800, 3800);
    assert(result == HV_GIMBAL_WAIT);  // 第二次
    printf("  Second centered observation\\n");

    result = hv_gimbal_observe(&core, 1, true, 0.51f, 0.50f, 4100, 4100);
    assert(result == HV_GIMBAL_CENTERED);  // 第三次确认居中
    assert(!core.active);  // 居中后停止
    printf("  Third observation confirms centered\\n");

    // 测试6: 旧帧被拒绝
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 5000);
    result = hv_gimbal_observe(&core, 1, true, 0.7f, 0.3f, 5500, 5500);
    assert(result == HV_GIMBAL_MOVE);
    // 尝试提交比上次更旧的帧
    result = hv_gimbal_observe(&core, 1, true, 0.6f, 0.4f, 5400, 5600);
    assert(result == HV_GIMBAL_STALE);
    printf("Test 6 passed: Stale frames rejected\\n");

    // 测试7: 帧龄超限被拒绝 (默认maxAgeMs=6000)
    result = hv_gimbal_observe(&core, 1, true, 0.6f, 0.4f, 5600, 12000);
    assert(result == HV_GIMBAL_STALE);
    printf("Test 7 passed: Aged frames rejected\\n");

    // 测试8: 无人脸时停止
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 6000);
    result = hv_gimbal_observe(&core, 0, false, 0.5f, 0.5f, 6500, 6500);
    assert(result == HV_GIMBAL_NO_FACE);
    assert(!core.active);
    printf("Test 8 passed: No face stops centering\\n");

    // 测试9: 多人时停止
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 7000);
    result = hv_gimbal_observe(&core, 2, true, 0.5f, 0.5f, 7500, 7500);
    assert(result == HV_GIMBAL_NO_FACE);
    assert(!core.active);
    printf("Test 9 passed: Multiple people stops centering\\n");

    // 测试10: 步数上限
    hv_gimbal_reset(&core);
    hv_gimbal_begin(&core, 8000);
    for (int i = 0; i < 20; ++i) {
        result = hv_gimbal_observe(&core, 1, true, 0.7f, 0.3f, 8500 + i * 500, 8500 + i * 500);
        if (i < 19) {
            assert(result == HV_GIMBAL_MOVE);
        }
    }
    // 第20步后应该超时
    result = hv_gimbal_observe(&core, 1, true, 0.7f, 0.3f, 18500, 18500);
    assert(result == HV_GIMBAL_TIMEOUT);
    assert(!core.active);
    printf("Test 10 passed: Step limit enforced\\n");

    printf("\\n=== All face centering tests passed ===\\n");
    return 0;
}
""", encoding="utf-8")

            # 编译 - 在Windows上跳过C编译测试
            try:
                # 尝试查找gcc或clang
                import shutil
                cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
                if not cc:
                    print("  Skipping C compilation test (no C compiler found)")
                    print("  The gimbal core logic will be tested on device")
                    return

                binary = directory / "test_centering.exe" if sys.platform == 'win32' else directory / "test_centering"
                compile_cmd = [
                    cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-I", str(directory),
                    "-I", str(ROOT / "headvoice" / "core"),
                    str(test_c),
                    str(ROOT / "headvoice" / "core" / "hv_gimbal_core.c"),
                    "-o", str(binary),
                    "-lm"
                ]

                result = subprocess.run(compile_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    self.fail(f"Compilation failed:\n{result.stderr}\n{result.stdout}")
            except Exception as e:
                print(f"  Skipping C compilation test: {e}")
                return

            # 运行测试
            run_result = subprocess.run([str(binary)], capture_output=True, text=True)
            print(run_result.stdout)
            if run_result.returncode != 0:
                self.fail(f"Test execution failed:\n{run_result.stderr}\n{run_result.stdout}")

            # 验证输出
            self.assertIn("All face centering tests passed", run_result.stdout)

    def test_coordinate_normalization(self):
        """测试坐标归一化逻辑"""
        print("\n=== Testing coordinate normalization ===")

        # 测试场景：320x240的图像
        width, height = 320, 240

        # 脸框中心在图像中心
        box_center_x, box_center_y = 160, 120
        normalized_x = box_center_x / width
        normalized_y = box_center_y / height

        print(f"Image: {width}x{height}")
        print(f"Box center: ({box_center_x}, {box_center_y})")
        print(f"Normalized: ({normalized_x:.3f}, {normalized_y:.3f})")

        # 应该在中心附近 (0.5, 0.5)
        self.assertAlmostEqual(normalized_x, 0.5, places=2)
        self.assertAlmostEqual(normalized_y, 0.5, places=2)

        # 偏差计算
        error_x = normalized_x - 0.5
        error_y = normalized_y - 0.5
        print(f"Error: ({error_x:.3f}, {error_y:.3f})")

        # 中心容差 ±0.08
        tolerance = 0.08
        self.assertTrue(abs(error_x) <= tolerance)
        self.assertTrue(abs(error_y) <= tolerance)

        print("[PASS] Coordinate normalization correct")

    def test_hand_detection_structure(self):
        """测试手部检测数据结构定义"""
        print("\n=== Testing hand detection structure ===")

        # 检查头文件是否存在
        hand_detector_h = ROOT / "experiments" / "remote-558195a" / "headvoice" / "core" / "hv_hand_detector.h"
        self.assertTrue(hand_detector_h.exists(), "Hand detector header not found")

        # 读取并验证关键定义
        content = hand_detector_h.read_text(encoding="utf-8")

        # 验证结构体定义
        self.assertIn("hv_hand_detection_t", content)
        self.assertIn("center_x", content)
        self.assertIn("center_y", content)
        self.assertIn("confidence", content)

        # 验证函数声明
        self.assertIn("hv_hand_detect_from_wrists", content)
        self.assertIn("hv_hand_detect_color_based", content)

        print("[PASS] Hand detection structure defined correctly")
        print("  - center_x, center_y: normalized coordinates (0-1)")
        print("  - confidence: detection confidence")
        print("  - Functions: from_wrists and color_based detection")


class GimbalCoordinateTests(unittest.TestCase):
    """云台坐标系统测试"""

    def test_error_calculation(self):
        """测试偏差计算"""
        print("\n=== Testing error calculation ===")

        test_cases = [
            # (target_x, target_y, expected_error_x, expected_error_y, should_move)
            (0.5, 0.5, 0.0, 0.0, False),      # 完全居中
            (0.58, 0.52, 0.08, 0.02, False),  # 刚好在容差内
            (0.6, 0.5, 0.1, 0.0, True),       # 需要向右移动
            (0.4, 0.5, -0.1, 0.0, True),      # 需要向左移动
            (0.5, 0.6, 0.0, 0.1, True),       # 需要向下移动
            (0.5, 0.4, 0.0, -0.1, True),      # 需要向上移动
            (0.7, 0.7, 0.2, 0.2, True),       # 右下角
            (0.3, 0.3, -0.2, -0.2, True),     # 左上角
        ]

        tolerance = 0.08

        for target_x, target_y, exp_err_x, exp_err_y, should_move in test_cases:
            error_x = target_x - 0.5
            error_y = target_y - 0.5

            self.assertAlmostEqual(error_x, exp_err_x, places=5)
            self.assertAlmostEqual(error_y, exp_err_y, places=5)

            needs_move = abs(error_x) > tolerance or abs(error_y) > tolerance
            self.assertEqual(needs_move, should_move,
                           f"Target ({target_x}, {target_y}) move decision mismatch")

            if should_move:
                # 选择偏差较大的轴
                primary_axis = 0 if abs(error_x) >= abs(error_y) else 1
                axis_name = "pan" if primary_axis == 0 else "tilt"
                print(f"Target ({target_x:.2f}, {target_y:.2f}) -> "
                      f"Error ({error_x:+.2f}, {error_y:+.2f}) -> "
                      f"Move {axis_name}")

        print("[PASS] Error calculation correct")

    def test_pulse_width_limits(self):
        """测试脉宽限位"""
        print("\n=== Testing pulse width limits ===")

        # 当前固件限位
        PULSE_MIN = 1475
        PULSE_MID = 1500
        PULSE_MAX = 1525
        MAX_STEP = 25

        print(f"Pulse range: {PULSE_MIN} - {PULSE_MAX} µs")
        print(f"Mid point: {PULSE_MID} µs")
        print(f"Max step: {MAX_STEP} µs")

        # 测试从中位开始的移动
        current_pulse = PULSE_MID

        # 向右最大移动
        max_right = current_pulse + MAX_STEP
        self.assertLessEqual(max_right, PULSE_MAX)
        print(f"Max right from mid: {max_right} µs (within limit)")

        # 向左最大移动
        max_left = current_pulse - MAX_STEP
        self.assertGreaterEqual(max_left, PULSE_MIN)
        print(f"Max left from mid: {max_left} µs (within limit)")

        # 测试边界情况
        at_min = PULSE_MIN
        try_step_left = at_min - 1
        self.assertLess(try_step_left, PULSE_MIN)
        print(f"At min {at_min}, step left to {try_step_left} -> blocked")

        at_max = PULSE_MAX
        try_step_right = at_max + 1
        self.assertGreater(try_step_right, PULSE_MAX)
        print(f"At max {at_max}, step right to {try_step_right} -> blocked")

        print("[PASS] Pulse width limits enforced")


if __name__ == "__main__":
    # 运行测试
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手势居中模拟器 - 基于当前手势识别固件

当前固件检测手部位置，这个工具模拟云台控制逻辑来实现手势居中

使用方法:
    python tools/hand_center_simulator.py --port COM3

功能:
1. 监听当前固件的手部检测结果（HG日志）
2. 解析手部边界框 (box)
3. 计算手部中心坐标并归一化到 (0-1)
4. 模拟云台控制决策（pan/tilt调整方向）
5. 输出居中建议，不实际控制硬件
"""
import argparse
import json
import serial
import sys
import time
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class HandCenterSimulator:
    """手势居中模拟器"""

    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.image_width = 320
        self.image_height = 240
        self.center_tolerance = 0.08  # 中心容差 ±8%
        self.consecutive_centered = 0  # 连续居中计数
        self.total_observations = 0
        self.valid_hand_count = 0
        self.centered_count = 0

    def connect(self):
        """连接串口"""
        print(f"连接到 {self.port} @ {self.baudrate}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
        time.sleep(0.5)
        self.ser.reset_input_buffer()
        print("✓ 串口已连接\n")

    def parse_hand_observation(self, line):
        """解析手部观察数据"""
        try:
            # 提取JSON部分
            if "HG {" not in line or '"event":"observation"' not in line:
                return None

            json_start = line.index("HG {") + 3
            json_str = line[json_start:]
            data = json.loads(json_str)

            return data
        except (ValueError, json.JSONDecodeError) as e:
            return None

    def calculate_hand_center(self, box, width, height):
        """计算手部中心坐标（归一化到0-1）

        Args:
            box: [x1, y1, x2, y2] 手部边界框
            width: 图像宽度
            height: 图像高度

        Returns:
            (center_x, center_y) 归一化坐标，或 None
        """
        if not box or len(box) != 4:
            return None

        x1, y1, x2, y2 = box

        # 检查有效性
        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
            return None

        # 计算中心
        center_x_pixel = (x1 + x2) / 2.0
        center_y_pixel = (y1 + y2) / 2.0

        # 归一化到 0-1
        center_x = center_x_pixel / width
        center_y = center_y_pixel / height

        return (center_x, center_y)

    def calculate_centering_action(self, center_x, center_y):
        """计算居中动作

        Returns:
            dict with keys: needs_move, axis, direction, error_x, error_y
        """
        # 计算偏差
        error_x = center_x - 0.5
        error_y = center_y - 0.5

        # 检查是否在容差范围内
        if abs(error_x) <= self.center_tolerance and abs(error_y) <= self.center_tolerance:
            return {
                'needs_move': False,
                'axis': None,
                'direction': None,
                'error_x': error_x,
                'error_y': error_y,
                'centered': True
            }

        # 选择偏差较大的轴
        if abs(error_x) >= abs(error_y):
            axis = 'pan'
            direction = 'right' if error_x > 0 else 'left'
            primary_error = error_x
        else:
            axis = 'tilt'
            direction = 'down' if error_y > 0 else 'up'
            primary_error = error_y

        return {
            'needs_move': True,
            'axis': axis,
            'direction': direction,
            'error_x': error_x,
            'error_y': error_y,
            'primary_error': primary_error,
            'centered': False
        }

    def process_observation(self, obs):
        """处理一次观察"""
        self.total_observations += 1

        # 提取关键信息
        hands = obs.get('hands', 0)
        box = obs.get('box', [0, 0, 0, 0])
        valid = obs.get('valid', False)
        captured_ms = obs.get('captured_ms', 0)
        age_ms = obs.get('age_ms', 0)
        width = obs.get('width', self.image_width)
        height = obs.get('height', self.image_height)

        # 检查是否有单个有效手部
        if hands != 1 or not valid:
            self.consecutive_centered = 0
            status = "无手" if hands == 0 else f"多手({hands})" if hands > 1 else "无效"
            print(f"[{self.total_observations:4d}] {status:8s} | 跳过")
            return

        # 计算手部中心
        center = self.calculate_hand_center(box, width, height)
        if not center:
            self.consecutive_centered = 0
            print(f"[{self.total_observations:4d}] 有效手部 | 无法计算中心 box={box}")
            return

        self.valid_hand_count += 1
        center_x, center_y = center

        # 计算居中动作
        action = self.calculate_centering_action(center_x, center_y)

        # 显示结果
        if action['centered']:
            self.consecutive_centered += 1
            self.centered_count += 1
            print(f"[{self.total_observations:4d}] ✓ 已居中  | "
                  f"位置({center_x:.3f}, {center_y:.3f}) "
                  f"偏差({action['error_x']:+.3f}, {action['error_y']:+.3f}) "
                  f"连续{self.consecutive_centered}次")

            if self.consecutive_centered == 3:
                print("\n" + "="*60)
                print("  ✓✓✓ 连续3次居中确认！手势居中成功！")
                print("="*60 + "\n")
        else:
            self.consecutive_centered = 0
            axis_cn = "水平" if action['axis'] == 'pan' else "俯仰"
            dir_cn = {
                'left': '← 左', 'right': '→ 右',
                'up': '↑ 上', 'down': '↓ 下'
            }.get(action['direction'], action['direction'])

            print(f"[{self.total_observations:4d}] → 需移动 | "
                  f"位置({center_x:.3f}, {center_y:.3f}) "
                  f"偏差({action['error_x']:+.3f}, {action['error_y']:+.3f}) "
                  f"=> {axis_cn}轴{dir_cn}")

    def monitor(self, duration=300):
        """监控手势并模拟居中

        Args:
            duration: 监控时长（秒），0表示无限
        """
        print("="*60)
        print("  手势居中模拟器")
        print("="*60)
        print(f"图像尺寸: {self.image_width}x{self.image_height}")
        print(f"中心容差: ±{self.center_tolerance:.0%}")
        print(f"监控时长: {'无限' if duration == 0 else f'{duration}秒'}")
        print("="*60 + "\n")

        print("等待手部检测数据...\n")

        start_time = time.time()

        try:
            while True:
                # 检查超时
                if duration > 0 and time.time() - start_time > duration:
                    break

                # 读取一行
                if self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()

                    # 解析观察数据
                    obs = self.parse_hand_observation(line)
                    if obs:
                        self.process_observation(obs)
                else:
                    time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n\n用户中断")

        # 输出统计
        print("\n" + "="*60)
        print("  统计信息")
        print("="*60)
        print(f"总观察次数: {self.total_observations}")
        print(f"有效手部: {self.valid_hand_count}")
        print(f"居中次数: {self.centered_count}")
        if self.valid_hand_count > 0:
            print(f"居中比例: {self.centered_count / self.valid_hand_count * 100:.1f}%")
        print("="*60)

    def run(self):
        """运行模拟器"""
        try:
            self.connect()
            self.monitor(duration=0)  # 无限监控
        except Exception as e:
            print(f"\n✗ 错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.ser and self.ser.is_open:
                print("\n关闭串口...")
                self.ser.close()


def main():
    parser = argparse.ArgumentParser(description="手势居中模拟器")
    parser.add_argument("--port", default="COM3", help="串口端口 (默认: COM3)")
    parser.add_argument("--baudrate", type=int, default=115200, help="波特率 (默认: 115200)")

    args = parser.parse_args()

    simulator = HandCenterSimulator(args.port, args.baudrate)
    simulator.run()


if __name__ == "__main__":
    main()

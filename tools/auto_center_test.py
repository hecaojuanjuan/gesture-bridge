#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动居中测试工具 - 启动时自动居中人像和手势

使用方法:
    python tools/auto_center_test.py --port COM3

功能:
1. 连接设备并等待启动
2. 自动检测人脸并居中
3. 自动检测手势并居中
4. 输出详细的调试日志
"""
import argparse
import json
import re
import serial
import sys
import time
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class AutoCenterController:
    """自动居中控制器"""

    def __init__(self, port, baudrate=115200, timeout=30):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.face_detected = False
        self.hand_detected = False

    def connect(self):
        """连接串口"""
        print(f"连接到 {self.port} @ {self.baudrate}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=2)
        time.sleep(0.5)
        # 清空缓冲区
        self.ser.reset_input_buffer()
        print("✓ 串口已连接")

    def wait_for_boot(self, timeout=10):
        """等待设备启动"""
        print("等待设备启动...")
        start = time.time()
        boot_detected = False

        while time.time() - start < timeout:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                print(f"  {line}")

                if "GIMBAL ready" in line or "ready" in line.lower():
                    boot_detected = True
                    print("✓ 设备已启动")
                    break

        if not boot_detected:
            print("⚠ 未检测到启动信息，继续尝试...")

        return boot_detected

    def send_command(self, cmd, wait_response=True, timeout=5):
        """发送命令并等待响应"""
        print(f"\n>>> {cmd}")
        self.ser.write(f"{cmd}\n".encode('utf-8'))
        self.ser.flush()

        if not wait_response:
            return []

        responses = []
        start = time.time()

        while time.time() - start < timeout:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"<<< {line}")
                    responses.append(line)

                    # 检测到错误或完成标记
                    if "ERROR" in line or "GIMBAL {" in line:
                        break
            else:
                time.sleep(0.1)

        return responses

    def parse_gimbal_status(self, responses):
        """解析云台状态"""
        for line in responses:
            if "GIMBAL {" in line:
                try:
                    # 提取JSON部分
                    json_str = line[line.index("{"):line.rindex("}")+1]
                    status = json.loads(json_str)
                    return status
                except (ValueError, json.JSONDecodeError) as e:
                    print(f"⚠ 解析状态失败: {e}")
        return None

    def parse_target(self, responses):
        """解析目标信息"""
        for line in responses:
            if '"event":"target"' in line:
                try:
                    json_str = line[line.index("{"):line.rindex("}")+1]
                    target = json.loads(json_str)
                    return target
                except (ValueError, json.JSONDecodeError) as e:
                    print(f"⚠ 解析目标失败: {e}")
        return None

    def check_face_target(self):
        """检查人脸目标"""
        print("\n=== 检查人脸目标 ===")
        responses = self.send_command("hv_gimbal target")
        target = self.parse_target(responses)

        if target and target.get("valid"):
            print(f"✓ 检测到人脸: x={target['x']:.3f}, y={target['y']:.3f}")
            print(f"  采集时间: {target['captured_ms']}ms, 帧龄: {target['age_ms']}ms")
            self.face_detected = True
            return target
        else:
            print("✗ 未检测到有效人脸目标")
            if target:
                print(f"  people={target.get('people', 0)}, valid={target.get('valid', False)}")
            self.face_detected = False
            return None

    def auto_center_face(self):
        """自动居中人脸"""
        print("\n=== 启动人脸自动居中 ===")

        # 1. 检查状态
        responses = self.send_command("hv_gimbal status")
        status = self.parse_gimbal_status(responses)

        if not status:
            print("✗ 无法获取云台状态")
            return False

        # 2. 检查目标
        target = self.check_face_target()
        if not target:
            print("✗ 需要有效的人脸目标才能启动居中")
            return False

        # 3. 如果已经在运行，先停止
        if status.get("active"):
            print("  云台正在运行，先停止...")
            self.send_command("hv_gimbal stop")
            time.sleep(0.5)

        # 4. 启动两个轴
        print("  启动pan轴...")
        self.send_command("hv_gimbal arm pan")
        time.sleep(0.5)

        print("  启动tilt轴...")
        self.send_command("hv_gimbal arm tilt")
        time.sleep(0.5)

        # 5. 设置方向（根据之前的标定，这里假设都是+1）
        print("  设置方向...")
        self.send_command("hv_gimbal dir 1 1")
        time.sleep(0.5)

        # 6. 再次检查目标
        target = self.check_face_target()
        if not target:
            print("✗ 启动前目标丢失")
            return False

        # 7. 启动自动居中
        print("  启动自动居中...")
        responses = self.send_command("hv_gimbal start", timeout=10)

        # 检查是否成功启动
        for line in responses:
            if "started" in line:
                print("✓ 自动居中已启动")
                return True
            elif "ERROR" in line:
                print(f"✗ 启动失败: {line}")
                return False

        return False

    def monitor_centering(self, duration=60):
        """监控居中过程"""
        print(f"\n=== 监控居中过程 ({duration}秒) ===")
        start = time.time()
        last_status_time = start

        while time.time() - start < duration:
            # 每5秒查询一次状态
            if time.time() - last_status_time >= 5:
                responses = self.send_command("hv_gimbal status")
                status = self.parse_gimbal_status(responses)

                if status:
                    if not status.get("active"):
                        reason = status.get("last_stop_reason", "unknown")
                        print(f"\n居中已停止: {reason}")

                        if reason == "centered":
                            print("✓ 成功居中！")
                            return True
                        elif reason in ["timeout", "lost_target", "wrong_direction"]:
                            print(f"✗ 居中失败: {reason}")
                            return False
                        else:
                            print(f"⚠ 居中结束: {reason}")
                            return False
                    else:
                        print(f"  运行中... steps={status.get('steps', 0)}, "
                              f"pan={status.get('pan_us', 0)}µs, "
                              f"tilt={status.get('tilt_us', 0)}µs")

                last_status_time = time.time()

            # 读取实时日志
            while self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line and "GIMBAL" in line:
                    print(f"  {line}")

            time.sleep(0.2)

        print("\n⚠ 监控超时")
        return False

    def run_auto_center_sequence(self):
        """运行完整的自动居中序列"""
        print("\n" + "="*60)
        print("  自动居中测试")
        print("="*60)

        try:
            # 1. 连接设备
            self.connect()

            # 2. 等待启动
            self.wait_for_boot()
            time.sleep(2)

            # 3. 检查初始状态
            print("\n=== 检查初始状态 ===")
            responses = self.send_command("hv_gimbal status")
            status = self.parse_gimbal_status(responses)

            if status:
                print(f"  PWM状态: pan={status.get('pan_armed', False)}, "
                      f"tilt={status.get('tilt_armed', False)}")
                print(f"  活动状态: {status.get('active', False)}")

            # 4. 等待一会让摄像头稳定
            print("\n等待摄像头稳定...")
            time.sleep(3)

            # 5. 执行人脸居中
            if self.auto_center_face():
                # 6. 监控居中过程
                success = self.monitor_centering(duration=90)

                if success:
                    print("\n" + "="*60)
                    print("  ✓ 人脸自动居中成功！")
                    print("="*60)
                else:
                    print("\n" + "="*60)
                    print("  ✗ 人脸自动居中失败")
                    print("="*60)
            else:
                print("\n✗ 无法启动人脸居中")

        except KeyboardInterrupt:
            print("\n\n用户中断")
        except Exception as e:
            print(f"\n✗ 错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.ser and self.ser.is_open:
                print("\n关闭串口...")
                self.ser.close()


def main():
    parser = argparse.ArgumentParser(description="自动居中测试工具")
    parser.add_argument("--port", default="COM3", help="串口端口 (默认: COM3)")
    parser.add_argument("--baudrate", type=int, default=115200, help="波特率 (默认: 115200)")

    args = parser.parse_args()

    controller = AutoCenterController(args.port, args.baudrate)
    controller.run_auto_center_sequence()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动居中启动脚本 - 设备启动时自动运行

这个脚本会：
1. 检测设备启动
2. 等待固件加载完成
3. 如果固件支持云台，自动执行居中
4. 如果固件不支持，提示需要烧录正确固件

使用方法:
    python tools/auto_center_on_boot.py --port COM3
"""
import argparse
import json
import serial
import sys
import time
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class AutoCenterOnBoot:
    """启动时自动居中"""

    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.has_gimbal = False

    def connect(self):
        """连接串口"""
        print(f"[启动] 连接到 {self.port}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=2)
        time.sleep(1)
        self.ser.reset_input_buffer()
        print("[启动] ✓ 已连接\n")

    def wait_for_boot(self, timeout=30):
        """等待设备启动"""
        print("[启动] 等待设备启动...")
        start = time.time()
        boot_detected = False
        gimbal_ready = False

        while time.time() - start < timeout:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()

                if "GIMBAL ready" in line:
                    print(f"[启动] ✓ 检测到云台模块")
                    gimbal_ready = True
                    boot_detected = True
                    break
                elif "HeadVoice" in line or "ready" in line.lower():
                    boot_detected = True
                    print(f"[启动] ✓ 设备已启动")

        if gimbal_ready:
            self.has_gimbal = True
            return True
        elif boot_detected:
            print("[启动] ⚠ 设备已启动，但没有云台模块")
            return False
        else:
            print("[启动] ⚠ 超时未检测到启动")
            return False

    def check_gimbal_support(self):
        """检查云台支持"""
        print("\n[检查] 验证云台功能...")

        self.ser.write(b"hv_gimbal status\n")
        self.ser.flush()
        time.sleep(1)

        responses = []
        while self.ser.in_waiting:
            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
            responses.append(line)
            if "GIMBAL {" in line:
                print("[检查] ✓ 云台功能已启用")
                self.has_gimbal = True
                return True
            elif "not found" in line.lower():
                print("[检查] ✗ 云台功能未找到")
                self.has_gimbal = False
                return False

        if not responses:
            print("[检查] ✗ 无响应")
            self.has_gimbal = False

        return self.has_gimbal

    def auto_center_face(self):
        """自动居中人脸"""
        if not self.has_gimbal:
            print("\n" + "="*60)
            print("  ✗ 当前固件不支持云台功能")
            print("="*60)
            print("\n需要烧录云台固件:")
            print("1. 构建固件: python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90")
            print("2. 烧录固件: python tools/build.py headvoice flash --port COM3")
            print("3. 重新运行此脚本")
            return False

        print("\n" + "="*60)
        print("  开始自动居中")
        print("="*60)

        # 等待一会让摄像头稳定
        print("\n[居中] 等待摄像头稳定...")
        time.sleep(3)

        # 1. 检查目标
        print("[居中] 检查人脸目标...")
        self.ser.write(b"hv_gimbal target\n")
        self.ser.flush()
        time.sleep(1)

        target_valid = False
        while self.ser.in_waiting:
            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
            if '"valid":true' in line:
                target_valid = True
                print("[居中] ✓ 检测到人脸")
                break

        if not target_valid:
            print("[居中] ✗ 未检测到人脸，请面向摄像头")
            return False

        # 2. 启动pan轴
        print("[居中] 启动水平轴...")
        self.ser.write(b"hv_gimbal arm pan\n")
        self.ser.flush()
        time.sleep(1)
        self.clear_buffer()

        # 3. 启动tilt轴
        print("[居中] 启动俯仰轴...")
        self.ser.write(b"hv_gimbal arm tilt\n")
        self.ser.flush()
        time.sleep(1)
        self.clear_buffer()

        # 4. 设置方向 (假设都是+1，实际需要校准)
        print("[居中] 设置方向...")
        self.ser.write(b"hv_gimbal dir 1 1\n")
        self.ser.flush()
        time.sleep(1)
        self.clear_buffer()

        # 5. 启动自动居中
        print("[居中] 启动自动居中...")
        self.ser.write(b"hv_gimbal start\n")
        self.ser.flush()
        time.sleep(2)

        started = False
        while self.ser.in_waiting:
            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
            print(f"  {line}")
            if '"event":"started"' in line:
                started = True

        if started:
            print("\n[居中] ✓ 自动居中已启动")
            print("[居中] 监控居中过程（90秒）...")
            self.monitor_centering(90)
            return True
        else:
            print("\n[居中] ✗ 启动失败")
            return False

    def monitor_centering(self, duration):
        """监控居中过程"""
        start = time.time()

        while time.time() - start < duration:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if "GIMBAL" in line:
                    if '"event":"stopped"' in line or 'STOP' in line:
                        if 'centered' in line:
                            print("\n" + "="*60)
                            print("  ✓✓✓ 居中成功！")
                            print("="*60)
                        else:
                            print(f"\n[居中] 停止: {line}")
                        return
                    elif '"event":"observation"' in line:
                        # 显示进度
                        try:
                            data = json.loads(line[line.index("{"):])
                            if data.get('active'):
                                print(f"  步骤 {data.get('steps', 0)}: "
                                      f"pan={data.get('pan_us', 0)}µs, "
                                      f"tilt={data.get('tilt_us', 0)}µs")
                        except:
                            pass
            time.sleep(0.2)

        print("\n[居中] 超时")

    def clear_buffer(self):
        """清空串口缓冲"""
        while self.ser.in_waiting:
            self.ser.readline()

    def run(self):
        """运行自动居中流程"""
        print("\n" + "="*60)
        print("  设备启动自动居中")
        print("="*60)

        try:
            # 1. 连接
            self.connect()

            # 2. 等待启动
            boot_ok = self.wait_for_boot(timeout=30)

            # 3. 检查云台支持
            if not self.has_gimbal:
                time.sleep(2)
                self.check_gimbal_support()

            # 4. 执行自动居中
            if self.has_gimbal:
                self.auto_center_face()
            else:
                print("\n" + "="*60)
                print("  当前固件不支持云台")
                print("="*60)
                print("\n你需要:")
                print("1. 烧录云台固件: artifacts/headvoice-face-autocenter-stage2-20261031.bin")
                print("2. 或者构建并烧录新固件")
                print("\n构建命令:")
                print("  python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90")
                print("\n烧录命令:")
                print("  python tools/build.py headvoice flash --port COM3")

        except KeyboardInterrupt:
            print("\n\n[中断] 用户中断")
        except Exception as e:
            print(f"\n[错误] {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.ser and self.ser.is_open:
                print("\n[关闭] 断开连接...")
                self.ser.close()


def main():
    parser = argparse.ArgumentParser(description="设备启动自动居中")
    parser.add_argument("--port", default="COM3", help="串口端口")
    parser.add_argument("--baudrate", type=int, default=115200, help="波特率")

    args = parser.parse_args()

    auto_center = AutoCenterOnBoot(args.port, args.baudrate)
    auto_center.run()


if __name__ == "__main__":
    main()

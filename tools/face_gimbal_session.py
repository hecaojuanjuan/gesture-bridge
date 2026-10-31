"""Safely calibrate face-stage-2 gimbal over one persistent serial connection."""
import argparse
from collections import deque
import datetime
import json
import math
from pathlib import Path
import re
import shlex
import time

from camera_preview import SerialLines


RESTART = re.compile(r"ESP-ROM:|(?:^|\s)rst:0x|Guru Meditation|Brownout|Restarting\.\.\.")
LIMITS = [1475, 1525]
TARGET_READ_RETRIES = 2


class DeviceRestarted(RuntimeError):
    pass


class CorruptReceipt(RuntimeError):
    pass


class TargetReceiptInterrupted(RuntimeError):
    pass


class FaceGimbalSession:
    def __init__(self, device, log, clock=time.monotonic):
        self.device, self.log, self.clock = device, log, clock
        self.framing = SerialLines(max_line_bytes=65536, encoding="utf-8")
        self.lines = deque()
        self.restarted = False
        self.restart_count = 0
        self.motion_sent = False
        self.status = None
        self.ready_seen = False

    def _read_line(self, deadline, startup=False):
        while self.clock() < deadline:
            if not self.lines:
                self.lines.extend(self.framing.feed(self.device.read(4096)))
                continue
            line = self.lines.popleft()
            self.log.write(json.dumps({
                "host_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "line": line}, ensure_ascii=False) + "\n")
            self.log.flush()
            if RESTART.search(line):
                self.restart_count += 1
                print("设备启动/重启：", line, flush=True)
                if startup:
                    self.ready_seen = False
                    self.status = None
                    continue
                self.restarted = True
                raise DeviceRestarted("串口出现重启或崩溃标记；已停止后续运动命令")
            if "GIMBAL ready" in line:
                self.ready_seen = True
                print("云台固件已就绪", flush=True)
            if "GIMBAL ERROR" in line or "GIMBAL STOP" in line:
                print(line, flush=True)
                if not startup:
                    raise RuntimeError("设备拒绝命令或安全停机；本次交互结束")
            if "GIMBAL {" in line:
                print(line[line.find("GIMBAL {"):], flush=True)
            return line
        return None

    @staticmethod
    def _event(line):
        start = line.find("GIMBAL {")
        if start < 0:
            return None
        try:
            event = json.loads(line[start + len("GIMBAL "):])
        except (ValueError, TypeError):
            raise CorruptReceipt("设备云台回执被串口回显打断") from None
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise CorruptReceipt("设备云台回执缺少 event")
        return event

    @staticmethod
    def _check_status(status):
        if (status.get("event") != "status" or status.get("limits_us") != LIMITS or
                status.get("max_step_us") != 25 or status.get("max_age_ms") != 400 or
                status.get("lost_after_ms") != 1000):
            raise RuntimeError("固件不是本次 face stage 2 安全云台版本")
        for key in ("active", "pan_armed", "tilt_armed", "directions_ready",
                    "holding", "output_fault"):
            if type(status.get(key)) is not bool:
                raise RuntimeError(f"云台回执字段 {key} 无效")
        if (status["output_fault"] or
                any(type(status.get(key)) is not int for key in ("pan_us", "tilt_us")) or
                any(not LIMITS[0] <= status[key] <= LIMITS[1]
                    for key in ("pan_us", "tilt_us"))):
            raise RuntimeError("PWM 输出故障或脉宽越界；停止测试")
        return status

    def _write(self, *words):
        wire = "hv_gimbal " + " ".join(words) + "\r\n"
        if words[0] in ("arm", "jog", "start"):
            self.motion_sent = True
        self.device.write(wire.encode("ascii"))
        self.device.flush()

    def _drain(self):
        deadline = self.clock() + 0.12
        while True:
            line = self._read_line(deadline)
            if line is None:
                return
            try:
                self._event(line)
            except CorruptReceipt:
                self._recover_status()
                raise RuntimeError("上一条回执损坏；已只读复核，本次不发送新的运动命令") from None

    def _recover_status(self, timeout=5):
        """A damaged receipt may mean the command ran; query, never replay it."""
        deadline, next_query = self.clock() + timeout, 0
        while self.clock() < deadline:
            if self.clock() >= next_query:
                self._write("status")
                next_query = self.clock() + 1
            line = self._read_line(min(deadline, next_query))
            if line is None:
                continue
            try:
                event = self._event(line)
            except CorruptReceipt:
                continue
            if event is not None and event["event"] == "status":
                status = self._check_status(event)
                self.status = status
                print("已通过只读 status 复核；原动作命令没有重发。", flush=True)
                return status
        raise TimeoutError("回执损坏后未能用只读 status 确认设备状态")

    def exchange(self, words, before=None, timeout=5):
        self._drain()
        self._write(*words)
        primary = None
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            line = self._read_line(deadline)
            if line is None:
                break
            try:
                event = self._event(line)
            except CorruptReceipt:
                print("云台回执损坏，改用只读 status 复核。", flush=True)
                status = self._recover_status()
                if words[0] == "target" and primary is None:
                    raise TargetReceiptInterrupted("目标回执损坏；仅允许重读 target")
                if words[0] == "start" and primary is None:
                    raise RuntimeError("start 回执损坏，启动状态不确定；请求停机")
                return primary, status
            if event is None:
                continue
            if before and event["event"] == before:
                primary = event
            if event["event"] == "status" and (not before or primary is not None):
                status = self._check_status(event)
                self.status = status
                return primary, status
        raise TimeoutError("没有收到与命令匹配的完整云台回执")

    def startup(self, timeout=35):
        """Read through USB-triggered boots, then require two safe status replies."""
        deadline, next_query, safe_reports = self.clock() + timeout, 0, 0
        seen_restarts = self.restart_count
        while self.clock() < deadline:
            if self.clock() >= next_query:
                self._write("status")
                next_query = self.clock() + 1
            line = self._read_line(min(deadline, next_query), startup=True)
            if self.restart_count != seen_restarts:
                safe_reports = 0
                seen_restarts = self.restart_count
            if line is None:
                continue
            try:
                event = self._event(line)
            except CorruptReceipt:
                safe_reports = 0
                continue
            if event is None or event["event"] != "status":
                continue
            status = self._check_status(event)
            if status["active"] or status["pan_armed"] or status["tilt_armed"]:
                raise RuntimeError("启动后云台输出不为关闭状态；未发送运动命令")
            safe_reports += 1
            self.status = status
            if safe_reports >= 2:
                return status
        raise TimeoutError("未连续两次确认双轴 PWM 关闭；确认已烧录 face 云台固件及串口端口")

    def guarded_exchange(self, words, before=None, timeout=5):
        previous = self.status
        _, current = self.exchange(("status",))
        if previous is not None and any(previous[key] != current[key] for key in
                ("active", "pan_armed", "tilt_armed", "holding", "pan_us", "tilt_us")):
            raise RuntimeError("设备状态在两条命令之间发生变化；未发送新的运动命令")
        return self.exchange(words, before=before, timeout=timeout)

    def target(self):
        for attempt in range(TARGET_READ_RETRIES + 1):
            try:
                target, _ = self.exchange(("target",), before="target")
                break
            except TargetReceiptInterrupted:
                if attempt == TARGET_READ_RETRIES:
                    raise RuntimeError("目标回执连续损坏；已停止只读重试，不发送运动命令") from None
                print("目标回执被日志打断；只重读 target，不重发任何运动命令。", flush=True)
        if (type(target.get("valid")) is not bool or type(target.get("people")) is not int or
                type(target.get("age_ms")) is not int):
            raise RuntimeError("目标坐标回执无效")
        if target["valid"] and (target["people"] != 1 or target["age_ms"] > 400 or
                any(type(target.get(key)) not in (float, int) or
                    not math.isfinite(target[key]) or not 0 <= target[key] <= 1
                    for key in ("x", "y"))):
            raise RuntimeError("设备报告了不可信的有效目标")
        return target

    def move_command(self, words):
        action = words[0]
        previous = self.status
        if action == "arm":
            print(f"arm {words[1]} 会立即输出 1500 µs，可能从当前角度大幅转动；"
                  "1500 µs 不是已标定的镜头朝前位置，±25 µs 步长不限制这次初始位移。", flush=True)
        primary = "started" if action == "start" else "stopped" if action == "stop" else None
        event, status = self.guarded_exchange(words, before=primary)
        if action == "arm":
            axis = words[1]
            if not status[f"{axis}_armed"] or status[f"{axis}_us"] != 1500:
                raise RuntimeError("arm 未得到指定轴的 1500 µs 回执")
        elif action == "jog":
            axis, delta = words[1], int(words[2])
            if not status[f"{axis}_armed"] or status[f"{axis}_us"] != previous[f"{axis}_us"] + delta:
                raise RuntimeError("jog 回执与请求的脉宽变化不符")
        elif action == "dir":
            if (not status["directions_ready"] or status["pan_dir"] != int(words[1]) or
                    status["tilt_dir"] != int(words[2])):
                raise RuntimeError("方向回执与请求不符")
        elif action == "start":
            if event is None or not status["active"]:
                raise RuntimeError("自动居中没有启动")
        elif action == "stop":
            if status["active"] or status["pan_armed"] or status["tilt_armed"]:
                raise RuntimeError("停机回执未确认两轴关闭")
            self.motion_sent = False
        return status

    def monitor_centering(self, timeout=95):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            line = self._read_line(deadline)
            if line is None:
                break
            event = self._event(line)
            if not event or event["event"] != "observation":
                continue
            if (type(event.get("active")) is not bool or type(event.get("result")) is not int or
                    any(type(event.get(key)) is not int or
                        not LIMITS[0] <= event[key] <= LIMITS[1]
                        for key in ("pan_us", "tilt_us"))):
                raise RuntimeError("自动居中观测回执无效")
            if not event["active"]:
                if event["result"] != 2 or event.get("holding") is not True:
                    raise RuntimeError("自动居中在达到目标前停止")
                _, status = self.exchange(("status",))
                if not status["holding"]:
                    raise RuntimeError("居中后保持状态未确认")
                return status
        raise TimeoutError("自动居中没有在限定时间内报告完成")


def parse_input(text):
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    if not words:
        return None
    if words in (["quit"], ["exit"], ["status"], ["target"], ["start"], ["stop"]):
        return words
    if len(words) == 2 and words[0] == "arm" and words[1] in ("pan", "tilt"):
        return words
    if len(words) == 3 and words[0] == "jog" and words[1] in ("pan", "tilt"):
        try:
            delta = int(words[2])
        except ValueError:
            return None
        if words[2] in (str(delta), "+" + str(delta)) and 0 < abs(delta) <= 25:
            return words
    if len(words) == 3 and words[0] == "dir":
        try:
            directions = [int(word) for word in words[1:]]
        except ValueError:
            return None
        if all(value in (-1, 1) and word in (str(value), "+" + str(value))
               for value, word in zip(directions, words[1:])):
            return words
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="CH343 /dev/cu.usbmodem... port")
    parser.add_argument("--output", type=Path,
                        default=Path(".local/face-gimbal-session-" +
                                     datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl"))
    args = parser.parse_args()
    import serial

    args.output.parent.mkdir(parents=True, exist_ok=True)
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.2
    device.dtr = device.rts = False
    failed = False
    with device, args.output.open("w", encoding="utf-8") as log:
        session = FaceGimbalSession(device, log)
        try:
            session.startup()
            print("已连续两次确认双轴 PWM 关闭；这不代表已测得实际轴角。单次 arm/jog 租期 10 秒，离开会自动发送 stop。")
            print("arm 会直接驱动到 1500 µs 对应位置，并非保持当前位置；镜头朝前的位置尚未标定。")
            print("stop 或租期到期会关闭 PWM；需由机械结构承托支架。运动前先确认启动位置、线材余量与供电。")
            session.target()
            print("输入 status、target、arm pan|tilt、jog pan|tilt ±25、dir ±1 ±1、start、stop、quit。")
            while True:
                try:
                    words = parse_input(input("face-gimbal> ").strip())
                except EOFError:
                    break
                if not words:
                    print("命令格式不对；输入 status 查看状态。")
                    continue
                if words[0] in ("quit", "exit"):
                    break
                if words[0] == "status":
                    session.exchange(("status",))
                elif words[0] == "target":
                    session.target()
                else:
                    if words[0] == "start" and not session.target()["valid"]:
                        print("当前没有 400 ms 内的有效单脸目标，未发送 start。")
                        continue
                    session.move_command(words)
                    if words[0] == "start":
                        print("自动居中已启动；观察支架。Ctrl+C 可请求停机。")
                        session.monitor_centering()
        except (KeyboardInterrupt, DeviceRestarted, RuntimeError, TimeoutError) as exc:
            failed = True
            print(f"测试结束：{exc}")
        finally:
            if not session.restarted and session.motion_sent:
                try:
                    _, status = session.exchange(("stop",), before="stopped")
                    if status["active"] or status["pan_armed"] or status["tilt_armed"]:
                        raise RuntimeError("停机回执仍显示输出开启")
                except Exception as exc:
                    failed = True
                    print(f"自动停机未取得确认：{exc}")
            print("本地串口记录：", args.output.resolve())
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

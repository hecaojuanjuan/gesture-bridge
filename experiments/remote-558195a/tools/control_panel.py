"""Local serial setup guide and RGB panel; never opens a port on startup."""
import json
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

import serial
from serial.tools import list_ports


STATES = {
    "starting": "设备正在启动 · 白灯",
    "provisioning": "等待小程序 BLE 配网 · 蓝灯慢闪",
    "connecting": "正在连接 Wi-Fi · 黄灯闪烁",
    "cloud_connecting": "Wi-Fi 已取得 IP，正在连接云端 · 黄灯闪烁",
    "online": "云端已连接 · 绿灯",
    "disconnected": "连接已断开，设备正在重连 · 红灯慢闪",
    "error": "设备初始化或配网失败 · 红灯慢闪",
}


def parse_reply(line, request_id):
    """Accept only a complete, matching, version-compatible device reply."""
    start = line.find("PANEL {")
    if start < 0:
        return None
    try:
        row, _ = json.JSONDecoder().raw_decode(line[start + 6:])
    except (ValueError, TypeError):
        return None
    if (not isinstance(row, dict) or type(row.get("id")) is not int
            or row.get("id") != request_id):
        return None
    if row.get("ok") is not True:
        raise RuntimeError("设备拒绝命令")
    required = {"state", "mode", "brightness", "ready", "render_ok",
                "rgb", "uptime"}
    if not required.issubset(row):
        raise RuntimeError("设备回执格式不完整，请核对固件版本")
    if (row["state"] not in STATES or row["mode"] not in {"auto", "manual"}
            or type(row["brightness"]) is not int
            or not 0 <= row["brightness"] <= 100
            or type(row["uptime"]) is not int or row["uptime"] < 0
            or type(row["ready"]) is not bool
            or type(row["render_ok"]) is not bool
            or not isinstance(row["rgb"], list) or len(row["rgb"]) != 3
            or any(type(v) is not int or not 0 <= v <= 255
                   for v in row["rgb"])):
        raise RuntimeError("设备回执字段无效")
    return row


def validate_action(action):
    if action in {"status", "auto", "off", "restart"}:
        return
    parts = action.split()
    if (len(parts) == 2 and parts[0] == "brightness"
            and re.fullmatch(r"\d{1,3}", parts[1])
            and 0 <= int(parts[1]) <= 100):
        return
    if (len(parts) == 4 and parts[0] == "color"
            and all(re.fullmatch(r"\d{1,3}", p)
                    and 0 <= int(p) <= 255 for p in parts[1:])):
        return
    raise ValueError("Invalid panel action")


def exchange(device, request_id, action):
    validate_action(action)
    device.write(f"hv_panel {request_id} {action}\r\n".encode("ascii"))
    device.flush()
    deadline = time.monotonic() + 4
    pending = b""
    while time.monotonic() < deadline:
        pending += device.read_until(b"\n", 1024)
        if len(pending) > 4096:
            pending = b""
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace")
            if re.search(r"Guru Meditation|ESP-ROM:|rst:", text):
                raise RuntimeError("设备发生重启，请等待启动后重新连接")
            reply = parse_reply(text, request_id)
            if reply is not None:
                return reply
    raise TimeoutError("设备未回执：请确认面板固件已烧录且串口未被占用")


def serial_worker(port, commands, events, stop):
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = port, 115200, 0.2
    device.write_timeout = 1
    device.dtr = device.rts = False
    try:
        with device:
            device.reset_input_buffer()
            request_id = int(time.monotonic() * 1000) % 999999
            while not stop.is_set():
                try:
                    action = commands.get(timeout=0.1)
                except queue.Empty:
                    action = "status"
                if stop.is_set():
                    break
                request_id = request_id % 999999 + 1
                row = exchange(device, request_id, action)
                events.put(("reply", (action, row)))
                if action == "restart":
                    events.put(("reset", None))
                    break
                if action == "status":
                    stop.wait(1.5)
    except Exception as error:
        events.put(("error", str(error)))
    finally:
        events.put(("closed", None))


class Panel:
    def __init__(self, root):
        self.root = root
        self.commands, self.events = queue.Queue(8), queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.verified = False
        self.ports = {}
        self.last_reply = 0
        self.port = tk.StringVar()
        self.link = tk.StringVar(value="串口未连接")
        self.state = tk.StringVar(value="设备状态未知")
        self.light = tk.StringVar(value="等待设备回执")
        self.notice = tk.StringVar(value="连接串口不会清除已有 Wi-Fi。")
        self.brightness = tk.IntVar(value=20)
        root.title("颔语 · 配网与灯光控制")
        root.geometry("850x700")
        root.minsize(760, 650)
        style = ttk.Style()
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=(
            "Microsoft YaHei UI", 20, "bold"))
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="颔语 · 设备控制台",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer, text="配网引导 / 实时联网状态 / RGB 灯板").pack(anchor="w", pady=(4, 16))
        connection = ttk.Frame(outer)
        connection.pack(fill="x")
        self.selector = ttk.Combobox(connection, textvariable=self.port,
                                     state="readonly", width=42)
        self.selector.pack(side="left", padx=(0, 8))
        ttk.Button(connection, text="刷新端口",
                   command=self.refresh).pack(side="left")
        self.connect_button = ttk.Button(
            connection, text="连接", command=self.connect)
        self.connect_button.pack(side="left", padx=8)
        ttk.Button(connection, text="断开",
                   command=self.disconnect).pack(side="left")
        status = ttk.LabelFrame(outer, text="设备回执", padding=12)
        status.pack(fill="x", pady=14)
        for variable in (self.link, self.state, self.light):
            ttk.Label(status, textvariable=variable,
                      wraplength=740).pack(anchor="w", pady=2)
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        guide = ttk.Frame(tabs, padding=16)
        rgb = ttk.Frame(tabs, padding=16)
        tabs.add(guide, text=" 配网引导 ")
        tabs.add(rgb, text=" RGB 灯光 ")
        steps = [
            ("1  连接设备", "通过 USB 连接开发板，选择 CH343 对应端口。关闭其他串口程序，再点连接。"),
            ("2  进入配网", "首次使用无已存网络时，设备自动进入 BLE 配网。更换网络时使用下方按钮。"),
            ("3  手机完成配网", "打开配套小程序，启用蓝牙和小程序所需权限，添加设备并选择 2.4 GHz Wi-Fi。密码只在小程序输入，无需先在系统蓝牙设置中配对。"),
            ("4  核对结果", "蓝灯慢闪：等待配网；黄灯闪烁：连接中；绿灯：云端已连接；红灯慢闪：断开或失败。请同时查看上方设备状态文字。"),
        ]
        for title, body in steps:
            ttk.Label(guide, text=title, font=("Microsoft YaHei UI",
                      11, "bold")).pack(anchor="w", pady=(5, 2))
            ttk.Label(guide, text=body, wraplength=700).pack(
                anchor="w", pady=(0, 7))
        self.reset_button = ttk.Button(
            guide, text="更换 Wi-Fi / 重新进入配网…", command=self.reset)
        self.reset_button.pack(anchor="w", pady=8)
        ttk.Label(rgb, text="自动模式随联网状态变化；手动测试后可恢复自动提示。",
                  wraplength=700).pack(anchor="w", pady=8)
        actions = ttk.Frame(rgb)
        actions.pack(anchor="w", pady=10)
        self.controls = []
        for text, action in [("自动状态灯", "auto"), ("关闭灯光", "off")]:
            button = ttk.Button(actions, text=text,
                                command=lambda a=action: self.send(a))
            button.pack(side="left", padx=(0, 8))
            self.controls.append(button)
        choose = ttk.Button(actions, text="选择测试颜色…", command=self.choose_color)
        choose.pack(side="left")
        self.controls.append(choose)
        ttk.Label(rgb, text="亮度（0–100%，最大输出限制为原厂示例亮度）").pack(
            anchor="w", pady=(15, 6))
        self.slider = tk.Scale(
            rgb, from_=0, to=100, orient="horizontal", variable=self.brightness, length=380)
        self.slider.pack(anchor="w")
        apply = ttk.Button(rgb, text="应用亮度", command=lambda: self.send(
            f"brightness {self.brightness.get()}"))
        apply.pack(anchor="w", pady=8)
        self.controls.extend([apply, self.slider])
        ttk.Label(rgb, text="表达功能运行时，自动模式仍保留白色校准、黄色待确认和蓝色播放提示。\n灯光写入成功不代表已经人工确认灯珠亮起。",
                  wraplength=700).pack(anchor="w", pady=16)
        ttk.Label(outer, textvariable=self.notice,
                  wraplength=770).pack(anchor="w", pady=(12, 0))
        self.refresh()
        self.set_controls(False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def set_controls(self, enabled):
        self.verified = enabled
        for widget in self.controls + [self.reset_button]:
            widget.configure(state="normal" if enabled else "disabled")

    def refresh(self):
        self.ports = {f"{p.device} · {p.description}": p.device
                      for p in list_ports.comports()}
        self.selector["values"] = list(self.ports)
        if self.port.get() not in self.ports:
            self.port.set("")

    def connect(self):
        if self.worker and self.worker.is_alive():
            return
        if self.port.get() not in self.ports:
            self.notice.set("请先选择开发板实际串口。")
            return
        self.commands = queue.Queue(8)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.set_controls(False)
        self.connect_button.configure(state="disabled")
        self.link.set("串口连接中，正在等待面板固件回执…")
        self.worker = threading.Thread(target=serial_worker, daemon=True,
                                       args=(self.ports[self.port.get()], self.commands,
                                             self.events, self.stop))
        self.worker.start()

    def disconnect(self):
        self.stop.set()
        self.set_controls(False)
        self.link.set("串口已断开（正在释放端口）")
        self.state.set("设备状态未知；断开面板不改变设备网络和灯光")
        self.light.set("无实时回执")

    def send(self, action):
        if not self.verified or self.stop.is_set():
            return
        try:
            self.commands.put_nowait(action)
            self.notice.set("命令已排队，等待设备回执…")
        except queue.Full:
            self.notice.set("命令队列忙，请稍后再试。")

    def reset(self):
        if messagebox.askyesno("重新配网", "这会清除设备保存的 Wi-Fi、配网环境和本地绑定标记，并重启进入 BLE 配网。不会删除云端账号设备。\n\n确定继续？"):
            self.send("restart")

    def choose_color(self):
        color, _ = colorchooser.askcolor(title="选择 RGB 测试颜色")
        if color:
            self.send("color " + " ".join(str(round(c)) for c in color))

    def poll(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "reply" and not self.stop.is_set():
                    action, row = payload
                    self.last_reply = time.monotonic()
                    self.set_controls(True)
                    self.link.set(f"串口已连接 · 设备运行 {row['uptime']} 秒 · 刚收到回执")
                    self.state.set(STATES[row["state"]])
                    mode = "自动" if row["mode"] == "auto" else "手动"
                    health = "写入正常" if row["render_ok"] else "未就绪或写入失败"
                    self.light.set(
                        f"RGB：{mode} · 亮度 {row['brightness']}% · {health} · 最近输出 {row['rgb']}")
                    if action != "status":
                        self.notice.set("设备已回执；实际灯光将在下次刷新后更新。")
                elif event == "error":
                    self.notice.set(payload)
                    self.link.set("连接失败或已中断")
                    self.state.set("设备状态未知")
                    self.light.set("无实时回执")
                    self.set_controls(False)
                elif event == "reset":
                    self.notice.set("设备已接受重置请求；请等待重启后重新连接，按引导在小程序配网。")
                    self.state.set("重启及配网结果待核对")
                    self.light.set("无实时回执")
                    self.link.set("设备正在重启，串口已释放")
                    self.set_controls(False)
                elif event == "closed":
                    self.connect_button.configure(state="normal")
                    self.set_controls(False)
        except queue.Empty:
            pass
        if self.verified and time.monotonic() - self.last_reply > 4:
            self.link.set("回执已过期，正在等待设备响应…")
        self.root.after(100, self.poll)

    def close(self):
        self.stop.set()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    Panel(window)
    window.mainloop()

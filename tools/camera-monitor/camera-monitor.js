const { SnapshotParser } = window.CameraProtocol;

const byId = (id) => document.getElementById(id);
const state = {
  port: null,
  reader: null,
  writer: null,
  readTask: null,
  capture: null,
  closing: false,
  running: false,
  pauseRequested: false,
  frame: null,
  frameCount: 0,
  lastFrameAt: 0,
  zoom: "fit",
  log: [],
};

const connectButton = byId("connectButton");
const disconnectButton = byId("disconnectButton");
const previewButton = byId("previewButton");
const downloadButton = byId("downloadButton");
const connectionBadge = byId("connectionBadge");
const connectionLabel = byId("connectionLabel");
const connectionDetail = byId("connectionDetail");
const statusBox = byId("statusBox");
const viewport = byId("viewport");
const canvasStage = byId("canvasStage");
const canvas = byId("frameCanvas");
const context = canvas.getContext("2d", { alpha: false });
const emptyStage = byId("emptyStage");
const encoder = new TextEncoder();

const serialSupported = window.isSecureContext && "serial" in navigator;

function setStatus(message, kind = "") {
  statusBox.className = "status-box" + (kind ? " " + kind : "");
  statusBox.textContent = message;
}

function setConnectionBadge(connected, error = false) {
  connectionBadge.className = "connection-badge" + (connected ? " online" : error ? " error" : "");
  connectionLabel.textContent = connected ? "已连接" : error ? "连接异常" : "未连接";
}

function updateControls() {
  const connected = Boolean(state.port) && !state.closing;
  connectButton.disabled = !serialSupported || connected;
  disconnectButton.disabled = !connected;
  previewButton.disabled = !connected || state.pauseRequested;
  downloadButton.disabled = !state.frame;

  if (state.pauseRequested) previewButton.textContent = "当前帧完成后暂停";
  else if (state.running) previewButton.textContent = "暂停刷新";
  else previewButton.textContent = state.frameCount ? "继续预览" : "开始预览";
}

function setEmptyMessage(title, detail) {
  byId("emptyTitle").textContent = title;
  byId("emptyText").textContent = detail;
}

function addDeviceLog(line) {
  const clean = line.trim();
  if (!clean || clean.startsWith("HVCAM DATA ")) return;
  state.log.push(clean.slice(0, 180));
  state.log = state.log.slice(-5);
  const list = byId("deviceLog");
  list.replaceChildren();
  for (const entry of state.log) {
    const item = document.createElement("li");
    item.textContent = entry;
    list.append(item);
  }
}

function clearCaptureTimers(capture) {
  clearTimeout(capture.responseTimer);
  clearTimeout(capture.transferTimer);
  clearTimeout(capture.retryTimer);
}

function finishCapture(capture, error, frame) {
  if (state.capture !== capture) return;
  clearCaptureTimers(capture);
  state.capture = null;
  byId("progressWrap").hidden = true;
  if (error) capture.reject(error);
  else capture.resolve(frame);
}

function requestSnapshot() {
  return new Promise((resolve, reject) => {
    const capture = {
      parser: new SnapshotParser(),
      resolve,
      reject,
      retries: 0,
      responseTimer: 0,
      transferTimer: 0,
      retryTimer: 0,
    };
    state.capture = capture;
    capture.responseTimer = setTimeout(() => {
      finishCapture(
        capture,
        new Error("设备未响应摄像头命令。固件可能不支持 hv_camera snapshot。"),
      );
    }, 5000);
    capture.transferTimer = setTimeout(() => {
      finishCapture(
        capture,
        new Error("等待完整图像帧超时。请检查摄像头连接及固件取帧状态。"),
      );
    }, 30000);
    void sendSnapshotCommand(capture);
  });
}

async function sendSnapshotCommand(capture) {
  if (state.capture !== capture || !state.writer) return;
  try {
    await state.writer.write(encoder.encode("hv_camera snapshot\r\n"));
  } catch (error) {
    finishCapture(capture, new Error("串口写入失败：" + error.message));
  }
}

function handleCameraLine(line) {
  const marker = line.indexOf("HVCAM ");
  if (marker >= 0) line = line.slice(marker);
  addDeviceLog(line);

  const capture = state.capture;
  if (!capture) return;

  try {
    const event = capture.parser.feed(line);
    if (!event) return;

    if (event.type === "wait") {
      clearTimeout(capture.responseTimer);
      capture.responseTimer = 0;
      setStatus("命令已接收，等待相机帧。", "");
    } else if (event.type === "busy") {
      clearTimeout(capture.responseTimer);
      capture.responseTimer = 0;
      if (capture.retries >= 4) {
        finishCapture(capture, new Error("相机预览任务持续繁忙，请稍后重试。"));
        return;
      }
      capture.retries += 1;
      setStatus("相机正在处理上一帧，稍后重试。", "warn");
      capture.retryTimer = setTimeout(() => {
        capture.responseTimer = setTimeout(() => {
          finishCapture(capture, new Error("设备未返回摄像头响应。"));
        }, 5000);
        void sendSnapshotCommand(capture);
      }, 700);
    } else if (event.type === "begin") {
      clearTimeout(capture.responseTimer);
      capture.responseTimer = 0;
      byId("progressWrap").hidden = false;
      byId("frameProgress").value = 0;
      byId("progressText").textContent = "0%";
      setStatus("正在接收并校验图像数据。", "");
    } else if (event.type === "progress") {
      const percent = Math.floor((event.received / event.total) * 100);
      byId("progressWrap").hidden = false;
      byId("frameProgress").value = percent;
      byId("progressText").textContent = percent + "%";
    } else if (event.type === "frame") {
      finishCapture(capture, null, event);
    }
  } catch (error) {
    finishCapture(capture, error);
  }
}

async function readSerial(port, reader) {
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (state.port === port) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        handleCameraLine(line);
        newline = buffer.indexOf("\n");
      }
      if (buffer.length > 4096) {
        addDeviceLog(buffer.slice(-180));
        buffer = buffer.slice(-512);
      }
    }
  } catch (error) {
    if (state.port === port && !state.closing) {
      setStatus("串口读取中断：" + error.message, "bad");
    }
  } finally {
    try { reader.releaseLock(); } catch { /* Port is already closing. */ }
    if (state.reader === reader) state.reader = null;
    if (state.port === port && !state.closing) {
      setStatus("开发板串口已断开。", "warn");
      setConnectionBadge(false, true);
      window.setTimeout(() => void disconnectPort("开发板串口已断开。", "warn"), 0);
    }
  }
}

async function connectPort() {
  if (!serialSupported) return;
  let candidate = null;
  connectButton.disabled = true;
  setStatus("请选择开发板对应的串口。", "");
  try {
    candidate = await navigator.serial.requestPort();
    await candidate.open({
      baudRate: 115200,
      dataBits: 8,
      stopBits: 1,
      parity: "none",
      flowControl: "none",
    });
    try {
      if (candidate.setSignals) {
        await candidate.setSignals({ dataTerminalReady: false, requestToSend: false });
      }
    } catch { /* Some USB serial drivers do not expose modem-line control. */ }

    if (!candidate.readable || !candidate.writable) throw new Error("串口数据流不可用。");
    state.port = candidate;
    state.reader = candidate.readable.getReader();
    state.writer = candidate.writable.getWriter();
    state.readTask = readSerial(candidate, state.reader);
    const info = candidate.getInfo ? candidate.getInfo() : {};
    const ids = info.usbVendorId && info.usbProductId
      ? "VID 0x" + info.usbVendorId.toString(16).padStart(4, "0") +
        " · PID 0x" + info.usbProductId.toString(16).padStart(4, "0")
      : "USB 串口 · 115200 8N1";
    connectionDetail.textContent = ids + " · 请关闭其他串口监视器";
    setConnectionBadge(true);
    setStatus("串口已连接。开始预览以请求第一帧。", "good");
    updateControls();
  } catch (error) {
    if (candidate && candidate !== state.port) {
      try { await candidate.close(); } catch { /* The port may not have opened. */ }
    }
    setConnectionBadge(false, error.name !== "NotFoundError");
    if (error.name === "NotFoundError" || error.name === "AbortError") {
      setStatus("未选择串口。", "");
    } else if (error.name === "NetworkError") {
      setStatus("串口无法打开，请关闭串口监视器或其他占用程序。", "bad");
    } else {
      setStatus("连接失败：" + error.message, "bad");
    }
    updateControls();
  }
}

async function disconnectPort(message = "串口已断开。", kind = "") {
  if (!state.port || state.closing) return;
  state.closing = true;
  const port = state.port;
  const reader = state.reader;
  const writer = state.writer;
  const readTask = state.readTask;
  state.port = null;
  state.running = false;
  state.pauseRequested = false;
  if (state.capture) finishCapture(state.capture, new Error("串口已断开。"));

  if (reader) {
    try { await reader.cancel(); } catch { /* The device may already be gone. */ }
  }
  if (readTask) {
    try { await readTask; } catch { /* The read loop reports its own status. */ }
  }
  state.reader = null;
  state.readTask = null;
  if (writer) {
    try { await writer.close(); } catch { /* The port may already be gone. */ }
    try { writer.releaseLock(); } catch { /* The writable stream may have closed. */ }
  }
  state.writer = null;
  try { await port.close(); } catch { /* A disconnected USB device cannot be closed. */ }
  state.closing = false;
  setConnectionBadge(false);
  connectionDetail.textContent = "选择开发板对应的 USB 串口；请先关闭其他串口监视器。";
  setStatus(message, kind);
  updateControls();
}

function resizeCanvas() {
  if (!state.frame) return;
  const frame = state.frame;
  const availableWidth = Math.max(80, viewport.clientWidth - 48);
  const availableHeight = Math.max(80, viewport.clientHeight - 48);
  const scale = state.zoom === "fit"
    ? Math.min(availableWidth / frame.width, availableHeight / frame.height)
    : Number(state.zoom);
  const width = Math.max(1, Math.round(frame.width * scale));
  const height = Math.max(1, Math.round(frame.height * scale));
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  canvasStage.style.width = Math.max(viewport.clientWidth, width + 48) + "px";
  canvasStage.style.height = Math.max(viewport.clientHeight, height + 48) + "px";
}

function showFrame(frame) {
  state.frame = frame;
  state.frameCount += 1;
  canvas.width = frame.width;
  canvas.height = frame.height;
  context.imageSmoothingEnabled = false;
  context.putImageData(new ImageData(frame.pixels, frame.width, frame.height), 0, 0);
  canvas.hidden = false;
  emptyStage.hidden = true;
  byId("resolutionValue").textContent = frame.width + "×" + frame.height;
  byId("frameCountValue").textContent = String(state.frameCount);
  byId("checksumValue").textContent = "PASS";
  byId("frameState").textContent = "FNV-1a PASS · " + frame.checksum.toUpperCase();
  byId("frameTime").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });

  const now = performance.now();
  if (state.lastFrameAt) {
    const interval = (now - state.lastFrameAt) / 1000;
    byId("rateValue").textContent = (1 / interval).toFixed(2) + " fps";
  } else {
    byId("rateValue").textContent = "--";
  }
  state.lastFrameAt = now;
  resizeCanvas();
  updateControls();
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function runPreview() {
  if (!state.port || state.running) return;
  state.running = true;
  state.pauseRequested = false;
  state.lastFrameAt = 0;
  updateControls();

  while (state.running && state.port) {
    try {
      const frame = await requestSnapshot();
      if (!state.port) break;
      showFrame(frame);
      if (state.pauseRequested) {
        state.pauseRequested = false;
        state.running = false;
        setStatus("当前帧已完成，刷新已暂停。", "good");
        updateControls();
        break;
      }
      setStatus("帧校验通过。正在请求下一帧。", "good");
      await delay(250);
    } catch (error) {
      if (!state.port) {
        state.running = false;
        state.pauseRequested = false;
        updateControls();
        break;
      }
      state.running = false;
      state.pauseRequested = false;
      setStatus(error.message, "bad");
      if (!state.frame) setEmptyMessage("尚未收到有效图像", error.message);
      updateControls();
      break;
    }
  }
  updateControls();
}

function togglePreview() {
  if (!state.port) return;
  if (!state.running) {
    void runPreview();
    return;
  }
  if (state.capture) {
    state.pauseRequested = true;
    setStatus("正在接收当前帧；帧完成后会暂停刷新。", "warn");
  } else {
    state.running = false;
    setStatus("刷新已暂停。", "");
  }
  updateControls();
}

function downloadFrame() {
  if (!state.frame) return;
  canvas.toBlob((blob) => {
    if (!blob) return;
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = "xjwb03-camera-" + new Date().toISOString().replace(/[:.]/g, "-") + ".png";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, "image/png");
}

connectButton.addEventListener("click", () => void connectPort());
disconnectButton.addEventListener("click", () => void disconnectPort());
previewButton.addEventListener("click", togglePreview);
downloadButton.addEventListener("click", downloadFrame);

document.querySelectorAll("[data-zoom]").forEach((button) => {
  button.addEventListener("click", () => {
    state.zoom = button.dataset.zoom;
    document.querySelectorAll("[data-zoom]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    resizeCanvas();
  });
});

window.addEventListener("resize", resizeCanvas);
if (navigator.serial) {
  navigator.serial.addEventListener("disconnect", (event) => {
    if (event.port === state.port) {
      void disconnectPort("开发板 USB 串口已移除。", "warn");
    }
  });
}

if (!window.isSecureContext) {
  setConnectionBadge(false, true);
  setStatus("请通过 localhost 或 HTTPS 打开页面后连接串口。", "warn");
  setEmptyMessage("需要安全页面来源", "使用 http://localhost 打开此页面。 ");
  updateControls();
} else if (!navigator.serial) {
  setConnectionBadge(false, true);
  setStatus("当前浏览器不支持 Web Serial。请使用桌面版 Chrome 或 Edge。", "warn");
  setEmptyMessage("浏览器不支持串口", "请使用支持 Web Serial 的桌面浏览器。");
  updateControls();
} else {
  updateControls();
}

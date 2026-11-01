"""Show verified XJWB03 camera frames in a local browser without Web Serial."""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from camera_preview import JpegSnapshot, SerialLines
from capture_serial import open_device


PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>XJWB03 摄像头画面</title>
<style>
body{margin:0;background:#151b19;color:#f1f5f2;font:16px system-ui,"Microsoft YaHei",sans-serif}
header{padding:18px 24px;background:#21312b;display:flex;justify-content:space-between;gap:12px;align-items:center}
h1{font-size:20px;margin:0} #status{font-size:14px;color:#b7d2c4}
main{max-width:1050px;margin:20px auto;padding:0 16px}
img{display:block;width:100%;max-height:calc(100vh - 160px);object-fit:contain;background:#090d0b;border-radius:8px;image-rendering:auto}
p{color:#b7d2c4} button{font:inherit;padding:8px 14px;border:0;border-radius:5px;cursor:pointer}
</style>
<header><h1>XJWB03 摄像头画面</h1><span id="status">正在连接开发板…</span></header>
<main><img id="frame" alt="等待开发板摄像头画面"><p id="detail">正在获取第一帧…</p><button onclick="refresh()">刷新画面</button></main>
<script>
let seen=0, polling=false;
async function refresh(){
  if(polling)return;
  polling=true;
  try {
    const r=await fetch('/status',{cache:'no-store',signal:AbortSignal.timeout(5000)});
    if(!r.ok)throw Error('status '+r.status);
    const s=await r.json(), age=s.updated ? Math.floor(Date.now()/1000-s.updated) : 0;
    const stale=s.count && age>15;
    document.getElementById('status').textContent=s.error ? '采集异常，正在重连' : stale ? '画面暂时停更' : s.count ? '摄像头已连接' : '正在获取画面…';
    document.getElementById('detail').textContent=s.error || (stale ? `距上一帧 ${age} 秒，正在等待开发板` : s.count ? `已收到 ${s.count} 帧 · ${new Date(s.updated*1000).toLocaleTimeString()} · 320 × 240` : '正在获取第一帧…');
    if(s.count && s.count!==seen){seen=s.count;document.getElementById('frame').src='/frame.jpg?count='+seen;}
  } catch(e){document.getElementById('status').textContent='本机服务已断开';document.getElementById('detail').textContent='请重新启动 camera_webview.py';}
  finally{polling=false}
}
refresh();setInterval(refresh,2000);
</script></html>"""


def capture_jpeg(device, lines, timeout=30):
    snapshot = JpegSnapshot(expected_source="camera")
    deadline, next_request, accepted = time.monotonic() + timeout, 0, False
    while time.monotonic() < deadline and not snapshot.complete:
        if not accepted and time.monotonic() >= next_request:
            device.write(b"hv_camera jpeg\r\n")
            next_request = time.monotonic() + 5
        for raw in lines.feed(device.read(4096)):
            start = raw.find("HVJPEG ")
            if start < 0:
                continue
            line = raw[start:].strip()
            if line.startswith(("HVJPEG WAIT", "HVJPEG SOURCE ", "HVJPEG BEGIN ")):
                accepted = True
            snapshot.feed(line)
            if snapshot.complete:
                break
    if not snapshot.complete:
        raise TimeoutError("30 秒内未收到完整画面；正在重连串口")
    return bytes(snapshot.data)


def run(port, http_port):
    state = {"frame": None, "count": 0, "updated": 0, "error": None}
    lock = threading.Lock()
    def capture_loop():
        import serial
        while True:
            try:
                with open_device(serial, port) as device:
                    lines = SerialLines()
                    while True:
                        frame = capture_jpeg(device, lines)
                        with lock:
                            state.update(frame=frame, count=state["count"] + 1,
                                         updated=time.time(), error=None)
                        time.sleep(0.5)
            except Exception as exc:
                with lock:
                    state["error"] = str(exc)
                print(f"Camera capture: {exc}", flush=True)
                time.sleep(2)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            with lock:
                data = dict(state)
            if path == "/":
                body, mime = PAGE.encode(), "text/html; charset=utf-8"
            elif path == "/status":
                data.pop("frame")
                body, mime = json.dumps(data).encode(), "application/json"
            elif path == "/frame.jpg" and data["frame"]:
                body, mime = data["frame"], "image/jpeg"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    threading.Thread(target=capture_loop, daemon=True).start()
    print(f"Camera Web View: http://127.0.0.1:{http_port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", http_port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--http-port", type=int, default=8765)
    args = parser.parse_args()
    run(args.port, args.http_port)

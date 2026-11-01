#!/usr/bin/env python3
"""Bounded device-to-LJYD chat bridge. No browser credentials enter firmware.

The merchant chat contract is observed in LJYD's official web application;
physical-device routing remains a deployment acceptance test.
"""
import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 4096
MAX_PROMPT_BYTES = 1023
EVENT_ID = re.compile(r"[0-9a-f]{16}-[1-9][0-9]{0,9}\Z")


class BridgeError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


@dataclass(frozen=True)
class Device:
    token: str
    pid: int
    did: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LjydChat:
    def __init__(self, token, environment="prod", opener=None):
        if not token or any(c in token for c in "\r\n"):
            raise ValueError("Set LJYD_MERCHANT_TOKEN to a valid merchant credential")
        host = {"prod": "api", "test": "api-test", "dev": "api-dev"}[environment]
        self.url = f"https://{host}.ljyd.cn/agent-merchant/agora/sendEvent"
        self.token = token
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def __call__(self, device, prompt):
        # Official AssistantList-Y9y655oE.js uses this GET query and tests ok.
        query = urllib.parse.urlencode({"pid": device.pid, "did": device.did,
                                      "event": "chat", "content": prompt})
        request = urllib.request.Request(self.url + "?" + query,
                                        headers={"Authorization": self.token,
                                                 "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=12) as response:
                raw = response.read(32769)
                if response.status != 200 or len(raw) > 32768:
                    raise BridgeError(502, "upstream_rejected")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get("ok") is not True:
                    raise BridgeError(502, "upstream_rejected")
        except BridgeError:
            raise
        except (OSError, ValueError, urllib.error.URLError):
            # No retry: the platform may have accepted the request before the
            # connection failed. Never expose a URL containing the prompt.
            raise BridgeError(502, "upstream_unconfirmed") from None


class Bridge:
    def __init__(self, devices, send_chat, clock=time.monotonic, capacity=1024, ttl=3600):
        if not devices or len({d.token for d in devices}) != len(devices):
            raise ValueError("Configure devices with unique bridge tokens")
        self.devices, self.send_chat, self.clock = devices, send_chat, clock
        self.capacity, self.ttl = capacity, ttl
        self.lock = threading.Lock()
        self.requests = {}
        self.busy = set()

    def submit(self, authorization, payload):
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not token.isascii():
            raise BridgeError(401, "unauthorized")
        device = next((d for d in self.devices if hmac.compare_digest(d.token, token)), None)
        if device is None:
            raise BridgeError(401, "unauthorized")
        if not isinstance(payload, dict) or set(payload) != {"event_id", "prompt"}:
            raise BridgeError(400, "invalid_request")
        event_id, prompt = payload["event_id"], payload["prompt"]
        if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
            raise BridgeError(400, "invalid_event_id")
        try:
            encoded = prompt.encode("utf-8") if isinstance(prompt, str) else b""
        except UnicodeError:
            raise BridgeError(400, "invalid_prompt") from None
        if (not isinstance(prompt, str) or not prompt.strip() or
                len(encoded) > MAX_PROMPT_BYTES or "\x00" in prompt):
            raise BridgeError(400, "invalid_prompt")
        digest = hashlib.sha256(encoded).digest()
        key = (device.pid, device.did, event_id)
        target = (device.pid, device.did)
        with self.lock:
            now = self.clock()
            self.requests = {k: v for k, v in self.requests.items()
                             if v[2] is None or now - v[0] < self.ttl}
            previous = self.requests.get(key)
            if previous:
                if previous[1] != digest:
                    raise BridgeError(409, "event_conflict")
                if previous[2] is None:
                    raise BridgeError(409, "in_progress")
                status, code = previous[2]
                if status != 200:
                    raise BridgeError(status, code)
                return {"accepted": True, "event_id": event_id}
            if target in self.busy:
                raise BridgeError(409, "device_busy")
            if len(self.requests) >= self.capacity:
                raise BridgeError(503, "capacity")
            self.requests[key] = (now, digest, None)
            self.busy.add(target)
        status, code = 200, "accepted"
        try:
            self.send_chat(device, prompt)
        except BridgeError as error:
            status, code = error.status, error.code
        except Exception:
            status, code = 502, "upstream_unconfirmed"
        finally:
            with self.lock:
                self.requests[key] = (self.clock(), digest, (status, code))
                self.busy.discard(target)
        if status != 200:
            raise BridgeError(status, code)
        return {"accepted": True, "event_id": event_id}


def handler_for(bridge):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass  # Never log authorization, prompt query strings or payloads.

        def reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(200 if self.path == "/healthz" else 404,
                       {"status": "ready"} if self.path == "/healthz" else {"error": "not_found"})

        def do_POST(self):
            try:
                if self.path != "/v1/gesture":
                    raise BridgeError(404, "not_found")
                if self.headers.get("Transfer-Encoding"):
                    raise BridgeError(400, "invalid_request")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise BridgeError(400, "invalid_request") from None
                if not 0 < length <= MAX_BODY:
                    raise BridgeError(413, "body_size")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise BridgeError(400, "invalid_request")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise BridgeError(400, "invalid_json") from None
                self.reply(200, bridge.submit(self.headers.get("Authorization", ""), payload))
            except BridgeError as error:
                self.reply(error.status, {"accepted": False, "error": error.code})
            except (OSError, UnicodeError):
                self.close_connection = True
    return Handler


def create_server(bridge, bind="127.0.0.1", port=8787, allow_insecure_local_http=False):
    """HTTP is loopback-only unless local IPv4 testing is explicitly enabled."""
    if bind == "localhost":
        bind = "127.0.0.1"
    try:
        address = ipaddress.IPv4Address(bind)
    except ipaddress.AddressValueError:
        raise ValueError("HTTP bridge bind must be a literal local IPv4 address") from None
    local_networks = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                      ipaddress.ip_network("192.168.0.0/16"))
    if not address.is_loopback and not (allow_insecure_local_http and
                                        any(address in network for network in local_networks)):
        raise ValueError("Non-loopback HTTP requires --allow-insecure-local-http and an RFC1918 bind address")
    return ThreadingHTTPServer((str(address), port), handler_for(bridge))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--allow-insecure-local-http", action="store_true",
                        help="Allow plaintext HTTP on one explicit RFC1918 IPv4 address for LAN testing")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as file:
        config = json.load(file)
    devices = []
    for item in config["devices"]:
        token = os.environ.get(item["token_env"], "")
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("Bridge device token must be >=32 ASCII characters without whitespace")
        if type(item["pid"]) is not int or item["pid"] <= 0 or not item["did"]:
            raise ValueError("Device pid/did must identify the physical device, not the agent draft")
        devices.append(Device(token, item["pid"], item["did"]))
    chat = LjydChat(os.environ.get("LJYD_MERCHANT_TOKEN", ""), config.get("environment", "prod"))
    server = create_server(Bridge(devices, chat), args.bind, args.port, args.allow_insecure_local_http)
    print(f"Gesture bridge listening on http://{args.bind}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

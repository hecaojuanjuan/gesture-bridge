import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from gesture_agent_bridge import Bridge, BridgeError, Device, LjydChat, handler_for


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.device = Device("x" * 32, 123, "test-device")
        self.bridge = Bridge([self.device], lambda d, p: self.calls.append((d, p)))
        self.payload = {"event_id": "0123456789abcdef-1", "prompt": "用户表达：我想喝水。"}
        self.auth = "Bearer " + self.device.token

    def test_submit_dedup_and_conflict(self):
        for _ in range(2): self.assertTrue(self.bridge.submit(self.auth, self.payload)["accepted"])
        self.assertEqual(self.calls, [(self.device, self.payload["prompt"])])
        with self.assertRaises(BridgeError) as error:
            self.bridge.submit(self.auth, {**self.payload, "prompt": "different"})
        self.assertEqual(error.exception.status, 409)

    def test_reject_auth_invalid_body_and_target_override(self):
        for auth, payload in [("", self.payload), ("Bearer wrong", self.payload),
                              (self.auth, {**self.payload, "did": "other"}),
                              (self.auth, {**self.payload, "prompt": "中" * 342}),
                              (self.auth, {**self.payload, "event_id": "bad"})]:
            with self.assertRaises(BridgeError): self.bridge.submit(auth, payload)
        self.assertEqual(self.calls, [])

    def test_timeout_never_replays(self):
        def uncertain(d, p):
            self.calls.append((d, p)); raise TimeoutError()
        self.bridge.send_chat = uncertain
        for _ in range(2):
            with self.assertRaises(BridgeError) as error: self.bridge.submit(self.auth, self.payload)
            self.assertEqual(error.exception.code, "upstream_unconfirmed")
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_requests_do_not_duplicate_or_overlap(self):
        entered, release = threading.Event(), threading.Event()
        def wait(d, p): self.calls.append((d, p)); entered.set(); release.wait(3)
        self.bridge.send_chat = wait
        thread = threading.Thread(target=self.bridge.submit, args=(self.auth, self.payload))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            for payload in (self.payload, {**self.payload, "event_id": "0123456789abcdef-2"}):
                with self.assertRaises(BridgeError): self.bridge.submit(self.auth, payload)
        finally: release.set(); thread.join(3)
        self.assertEqual(len(self.calls), 1)

    def test_capacity_and_expiry(self):
        now = [0]
        self.bridge.capacity = 1; self.bridge.clock = lambda: now[0]
        self.bridge.submit(self.auth, self.payload)
        second = {**self.payload, "event_id": "0123456789abcdef-2"}
        with self.assertRaises(BridgeError): self.bridge.submit(self.auth, second)
        now[0] = 3601
        self.assertTrue(self.bridge.submit(self.auth, second)["accepted"])

    def test_real_local_http_roundtrip(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/v1/gesture"
            request = urllib.request.Request(url, json.dumps(self.payload).encode(),
                                             {"Authorization": self.auth, "Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response), {"accepted": True, "event_id": self.payload["event_id"]})
        finally: server.shutdown(); thread.join(); server.server_close()


class UpstreamTests(unittest.TestCase):
    def test_official_chat_request_and_strict_success(self):
        class Response:
            status = 200
            body = b'{"ok":true}'
            def read(self, limit): return self.body[:limit]
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            request = None
            def open(self, request, timeout): self.request = request; return Response()
        opener = Opener()
        chat = LjydChat("merchant-test-token", opener=opener)
        chat(Device("ignored", 11785, "physical-device"), "中文 prompt & ?")
        self.assertEqual(opener.request.get_header("Authorization"), "merchant-test-token")
        parsed = urllib.parse.urlsplit(opener.request.full_url)
        self.assertEqual(parsed.path, "/agent-merchant/agora/sendEvent")
        self.assertEqual(urllib.parse.parse_qs(parsed.query),
                         {"pid": ["11785"], "did": ["physical-device"], "event": ["chat"],
                          "content": ["中文 prompt & ?"]})
        for body in (b'{"ok":false}', b'{"ok":"true"}', b'{}', b'not-json'):
            Response.body = body
            with self.assertRaises(BridgeError): chat(Device("ignored", 1, "d"), "text")


if __name__ == "__main__": unittest.main()

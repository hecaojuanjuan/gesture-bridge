import assert from "node:assert/strict";
import test from "node:test";
import "./camera-protocol.js";

const { decodeRgb565, fnv1a, SnapshotParser } = globalThis.CameraProtocol;

test("FNV-1a matches the standard single-byte vector", () => {
  assert.equal(fnv1a(new TextEncoder().encode("a")), 0xe40c292c);
});

test("RGB565 decodes primary colors and rotates clockwise", () => {
  const bytes = Uint8Array.of(0x00, 0xf8, 0xe0, 0x07);
  const image = decodeRgb565(bytes, 2, 1, true);
  assert.equal(image.width, 1);
  assert.equal(image.height, 2);
  assert.deepEqual(Array.from(image.pixels), [
    255, 0, 0, 255,
    0, 255, 0, 255,
  ]);
});

test("snapshot parser validates chunk order, length, and checksum", () => {
  const bytes = Uint8Array.of(0x00, 0xf8, 0xe0, 0x07, 0x1f, 0x00, 0xff, 0xff);
  const parser = new SnapshotParser();
  assert.deepEqual(parser.feed("HVCAM WAIT"), { type: "wait" });
  parser.feed("HVCAM BEGIN 2 2 8 123 0");
  parser.feed("HVCAM DATA 0 " + Buffer.from(bytes.subarray(0, 4)).toString("hex"));
  parser.feed("HVCAM DATA 4 " + Buffer.from(bytes.subarray(4)).toString("hex"));
  const frame = parser.feed("HVCAM END " + fnv1a(bytes).toString(16).padStart(8, "0"));
  assert.equal(frame.type, "frame");
  assert.deepEqual(Array.from(frame.pixels), [
    255, 0, 0, 255, 0, 255, 0, 255,
    0, 0, 255, 255, 255, 255, 255, 255,
  ]);
});

test("snapshot parser rejects missing chunks and corrupted checksums", () => {
  const missing = new SnapshotParser();
  missing.feed("HVCAM BEGIN 2 2 8 123 0");
  assert.throws(() => missing.feed("HVCAM DATA 4 00000000"), /数据块/);

  const corrupted = new SnapshotParser();
  corrupted.feed("HVCAM BEGIN 2 2 8 123 0");
  corrupted.feed("HVCAM DATA 0 0000000000000000");
  assert.throws(() => corrupted.feed("HVCAM END 00000000"), /校验/);
});

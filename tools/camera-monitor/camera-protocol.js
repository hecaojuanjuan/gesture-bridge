(() => {
  const MAX_DIMENSION = 320;

  function fnv1a(bytes) {
    let hash = 0x811c9dc5;
    for (const byte of bytes) hash = Math.imul(hash ^ byte, 0x01000193) >>> 0;
    return hash;
  }

  function decodeRgb565(bytes, width, height, rotateCw90) {
    if (bytes.length !== width * height * 2) {
      throw new Error("像素数据长度与图像尺寸不符");
    }

    const outputWidth = rotateCw90 ? height : width;
    const outputHeight = rotateCw90 ? width : height;
    const pixels = new Uint8ClampedArray(outputWidth * outputHeight * 4);

    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const source = (y * width + x) * 2;
        const color = bytes[source] | (bytes[source + 1] << 8);
        const targetX = rotateCw90 ? height - 1 - y : x;
        const targetY = rotateCw90 ? x : y;
        const target = (targetY * outputWidth + targetX) * 4;
        pixels[target] = (((color >> 11) & 31) * 255) / 31;
        pixels[target + 1] = (((color >> 5) & 63) * 255) / 63;
        pixels[target + 2] = ((color & 31) * 255) / 31;
        pixels[target + 3] = 255;
      }
    }

    return { width: outputWidth, height: outputHeight, pixels };
  }

  class SnapshotParser {
    constructor() {
      this.expectedLength = 0;
      this.received = 0;
      this.bytes = null;
      this.header = null;
    }

    feed(line) {
      if (line === "HVCAM WAIT") return { type: "wait" };
      if (line === "HVCAM BUSY") return { type: "busy" };

      if (line.startsWith("HVCAM ERROR ")) {
        const detail = line.slice("HVCAM ERROR ".length);
        const message = detail === "no_complete_frame"
          ? "10 秒内没有采到完整图像，请检查摄像头连接和取流状态。"
          : detail.startsWith("conversion_")
            ? "摄像头图像格式转换失败：" + detail.slice("conversion_".length)
            : "设备返回错误：" + detail;
        throw new Error(message);
      }

      if (line.startsWith("HVCAM BEGIN ")) {
        if (this.expectedLength) throw new Error("收到重复的图像头");
        const values = line.slice("HVCAM BEGIN ".length).split(" ").map(Number);
        if (values.length !== 5 || values.some((value) => !Number.isSafeInteger(value))) {
          throw new Error("图像头格式无效");
        }
        const [width, height, length, capturedMs, rotation] = values;
        if (
          width < 1 || width > MAX_DIMENSION ||
          height < 1 || height > MAX_DIMENSION ||
          length !== width * height * 2 || capturedMs < 0 ||
          (rotation !== 0 && rotation !== 1)
        ) {
          throw new Error("图像尺寸或格式不受支持");
        }
        this.expectedLength = length;
        this.bytes = new Uint8Array(length);
        this.header = { width, height, capturedMs, rotateCw90: rotation === 1 };
        return { type: "begin", length };
      }

      if (line.startsWith("HVCAM DATA ")) {
        const match = /^HVCAM DATA (\d+) ([0-9a-fA-F]+)$/.exec(line);
        if (!this.expectedLength || !match || match[2].length % 2 !== 0) {
          throw new Error("图像数据块格式无效");
        }
        const offset = Number(match[1]);
        const hex = match[2];
        const chunkLength = hex.length / 2;
        if (
          hex.length > 512 || offset !== this.received ||
          offset + chunkLength > this.expectedLength
        ) {
          throw new Error("图像数据块缺失、重复或越界");
        }
        for (let i = 0; i < chunkLength; i += 1) {
          this.bytes[offset + i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
        }
        this.received += chunkLength;
        return { type: "progress", received: this.received, total: this.expectedLength };
      }

      if (line.startsWith("HVCAM END ")) {
        const match = /^HVCAM END ([0-9a-fA-F]{8})$/.exec(line);
        if (!this.expectedLength || !match || this.received !== this.expectedLength) {
          throw new Error("收到不完整的图像帧");
        }
        const checksum = Number.parseInt(match[1], 16) >>> 0;
        if (fnv1a(this.bytes) !== checksum) throw new Error("帧校验失败");
        const image = decodeRgb565(
          this.bytes,
          this.header.width,
          this.header.height,
          this.header.rotateCw90,
        );
        return {
          type: "frame",
          ...this.header,
          ...image,
          checksum: checksum.toString(16).padStart(8, "0"),
        };
      }

      return null;
    }
  }

  globalThis.CameraProtocol = { fnv1a, decodeRgb565, SnapshotParser };
})();

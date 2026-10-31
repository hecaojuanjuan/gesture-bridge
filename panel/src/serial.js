import {CameraSnapshotParser} from './camera.mjs';
import {JpegSnapshotParser,decodeJpegFrame} from './jpeg.mjs';
import {parsePose} from './protocol.mjs';
import {parseHand} from './hand.mjs';

export async function connectSerial(onReport, onLost, {onPose,onHand,onReset,decodeJpeg=decodeJpegFrame}={}) {
  if (!navigator.serial) throw Error('此浏览器不支持串口，请使用桌面版 Chrome。');
  const port = await navigator.serial.requestPort();
  await port.open({baudRate: 115200, bufferSize: 8192});
  let closing = false, disconnected = false, buffer = '', reader, writing = Promise.resolve();
  let snapshot = null, cameraFailed = false, closeTask;
  function failSnapshot(current, message) {
    if (!current || snapshot!==current) return;
    snapshot=null; cameraFailed=true; clearTimeout(current.timer);
    current.reject(Error(`${message}；请断开 USB 连接后重连，再读取图像。`));
  }
  function snapshotExpired(current) {
    if (performance.now()-current.startedAt<25000) return false;
    failSnapshot(current,'25 秒内未收到完整且已授权的图像');
    return true;
  }
  function publishFrame(current,frame) {
    if(snapshot!==current || closing || disconnected || snapshotExpired(current)) return;
    snapshot=null; clearTimeout(current.timer);
    current.resolve({...frame,transferMs:Math.max(0,performance.now()-current.startedAt)});
  }
  async function decodeFrame(current,encoded) {
    // Do not block the serial reader while the browser decodes. A reset, close
    // or timeout can retire this request, and must also retire the decode result.
    current.accepting=false;
    try {
      const frame=await decodeJpeg(encoded);
      if(frame.width!==encoded.width || frame.height!==encoded.height ||
          frame.capturedMs!==encoded.capturedMs || !(frame.rgba instanceof Uint8ClampedArray) ||
          frame.rgba.length!==encoded.width*encoded.height*4)
        throw Error('JPEG 解码结果无效');
      publishFrame(current,frame);
    } catch(e) {failSnapshot(current,`JPEG 解码失败：${e.message}`);}
  }
  function write(command,beforeWrite) {
    if (closing || disconnected) return Promise.reject(Error('串口已断开'));
    const job=writing.then(async()=>{
      if (closing || disconnected) throw Error('串口已断开');
      beforeWrite?.();
      const writer=port.writable.getWriter();
      try { await writer.write(new TextEncoder().encode(command)); }
      finally { writer.releaseLock(); }
    });
    // HP and camera commands share one queue, never simultaneous writer locks.
    writing=job.catch(()=>{});
    return job;
  }
  const done = (async () => {
    const decoder = new TextDecoder();
    let failure = '串口已断开';
    try {
      reader = port.readable.getReader();
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        let index;
        while ((index = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
          if (/(?:ESP-ROM:esp32s3|(?:^|\s)rst:0x[0-9a-f]+)/i.test(line)) {
            failSnapshot(snapshot,'设备在取帧期间重新启动，图像已丢弃');
            onReset?.('检测到设备重新启动');
          }
          const start = line.indexOf('HP {');
          if (start >= 0) onReport(line.slice(start + 3).trim());
          const poseStart=line.indexOf('HV {');
          if (poseStart>=0 && onPose) {
            const pose=parsePose(line.slice(poseStart+3).trim());
            if (pose) onPose(pose);
          }
          const handStart=line.indexOf('HG {');
          if(handStart>=0 && onHand) {
            const hand=parseHand(line.slice(handStart+3).trim());
            if(hand) onHand(hand);
          }
          const cameraStart=snapshot ? line.indexOf(snapshot.protocol+' ') : -1;
          if (cameraStart>=0 && snapshot?.accepting) {
            const current=snapshot;
            // Background tabs can delay setTimeout: enforce the deadline on
            // arrival too, before a late END/WAIT can publish an old image.
            if (snapshotExpired(current)) continue;
            try {
              const frame=current.parser.feed(line.slice(cameraStart).trim());
              if (frame) {
                if(current.protocol==='HVJPEG') void decodeFrame(current,frame);
                else publishFrame(current,frame);
              }
            } catch(e) { failSnapshot(current,e.message); }
          }
        }
        if (buffer.length > 8192) buffer = ''; // Bound partial/noisy input.
      }
    } catch (e) { failure = e.message; }
    finally {
      disconnected=true;
      failSnapshot(snapshot,'串口已断开，图像读取已取消');
      reader?.releaseLock(); reader = undefined;
      if (!closing) onLost(failure);
    }
  })();
  return {
    name: 'USB 串口',
    send(wire) {
      return write(`hv_panel ${wire}\r\n`);
    },
    snapshot({onProgress,source='camera'}={}) {
      if (closing || disconnected) return Promise.reject(Error('串口已断开'));
      if(source!=='camera' && source!=='inputjpeg') return Promise.reject(Error('不支持的画面来源'));
      if (snapshot) return Promise.reject(Error('正在读取图像，请等待当前帧完成。'));
      if (cameraFailed) return Promise.reject(Error('上次图像读取未完成，请断开 USB 连接后重连。'));
      return new Promise((resolve,reject)=>{
        const jpeg=source==='inputjpeg';
        const current={parser:jpeg ? new JpegSnapshotParser(onProgress) : new CameraSnapshotParser(onProgress),
          protocol:jpeg ? 'HVJPEG' : 'HVCAM',resolve,reject,
          startedAt:performance.now()};
        snapshot=current;
        current.timer=setTimeout(()=>failSnapshot(current,'25 秒内未收到完整且已授权的图像'),25000);
        void write(`hv_camera ${jpeg ? 'inputjpeg' : 'snapshot'}\r\n`,()=>{
          if (snapshot!==current) throw Error('图像请求已取消');
          if (snapshotExpired(current)) throw Error('图像请求已超时');
          current.accepting=true;
        }).catch(e=>failSnapshot(current,`图像指令发送失败：${e.message}`));
      });
    },
    close() {
      if (closeTask) return closeTask;
      closing = true;
      failSnapshot(snapshot,'连接已关闭，图像读取已取消');
      closeTask=(async()=>{
        await reader?.cancel(); await done;
        // SerialPort.close rejects while either stream is locked.
        await writing;
        await port.close();
      })();
      return closeTask;
    }
  };
}

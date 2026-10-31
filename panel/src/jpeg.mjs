// HVJPEG v1 carries the already-oriented model input. Check the source,
// authorization, byte checksum and encoded dimensions before browser decoding.
const MAX_BYTES=240*320*2+4096;
const integer=(n,min,max)=>Number.isSafeInteger(n) && n>=min && n<=max;

export function jpegDimensions(data) {
  if (data.length<4 || data[0]!==255 || data[1]!==216 ||
      data.at(-2)!==255 || data.at(-1)!==217) throw Error('JPEG 起止标记无效');
  const sof=new Set([192,193,194,195,197,198,199,201,202,203,205,206,207]);
  let offset=2;
  while(offset<data.length) {
    if(data[offset]!==255) throw Error('JPEG 标记无效');
    while(data[offset]===255) offset++;
    if(offset>=data.length) break;
    const marker=data[offset++];
    if(marker===218 || marker===217) break;
    if(marker===1 || (marker>=208 && marker<=215)) continue;
    if(offset+2>data.length) throw Error('JPEG 标记不完整');
    const length=(data[offset]<<8)|data[offset+1];
    if(length<2 || offset+length>data.length) throw Error('JPEG 标记长度无效');
    if(sof.has(marker)) {
      if(length<8) throw Error('JPEG 尺寸段无效');
      return {width:(data[offset+5]<<8)|data[offset+6],
        height:(data[offset+3]<<8)|data[offset+4]};
    }
    offset+=length;
  }
  throw Error('JPEG 缺少图像尺寸');
}

export class JpegSnapshotParser {
  constructor(onProgress,expectedSource='model') {
    this.onProgress=onProgress; this.expectedSource=expectedSource;
    this.authorized=false; this.verified=false; this.source=null;
    this.received=0; this.checksum=2166136261;
  }
  progress() {
    try {this.onProgress?.({received:this.received,total:this.data?.length ?? 0});} catch {}
  }
  feed(line) {
    if(!line.startsWith('HVJPEG ')) return null;
    if(line==='HVJPEG BUSY') throw Error('设备正在导出另一帧');
    if(line.startsWith('HVJPEG ERROR ')) throw Error('摄像头未完成取帧：'+line.slice(13));
    if(line==='HVJPEG WAIT') {
      if(this.authorized) throw Error('收到重复的图像请求授权');
      this.authorized=true;
    } else if(line.startsWith('HVJPEG SOURCE ')) {
      if(this.source!==null || line.slice(14)!==this.expectedSource)
        throw Error('JPEG 图像来源未经确认');
      this.source=line.slice(14);
    } else if(line.startsWith('HVJPEG BEGIN ')) {
      const match=/^HVJPEG BEGIN 1 (\d+) (\d+) (\d+) (\d+) 0 (\d+)$/.exec(line);
      if(this.data || !match || this.source!==this.expectedSource)
        throw Error('JPEG 头部、方向或来源无效');
      const [width,height,length,capturedMs,quality]=match.slice(1).map(Number);
      if(!integer(width,1,320) || !integer(height,1,320) ||
          !integer(length,1,MAX_BYTES) || !integer(capturedMs,0,Number.MAX_SAFE_INTEGER) ||
          !integer(quality,1,100)) throw Error('JPEG 尺寸、长度或时间戳无效');
      Object.assign(this,{width,height,capturedMs,quality,data:new Uint8Array(length)});
      this.progress();
    } else if(line.startsWith('HVJPEG DATA ')) {
      const match=/^HVJPEG DATA (\d+) ([A-Za-z0-9+/]+={0,2})$/.exec(line);
      if(!this.data || this.verified || !match || match[2].length>256 || match[2].length%4)
        throw Error('JPEG 数据块顺序或格式错误');
      let bytes;
      try {
        bytes=atob(match[2]);
        if(btoa(bytes)!==match[2]) throw Error('noncanonical');
      } catch {throw Error('JPEG base64 数据无效');}
      const offset=Number(match[1]);
      if(!bytes.length || offset!==this.received || offset+bytes.length>this.data.length)
        throw Error('JPEG 数据块缺失、重复或超长');
      for(let i=0;i<bytes.length;i++) {
        const value=bytes.charCodeAt(i);
        this.data[this.received++]=value;
        this.checksum=Math.imul(this.checksum^value,16777619)>>>0;
      }
      this.progress();
    } else if(line.startsWith('HVJPEG END ')) {
      const match=/^HVJPEG END ([0-9a-fA-F]{8})$/.exec(line);
      if(!this.data || this.verified || !match || this.received!==this.data.length ||
          this.checksum!==parseInt(match[1],16)) throw Error('JPEG 不完整或校验失败');
      const size=jpegDimensions(this.data);
      if(size.width!==this.width || size.height!==this.height) throw Error('JPEG 像素尺寸与头部不一致');
      this.verified=true;
    } else throw Error('无法识别的 JPEG 协议消息');
    return this.authorized && this.verified ? this.frame() : null;
  }
  frame() {
    if(!this.authorized || !this.verified) throw Error('JPEG 尚未完成授权和校验');
    return {width:this.width,height:this.height,capturedMs:this.capturedMs,
      jpeg:this.data,quality:this.quality,encoding:'jpeg'};
  }
}

export async function decodeJpegFrame(frame) {
  if(typeof globalThis.createImageBitmap!=='function') throw Error('浏览器无法解码 JPEG 画面');
  const bitmap=await createImageBitmap(new Blob([frame.jpeg],{type:'image/jpeg'}),{imageOrientation:'none'});
  try {
    if(bitmap.width!==frame.width || bitmap.height!==frame.height)
      throw Error('JPEG 解码尺寸与头部不一致');
    const canvas=typeof OffscreenCanvas==='function'
      ? new OffscreenCanvas(frame.width,frame.height) : document.createElement('canvas');
    canvas.width=frame.width; canvas.height=frame.height;
    const context=canvas.getContext('2d');
    if(!context) throw Error('浏览器无法绘制 JPEG 画面');
    context.drawImage(bitmap,0,0);
    const rgba=context.getImageData(0,0,frame.width,frame.height).data;
    return {width:frame.width,height:frame.height,rgba,capturedMs:frame.capturedMs,encoding:'jpeg'};
  } finally {bitmap.close();}
}

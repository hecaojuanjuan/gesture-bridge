// HVCAM is a local, single-frame RGB565LE protocol without request IDs.
// A frame is publishable only after WAIT authorization and a verified END.
export class CameraSnapshotParser {
  constructor(onProgress) {
    this.onProgress=onProgress;
    this.authorized=false;
    this.started=false;
    this.complete=false;
    this.received=0;
    this.checksum=2166136261;
  }
  progress() {
    // A UI observer must not interrupt serial parsing or corrupt a frame.
    try { this.onProgress?.({received:this.received,total:this.data?.length ?? 0}); } catch {}
  }
  feed(line) {
    if (!line.startsWith('HVCAM ')) return null;
    if (/^HVCAM ready(?:\s|$)/.test(line)) return null;
    if (line==='HVCAM BUSY') throw Error('设备正在导出另一帧');
    if (line.startsWith('HVCAM ERROR ')) throw Error(`摄像头未完成取帧：${line.slice(12)}`);
    if (line==='HVCAM WAIT') {
      if (this.authorized) throw Error('收到重复的图像请求授权');
      this.authorized=true;
    } else if (line.startsWith('HVCAM BEGIN ')) {
      const match=/^HVCAM BEGIN (\d+) (\d+) (\d+) (\d+) ([01])$/.exec(line);
      if (this.started || !match) throw Error('图像头部顺序或格式错误');
      const [width,height,length,captured,rotation]=match.slice(1).map(Number);
      if (!Number.isInteger(width) || width<1 || width>320 ||
          !Number.isInteger(height) || height<1 || height>320 ||
          length!==width*height*2 || !Number.isInteger(captured) ||
          captured<0 || captured>4294967295) throw Error('图像尺寸或时间戳无效');
      this.started=true;
      this.width=width; this.height=height; this.capturedMs=captured; this.rotation=rotation;
      this.data=new Uint8Array(length);
      this.progress();
    } else if (line.startsWith('HVCAM DATA ')) {
      const match=/^HVCAM DATA (\d+) ([0-9a-fA-F]+)$/.exec(line);
      if (!this.started || this.complete || !match || match[2].length%2 || match[2].length>256)
        throw Error('图像数据块顺序或格式错误');
      const offset=Number(match[1]), count=match[2].length/2;
      if (offset!==this.received || count+offset>this.data.length)
        throw Error('图像数据块缺失、重复或超长');
      for(let i=0;i<count;i++) {
        const value=parseInt(match[2].slice(i*2,i*2+2),16);
        this.data[this.received++]=value;
        this.checksum=Math.imul(this.checksum^value,16777619)>>>0;
      }
      this.progress();
    } else if (line.startsWith('HVCAM END ')) {
      const match=/^HVCAM END ([0-9a-fA-F]{8})$/.exec(line);
      if (!this.started || this.complete || !match || this.received!==this.data.length ||
          this.checksum!==parseInt(match[1],16)) throw Error('图像不完整或校验失败');
      this.complete=true;
    } else {
      throw Error('无法识别的图像协议消息');
    }
    // Firmware emits WAIT through the CLI after releasing its state lock;
    // BEGIN/DATA/END can therefore arrive before WAIT. Never reset that data.
    return this.authorized && this.complete ? this.frame() : null;
  }
  frame() {
    if (!this.authorized || !this.complete) throw Error('图像尚未完成授权和校验');
    const width=this.rotation ? this.height : this.width;
    const height=this.rotation ? this.width : this.height;
    const rgba=new Uint8ClampedArray(width*height*4);
    for(let y=0;y<this.height;y++) for(let x=0;x<this.width;x++) {
      const source=(y*this.width+x)*2, value=this.data[source]|(this.data[source+1]<<8);
      const dx=this.rotation ? this.height-1-y : x, dy=this.rotation ? x : y;
      const dest=(dy*width+dx)*4;
      rgba[dest]=Math.floor(((value>>11)&31)*255/31);
      rgba[dest+1]=Math.floor(((value>>5)&63)*255/63);
      rgba[dest+2]=Math.floor((value&31)*255/31);
      rgba[dest+3]=255;
    }
    return {width,height,rgba,capturedMs:this.capturedMs};
  }
}

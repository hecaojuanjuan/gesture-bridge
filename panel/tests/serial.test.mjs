import {test} from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate} from 'node:timers/promises';
import {connectSerial} from '../src/serial.js';
import {jpegWire,decodedFrame} from './jpeg-fixture.mjs';

function fixture(t, write) {
  let input, closed = false;
  const output = [];
  const port = {
    readable: new ReadableStream({start(c) {input = c;}}),
    writable: new WritableStream({async write(bytes) {
      output.push(new TextDecoder().decode(bytes)); await write?.();
    }}),
    async open(options) {assert.equal(options.baudRate, 115200);},
    async close() {
      assert.equal(this.readable.locked, false);
      assert.equal(this.writable.locked, false);
      closed = true;
    }
  };
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {configurable: true,
    value: {serial: {async requestPort() {return port;}}}});
  t.after(() => descriptor ? Object.defineProperty(globalThis, 'navigator', descriptor)
    : delete globalThis.navigator);
  return {input, output, closed: () => closed};
}

test('real serial adapter parses split HP lines and writes the CLI wire format', async t => {
  const f = fixture(t), reports = [], lost = [];
  const connection = await connectSerial(r => reports.push(r), e => lost.push(e));
  const encode = s => new TextEncoder().encode(s);
  f.input.enqueue(encode('boot noise\r\n# HP {"id":'));
  f.input.enqueue(encode('7}\r\nHP {"id":8}\n'));
  await setImmediate();
  assert.deepEqual(reports, ['{"id":7}', '{"id":8}']);
  await connection.send('7 get');
  assert.deepEqual(f.output, ['hv_panel 7 get\r\n']);
  await connection.close();
  assert.equal(f.closed(), true); assert.deepEqual(lost, []);
  await assert.rejects(connection.send('8 test'), /断开/);
});

test('read failure notifies disconnect once, then releases the port for reconnection', async t => {
  const f = fixture(t), lost = [];
  const connection = await connectSerial(() => {}, e => lost.push(e));
  f.input.error(Error('USB removed'));
  await setImmediate();
  assert.deepEqual(lost, ['USB removed']);
  await connection.close();
  assert.equal(f.closed(), true);
});

test('disconnect waits for an in-flight writer to release its lock', async t => {
  let finish;
  const f = fixture(t, () => new Promise(resolve => {finish = resolve;}));
  const connection = await connectSerial(() => {}, () => {});
  const sending = connection.send('9 test');
  await setImmediate();
  const closing = connection.close();
  await setImmediate(); assert.equal(f.closed(), false);
  finish(); await sending; await closing;
  assert.equal(f.closed(), true);
});

const encode=s=>new TextEncoder().encode(s);
const cameraFrame='HVCAM BEGIN 2 2 8 12345 1\nHVCAM DATA 0 00f8e0071f00ffff\nHVCAM END a66d049d\n';

test('one reader receives split camera lines, noise, and interleaved HP reports',async t=>{
  const f=fixture(t), reports=[], progress=[];
  const connection=await connectSerial(r=>reports.push(r),()=>{});
  t.after(()=>connection.close());
  const taking=connection.snapshot({onProgress:p=>progress.push(p)});
  await setImmediate();
  assert.deepEqual(f.output,['hv_camera snapshot\r\n']);
  f.input.enqueue(encode('boot noise\n# HVCAM WA'));
  f.input.enqueue(encode('IT\r\nHVCAM BEGIN 2 2 8 12345 1\nHP {"id":17}\nHVCAM DATA 0 00f8'));
  f.input.enqueue(encode('e0071f00ffff\nI ordinary log\nHVCAM END a66d049d\n'));
  const frame=await taking;
  assert.deepEqual(reports,['{"id":17}']);
  assert.equal(frame.width,2); assert.equal(frame.rgba.length,16);
  assert.equal(frame.capturedMs,12345); assert.ok(frame.transferMs>=0);
  assert.deepEqual(progress.at(-1),{received:8,total:8});
});

test('camera and panel writes queue without sharing a writer lock',async t=>{
  let finish;
  const f=fixture(t,()=>new Promise(resolve=>{finish=resolve;}));
  const connection=await connectSerial(()=>{},()=>{});
  t.after(()=>connection.close());
  const lighting=connection.send('9 get');
  const taking=connection.snapshot();
  await assert.rejects(connection.snapshot(),/正在读取图像/);
  await setImmediate(); assert.equal(f.output.length,1);
  finish(); await lighting; await setImmediate();
  assert.deepEqual(f.output,['hv_panel 9 get\r\n','hv_camera snapshot\r\n']);
  finish(); f.input.enqueue(encode('HVCAM WAIT\n'+cameraFrame));
  await taking;
});

test('late WAIT authorizes a verified frame without discarding it',async t=>{
  const f=fixture(t), connection=await connectSerial(()=>{},()=>{});
  t.after(()=>connection.close());
  let completed=false;
  const taking=connection.snapshot().then(frame=>{completed=true;return frame;});
  f.input.enqueue(encode(cameraFrame)); await setImmediate();
  assert.equal(completed,false);
  f.input.enqueue(encode('HVCAM WAIT\n'));
  assert.equal((await taking).rgba.length,16);
});

test('corrupt frame rejects only the image and requires reconnect before another image',async t=>{
  const f=fixture(t), reports=[], lost=[];
  const connection=await connectSerial(r=>reports.push(r),e=>lost.push(e));
  t.after(()=>connection.close());
  const taking=connection.snapshot();
  const rejected=assert.rejects(taking,/校验失败.*重连/);
  f.input.enqueue(encode('HVCAM WAIT\n'+cameraFrame.replace('a66d049d','00000000')));
  await rejected;
  f.input.enqueue(encode('HVCAM WAIT\n'+cameraFrame+'HP {"id":18}\n'));
  await assert.rejects(connection.snapshot(),/上次图像读取未完成.*重连/);
  await connection.send('18 get'); await setImmediate();
  assert.deepEqual(reports,['{"id":18}']); assert.deepEqual(lost,[]);
  assert.equal(f.output.filter(w=>w==='hv_camera snapshot\r\n').length,1);
});

test('timeout rejects a partial image and ignores its late bytes on this connection',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture(t), connection=await connectSerial(()=>{},()=>{});
  t.after(()=>connection.close());
  const taking=connection.snapshot(), rejected=assert.rejects(taking,/25 秒.*重连/);
  f.input.enqueue(encode('HVCAM WAIT\nHVCAM BEGIN 2 2 8 0 0\nHVCAM DATA 0 00f8\n'));
  await setImmediate();
  t.mock.timers.tick(25000); await rejected;
  f.input.enqueue(encode(cameraFrame)); await setImmediate();
  await assert.rejects(connection.snapshot(),/重连/);
  assert.equal(f.output.length,1);
});

test('disconnect rejects a pending image and never exposes its partial pixels',async t=>{
  const f=fixture(t), lost=[], connection=await connectSerial(()=>{},e=>lost.push(e));
  const taking=connection.snapshot(), rejected=assert.rejects(taking,/断开.*取消/);
  f.input.enqueue(encode('HVCAM WAIT\nHVCAM BEGIN 2 2 8 0 0\n'));
  f.input.error(Error('USB removed')); await rejected; await setImmediate();
  assert.deepEqual(lost,['USB removed']);
  await connection.close();
  await assert.rejects(connection.snapshot(),/断开/);
});

test('BUSY and firmware ERROR reject without accepting an existing device frame',async t=>{
  for(const terminal of ['HVCAM BUSY','HVCAM ERROR no_complete_frame']) {
    const f=fixture(t), connection=await connectSerial(()=>{},()=>{});
    const taking=connection.snapshot(), rejected=assert.rejects(taking,/重连/);
    f.input.enqueue(encode(terminal+'\nHVCAM WAIT\n'+cameraFrame)); await rejected;
    await assert.rejects(connection.snapshot(),/重连/);
    await connection.close();
  }
});

test('a queued camera command is not transmitted after its request timed out',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  let finish;
  const f=fixture(t,()=>new Promise(resolve=>{finish=resolve;}));
  const connection=await connectSerial(()=>{},()=>{});
  const lighting=connection.send('19 get');
  const taking=connection.snapshot(), rejected=assert.rejects(taking,/25 秒/);
  await setImmediate(); t.mock.timers.tick(25000); await rejected;
  finish(); await lighting; await setImmediate();
  assert.deepEqual(f.output,['hv_panel 19 get\r\n']);
  await connection.close();
});

test('a ROM startup marker cancels a frame before its remaining bytes can publish',async t=>{
  for(const marker of ['ESP-ROM:esp32s3-20210327','rst:0x1 (POWERON),boot:0x8']) {
    const f=fixture(t), connection=await connectSerial(()=>{},()=>{});
    const taking=connection.snapshot(), rejected=assert.rejects(taking,/重新启动.*丢弃.*重连/);
    f.input.enqueue(encode('HVCAM WAIT\nHVCAM BEGIN 2 2 8 0 0\n'+marker+'\n'+cameraFrame));
    await rejected;
    await assert.rejects(connection.snapshot(),/重连/);
    await connection.close();
  }
});

test('a throttled timeout callback cannot allow an over-deadline image to publish',async t=>{
  let now=0;
  t.mock.method(performance,'now',()=>now);
  const f=fixture(t), connection=await connectSerial(()=>{},()=>{});
  const taking=connection.snapshot(), rejected=assert.rejects(taking,/25 秒.*重连/);
  await setImmediate(); now=25001;
  f.input.enqueue(encode('HVCAM WAIT\n'+cameraFrame));
  await rejected; await connection.close();
});

test('USB pose callbacks require newline-complete valid JSON and leave HP handling independent',async t=>{
  const f=fixture(t), poses=[], reports=[], resets=[];
  const connection=await connectSerial(r=>reports.push(r),()=>{},
    {onPose:p=>poses.push(p),onReset:r=>resets.push(r)});
  t.after(()=>connection.close());
  const pose={event:'pose',captured_ms:1100,age_ms:120,people:0,tilt:0,
    tracking_valid:false,valid:false,infer_ms:90};
  const line='HV '+JSON.stringify(pose);
  f.input.enqueue(encode(line.slice(0,40)));await setImmediate();
  assert.equal(poses.length,0);
  f.input.enqueue(encode(line.slice(40)));await setImmediate();
  assert.equal(poses.length,0);
  f.input.enqueue(encode('\r\nHP {"id":23}\nHV {"event":"metrics"}\n'+
    'HV '+JSON.stringify({...pose,age_ms:-1})+'\n'+line+' polluted\nESP-ROM:esp32s3-20210327\n'));
  await setImmediate();
  assert.deepEqual(poses,[pose]);assert.deepEqual(reports,['{"id":23}']);
  assert.equal(resets.length,1);
});

test('JPEG requests use one serial reader for split JPEG, HG observations and HP receipts',async t=>{
  const f=fixture(t),hands=[],reports=[],progress=[];
  let decodes=0;
  const connection=await connectSerial(r=>reports.push(r),()=>{},
    {onHand:hand=>hands.push(hand),decodeJpeg:async frame=>{decodes++;return decodedFrame(frame);}});
  t.after(()=>connection.close());
  const hand={v:1,event:'observation',seq:1,captured_ms:1100,age_ms:120,epoch:0,
    width:320,height:240,hands:1,box:[70,40,170,160],detect_score:0.75,valid:true,
    classifier_ready:false,gesture:'untrained',infer_ms:100};
  const taking=connection.snapshot({source:'inputjpeg',onProgress:p=>progress.push(p)});
  await setImmediate();assert.deepEqual(f.output,['hv_camera inputjpeg\r\n']);
  const wire='HVCAM WAIT\n'+cameraFrame+'HG '+JSON.stringify(hand)+'\nHP {"id":41}\n'+jpegWire();
  f.input.enqueue(encode(wire.slice(0,70)));f.input.enqueue(encode(wire.slice(70)));
  const frame=await taking;
  assert.equal(frame.width,2);assert.equal(frame.height,1);assert.equal(frame.rgba.length,8);
  assert.equal(frame.capturedMs,12345);assert.equal(decodes,1);
  assert.equal(hands.length,1);assert.equal(hands[0].classifier_ready,false);
  assert.deepEqual(reports,['{"id":41}']);assert.ok(progress.at(-1).total>0);
});

test('JPEG decode waits for late WAIT and serial receipts continue while decoding',async t=>{
  const f=fixture(t),reports=[];let finish,encoded,decodes=0;
  const connection=await connectSerial(r=>reports.push(r),()=>{},
    {decodeJpeg:frame=>{encoded=frame;decodes++;return new Promise(resolve=>{finish=resolve;});}});
  t.after(()=>connection.close());
  const taking=connection.snapshot({source:'inputjpeg'});await setImmediate();
  f.input.enqueue(encode(jpegWire({wait:false})));await setImmediate();assert.equal(decodes,0);
  f.input.enqueue(encode('HVJPEG WAIT\nHP {"id":42}\n'));await setImmediate();
  assert.equal(decodes,1);assert.deepEqual(reports,['{"id":42}']);
  await assert.rejects(connection.snapshot(),/正在读取图像/);
  finish(decodedFrame(encoded));assert.equal((await taking).rgba.length,8);
});

test('JPEG source and encoded dimensions are rejected before decoding',async t=>{
  for(const options of [{source:'camera'},{width:3}]) {
    const f=fixture(t);let decodes=0;
    const connection=await connectSerial(()=>{},()=>{},
      {decodeJpeg:async frame=>{decodes++;return decodedFrame(frame);}});
    const taking=connection.snapshot({source:'inputjpeg'}),rejected=assert.rejects(taking,/重连/);
    await setImmediate();f.input.enqueue(encode(jpegWire(options)));await rejected;
    assert.equal(decodes,0);await connection.close();
  }
});

test('ROM reset or disconnect during JPEG decoding retires the late decode result',async t=>{
  for(const reset of [true,false]) {
    const f=fixture(t);let finish,encoded;
    const connection=await connectSerial(()=>{},()=>{},
      {decodeJpeg:frame=>{encoded=frame;return new Promise(resolve=>{finish=resolve;});}});
    let published=false;
    const taking=connection.snapshot({source:'inputjpeg'}).then(frame=>{published=true;return frame;});
    const rejected=assert.rejects(taking,/重连/);
    await setImmediate();f.input.enqueue(encode(jpegWire()));await setImmediate();
    if(reset) f.input.enqueue(encode('ESP-ROM:esp32s3-20210327\n'));
    else await connection.close();
    await rejected;finish(decodedFrame(encoded));await setImmediate();
    assert.equal(published,false);
    await assert.rejects(connection.snapshot({source:'inputjpeg'}),/重连|断开/);
    await connection.close();
  }
});

test('JPEG browser decode failure rejects the image without losing HP receipts',async t=>{
  const f=fixture(t),reports=[],lost=[];
  const connection=await connectSerial(r=>reports.push(r),e=>lost.push(e),
    {decodeJpeg:async()=>{throw Error('bad JPEG');}});
  t.after(()=>connection.close());
  const taking=connection.snapshot({source:'inputjpeg'}),rejected=assert.rejects(taking,/解码失败.*重连/);
  await setImmediate();f.input.enqueue(encode(jpegWire()+'HP {"id":43}\n'));await rejected;
  assert.deepEqual(reports,['{"id":43}']);assert.deepEqual(lost,[]);
  await assert.rejects(connection.snapshot(),/重连/);
});

test('late JPEG decoding cannot bypass a throttled timeout callback',async t=>{
  let now=0,finish,encoded;t.mock.method(performance,'now',()=>now);
  const f=fixture(t),connection=await connectSerial(()=>{},()=>{},
    {decodeJpeg:frame=>{encoded=frame;return new Promise(resolve=>{finish=resolve;});}});
  const taking=connection.snapshot({source:'inputjpeg'}),rejected=assert.rejects(taking,/25 秒.*重连/);
  await setImmediate();f.input.enqueue(encode(jpegWire()));await setImmediate();
  now=25001;finish(decodedFrame(encoded));await rejected;await connection.close();
});

test('a late JPEG decode cannot publish pixels after the timeout callback',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture(t);let finish,encoded;
  const connection=await connectSerial(()=>{},()=>{},
    {decodeJpeg:frame=>{encoded=frame;return new Promise(resolve=>{finish=resolve;});}});
  const taking=connection.snapshot({source:'inputjpeg'}),rejected=assert.rejects(taking,/25 秒.*重连/);
  await setImmediate();f.input.enqueue(encode(jpegWire()));await setImmediate();
  t.mock.timers.tick(25000);await rejected;
  finish({...decodedFrame(encoded),width:3});await setImmediate();await connection.close();
});

test('an active JPEG request rejects a decoder result with mismatched pixels or metadata',async t=>{
  for(const alter of [frame=>({...frame,width:3}),frame=>({...frame,capturedMs:2}),
    frame=>({...frame,rgba:new Uint8ClampedArray(4)})]) {
    const f=fixture(t),connection=await connectSerial(()=>{},()=>{},
      {decodeJpeg:async encoded=>alter(decodedFrame(encoded))});
    const taking=connection.snapshot({source:'inputjpeg'}),rejected=assert.rejects(taking,/解码结果无效.*重连/);
    await setImmediate();f.input.enqueue(encode(jpegWire()));await rejected;await connection.close();
  }
});

test('unknown JPEG request sources fail before any command is sent',async t=>{
  const f=fixture(t),connection=await connectSerial(()=>{},()=>{});
  await assert.rejects(connection.snapshot({source:'unexpected'}),/不支持/);
  assert.deepEqual(f.output,[]);await connection.close();
});

test('one USB reader routes split real dictionary and agent lines without inferring raw HG events',async t=>{
  const f=fixture(t),dictionary=[],agent=[],hand=[];
  const connection=await connectSerial(()=>{},()=>{},{onDictionary:r=>dictionary.push(r),onAgent:r=>agent.push(r),onHand:r=>hand.push(r)});
  t.after(()=>connection.close());
  const boot='0123456789abcdef';
  const report={v:1,boot,id:17,ok:true,code:'ok',persisted:true,max_age_ms:1000,bindings:{open_palm:'我想喝水',v_sign:''}};
  const state={v:1,boot,id:1,state:'connecting',code:0};
  const reply={...state,state:'reply',text:'用户想喝水了。',truncated:false};
  const wire='HGD '+JSON.stringify(report)+'\nHG_AGENT '+JSON.stringify(state)+'\nHG_AGENT '+JSON.stringify(reply)+'\n';
  const bytes=encode(wire);for(let i=0;i<bytes.length;i+=7)f.input.enqueue(bytes.slice(i,i+7));
  f.input.enqueue(encode('HG_AGENT {"v":1,"id":1,"state":"accepted","code":0}\nHG {"event":"gesture","gesture":"open_palm"}\n'));
  await setImmediate();assert.deepEqual(dictionary,[report]);assert.deepEqual(agent,[state,reply]);assert.deepEqual(hand,[]);
});
test('dictionary wire uses the shared writer queue and rejects injection or odd hex',async t=>{
  const f=fixture(t),connection=await connectSerial(()=>{},()=>{});t.after(()=>connection.close());
  await connection.dictionary('10 get');await connection.dictionary('11 set open_palm e68891e683b3e5969de6b0b4');await connection.dictionary('12 set v_sign -');
  assert.deepEqual(f.output,['hg_dict 10 get\r\n','hg_dict 11 set open_palm e68891e683b3e5969de6b0b4\r\n','hg_dict 12 set v_sign -\r\n']);
  for(const wire of ['1 get\nhv_panel 2 test','1 set open_palm abc','0 get','1 set other ff','1 set open_palm '+ 'ff'.repeat(181)])await assert.rejects(connection.dictionary(wire),/无效/);
});

test('explicit next-round command uses hg_dict arm on the same serial writer',async t=>{
  const f=fixture(t),connection=await connectSerial(()=>{},()=>{});t.after(()=>connection.close());
  await connection.dictionary('23 arm');assert.deepEqual(f.output,['hg_dict 23 arm\r\n']);
});

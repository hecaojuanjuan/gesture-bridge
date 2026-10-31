import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JpegSnapshotParser,jpegDimensions,decodeJpegFrame} from '../src/jpeg.mjs';
import {jpegBytes,jpegWire} from './jpeg-fixture.mjs';

function feed(parser,wire) {
  let result=null;
  for(const line of wire.trim().split('\n')) result=parser.feed(line);
  return result;
}

test('verified model JPEG preserves bytes and does not apply a second rotation',()=>{
  const progress=[], parser=new JpegSnapshotParser(p=>progress.push(p));
  assert.equal(parser.feed('ordinary boot log'),null);
  const frame=feed(parser,jpegWire());
  assert.deepEqual(jpegDimensions(frame.jpeg),{width:2,height:1});
  assert.equal(frame.capturedMs,12345); assert.equal(frame.encoding,'jpeg');
  assert.deepEqual(frame.jpeg,jpegBytes);
  assert.deepEqual(progress.at(-1),{received:jpegBytes.length,total:jpegBytes.length});
});

test('JPEG END without WAIT cannot authorize publication; late WAIT preserves verified bytes',()=>{
  const parser=new JpegSnapshotParser();
  assert.equal(feed(parser,jpegWire({wait:false})),null);
  assert.throws(()=>parser.frame(),/授权和校验/);
  assert.deepEqual(parser.feed('HVJPEG WAIT').jpeg,jpegBytes);
  assert.throws(()=>parser.feed('HVJPEG WAIT'),/重复/);
});

test('JPEG source, version, bounds and orientation must be verified before allocation',()=>{
  const headers=[
    'HVJPEG BEGIN 2 2 1 100 1 0 75',
    'HVJPEG BEGIN 1 2 1 100 1 1 75',
    'HVJPEG BEGIN 1 321 1 100 1 0 75',
    'HVJPEG BEGIN 1 2 0 100 1 0 75',
    'HVJPEG BEGIN 1 2 1 157697 1 0 75',
    'HVJPEG BEGIN 1 2 1 0 1 0 75',
    'HVJPEG BEGIN 1 2 1 100 9007199254740992 0 75',
    'HVJPEG BEGIN 1 2 1 100 1 0 0',
    'HVJPEG BEGIN 1 2 1 100 1 0 101',
    'HVJPEG BEGIN 1 2 1 100 1 0 75 extra'
  ];
  for(const header of headers) {
    const parser=new JpegSnapshotParser(); parser.feed('HVJPEG SOURCE model');
    assert.throws(()=>parser.feed(header),undefined,header);
    assert.equal(parser.data,undefined);
  }
  for(const source of ['camera','model extra'])
    assert.throws(()=>new JpegSnapshotParser().feed('HVJPEG SOURCE '+source),/来源/);
  assert.throws(()=>new JpegSnapshotParser().feed('HVJPEG BEGIN 1 2 1 100 1 0 75'),/来源/);
  const parser=new JpegSnapshotParser(); parser.feed('HVJPEG SOURCE model');
  assert.throws(()=>parser.feed('HVJPEG SOURCE model'),/来源/);
});

test('JPEG chunk gaps, noncanonical base64 and checksum corruption are rejected',()=>{
  for(const data of ['HVJPEG DATA 1 /9g=', 'HVJPEG DATA 0 A', 'HVJPEG DATA 0 /9h=',
    'HVJPEG DATA 0 AA===','HVJPEG DATA 0 !!!!','HVJPEG DATA 0 '+ 'AAAA'.repeat(65)]) {
    const parser=new JpegSnapshotParser();
    parser.feed('HVJPEG SOURCE model'); parser.feed('HVJPEG BEGIN 1 2 1 100 1 0 75');
    assert.throws(()=>parser.feed(data),undefined,data);
    assert.throws(()=>parser.frame());
  }
  for(const alter of [wire=>wire.replace('HVJPEG DATA 192','HVJPEG DATA 0'),
    wire=>wire.replace(/HVJPEG END [a-f0-9]+/,'HVJPEG END 00000000'),
    wire=>wire.replace(/HVJPEG DATA 192[^\n]*\n/,'')])
    assert.throws(()=>feed(new JpegSnapshotParser(),alter(jpegWire())));
});

test('encoded JPEG dimensions and markers are checked even when the byte hash matches',()=>{
  assert.throws(()=>feed(new JpegSnapshotParser(),jpegWire({width:3})),/尺寸/);
  for(const data of [jpegBytes.slice(1),jpegBytes.slice(0,-2),
    new Uint8Array([255,216,255,224,255,255,255,217]),
    new Uint8Array([255,216,255,218,0,0,255,217])])
    assert.throws(()=>feed(new JpegSnapshotParser(),jpegWire({data})));
});

test('JPEG errors, repeated headers and DATA after END cannot start a new frame',()=>{
  for(const line of ['HVJPEG BUSY','HVJPEG ERROR no_complete_frame','HVJPEG BOGUS'])
    assert.throws(()=>new JpegSnapshotParser().feed(line));
  const parser=new JpegSnapshotParser();
  parser.feed('HVJPEG SOURCE model'); parser.feed('HVJPEG BEGIN 1 2 1 100 1 0 75');
  assert.throws(()=>parser.feed('HVJPEG BEGIN 1 2 1 100 1 0 75'));
  const complete=new JpegSnapshotParser(); feed(complete,jpegWire({wait:false}));
  assert.throws(()=>complete.feed('HVJPEG DATA 668 AA=='));
});

test('progress observers cannot corrupt JPEG protocol processing',()=>{
  const parser=new JpegSnapshotParser(()=>{throw Error('UI observer failed');});
  assert.equal(feed(parser,jpegWire()).jpeg.length,jpegBytes.length);
});

function browserFixture(t,{width=2,height=1,context=true}={}) {
  let closed=0,drawn=0;
  const bitmap={width,height,close(){closed++;}};
  for(const [name,value] of Object.entries({
    createImageBitmap:async(blob,options)=>{
      assert.equal(blob.type,'image/jpeg');assert.deepEqual(options,{imageOrientation:'none'});
      assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),jpegBytes);return bitmap;
    },
    OffscreenCanvas:class {
      constructor(w,h){assert.equal(w,2);assert.equal(h,1);}
      getContext(kind){assert.equal(kind,'2d');return context ? {
        drawImage(image,x,y){assert.equal(image,bitmap);assert.equal(x,0);assert.equal(y,0);drawn++;},
        getImageData(x,y,w,h){assert.deepEqual([x,y,w,h],[0,0,2,1]);return {data:new Uint8ClampedArray(8)};}
      } : null;}
    }
  })) {
    const descriptor=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});
    t.after(()=>descriptor ? Object.defineProperty(globalThis,name,descriptor) : delete globalThis[name]);
  }
  return {closed:()=>closed,drawn:()=>drawn};
}

test('browser decode adapter returns RGBA and closes the bitmap',async t=>{
  const fixture=browserFixture(t), encoded=feed(new JpegSnapshotParser(),jpegWire());
  const frame=await decodeJpegFrame(encoded);
  assert.equal(frame.rgba.length,8);assert.equal(frame.capturedMs,12345);
  assert.equal(fixture.drawn(),1);assert.equal(fixture.closed(),1);
});

test('browser decode adapter rejects decoded dimension changes and still closes the bitmap',async t=>{
  const fixture=browserFixture(t,{width:3}), encoded=feed(new JpegSnapshotParser(),jpegWire());
  await assert.rejects(decodeJpegFrame(encoded),/解码尺寸/);
  assert.equal(fixture.drawn(),0);assert.equal(fixture.closed(),1);
});

test('browser decode adapter releases the bitmap if canvas creation fails',async t=>{
  const fixture=browserFixture(t,{context:false}), encoded=feed(new JpegSnapshotParser(),jpegWire());
  await assert.rejects(decodeJpegFrame(encoded),/绘制/);assert.equal(fixture.closed(),1);
});

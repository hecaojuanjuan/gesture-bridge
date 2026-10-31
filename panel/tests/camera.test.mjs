import {test} from 'node:test';
import assert from 'node:assert/strict';
import {CameraSnapshotParser} from '../src/camera.mjs';

const header='HVCAM BEGIN 2 2 8 12345 1';
const pixels='HVCAM DATA 0 00f8e0071f00ffff';
const ending='HVCAM END a66d049d';

test('RGB565LE checksum and clockwise rotation preserve pixel positions',()=>{
  const progress=[], parser=new CameraSnapshotParser(p=>progress.push(p));
  assert.equal(parser.feed('ordinary boot log'),null);
  parser.feed('HVCAM WAIT'); parser.feed(header); parser.feed(pixels);
  const frame=parser.feed(ending);
  assert.equal(frame.width,2); assert.equal(frame.height,2); assert.equal(frame.capturedMs,12345);
  assert.ok(frame.rgba instanceof Uint8ClampedArray);
  assert.deepEqual([...frame.rgba],[0,0,255,255,255,0,0,255,255,255,255,255,0,255,0,255]);
  assert.deepEqual(progress,[{received:0,total:8},{received:8,total:8}]);
});

test('WAIT can arrive after all frame bytes but is still required before publication',()=>{
  const parser=new CameraSnapshotParser();
  parser.feed(header); parser.feed(pixels);
  assert.equal(parser.feed(ending),null);
  assert.throws(()=>parser.frame(),/授权和校验/);
  const frame=parser.feed('HVCAM WAIT');
  assert.equal(frame.rgba.length,16);
});

test('clockwise rotation swaps non-square dimensions',()=>{
  const parser=new CameraSnapshotParser();
  parser.feed('HVCAM WAIT'); parser.feed('HVCAM BEGIN 2 1 4 0 1');
  parser.feed('HVCAM DATA 0 00f8e007');
  const frame=parser.feed('HVCAM END 27e41548');
  assert.equal(frame.width,1); assert.equal(frame.height,2);
  assert.deepEqual([...frame.rgba],[255,0,0,255,0,255,0,255]);
});

test('an unrotated frame retains source dimensions and RGB565LE pixel order',()=>{
  const parser=new CameraSnapshotParser();
  parser.feed('HVCAM WAIT'); parser.feed('HVCAM BEGIN 2 1 4 4294967295 0');
  parser.feed('HVCAM DATA 0 00f8e007');
  const frame=parser.feed('HVCAM END 27e41548');
  assert.equal(frame.width,2); assert.equal(frame.height,1);
  assert.equal(frame.capturedMs,4294967295);
  assert.deepEqual([...frame.rgba],[255,0,0,255,0,255,0,255]);
});

test('malformed, missing, repeated, and corrupt camera bytes never produce a frame',()=>{
  const cases=[
    ['HVCAM DATA 0 00'],
    ['HVCAM BEGIN 321 1 642 0 0'],
    ['HVCAM BEGIN 2 2 6 0 0'],
    ['HVCAM BEGIN 2 2 8 4294967296 0'],
    ['HVCAM BEGIN 2 2 8 0 2'],
    [header,header],
    [header,'HVCAM DATA 0 0'],
    [header,'HVCAM DATA 0 zz'],
    [header,'HVCAM DATA 2 00f8'],
    [header,'HVCAM DATA 0 00f8','HVCAM DATA 0 e007'],
    [header,'HVCAM DATA 0 00f8e0071f00ffff00'],
    [header,'HVCAM DATA 0 00f8 LOG noise'],
    [header,ending],
    [header,pixels,'HVCAM END 00000000'],
    [header,pixels,'HVCAM END a66d049d trailing'],
    ['HVCAM WAIT'],
    ['HVCAM BUSY'],
    ['HVCAM ERROR no_complete_frame']
  ];
  for(const lines of cases) {
    const parser=new CameraSnapshotParser(); parser.feed('HVCAM WAIT');
    assert.throws(()=>lines.forEach(line=>parser.feed(line)),undefined,lines.join(' / '));
    assert.throws(()=>parser.frame());
  }
});

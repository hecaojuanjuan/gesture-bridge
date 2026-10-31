import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseReport, parsePose, PoseStream, command, RequestTracker, poseState, resetReason, reportState} from '../src/protocol.mjs';
const draft={mode:1,brightness:20,rgb:[80,190,255]};
const valid={v:1,boot:100,id:12,ok:true,uptime_ms:20000,...draft,output:[3,7,9],test_ms:0,stage:2,
  pose:{age_ms:2700,people:1,tilt:16.7,tracking:true,valid:false,infer_ms:2676}};
test('wire command validates all controllable values',()=>{
  assert.equal(command(12,'set',draft),'12 set 1 20 80 190 255');
  for(const data of [{...draft,mode:3},{...draft,brightness:NaN},{...draft,rgb:[-1,2,3]}]) assert.throws(()=>command(12,'set',data));
});
test('send and unrelated shadow reports never establish execution',()=>{
  const t=new RequestTracker();t.begin(12,'set',draft,0);
  assert.equal(t.receive({...valid,id:11}).matched,false);
  assert.ok(t.pending);
  assert.equal(t.receive({...valid,rgb:[0,0,0]}).applied,false);
  assert.equal(t.pending,null);
});
test('only matching successful report confirms exact desired state',()=>{
  const t=new RequestTracker();t.begin(12,'set',draft,0);
  assert.equal(t.receive(JSON.stringify(valid)).applied,true);
  t.begin(13,'test',draft,0);assert.equal(t.receive({...valid,id:13,ok:false}).applied,false);
});
test('timeout reports unknown outcome, no automatic command replay',()=>{
  const t=new RequestTracker();t.begin(12,'test',draft,10);
  assert.equal(t.expire(10009),false);assert.equal(t.expire(10010),true);
  assert.equal(t.receive(valid).matched,false);
});
test('report exposes round trip for conservative camera freshness',()=>{
  const t=new RequestTracker();t.begin(12,'get',draft,100);
  assert.equal(t.receive(valid,650).roundTripMs,550);
});
test('a throttled timer cannot let a late reply confirm a timed-out command',()=>{
  const t=new RequestTracker();t.begin(12,'set',draft,100);
  assert.equal(t.receive(valid,10100).matched,false);
  assert.equal(t.expire(10100),true);
  t.begin(13,'get',draft,10200);
  assert.equal(t.receive(valid,10201).matched,false);
  assert.equal(t.pending.id,13);
});
test('malformed reports and slow inference do not appear usable',()=>{
  assert.equal(parseReport('not json'),null);
  assert.equal(parseReport({...valid,pose:null}),null);
  assert.equal(parseReport({...valid,mode:5}),null);
  assert.match(poseState(valid),/过期/);
  const fresh={...valid,pose:{...valid.pose,age_ms:250,valid:true}};
  assert.match(poseState(fresh,100),/设备报告.*仅诊断观测/);
  assert.match(poseState(fresh,401),/本页超过 400 ms 未收到新观测/);
  assert.equal(fresh.pose.age_ms,250);
  assert.match(poseState({...fresh,stage:1}),/未运行/);
});

const pose={event:'pose',captured_ms:20100,age_ms:120,people:1,tilt:12.5,
  tracking_valid:true,valid:true,infer_ms:90,conversion_ms:10,model_ms:80,eye_span_px:40};
test('USB pose diagnostics require complete, bounded, internally consistent fields',()=>{
  assert.deepEqual(parsePose(JSON.stringify(pose)),pose);
  for(const data of [{...pose,age_ms:-1},{...pose,captured_ms:1.5},{...pose,tilt:NaN},
    {...pose,people:0},{...pose,tracking_valid:false},{...pose,infer_ms:'90'},
    {...pose,valid:1},{...pose,model_ms:-1},{...pose,event:'metrics'}]) assert.equal(parsePose(data),null);
  assert.equal(parsePose(JSON.stringify(pose).slice(0,-1)),null);
  assert.equal(parsePose(JSON.stringify(pose)+' noise'),null);
  assert.ok(parsePose({...pose,people:0,tracking_valid:false,valid:false}));
});

test('USB diagnostics require an HP barrier and reconfirm after non-monotonic device time',()=>{
  const stream=new PoseStream();
  assert.equal(stream.receive(pose,20).accepted,false);
  assert.equal(stream.confirm(valid),true);
  assert.equal(stream.receive({...pose,captured_ms:19999},20).accepted,false);
  assert.equal(stream.receive(pose,25).accepted,true);
  assert.equal(stream.pose.age_ms,120);assert.equal(stream.receivedAt,25);
  assert.equal(stream.confirm({...valid,uptime_ms:20500}),false);
  assert.equal(stream.pose,pose);
  assert.equal(stream.receive({...pose,captured_ms:20050},30).invalidated,true);
  assert.equal(stream.pose,null);assert.equal(stream.enabled,false);
  assert.equal(stream.receive({...pose,captured_ms:22000},40).accepted,false);
  stream.confirm({...valid,uptime_ms:21000});
  assert.equal(stream.receive({...pose,captured_ms:22000,age_ms:300},50).accepted,true);
  assert.equal(stream.receive({...pose,captured_ms:22100,age_ms:100},60).invalidated,true);
  stream.confirm({...valid,boot:101,uptime_ms:100});
  assert.equal(stream.receive({...pose,captured_ms:200},70).accepted,true);
  stream.reset();assert.equal(stream.pose,null);assert.equal(stream.enabled,false);
});
test('only matched receipts establish a boot or confirm a reboot',()=>{
  const t=new RequestTracker();
  assert.equal(t.receive({...valid,boot:200}).matched,false);
  t.begin(12,'get',draft,0);
  assert.equal(t.receive(valid,20).restarted,false);
  assert.equal(t.receive({...valid,boot:999}).matched,false);
  t.begin(13,'get',draft,30);
  assert.equal(t.receive({...valid,id:13,boot:101,uptime_ms:100,reset_reason:4},40).restarted,true);
  t.begin(14,'get',draft,50);
  assert.equal(t.receive({...valid,id:14,boot:101,uptime_ms:90},60).matched,false);
  assert.ok(t.pending);
  t.reset();t.begin(15,'get',draft,70);
  assert.equal(t.receive({...valid,id:15,boot:102,uptime_ms:10},80).restarted,false);
});
test('reset reasons accept old firmware and preserve unknown future codes',()=>{
  assert.ok(parseReport(valid));
  assert.equal(resetReason(undefined),'固件未提供');
  assert.equal(resetReason(4),'异常复位（panic）');
  assert.equal(resetReason(9),'欠压复位');
  assert.match(resetReason(99),/99/);
  assert.equal(parseReport({...valid,reset_reason:'panic'}),null);
});
test('a local test countdown cannot confirm the device restored its settings',()=>{
  const running={...valid,test_ms:3000};
  assert.equal(reportState(running,true,1000,100),'设备回执：试灯中');
  assert.equal(reportState(running,true,1000,2500),'试灯可能已结束，等待刷新确认');
  assert.equal(reportState(running,true,3500),'试灯可能已结束，等待刷新确认');
  assert.equal(reportState(valid,true),'设备状态已同步');
  assert.equal(reportState(running,false),'回执未确认或已过期');
});

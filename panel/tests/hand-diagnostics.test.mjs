import {test} from 'node:test';
import assert from 'node:assert/strict';
import {HandDiagnostics,handScores,handProgress} from '../src/hand.mjs';
const h={v:1,event:'observation',seq:1,captured_ms:1000,age_ms:700,epoch:1,width:320,height:240,hands:1,box:[20,20,180,190],detect_score:.9,valid:true,classifier:'espdl_gesture11',classifier_ready:true,gesture:'five',scores:[.1,0,0,0,.9,0,0,0,0,0,0],classification_valid:true,classifier_status:0,confirmed:false,gate_visible:'open_palm',gate_latched:'unknown',candidate_samples:1,palm_count:0,v_count:0,infer_ms:680};
test('diagnostics calculate top margin and never promote a single target to completion',()=>{
  const s=handScores(h);assert.equal(s.top.label,'five');assert.equal(s.margin,.8);
  assert.match(handProgress(h,0,1000),/单帧候选.*尚未报告确认.*样本数 1/);
  assert.match(handProgress({...h,confirmed:true},0,1000),/持续保持不会重复计数/);
  assert.match(handProgress(h,301,1000),/已过期/);
  assert.match(handProgress({...h,classification_valid:false},0,1000),/未报告本帧分类有效/);
});
test('bounded diagnostics preserve camera-time observations and export known hand fields only',()=>{
  const d=new HandDiagnostics();assert.equal(d.receive(h,0),null);d.confirm(8);
  for(let i=0;i<205;i++)d.receive({...h,seq:i+1,captured_ms:1000+i*750,token:'secret',reply:'private'},i*800,true);
  assert.equal(d.records.length,200);assert.equal(d.records[0].hand.seq,6);assert.equal(d.records.at(-1).capture_gap_ms,750);
  assert.equal(d.records.at(-1).receipt_gap_ms,800);assert.equal(d.records.at(-1).during_camera,true);
  const text=d.exportJsonl();assert.doesNotMatch(text,/secret|private|"token"|"reply"/);assert.equal(text.trim().split('\n').length,201);
});
test('frame pairing requires current session, boot, exact timestamp and full dimensions',()=>{
  const d=new HandDiagnostics();d.reset(4);d.confirm(8);d.receive(h,0,true);
  const f={encoding:'jpeg',source:'inputjpeg',session:4,hp_boot:8,capturedMs:1000,width:320,height:240,rgba:'private pixels'};
  const match=d.matchFrame(f);assert.equal(match.hand.seq,1);
  for(const patch of [{session:3},{hp_boot:9},{capturedMs:999},{width:240},{source:'camera'},{encoding:'rgb565'}])assert.equal(d.matchFrame({...f,...patch}),null);
  const rows=d.exportJsonl(f,match);assert.match(rows,/camera_metadata/);assert.doesNotMatch(rows,/private pixels|rgba/);
  d.reset(5);d.confirm(8);assert.equal(d.records.length,0);assert.equal(d.matchFrame(f),null);
});
test('epoch discontinuity suppresses gap inference and ambiguous matching',()=>{
  const d=new HandDiagnostics();d.confirm(1);d.receive(h,0);d.receive({...h,epoch:2},50);
  assert.equal(d.records.at(-1).capture_gap_ms,null);assert.equal(d.records.at(-1).segment,1);
  assert.equal(d.matchFrame({encoding:'jpeg',source:'inputjpeg',session:0,hp_boot:1,capturedMs:1000,width:320,height:240}),null);
});

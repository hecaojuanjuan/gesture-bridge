import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseHand,HandStream,handState,handCandidate,handFresh,GESTURE11_LABELS} from '../src/hand.mjs';

const detector={v:1,event:'observation',seq:1,captured_ms:1100,age_ms:250,epoch:0,
  width:320,height:240,hands:1,box:[145,67,215,148],detect_score:.5,valid:true,
  classifier_ready:false,gesture:'untrained',infer_ms:209};
const trained={...detector,classifier_ready:true,gesture:'closed_fist',scores:[.05,.9,.05],
  classification_valid:true,classifier_status:0,confirmed:false,gate_visible:'unknown',
  gate_latched:'open_palm',candidate_samples:1,palm_count:1,fist_count:0};
const report={boot:1,uptime_ms:1000,stage:2};

test('old detector-only and current untrained observations remain diagnostics',()=>{
  assert.deepEqual(parseHand(JSON.stringify(detector)),detector);
  const current={...detector,scores:[0,0,0],classification_valid:false,classifier_status:1,
    confirmed:false,gate_visible:'unknown',gate_latched:'unknown',candidate_samples:0,palm_count:0,fist_count:0};
  assert.deepEqual(parseHand(current),current);
  assert.match(handState(current),/有效单手.*分类器未加载/);
  assert.equal(handCandidate(current),'—');
  assert.equal(parseHand({...detector,event:'gesture'}),null);
});

test('reject malformed detector fields and impossible untrained success',()=>{
  for (const change of [ {v:2},{seq:-1},{captured_ms:Infinity},{age_ms:-1},{epoch:1.1},
    {width:0},{height:0},{hands:2},{box:[145,67,321,148]},{box:[5,5,2,2]},
    {detect_score:.49},{detect_score:NaN},{infer_ms:-1},{valid:'true'},
    {gesture:'closed_fist'},{classification_valid:true},{confirmed:true},{scores:[1,0,0]},
    {scores:[0,0]},{palm_count:-1},{gate_visible:'nonsense'}]) {
    assert.equal(parseHand({...detector,...change}),null,JSON.stringify(change));
  }
  assert.ok(parseHand({...detector,hands:0,width:0,height:0,valid:false,box:[0,0,0,0],detect_score:0}));
});

test('raw candidates never become completed gestures or use a stale gate latch',()=>{
  assert.ok(parseHand(trained));
  assert.equal(handCandidate(trained),'握拳');
  assert.match(handState(trained),/原始候选不代表动作完成/);
  const lost={...trained,valid:false,classification_valid:false,gesture:'unknown',scores:[0,0,0],
    hands:0,box:[0,0,0,0],detect_score:0,gate_visible:'unknown'};
  assert.ok(parseHand(lost));assert.equal(handCandidate(lost),'—');
  assert.equal(parseHand({...trained,classifier_ready:false}),null);
  assert.equal(parseHand({...trained,scores:[.2,.9,.2]}),null);
  assert.equal(parseHand({...trained,valid:false}),null);
});

test('600 ms freshness sums device age and local elapsed without altering reported age',()=>{
  assert.equal(handFresh(trained,350),true);
  assert.equal(handCandidate(trained,350),'握拳');
  assert.equal(handFresh(trained,351),false);
  assert.equal(handCandidate(trained,351),'—');
  assert.match(handState(trained,351),/观测已过期/);
  assert.equal(trained.age_ms,250);
  assert.equal(handFresh(trained,-1),false);
  assert.equal(handFresh(trained,NaN),false);
});

test('stream requires a matching-HP barrier and post-barrier captures',()=>{
  const stream=new HandStream();
  assert.equal(stream.receive(detector,1).accepted,false);
  assert.equal(stream.confirm(report),true);
  assert.equal(stream.receive({...detector,captured_ms:1000},2).accepted,false);
  assert.equal(stream.receive(detector,3).accepted,true);
  assert.equal(stream.hand,detector);
  assert.equal(stream.confirm({...report,uptime_ms:1500}),false);
  assert.equal(stream.hand,detector);
  stream.reset();assert.equal(stream.receive(detector,4).accepted,false);
});

test('timestamp, sequence, epoch and host-time discontinuities clear old hand data',()=>{
  for (const [patch,host] of [[{captured_ms:900},20],[{captured_ms:1100},20],
      [{captured_ms:1200,age_ms:1},20],[{captured_ms:1200,seq:1},20],
      [{captured_ms:1200,seq:2,epoch:1},20],[{captured_ms:1200,seq:2},9]]) {
    const stream=new HandStream();stream.confirm(report);stream.receive(detector,10);
    assert.equal(stream.receive({...detector,seq:2,...patch},host).invalidated,true);
    assert.equal(stream.enabled,false);assert.equal(stream.hand,null);
    assert.equal(stream.receive({...detector,seq:3,captured_ms:1400},30).accepted,false);
    stream.confirm({...report,uptime_ms:1500});
    assert.equal(stream.receive({...detector,seq:4,captured_ms:1600,epoch:1},40).accepted,true);
  }
});

test('a new boot or non-vision stage clears prior model readiness',()=>{
  const stream=new HandStream();stream.confirm(report);stream.receive(trained,10);
  assert.equal(stream.confirm({...report,boot:2,uptime_ms:100}),true);
  assert.equal(stream.hand,null);assert.equal(stream.boot,2);
  assert.equal(stream.confirm({...report,stage:1}),false);assert.equal(stream.enabled,false);
  assert.equal(stream.confirm({}),false);
});

function nativeGesture(label,changes={}) {
  const scores=Array(11).fill(.003906);
  scores[GESTURE11_LABELS.indexOf(label)]=.941406;
  return {...detector,classifier:'espdl_gesture11',classifier_ready:true,gesture:label,scores,
    classification_valid:true,classifier_status:0,confirmed:false,
    gate_visible:'unknown',gate_latched:'v_sign',candidate_samples:1,v_count:2,...changes};
}

test('native classifier retains the fixed eleven-class order and maps only five/two to targets',()=>{
  assert.deepEqual(GESTURE11_LABELS,['one','two','three','four','five','like','ok','no_gesture','call','dislike','no_hand']);
  for(const label of GESTURE11_LABELS) {
    const h=nativeGesture(label);
    assert.equal(parseHand(h),h,label);
    const candidate=handCandidate(h);
    if(label==='five') assert.equal(candidate,'张掌');
    else if(label==='two') assert.equal(candidate,'V字');
    else assert.match(candidate,/非目标/,label);
    assert.match(handState(h),/11 类.*目标为张掌和V字.*不代表动作完成/);
  }
  assert.equal(handCandidate(nativeGesture('two'),351),'—');
});

test('native packets require the model tag, eleven bounded scores and matching raw top class',()=>{
  const h=nativeGesture('two');
  // Sum is deliberately not 1: preserve real quantized outputs, do not renormalize.
  assert.ok(Math.abs(h.scores.reduce((a,b)=>a+b)-1)>.001);
  assert.ok(parseHand(h));
  for(const change of [{classifier:undefined},{classifier:'tiny_cnn3'},{classifier:'unknown-model'},
    {gesture:'five'},{gesture:'closed_fist'},{scores:[0,1,0]},
    {scores:Array(11).fill(0)},{scores:Array(11).fill(NaN)},
    {scores:h.scores.map((n,i)=>i===3 ? 1.1 : n)},{v_count:-1}]) {
    assert.equal(parseHand({...h,...change}),null,JSON.stringify(change));
  }
  const tie=[...h.scores];tie[4]=tie[1]+.000001;
  assert.ok(parseHand({...h,scores:tie}));
  tie[4]=tie[1]+.000004;
  assert.equal(parseHand({...h,scores:tie}),null);
});

test('unready native and retained V latches never show a completed target',()=>{
  const h=nativeGesture('two',{classifier_ready:false,gesture:'untrained',scores:Array(11).fill(0),
    classification_valid:false,classifier_status:1,gate_visible:'unknown'});
  assert.ok(parseHand(h));assert.equal(handCandidate(h),'—');
  assert.match(handState(h),/未加载.*张掌或V字/);
  assert.equal(parseHand({...h,confirmed:true}),null);
  const lost=nativeGesture('two',{gesture:'unknown',classification_valid:false,valid:false,
    gate_visible:'unknown',gate_latched:'v_sign'});
  assert.ok(parseHand(lost));assert.equal(handCandidate(lost),'—');
  assert.equal(handCandidate({...trained,classifier:'tiny_cnn3'}),'握拳');
});

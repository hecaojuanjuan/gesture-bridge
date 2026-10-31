import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import * as protocol from '../src/protocol.mjs';
import * as hand from '../src/hand.mjs';

// Exercise the actual page controller with a small DOM/transport fixture.
// Browser layout and real USB/cloud paths are tested separately on-device.
const source=(await readFile(new URL('../src/main.js',import.meta.url),'utf8'))
  .replace(/^import .*;\n/gm,'');
function page(open) {
  const elements=new Map();
  function node(id) {
    if(!elements.has(id)) elements.set(id,{style:{setProperty(){}},
      classList:{toggle(){}},setAttribute(){},textContent:'',value:'',painted:0,
      getContext(){return {createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
        putImageData:()=>{elements.get(id).painted++;}};}});
    return elements.get(id);
  }
  let now=0, interval, nextId=100;
  const listeners={};
  const document={getElementById:node,querySelector:node,querySelectorAll:()=>[],hidden:false,
    addEventListener:(name,callback)=>{listeners[name]=callback;}};
  const context=vm.createContext({...protocol,...hand,connectSerial:open,
    document,
    performance:{now:()=>now},structuredClone,
    crypto:{getRandomValues:array=>{array[0]=nextId++;return array;}},
    navigator:{userAgent:'controller-test'},window:{},
    setInterval:fn=>{interval=fn;}});
  vm.runInContext(source,context);
  return {run:code=>vm.runInContext(code,context),node,
    tick:ms=>{now=ms;interval();},
    hide:()=>{document.hidden=true;listeners.visibilitychange?.();}};
}

test('loss during open closes the late transport instead of installing a ghost connection',async()=>{
  let finish,lost,closed=0;
  const p=page((report,onLost)=>{lost=onLost;return new Promise(resolve=>{finish=resolve;});});
  const opening=p.run("connect('serial')");
  lost('USB removed while opening');
  finish({name:'USB 串口',async close(){closed++;},async send(){assert.fail('stale connection sent a command');}});
  await opening;
  assert.equal(closed,1);
  assert.equal(p.run('transport'),null);
  assert.equal(p.node('serial-connect').disabled,false);
  assert.match(p.node('notice').textContent,/USB removed/);
});

test('reconnect is disabled until the previous port has actually closed',async()=>{
  let finishClose,opens=0;
  const p=page(async()=>{opens++;return {name:'USB 串口',async send(){},
    close:()=>new Promise(resolve=>{finishClose=resolve;})};});
  await p.run("connect('serial')");
  const closing=p.run('disconnect()');
  assert.equal(p.node('serial-connect').disabled,true);
  await p.run("connect('serial')");assert.equal(opens,1);
  finishClose();await closing;
  assert.equal(p.node('serial-connect').disabled,false);
});

test('a setting edited while an earlier command is pending survives its acknowledgement',async()=>{
  let deliver;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");
  const report={v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:1,brightness:20,
    rgb:[80,190,255],output:[3,7,9],test_ms:0,stage:1,
    pose:{age_ms:4294967295,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}};
  deliver(report);
  await p.run("send('set')");
  p.run('draft.brightness=45;dirty=true;updateDraft()');
  deliver({...report,id:p.run('requests.pending.id'),uptime_ms:1100});
  await p.run("send('get')");
  deliver({...report,id:p.run('requests.pending.id'),uptime_ms:1200});
  assert.equal(p.run('draft.brightness'),45);
  assert.equal(p.run('dirty'),true);
});

test('an unmatched cached boot reason cannot become a restart warning',async()=>{
  let deliver;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");
  const report={v:1,boot:1,id:99,ok:true,reset_reason:4,uptime_ms:1000,mode:0,brightness:20,
    rgb:[80,190,255],output:[0,0,0],test_ms:0,stage:1,
    pose:{age_ms:4294967295,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}};
  deliver(report);
  assert.equal(p.node('actual-boot').textContent,'上次启动：等待匹配回执');
  deliver({...report,id:101,boot:2,reset_reason:1});
  assert.equal(p.node('actual-boot').textContent,'上次启动：上电启动');
  await p.run("send('get')");
  deliver({...report,id:102,boot:3,reset_reason:4,uptime_ms:50});
  assert.match(p.node('actual-boot').textContent,/异常复位.*1 次重启/);
  assert.match(p.node('notice').textContent,/设备已重新启动/);
});

test('USB startup retries get on the same port after the first request is lost',async()=>{
  let deliver,opens=0;
  const sent=[];
  const p=page(async report=>{opens++;deliver=report;return {name:'USB 串口',
    async send(wire){sent.push(wire);},async close(){}};});
  await p.run("connect('serial')");
  assert.equal(p.node('apply').disabled,true);
  assert.match(p.node('connection-state').textContent,/设备启动中/);
  p.tick(2000);
  assert.deepEqual(sent,['101 get','102 get']);
  const report={v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:1,brightness:20,
    rgb:[80,190,255],output:[3,7,9],test_ms:0,stage:1,
    pose:{age_ms:4294967295,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}};
  deliver(report); // A superseded read cannot establish readiness.
  assert.equal(p.node('apply').disabled,true);
  deliver({...report,id:102});
  assert.equal(p.node('apply').disabled,false);
  assert.match(p.node('connection-state').textContent,/设备已响应/);
  p.tick(4000);
  assert.equal(sent.length,2);
  assert.equal(opens,1);
});

test('USB startup probing stops after twenty seconds without claiming readiness',async()=>{
  const sent=[];
  const p=page(async()=>({name:'USB 串口',async send(wire){sent.push(wire);},async close(){}}));
  await p.run("connect('serial')");
  for(let now=2000;now<=20000;now+=2000) p.tick(now);
  assert.equal(sent.length,10);
  assert.ok(sent.every(wire=>wire.endsWith(' get')));
  assert.equal(p.run('initialProbe'),null);
  assert.equal(p.run('requests.pending'),null);
  assert.equal(p.node('apply').disabled,true);
  assert.match(p.node('notice').textContent,/20 秒内未收到设备回执/);
  assert.doesNotMatch(p.node('connection-state').textContent,/设备已响应|设备启动中/);
});

test('ROM restart cancels old requests and retires their boot until a fresh get confirms the new boot',async()=>{
  for (const verb of ['get','set','test']) {
    let deliver,telemetry;
    const sent=[];
    const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
      return {name:'USB 串口',async send(wire){sent.push(wire);},async close(){}};});
    await p.run("connect('serial')");
    const report={v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:1,brightness:20,
      rgb:[80,190,255],output:[3,7,9],test_ms:0,stage:2,
      pose:{age_ms:100,people:1,tilt:3,tracking:true,valid:true,infer_ms:120}};
    deliver(report);
    assert.equal(p.node('draft-status').textContent,'已同步');
    await p.run(`send('${verb}')`);
    assert.equal(p.run('requests.pending.id'),102);
    telemetry.onReset('检测到设备重新启动');
    assert.equal(p.run('requests.pending.id'),103);
    assert.equal(p.run('requests.pending.verb'),'get');
    assert.equal(p.run('report'),null);
    assert.equal(p.node('apply').disabled,true);
    assert.equal(p.node('test').disabled,true);
    assert.equal(p.node('camera-capture').disabled,true);
    assert.equal(p.node('draft-status').textContent,'待应用');
    assert.doesNotMatch(p.node('connection-state').textContent,/设备已响应/);
    assert.doesNotMatch(p.node('report-title').textContent,/已同步/);
    if (verb!=='get') assert.match(p.node('notice').textContent,/结果未知.*不会自动重发/);
    // Neither the cancelled receipt, a new boot with the cancelled ID, nor
    // an old boot carrying the new ID may restore readiness.
    for (const old of [report,{...report,id:102},{...report,id:102,boot:2},
      {...report,id:103,uptime_ms:1200}]) {
      deliver(old);
      assert.equal(p.node('apply').disabled,true);
      assert.doesNotMatch(p.node('connection-state').textContent,/设备已响应/);
      assert.equal(p.run('requests.pending.id'),103);
    }
    p.tick(2000); // The first post-reset get was lost; retry only the read.
    assert.equal(p.run('requests.pending.id'),104);
    deliver({...report,id:103,boot:2,uptime_ms:200});
    assert.equal(p.node('apply').disabled,true);
    deliver({...report,id:104,boot:2,uptime_ms:300});
    assert.equal(p.node('apply').disabled,false);
    assert.equal(p.node('draft-status').textContent,'已同步');
    assert.equal(p.run('initialProbe'),null);
    assert.equal(p.run('restarts'),1);
    assert.deepEqual(sent,['101 get',`102 ${verb}`+(verb==='set' ? ' 1 20 80 190 255' : ''),
      '103 get','104 get']);
  }
});

test('a timed-out set or test is never replayed by startup or periodic reads',async()=>{
  for(const verb of ['set','test']) {
    let deliver;
    const sent=[];
    const p=page(async report=>{deliver=report;return {name:'USB 串口',
      async send(wire){sent.push(wire);},async close(){}};});
    await p.run("connect('serial')");
    deliver({v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:1,brightness:20,
      rgb:[80,190,255],output:[3,7,9],test_ms:0,stage:1,
      pose:{age_ms:4294967295,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}});
    await p.run(`send('${verb}')`);
    p.tick(10000);
    assert.equal(sent.filter(wire=>wire.split(' ')[1]===verb).length,1);
    assert.equal(sent.length,2);
    assert.match(p.node('notice').textContent,/执行结果未知/);
    p.tick(18000);
    assert.equal(sent.at(-1),'103 get');
    assert.equal(p.node('apply').disabled,true);
  }
});

const cameraReport={v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:2,brightness:20,
  rgb:[80,190,255],output:[0,0,0],test_ms:0,stage:1,
  pose:{age_ms:4294967295,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}};
const cameraFrame={width:2,height:1,rgba:new Uint8ClampedArray([255,0,0,255,0,255,0,255]),
  capturedMs:1100,transferMs:7200};

test('camera capture requires a ready USB transport and never starts on connection alone',async()=>{
  let deliver,captures=0;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){},
    async snapshot(){captures++;return cameraFrame;}};});
  await p.run("connect('serial')");
  await p.run('captureCamera()');assert.equal(captures,0);
  deliver(cameraReport);
  assert.equal(captures,0);assert.equal(p.node('camera-capture').disabled,false);
  await p.run('captureCamera()');
  assert.equal(captures,1);assert.equal(p.node('camera-canvas').painted,1);
  assert.equal(p.node('camera-canvas').hidden,false);
  assert.match(p.node('camera-details').textContent,/2 × 1.*7.2 秒/);
  assert.match(p.node('camera-status').textContent,/最近一次完整画面/);
});

test('disconnect clears the camera and late capture results cannot repaint it',async()=>{
  let deliver,finish,progress;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){},
    snapshot:options=>{progress=options.onProgress;return new Promise(resolve=>{finish=resolve;});}};});
  await p.run("connect('serial')");deliver(cameraReport);
  const capture=p.run('captureCamera()');
  progress({received:50,total:100});assert.equal(p.node('camera-progress').value,50);
  await p.run('disconnect()');
  finish(cameraFrame);await capture;
  progress({received:100,total:100});
  assert.equal(p.node('camera-canvas').hidden,true);
  assert.equal(p.node('camera-canvas').painted,0);
  assert.equal(p.run('camera.frame'),null);
  assert.equal(p.node('camera-capture').disabled,true);
});

test('automatic camera refresh never overlaps and stops when the page is hidden',async()=>{
  let deliver,finish,captures=0;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){},
    snapshot:()=>{captures++;return new Promise(resolve=>{finish=resolve;});}};});
  await p.run("connect('serial')");deliver(cameraReport);
  p.run('toggleCameraAuto()');
  p.tick(1000);p.tick(2000);assert.equal(captures,1);
  assert.equal(p.node('camera-auto').disabled,false);
  p.hide();assert.equal(p.run('camera.auto'),false);
  finish(cameraFrame);await Promise.resolve();await Promise.resolve();
  p.tick(5000);assert.equal(captures,1);
  assert.equal(p.node('camera-auto').textContent,'自动刷新');
});

test('camera errors stop automatic refresh and transports without snapshots stay disabled',async()=>{
  let deliver;
  const p=page(async report=>{deliver=report;return {name:'USB 串口',async send(){},async close(){},
    async snapshot(){throw Error('摄像头未返回完整帧');}};});
  await p.run("connect('serial')");deliver(cameraReport);
  p.run('camera.auto=true');await p.run('captureCamera()');
  assert.equal(p.run('camera.auto'),false);
  assert.match(p.node('camera-status').textContent,/获取失败.*未返回完整帧/);
  p.run('delete transport.snapshot;render()');
  assert.equal(p.node('camera-capture').disabled,true);
  assert.match(p.node('camera-status').textContent,/不支持画面/);
});

const diagnosticPose={event:'pose',captured_ms:1100,age_ms:120,people:1,tilt:12.5,
  tracking_valid:true,valid:true,infer_ms:90};
const diagnosticReport={...cameraReport,stage:2,
  pose:{age_ms:250,people:1,tilt:8,tracking:true,valid:true,infer_ms:100}};

test('USB diagnostics wait for matching HP and preserve device age independently of host receipt time',async()=>{
  let deliver,telemetry;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");
  telemetry.onPose(diagnosticPose);assert.equal(p.node('pose-age').textContent,'—');
  deliver({...diagnosticReport,id:99});
  telemetry.onPose(diagnosticPose);assert.equal(p.node('pose-age').textContent,'—');
  deliver(diagnosticReport);
  telemetry.onPose({...diagnosticPose,captured_ms:999});assert.equal(p.node('pose-age').textContent,'—');
  telemetry.onPose(diagnosticPose);
  assert.equal(p.node('pose-age').textContent,'120 ms');
  assert.equal(p.node('pose-people').textContent,'1');
  assert.equal(p.node('pose-tilt').textContent,'12.5°');
  p.tick(1000);
  assert.equal(p.node('pose-age').textContent,'120 ms');
  assert.equal(p.node('pose-received').textContent,'1.0 秒前');
  assert.doesNotMatch(p.node('pose-status').textContent,/实时输入有效/);
  await p.run("send('get')");
  telemetry.onPose({...diagnosticPose,captured_ms:1200,people:0,tracking_valid:false,valid:false});
  assert.equal(p.node('pose-people').textContent,'0');
  assert.equal(p.node('pose-tilt').textContent,'—');
  assert.equal(p.run('requests.pending.id'),102);
  assert.equal(p.run('report.id'),101);
});

test('USB restart, time rollback, boot change, and disconnect require a fresh diagnostic barrier',async()=>{
  let deliver,telemetry;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");deliver(diagnosticReport);telemetry.onPose(diagnosticPose);
  telemetry.onReset('设备重新启动');
  assert.equal(p.node('pose-age').textContent,'—');
  telemetry.onPose({...diagnosticPose,captured_ms:1200});
  assert.equal(p.node('pose-age').textContent,'—');
  await p.run("send('get')");deliver({...diagnosticReport,id:102,boot:2,uptime_ms:1300});
  telemetry.onPose({...diagnosticPose,captured_ms:1400});
  assert.equal(p.node('pose-age').textContent,'120 ms');
  telemetry.onPose({...diagnosticPose,captured_ms:1350});
  assert.equal(p.node('pose-age').textContent,'—');
  assert.match(p.node('pose-status').textContent,/时间不连续/);
  await p.run("send('get')");deliver({...diagnosticReport,id:103,boot:3,uptime_ms:500});
  telemetry.onPose({...diagnosticPose,captured_ms:600});
  assert.equal(p.node('pose-age').textContent,'120 ms');
  await p.run('disconnect()');telemetry.onPose({...diagnosticPose,captured_ms:700});
  assert.equal(p.node('pose-age').textContent,'—');
});

test('camera transfer pauses USB diagnostics until its follow-up HP and a new capture',async()=>{
  let deliver,telemetry,finish;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){},
      snapshot:()=>new Promise(resolve=>{finish=resolve;})};});
  await p.run("connect('serial')");deliver(diagnosticReport);telemetry.onPose(diagnosticPose);
  const capture=p.run('captureCamera()');
  telemetry.onPose({...diagnosticPose,captured_ms:1200});
  assert.equal(p.node('pose-age').textContent,'—');
  assert.match(p.node('pose-status').textContent,/传输期间暂停/);
  finish(cameraFrame);await capture;
  telemetry.onPose({...diagnosticPose,captured_ms:1300});
  assert.equal(p.node('pose-age').textContent,'—');
  deliver({...diagnosticReport,id:102,uptime_ms:1500});
  telemetry.onPose({...diagnosticPose,captured_ms:1400});
  assert.equal(p.node('pose-age').textContent,'—');
  telemetry.onPose({...diagnosticPose,captured_ms:1600});
  assert.equal(p.node('pose-age').textContent,'120 ms');
});

test('cloud diagnostic mode remains an eight-second snapshot without adding RTT to reported age',async()=>{
  let deliver;
  const sent=[];
  const p=page(async report=>{deliver=report;return {name:'灵机云端',
    async send(wire){sent.push(wire);},async close(){}};});
  await p.run("connect('serial')");p.run("transportKind='cloud'");
  p.tick(100);deliver(diagnosticReport);
  p.tick(1100);
  assert.equal(p.node('pose-age').textContent,'250 ms');
  assert.equal(p.node('pose-received').textContent,'1.0 秒前');
  assert.match(p.node('pose-source').textContent,/云端姿态快照.*每 8 秒/);
  p.tick(8099);assert.equal(sent.length,1);
  p.tick(8100);assert.equal(sent.length,2);
  assert.ok(sent.every(wire=>wire.endsWith(' get')));
});

const diagnosticHand={v:1,event:'observation',seq:1,captured_ms:1100,age_ms:250,epoch:0,
  width:320,height:240,hands:1,box:[145,67,215,148],detect_score:.5,valid:true,
  classifier_ready:false,gesture:'untrained',infer_ms:209};
const handReport={...cameraReport,stage:2};

test('hand USB observations identify detection without claiming an untrained gesture or old head-pose light effects',async()=>{
  let deliver,telemetry;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");
  telemetry.onHand(diagnosticHand);assert.equal(p.node('pose-age').textContent,'—');
  deliver(handReport);telemetry.onHand(diagnosticHand);
  assert.equal(p.node('vision-title').textContent,'手部诊断');
  assert.equal(p.node('pose-people').textContent,'1');
  assert.equal(p.node('pose-tilt').textContent,'—');
  assert.equal(p.node('pose-visual').hidden,true);
  assert.match(p.node('pose-status').textContent,/有效单手.*分类器未加载/);
  assert.equal(p.node('legend-pose').hidden,true);
  assert.equal(p.node('legend-hand').hidden,true);
  assert.match(p.node('legend-help').textContent,/尚无.*分类灯效/);
  p.tick(351);
  assert.match(p.node('pose-status').textContent,/观测已过期/);
  assert.equal(p.node('pose-age').textContent,'250 ms');
});

test('hand epoch changes, ROM restarts and disconnect clear model and diagnostic state',async()=>{
  let deliver,telemetry;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");deliver(handReport);telemetry.onHand(diagnosticHand);
  telemetry.onHand({...diagnosticHand,seq:2,captured_ms:1200,epoch:1});
  assert.equal(p.node('pose-age').textContent,'—');
  assert.match(p.node('pose-status').textContent,/采样轮次变化/);
  await p.run("send('get')");deliver({...handReport,id:102,uptime_ms:1300});
  telemetry.onHand({...diagnosticHand,seq:3,captured_ms:1400,epoch:1});
  assert.equal(p.node('pose-age').textContent,'250 ms');
  telemetry.onReset('设备重新启动');
  telemetry.onHand({...diagnosticHand,seq:4,captured_ms:1500,epoch:1});
  assert.equal(p.node('pose-age').textContent,'—');
  deliver({...handReport,id:103,boot:2,uptime_ms:100});
  telemetry.onHand({...diagnosticHand,seq:1,captured_ms:200});
  assert.equal(p.node('pose-age').textContent,'250 ms');
  await p.run('disconnect()');telemetry.onHand({...diagnosticHand,seq:2,captured_ms:400});
  assert.equal(p.node('pose-age').textContent,'—');
  assert.equal(p.run('visionBackend'),null);
});

test('confirmed hand backend selects model JPEG before clearing streams and needs fresh HP after capture',async()=>{
  let deliver,telemetry,finish,source;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){},snapshot:options=>{
      source=options.source;return new Promise(resolve=>{finish=resolve;});}};});
  await p.run("connect('serial')");deliver(handReport);telemetry.onHand(diagnosticHand);
  const capture=p.run('captureCamera()');assert.equal(source,'inputjpeg');
  assert.equal(p.node('pose-age').textContent,'—');
  telemetry.onHand({...diagnosticHand,seq:2,captured_ms:1200});
  assert.equal(p.node('pose-age').textContent,'—');
  finish(cameraFrame);await capture;
  telemetry.onHand({...diagnosticHand,seq:3,captured_ms:1300});
  assert.equal(p.node('pose-age').textContent,'—');
  deliver({...handReport,id:102,uptime_ms:1400});
  telemetry.onHand({...diagnosticHand,seq:4,captured_ms:1500});
  assert.equal(p.node('vision-title').textContent,'手部诊断');
});

test('a legacy cloud report cannot infer a hand backend from stage two',async()=>{
  let deliver;
  const p=page(async report=>{deliver=report;return {name:'灵机云端',async send(){},async close(){}};});
  await p.run("connect('serial')");p.run("transportKind='cloud'");deliver(handReport);
  assert.equal(p.node('vision-title').textContent,'视觉诊断');
  assert.match(p.node('pose-status').textContent,/未提供识别后端.*无法判断/);
  assert.equal(p.node('legend-hand').hidden,true);assert.equal(p.node('legend-pose').hidden,true);
});

test('native eleven-class hand diagnostics show V targets while legacy remains fist-specific',async()=>{
  let deliver,telemetry;
  const p=page(async(report,lost,options)=>{deliver=report;telemetry=options;
    return {name:'USB 串口',async send(){},async close(){}};});
  await p.run("connect('serial')");deliver(handReport);
  const scores=Array(11).fill(.003906);scores[1]=.941406;
  telemetry.onHand({...diagnosticHand,classifier:'espdl_gesture11',classifier_ready:true,
    gesture:'two',scores,classification_valid:true,classifier_status:0,confirmed:false,
    gate_visible:'unknown',gate_latched:'v_sign',v_count:2});
  assert.equal(p.node('pose-tilt').textContent,'V字');
  assert.equal(p.node('pose-primary-label').textContent,'分类原始候选');
  assert.match(p.node('pose-status').textContent,/原始候选不代表动作完成/);
  assert.match(p.node('legend-hand').textContent,/蓝.*V字/);
  assert.doesNotMatch(p.node('legend-hand').textContent,/握拳/);
  p.tick(351);assert.equal(p.node('pose-tilt').textContent,'—');
  telemetry.onHand({...diagnosticHand,seq:2,captured_ms:1600,classifier_ready:true,
    gesture:'closed_fist',scores:[.05,.9,.05],classification_valid:true,classifier_status:0,confirmed:false});
  assert.equal(p.node('pose-tilt').textContent,'握拳');
  assert.match(p.node('legend-hand').textContent,/蓝.*握拳/);
});

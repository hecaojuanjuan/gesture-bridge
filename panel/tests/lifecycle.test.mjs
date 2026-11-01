import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {setImmediate} from 'node:timers/promises';
import * as protocol from '../src/protocol.mjs';
import * as hand from '../src/hand.mjs';
import * as agent from '../src/agent.mjs';
import {icon} from '../src/setup-art.mjs';
const source=(await readFile(new URL('../src/main.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const boot='0123456789abcdef';
const hp={v:1,boot:1,id:101,ok:true,uptime_ms:1000,mode:0,brightness:20,rgb:[80,190,255],output:[0,0,0],test_ms:0,stage:2,reset_reason:1,pose:{age_ms:1,people:0,tilt:0,tracking:false,valid:false,infer_ms:0}};
const dict={v:1,boot,id:102,ok:true,code:'ok',persisted:true,max_age_ms:1000,bindings:{open_palm:'我想喝水',v_sign:''}};
const hg={v:1,event:'observation',seq:1,captured_ms:1100,age_ms:700,epoch:1,width:160,height:120,hands:1,box:[20,20,80,90],detect_score:.9,valid:true,classifier:'espdl_gesture11',classifier_ready:true,gesture:'five',scores:[0,0,0,0,1,0,0,0,0,0,0],classification_valid:true,classifier_status:0,confirmed:true,gate_visible:'open_palm',gate_latched:'open_palm',candidate_samples:2,palm_count:2,v_count:0,infer_ms:680};
const ae=(state,id=1,extra={})=>({v:1,boot,id,state,code:0,...extra});
function page(open){
  const elements=new Map();function node(id){if(!elements.has(id))elements.set(id,{style:{},classList:{toggle(){}},textContent:'',value:'',painted:0,setAttribute(){},focus(){},getContext(){return{createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:()=>elements.get(id).painted++};}});return elements.get(id);}
  let time=0,interval,next=100;const listeners=new Map(),destinations=[];
  const listen=(type,handler)=>listeners.set(type,handler);
  const context=vm.createContext({...protocol,...hand,...agent,icon,connectSerial:open,document:{getElementById:node,querySelector:node,body:node('body'),addEventListener:listen},window:{addEventListener:listen,location:{assign:href=>destinations.push(href)}},performance:{now:()=>time},crypto:{getRandomValues:a=>{a[0]=next++;return a;}},TextEncoder,Uint8ClampedArray,structuredClone,setInterval:fn=>{interval=fn;return 1;},clearInterval:()=>{interval=null;}});
  vm.runInContext(source,context);
  return{run:code=>vm.runInContext(code,context),node,destinations,dispatch:(type,event={})=>listeners.get(type)?.(event),polling:()=>!!interval,tick:ms=>{time=ms;interval?.();},time:ms=>{time=ms;}};
}
async function fixture({autoDict=true,persisted=true,snapshot,close}={}){
  let report,telemetry,closed=0;const sent=[],dictionary=[];
  const p=page(async(r,lost,options)=>{report=r;telemetry=options;return{name:'USB',send:async wire=>{sent.push(wire);},dictionary:async wire=>{dictionary.push(wire);if(autoDict&&wire.endsWith(' get'))queueMicrotask(()=>options.onDictionary({...dict,id:Number(wire.split(' ')[0]),persisted}));},snapshot,close:async()=>{closed++;await close?.();}};});
  await p.run('connect()');report(hp);await setImmediate();
  return{p,report,telemetry,sent,dictionary,closed:()=>closed};
}
function navigationClick(href='./setup.html#dictionary',options={}){
  const link={target:'',hasAttribute:()=>false,getAttribute:()=>href,...options.link};
  return{button:0,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},target:{closest:()=>link},...options};
}
test('new workstation has no legacy lighting/cloud/prototype controls',()=>{
  const p=page(async()=>{}),html=p.node('#app').innerHTML;
  assert.match(html,/保存到设备并核对/);assert.match(html,/AGENT 回应/);
  assert.doesNotMatch(html,/灯光工作台|连接灵机|设计预览|看见状态/);
});
test('late transport after an opening loss is closed instead of installed',async()=>{
  let finish,lost,closed=0;const p=page((r,l)=>{lost=l;return new Promise(resolve=>finish=resolve);});
  const opening=p.run('connect()');lost('removed');finish({send:async()=>assert.fail(),close:async()=>closed++});await opening;
  assert.equal(closed,1);assert.equal(p.run('transport'),null);
});
test('serial open errors explain possible contention while preserving cancellation and other errors',async()=>{
  for(const [name,message,expected] of [
    ['NetworkError','Failed to execute open','无法打开 USB 串口，可能正被烧录程序或其他调试窗口占用。关闭占用程序后重试。'],
    ['Error','Failed to open serial port.','无法打开 USB 串口，可能正被烧录程序或其他调试窗口占用。关闭占用程序后重试。'],
    ['NotFoundError','No port selected','未选择 USB 设备。'],
    ['SecurityError','Serial permission denied','Serial permission denied']
  ]){
    const p=page(async()=>{const error=Error(message);error.name=name;throw error;});
    await p.run('connect()');assert.equal(p.node('notice').textContent,expected);
    assert.equal(p.run('transport'),null);assert.equal(p.node('serial-connect').disabled,false);
  }
});
test('USB startup retries only get and does not accept superseded receipts',async()=>{
  let deliver;const sent=[];const p=page(async r=>{deliver=r;return{send:async wire=>sent.push(wire),close:async()=>{}};});
  await p.run('connect()');p.tick(2000);assert.deepEqual(sent,['101 get','102 get']);
  deliver(hp);assert.equal(p.run('report'),null);deliver({...hp,id:102});assert.match(p.node('connection-state').textContent,/设备已响应/);
});
test('startup ends after twenty seconds without asserting readiness',async()=>{
  const p=page(async()=>({send:async()=>{},close:async()=>{}}));await p.run('connect()');
  p.tick(20000);assert.equal(p.run('probe'),null);assert.equal(p.node('save-bindings').disabled,true);assert.match(p.node('notice').textContent,/20 秒/);
});
test('initial binding comes only from a correlated HGD after matching HP',async()=>{
  const {p,telemetry}=await fixture({autoDict:false});
  assert.equal(p.run('dictionary'),null);telemetry.onDictionary({...dict,id:999});assert.equal(p.run('dictionary'),null);
  telemetry.onDictionary(dict);await setImmediate();assert.equal(p.run('dictionary.bindings.open_palm'),'我想喝水');assert.equal(p.node('binding-badge').textContent,'设备已保存');
});
test('firmware defaults are visible without claiming persisted configuration',async()=>{
  const {p}=await fixture({persisted:false});assert.equal(p.node('binding-badge').textContent,'设备当前配置');assert.match(p.node('dictionary-status').textContent,/尚无成功保存/);
});
test('save requires both set receipts followed by matching get readback',async()=>{
  const f=await fixture({autoDict:false}),{p,telemetry}=f;telemetry.onDictionary(dict);await setImmediate();
  p.run("draft.open_palm='我要喝水';editDirty=true");const saving=p.run('saveBindings()');
  assert.match(f.dictionary.at(-1),/set open_palm/);assert.equal(p.node('save-bindings').disabled,true);
  telemetry.onDictionary({...dict,id:p.run('dictPending.id'),bindings:{open_palm:'我要喝水',v_sign:''}});await setImmediate();assert.match(f.dictionary.at(-1),/set v_sign -$/);
  telemetry.onDictionary({...dict,id:p.run('dictPending.id'),bindings:{open_palm:'我要喝水',v_sign:''}});await setImmediate();assert.match(f.dictionary.at(-1),/ get$/);
  assert.doesNotMatch(p.node('dictionary-status').textContent,/通过重新读取确认/);
  telemetry.onDictionary({...dict,id:p.run('dictPending.id'),bindings:{open_palm:'我要喝水',v_sign:''}});await saving;
  assert.equal(p.run('dictionary.bindings.open_palm'),'我要喝水');assert.match(p.node('dictionary-status').textContent,/通过重新读取确认/);
});
test('write failure clears confirmation and does not overwrite draft or resend',async()=>{
  const {p,telemetry,dictionary}=await fixture();const saving=p.run('saveBindings()');const sent=dictionary.length;
  telemetry.onDictionary({v:1,boot,id:p.run('dictPending.id'),ok:false,code:'storage_failed'});await saving;
  assert.equal(dictionary.length,sent);assert.equal(p.run('dictionary'),null);assert.match(p.node('dictionary-status').textContent,/storage_failed.*可能已保留/);
});
test('wrong final readback cannot confirm requested meanings',async()=>{
  const {p,telemetry}=await fixture();p.run("draft.open_palm='不同表达';editDirty=true");const saving=p.run('saveBindings()');
  telemetry.onDictionary({...dict,id:p.run('dictPending.id'),bindings:{open_palm:'不同表达',v_sign:''}});await setImmediate();
  telemetry.onDictionary({...dict,id:p.run('dictPending.id'),bindings:{open_palm:'不同表达',v_sign:''}});await saving;
  assert.equal(p.run('dictionary'),null);assert.match(p.node('dictionary-status').textContent,/回读.*不一致/);
});
test('reply deadline is enforced on arrival even if interval was throttled',async()=>{
  const {p,telemetry}=await fixture({autoDict:false});p.time(10000);telemetry.onDictionary(dict);await setImmediate();
  assert.equal(p.run('dictionary'),null);p.tick(10000);await setImmediate();assert.match(p.node('dictionary-status').textContent,/10 秒/);
});
test('dictionary boot changes trigger fresh HP and retire old agent state',async()=>{
  const {p,telemetry}=await fixture({autoDict:false});telemetry.onDictionary(dict);await setImmediate();
  const reading=p.run('readDictionary()');telemetry.onDictionary({...dict,id:p.run('dictPending.id'),boot:'ffffffffffffffff'});await reading;
  assert.equal(p.run('dictionary'),null);assert.equal(p.run('report'),null);assert.equal(p.run('requests.pending.verb'),'get');
});
test('ROM reset cancels writes and refuses old boot HP and old dictionary callbacks',async()=>{
  const {p,report,telemetry}=await fixture();const saving=p.run('saveBindings()');const oldId=p.run('dictPending.id');
  telemetry.onReset('设备重新启动');await saving;
  assert.equal(p.run('dictionary'),null);assert.equal(p.run('agentStream.boot'),null);assert.equal(p.node('save-bindings').disabled,true);
  report({...hp,id:p.run('requests.pending.id'),uptime_ms:2000});assert.equal(p.run('report'),null);
  telemetry.onDictionary({...dict,id:oldId});assert.equal(p.run('dictionary'),null);
});
test('disconnect clears real replies, bindings and camera; late stream cannot restore them',async()=>{
  const {p,telemetry}=await fixture();telemetry.onAgent(ae('connecting'));telemetry.onAgent(ae('sending'));telemetry.onAgent(ae('reply',1,{text:'用户想喝水了。'}));
  assert.equal(p.node('agent-reply').textContent,'用户想喝水了。');await p.run('disconnect()');
  telemetry.onAgent(ae('reply',1,{text:'旧回复'}));telemetry.onDictionary(dict);
  assert.equal(p.run('dictionary'),null);assert.equal(p.run('agentStream.current'),null);assert.equal(p.node('agent-reply').textContent,'真实回复会显示在这里。');
});
test('agent waits for HGD boot and never labels unavailable completion as completed',async()=>{
  const {p,telemetry}=await fixture({autoDict:false});telemetry.onAgent(ae('connecting'));assert.equal(p.run('agentStream.current'),null);
  telemetry.onDictionary(dict);await setImmediate();telemetry.onAgent(ae('connecting'));telemetry.onAgent(ae('sending'));telemetry.onAgent(ae('accepted'));telemetry.onAgent(ae('reply',1,{text:'用户想喝水了。',truncated:true}));telemetry.onAgent(ae('speaking'));telemetry.onAgent(ae('playback_completion_unsupported',1,{code:-1}));
  assert.match(p.node('agent-state').textContent,/不提供播完回执/);assert.match(p.node('agent-detail').textContent,/文本不完整/);assert.equal(p.node('agent-reply').textContent,'用户想喝水了。');
});
test('device max age controls native display while historical counters remain distinct',async()=>{
  const {p,telemetry}=await fixture();telemetry.onHand(hg);assert.equal(p.node('hand-candidate').textContent,'张掌');assert.equal(p.node('palm-count').textContent,'2');
  p.tick(301);assert.equal(p.node('hand-candidate').textContent,'—');assert.equal(p.node('palm-count').textContent,'2');assert.match(p.node('gesture-status').textContent,/最近收到/);
  telemetry.onHand({...hg,seq:2,captured_ms:1900,palm_count:3});assert.match(p.node('gesture-status').textContent,/1 次新增/);
});
test('count rollback invalidates history until a new HP sampling barrier',async()=>{
  const {p,telemetry}=await fixture();telemetry.onHand(hg);telemetry.onHand({...hg,seq:2,captured_ms:1900,palm_count:1});
  assert.equal(p.node('palm-count').textContent,'—');assert.equal(p.run('eventDelta'),0);assert.equal(p.run('requests.pending.verb'),'get');
});
test('camera selects native JPEG, blocks writes, and confirms status again after transfer',async()=>{
  let finish,options;const {p,telemetry}=await fixture({snapshot:o=>{options=o;return new Promise(resolve=>finish=resolve);}});
  telemetry.onHand(hg);const capture=p.run('captureCamera()');assert.equal(options.source,'inputjpeg');assert.equal(p.node('save-bindings').disabled,true);assert.equal(p.node('hand-candidate').textContent,'—');
  finish({width:2,height:2,rgba:new Uint8ClampedArray(16),transferMs:100});await capture;
  assert.equal(p.node('camera-canvas').painted,1);assert.equal(p.run('requests.pending.verb'),'get');assert.equal(p.run('dictionary.bindings.open_palm'),'我想喝水');
});
test('late camera result after disconnect never paints',async()=>{
  let finish;const {p}=await fixture({snapshot:()=>new Promise(resolve=>finish=resolve)});const capture=p.run('captureCamera()');await p.run('disconnect()');
  finish({width:2,height:2,rgba:new Uint8ClampedArray(16)});await capture;assert.equal(p.node('camera-canvas').painted,0);assert.equal(p.run('camera.frame'),null);
});
test('editing draft during read preserves user input and keeps it unsaved',async()=>{
  const {p,telemetry}=await fixture({autoDict:false});p.node('meaning-palm').oninput({target:{value:'我需要帮助'}});telemetry.onDictionary(dict);await setImmediate();
  assert.equal(p.run('draft.open_palm'),'我需要帮助');assert.equal(p.node('binding-badge').textContent,'有未保存修改');assert.equal(p.run('dictionary.bindings.open_palm'),'我想喝水');
});
test('panel navigation waits for USB close and invalidates old callbacks before leaving',async()=>{
  let finishClose;const f=await fixture({close:()=>new Promise(resolve=>finishClose=resolve)}),{p,telemetry}=f;
  const click=navigationClick(),leaving=p.dispatch('click',click);
  assert.equal(click.defaultPrevented,true);assert.equal(f.closed(),1);assert.deepEqual(p.destinations,[]);
  assert.equal(p.run('transport'),null);assert.equal(p.run('dictionary'),null);
  telemetry.onDictionary(dict);telemetry.onAgent(ae('connecting'));
  assert.equal(p.run('dictionary'),null);assert.equal(p.run('agentStream.current'),null);
  const repeated=navigationClick('./setup.html#setup');await p.dispatch('click',repeated);
  assert.equal(repeated.defaultPrevented,true);assert.equal(f.closed(),1);
  finishClose();await leaving;assert.deepEqual(p.destinations,['./setup.html#dictionary']);
});
test('navigation blocks ongoing writes, reads, captures, connection opening and closing',async()=>{
  for(const state of ['saving=true','dictLoading=true','scanRearming=true','camera.busy=true','connecting=true','closing=true']){
    const f=await fixture(),{p}=f,priorCommands=f.dictionary.length;p.run(state);
    const click=navigationClick();await p.dispatch('click',click);
    assert.equal(click.defaultPrevented,true,state);assert.equal(f.closed(),0,state);
    assert.deepEqual(p.destinations,[],state);assert.equal(f.dictionary.length,priorCommands,state);
    assert.match(p.node('notice').textContent,/请等待完成后再切换页面/,state);
  }
});
test('disconnected navigation and modified or new-tab links keep their native behavior',async()=>{
  const p=page(async()=>assert.fail('navigation must not connect'));
  const offline=navigationClick();await p.dispatch('click',offline);assert.equal(offline.defaultPrevented,false);
  const f=await fixture();
  for(const options of [{metaKey:true},{ctrlKey:true},{shiftKey:true},{altKey:true},{button:1},{link:{target:'_blank'}},{link:{hasAttribute:()=>true}}]){
    const click=navigationClick('./setup.html#setup',options);await f.p.dispatch('click',click);assert.equal(click.defaultPrevented,false);
  }
  const skip=navigationClick('#workbench');await f.p.dispatch('click',skip);assert.equal(skip.defaultPrevented,false);
  const current=navigationClick('./index.html');await f.p.dispatch('click',current);assert.equal(current.defaultPrevented,true);
  assert.equal(f.closed(),0);assert.deepEqual(f.p.destinations,[]);
});
test('pagehide stops polling and cancels pending writes; cached restoration never reconnects or replays',async()=>{
  const f=await fixture(),{p,telemetry}=f;const writing=p.run('saveBindings()'),oldId=p.run('dictPending.id');
  const writesBefore=f.dictionary.length,commandsBefore=f.sent.length;
  p.dispatch('pagehide');assert.equal(p.polling(),false);assert.equal(p.run('live()'),false);
  await writing;await setImmediate();
  assert.equal(f.closed(),1);assert.equal(p.run('dictionary'),null);assert.equal(p.run('report'),null);
  telemetry.onDictionary({...dict,id:oldId});telemetry.onAgent(ae('connecting'));p.tick(10000);
  p.dispatch('pageshow',{persisted:true});p.tick(20000);
  assert.equal(p.polling(),true);assert.equal(p.run('transport'),null);assert.equal(p.run('agentStream.current'),null);
  assert.equal(f.dictionary.length,writesBefore);assert.equal(f.sent.length,commandsBefore);
  assert.match(p.node('connection-state').textContent,/尚未连接/);
});
test('a cached page restored while USB is closing cannot follow its old navigation',async()=>{
  let finishClose;const f=await fixture({close:()=>new Promise(resolve=>finishClose=resolve)}),{p}=f;
  const leaving=p.dispatch('click',navigationClick());
  p.dispatch('pagehide');p.dispatch('pageshow',{persisted:true});
  assert.equal(f.closed(),1);assert.equal(p.run('closing'),true);
  finishClose();await leaving;await setImmediate();
  assert.deepEqual(p.destinations,[]);assert.equal(p.run('transport'),null);
  assert.equal(p.run('closing'),false);assert.equal(p.polling(),true);
});

test('camera-time hand telemetry is cached and paired only to its exact JPEG frame',async()=>{
  let finish;const {p,telemetry}=await fixture({snapshot:()=>new Promise(resolve=>finish=resolve)});
  telemetry.onHand(hg);const taking=p.run('captureCamera()');
  telemetry.onHand({...hg,seq:2,captured_ms:2000});assert.equal(p.run('diagnostics.records.length'),2);assert.equal(p.run('diagnostics.records.at(-1).during_camera'),true);
  finish({encoding:'jpeg',capturedMs:2000,width:160,height:120,rgba:new Uint8ClampedArray(160*120*4)});await taking;
  assert.match(p.node('camera-match').textContent,/精确配对同帧.*seq 2/);assert.equal(p.run('camera.match.hand.captured_ms'),2000);
  telemetry.onHand({...hg,seq:3,captured_ms:2500});assert.equal(p.run('camera.match.hand.captured_ms'),2000);
  await p.run('disconnect()');assert.equal(p.run('diagnostics.records.length'),0);assert.equal(p.run('camera.match'),null);
});

const pausedScan={...dict,scan_supported:true,scan_armed:false,scan_generation:1,last_gesture:'open_palm',palm_count:2,v_count:0,agent_busy:false};
test('paused device readback preserves completed gesture and counters without fresh HG or automatic arm',async()=>{
  const {p,telemetry,dictionary}=await fixture({autoDict:false});telemetry.onDictionary(pausedScan);await setImmediate();
  assert.equal(p.node('hand-candidate').textContent,'张掌 · 本轮已确认');assert.equal(p.node('palm-count').textContent,'2');
  p.tick(1300);assert.equal(p.node('hand-candidate').textContent,'张掌 · 本轮已确认');assert.equal(p.node('scan-next').disabled,false);
  assert.equal(dictionary.some(w=>w.endsWith(' arm')),false);assert.match(p.node('hand-status').textContent,/识别已暂停/);
});
test('next round requires explicit arm plus generation-matched readback and does not resend on failure',async()=>{
  const {p,telemetry,dictionary}=await fixture({autoDict:false});telemetry.onDictionary(pausedScan);await setImmediate();
  const starting=p.run('startNext()');assert.match(dictionary.at(-1),/ arm$/);assert.equal(p.node('scan-next').disabled,true);
  telemetry.onDictionary({...pausedScan,id:p.run('dictPending.id'),scan_armed:true,scan_generation:2});await setImmediate();
  assert.match(dictionary.at(-1),/ get$/);assert.doesNotMatch(p.node('notice').textContent,/已开始下一轮/);
  telemetry.onDictionary({...pausedScan,id:p.run('dictPending.id'),scan_armed:true,scan_generation:2});await starting;
  assert.match(p.node('scan-state').textContent,/可以识别/);assert.match(p.node('notice').textContent,/已开始下一轮/);
  assert.equal(dictionary.filter(w=>w.endsWith(' arm')).length,1);
});
test('busy and legacy devices cannot be armed; raw candidates never imply pause support',async()=>{
  const {p,telemetry,dictionary}=await fixture({autoDict:false});telemetry.onDictionary({...pausedScan,agent_busy:true});await setImmediate();
  await p.run('startNext()');assert.equal(dictionary.some(w=>w.endsWith(' arm')),false);assert.equal(p.node('scan-next').disabled,true);assert.match(p.node('scan-state').textContent,/Agent 正在处理/);
  const reading=p.run('readDictionary()');telemetry.onDictionary({...dict,id:p.run('dictPending.id')});await reading;
  telemetry.onHand(hg);assert.match(p.node('scan-state').textContent,/未确认支持单次识别/);assert.equal(p.node('scan-next').disabled,true);
});
test('failed arm produces an unknown-result notice without automatically arming again',async()=>{
  const {p,telemetry,dictionary}=await fixture({autoDict:false});telemetry.onDictionary(pausedScan);await setImmediate();
  const starting=p.run('startNext()');telemetry.onDictionary({v:1,boot,id:p.run('dictPending.id'),ok:false,code:'busy'});await starting;
  assert.equal(dictionary.filter(w=>w.endsWith(' arm')).length,1);assert.match(p.node('notice').textContent,/busy.*回读/);
  assert.equal(p.run('dictionary.scan_armed'),false);
});

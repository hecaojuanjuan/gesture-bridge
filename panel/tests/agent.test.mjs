import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AgentStream,AGENT_DETAILS,parseAgent,parseDictionary,dictionaryCommand,validMeaning} from '../src/agent.mjs';
const boot='0123456789abcdef';
const dictionary={v:1,boot,id:10,ok:true,code:'ok',persisted:true,max_age_ms:1000,bindings:{open_palm:'我想喝水',v_sign:''}};
const event=(state,id=1,extra={})=>({v:1,boot,id,state,code:0,...extra});
test('dictionary validates UTF8 bytes, controls, scalars and exact wire encoding',()=>{
  assert.equal(dictionaryCommand(10,'set','open_palm','我想喝水'),'10 set open_palm e68891e683b3e5969de6b0b4');
  assert.equal(dictionaryCommand(1,'set','v_sign',''),'1 set v_sign -');
  assert.equal(validMeaning('水'.repeat(60)),true);assert.equal(validMeaning('水'.repeat(61)),false);
  for(const s of ['a\nb','a\rb','\u0080','\u009f','\u2028','\u2029','\ud800','\udfff'])assert.equal(validMeaning(s),false);
  assert.equal(validMeaning('✋😀'),true);
  assert.throws(()=>dictionaryCommand(0,'get'));assert.throws(()=>dictionaryCommand(1,'set','other','x'));
});
test('dictionary requires a full successful device report but accepts minimal correlated failures',()=>{
  assert.deepEqual(parseDictionary(dictionary),dictionary);
  for(const patch of [{boot:4},{id:0},{max_age_ms:0},{persisted:'true'},{bindings:{open_palm:'x'}},{code:'busy'}])assert.equal(parseDictionary({...dictionary,...patch}),null);
  assert.ok(parseDictionary({v:1,boot,id:1,ok:false,code:'memory'}));
});
test('agent validates boot, known states and bounded reply fragments',()=>{
  assert.ok(parseAgent(event('reply',1,{text:'用户想喝水了。',truncated:true})));
  for(const patch of [{boot:2},{id:-1},{state:'success'},{code:'0'},{state:'reply'},{state:'reply',text:'x'.repeat(2049)},{state:'reply',text:'x',truncated:'true'}])assert.equal(parseAgent({...event('connecting'),...patch}),null);
});
test('agent only starts a correlated fresh transaction after dictionary confirmation',()=>{
  const s=new AgentStream();assert.equal(s.receive(event('connecting')),false);
  s.confirm(boot);assert.equal(s.receive(event('accepted')),false);
  assert.equal(s.receive(event('connecting',1,{boot:'ffffffffffffffff'})),false);
  assert.equal(s.receive(event('connecting')),true);assert.equal(s.current.id,1);
  s.reset();assert.equal(s.current,null);assert.equal(s.receive(event('reply',1,{text:'old'})),false);
});
test('busy consumes a newer id without stealing the in-flight response',()=>{
  const s=new AgentStream();s.confirm(boot);s.receive(event('connecting'));s.receive(event('sending'));s.receive(event('accepted'));
  s.receive(event('busy',2));assert.equal(s.current.id,1);assert.match(s.note,/请求 2/);
  s.receive(event('reply',1,{text:'用户想喝水了。'}));s.receive(event('speaking'));s.receive(event('playback_completion_unsupported'));
  assert.equal(s.current.text,'用户想喝水了。');assert.equal(s.current.state,'playback_completion_unsupported');
  assert.equal(s.receive(event('connecting',2)),false);assert.equal(s.receive(event('connecting',3)),true);
  assert.equal(s.receive(event('failed',1)),false);assert.equal(s.current.id,3);
});
test('text supports delta and cumulative fragments, duplicate suppression and truncation',()=>{
  const s=new AgentStream();s.confirm(boot);s.receive(event('connecting'));s.receive(event('sending'));
  for(const text of ['用户','用户','用户想喝水','了。','了。'])s.receive(event('reply',1,{text}));
  assert.equal(s.current.text,'用户想喝水了。');
  s.receive(event('reply',1,{text:'片段',truncated:true}));assert.equal(s.current.truncated,true);
  for(let i=0;i<30;i++)s.receive(event('reply',1,{text:String(i)+'水'.repeat(100)}));
  assert.equal(s.current.text.length,2048);assert.equal(s.current.truncated,true);
});
test('terminal and lower-rank states cannot revive completed work or add late text',()=>{
  const s=new AgentStream();s.confirm(boot);s.receive(event('connecting'));s.receive(event('sending'));s.receive(event('speaking'));
  assert.equal(s.receive(event('accepted')),false);
  s.receive(event('playback_completion_unsupported'));assert.equal(s.receive(event('reply',1,{text:'late'})),false);
  assert.equal(s.receive(event('connecting')),false);assert.equal(s.receive(event('cleanup_failed')),true);
});

test('timeout reports retain phase and known session detail without guessing the cause',async()=>{
  const {agentStateLabel}=await import('../src/agent.mjs');
  for(const [phase,label] of [['connecting','建立语音会话超时'],['sending','提交表达超时'],['reply','等待回复超时'],[undefined,'本次表达超时']]){
    const s=new AgentStream();s.confirm(boot);s.receive(event('connecting'));s.receive(event('failed',1,{code:-2,phase,detail:'audio_active'}));
    assert.equal(agentStateLabel(s.current),label);assert.equal(s.current.detail,'audio_active');
  }
});

test('first unavailable report retains its startup failure snapshot and translated detail',()=>{
  const reasons={not_initialized:'语音链路尚未初始化',lifecycle_busy:'会话正在切换，请稍后重试',no_session:'尚无可用会话',
    cloud_disconnected:'设备尚未连接云端',voice_session_active:'已有语音会话占用',tts_pending:'上一段语音仍在结束',
    resource_active:'本地音频播放占用',gesture_session_active:'上一条手势会话尚未释放',start_failed:'语音组件拒绝启动'};
  for(const [detail,label] of Object.entries(reasons)){
    const s=new AgentStream();s.confirm(boot);
    assert.equal(s.receive(event('unavailable',5,{code:-7,phase:'connecting',detail}),123),true);
    assert.equal(s.current.detail,detail);assert.equal(AGENT_DETAILS[s.current.detail],label);
    assert.equal(s.current.code,-7);assert.equal(s.current.phase,'connecting');assert.equal(s.current.at,123);
    assert.equal(s.current.terminal,true);
    assert.equal(s.receive(event('connecting',5,{detail:'ready'})),false);
    assert.equal(s.current.detail,detail);
  }
});

test('first unavailable report accepts legacy firmware and ignores unknown diagnostic values',()=>{
  for(const extra of [{},{detail:'future_reason',phase:'future_phase'},{detail:'__proto__',phase:null}]){
    const s=new AgentStream();s.confirm(boot);
    assert.equal(s.receive(event('unavailable',1,{code:-7,...extra})),true);
    assert.equal(s.current.detail,null);assert.equal(s.current.phase,null);assert.equal(s.current.code,-7);
  }
});

test('single-shot fields are optional for old firmware and strictly validated when supported',()=>{
  const scan={...dictionary,scan_supported:true,scan_armed:false,scan_generation:1,last_gesture:'open_palm',palm_count:2,v_count:0,agent_busy:false};
  assert.ok(parseDictionary(scan));assert.equal(dictionaryCommand(12,'arm'),'12 arm');assert.ok(parseDictionary(dictionary));
  for(const patch of [{scan_armed:'false'},{scan_generation:0},{last_gesture:'five'},{agent_busy:null},{palm_count:-1}])assert.equal(parseDictionary({...scan,...patch}),null);
});

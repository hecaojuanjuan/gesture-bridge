import './style.css';
import './workbench-shell.css';
import {icon} from './setup-art.mjs';
import {RequestTracker,resetReason} from './protocol.mjs';
import {connectSerial} from './serial.js';
import {HandStream,HandDiagnostics,handScores,handProgress,handState,handCandidate,handFresh,handCompletionCounts,HAND_MAX_AGE_MS} from './hand.mjs';
import {AgentStream,AGENT_LABELS,AGENT_DETAILS,agentStateLabel,dictionaryCommand,parseDictionary,validMeaning} from './agent.mjs';
const $=id=>document.getElementById(id);
let transport=null,connecting=false,closing=false,generation=0,report=null,verifiedAt=-Infinity,lastPoll=0,probe=null;
let dictionary=null,dictPending=null,saving=false,dictLoading=false,dictStatus='连接设备后读取当前绑定。',editDirty=false;
let scanRearming=false,lastDictionaryPoll=0;
let sessionRevision=0,lastCounts=null,eventBaseline=null,eventDelta=0;
let pageActive=true,navigating=false,pollTimer=null,disconnectTask=null;
const draft={open_palm:'我想喝水',v_sign:''};
const requests=new RequestTracker(),handStream=new HandStream(),agentStream=new AgentStream();
const diagnostics=new HandDiagnostics(200);
const camera={frame:null,match:null,busy:false,error:'',progress:0,receivedAt:0,sequence:0};
document.querySelector('#app').innerHTML=`
<a class="skip-link" href="#workbench">跳到主要内容</a>
<aside class="panel-sidebar">
  <a href="./index.html" class="brand"><span class="brand-mark">颔</span><span>颔语<small>GESTURE BRIDGE</small></span></a>
  <div class="nav-caption">我的沟通空间</div>
  <nav aria-label="主导航">
    <a class="nav-item" href="./setup.html#setup">${icon('plus')}<span>手势建库</span></a>
    <a class="nav-item" href="./setup.html#dictionary">${icon('book')}<span>我的词典</span></a>
    <a class="nav-item active" href="./index.html" aria-current="page">${icon('monitor')}<span>设备控制</span><i></i></a>
  </nav>
  <div class="sidebar-bottom"><div class="gentle-note"><span class="note-symbol">“</span><p>每一个小动作，<br>都有想说的话。</p><span class="little-line"></span></div>
    <a class="panel-guide" href="./setup.html#setup">${icon('grid',19)} 从图卡开始建库 ${icon('arrow',15)}</a>
    <div class="sidebar-foot">HEADVOICE <span>设备控制 · USB 实机工作台</span></div>
  </div>
</aside>
<div class="workbench-body">
<header class="panel-topbar"><div class="breadcrumb">控制面板 <span>/</span> <strong>设备控制</strong></div><div class="top-actions"><span class="device-tag">${icon('monitor',15)} USB 实机工作台</span><button id="workbench-font" class="size-toggle" aria-pressed="false" aria-label="切换大字模式">A<span>大字</span></button></div></header>
<main id="workbench" tabindex="-1">
  <section class="connection-bar"><div><h1>让手势成为表达</h1><p id="connection-state">尚未连接设备</p></div><div class="actions"><button id="serial-connect" class="primary">连接 USB 设备</button><button id="disconnect" hidden>断开</button><button id="refresh" disabled>重新读取</button></div></section>
  <p id="notice" role="status" aria-live="polite">连接开发板，然后为手势设置固定含义。</p>
  <ol class="steps" aria-label="操作流程"><li><span>01</span>连接设备</li><li><span>02</span>写入手势含义</li><li><span>03</span>做出手势</li><li><span>04</span>听见回应</li></ol>
  <div class="workspace">
    <section class="card binding-card"><div class="card-heading"><div><span class="eyebrow">01 / 固定表达</span><h2>这个手势，代表什么</h2></div><span id="binding-badge" class="badge">未读取</span></div>
      <p class="intro">含义保存到开发板。写入并回读后，设备会将确认的手势交给 Agent。</p>
      <label for="meaning-palm" class="meaning-label"><span class="gesture-icon" aria-hidden="true">✋</span><span>张开手掌<small>open_palm</small></span></label>
      <input id="meaning-palm" type="text" value="我想喝水" maxlength="180" autocomplete="off" placeholder="例如：我想喝水">
      <p id="device-palm" class="device-value">设备当前绑定：未读取</p>
      <label for="meaning-v" class="meaning-label"><span class="gesture-icon" aria-hidden="true">✌</span><span>V 字手势<small>v_sign</small></span></label>
      <input id="meaning-v" type="text" value="" maxlength="180" autocomplete="off" placeholder="暂不使用可留空">
      <p id="device-v" class="device-value">设备当前绑定：未读取</p>
      <div class="actions binding-actions"><button id="save-bindings" class="primary" disabled>保存到设备并核对</button><button id="read-bindings" disabled>读取设备绑定</button></div>
      <p id="dictionary-status" class="status-line" role="status">连接设备后读取当前绑定。</p>
      <p class="hint">每项最多 180 个 UTF-8 字节（约 60 个汉字）。留空即解除该手势绑定。</p>
    </section>
    <section class="card expression-card"><div class="card-heading"><div><span class="eyebrow">02 / 实际表达</span><h2>做出手势，等待回应</h2></div><span id="agent-badge" class="badge">等待</span></div>
      <p class="intro">将手掌放在摄像头前并保持稳定。完成一次表达后移开手，再开始下一次。</p>
      <div class="recognition"><span>当前分类候选</span><strong id="hand-candidate">—</strong><small id="hand-status">等待设备诊断</small></div>
      <div class="counts"><div><span>设备累计张掌</span><strong id="palm-count">—</strong></div><div><span>设备累计 V 字</span><strong id="v-count">—</strong></div></div>
      <p id="gesture-status" class="hint">等待本次连接之后的设备观测。</p>
      <p id="hand-progress" class="status-line">单帧候选不等于手势完成。</p>
      <div class="scan-control"><div><strong id="scan-state">等待设备识别状态</strong><p id="scan-detail" class="hint">设备确认一次手势后暂停，下一轮由你手动开始。</p></div><button id="scan-next" class="primary" disabled>开始下一次</button></div>
      <div class="reply-box"><span class="eyebrow">AGENT 回应</span><p id="agent-state" role="status">等待已确认手势触发</p><blockquote id="agent-reply">真实回复会显示在这里。</blockquote><p id="agent-detail" class="hint">文本来自设备语音事务；实际声音请通过扬声器确认。</p></div>
      <p id="agent-note" class="status-line" role="status"></p>
    </section>
  </div>
  <details class="card diagnostics"><summary>摄像头与连接诊断 <span>按需展开</span></summary><div class="diagnostic-grid">
    <div><div class="camera-screen"><canvas id="camera-canvas" width="160" height="120" hidden aria-label="开发板最近一次摄像头画面"></canvas><span id="camera-empty">尚未获取画面</span></div><div class="actions"><button id="camera-capture" disabled>获取一帧画面</button><span id="camera-stamp" class="hint"></span></div><progress id="camera-progress" max="100" value="0" hidden></progress><p id="camera-status" class="hint">画面只保留在本页，接收时暂停手部观测显示。</p><p id="camera-match" class="hint">尚无可配对画面。</p></div>
    <div><dl class="readings"><div><dt>分类器</dt><dd id="classifier">—</dd></div><div><dt>推理耗时</dt><dd id="infer-time">—</dd></div><div><dt>设备帧龄</dt><dd id="frame-age">—</dd></div><div><dt>设备帧龄上限</dt><dd id="age-limit">600 ms · 兼容默认值</dd></div><div><dt>上次启动</dt><dd id="boot-reason">—</dd></div><div><dt>最近回执</dt><dd id="receipt-age">—</dd></div></dl><p class="hint">分类候选不等于完成事件。累计值只采用设备报告；取图后重新等待状态确认。帧龄不包含 USB 传输延迟。</p></div>
  </div><section class="hand-debug"><div class="card-heading"><h3>最近原始手部观测</h3><button id="hand-export" disabled>导出最近 200 条 JSONL</button></div><p id="hand-debug-age" class="hint">等待观测。</p><dl class="readings debug-readings"><div><dt>原始标签 / Top 1</dt><dd id="hand-raw">—</dd></div><div><dt>Top 1 / 领先第二名</dt><dd id="hand-score">—</dd></div><div><dt>检测分数 / 候选手数</dt><dd id="hand-detect">—</dd></div><div><dt>采样间隔 / 本页接收间隔</dt><dd id="hand-gap">—</dd></div><div><dt>检测有效 / 分类有效</dt><dd id="hand-validity">—</dd></div><div><dt>分类状态码 / confirmed</dt><dd id="hand-flags">—</dd></div><div><dt>gate visible / latched</dt><dd id="hand-gate">—</dd></div><div><dt>候选样本数 / 检测框</dt><dd id="hand-samples">—</dd></div></dl><p id="hand-top3" class="hint"></p><p class="hint">当前源码规则参考：最高分 ≥ 0.80、领先 ≥ 0.20、至少 3 个样本且保持 ≥ 600 ms、连续间隔 ≤ 800 ms。设备没有回报这些确认阈值，页面不据此宣称具体拒绝原因；帧龄上限采用设备回报。</p><p id="hand-log-status" class="hint">本页缓存仅含手部观测；不包含画面、绑定内容、Agent 文本或云端凭据，不上传。断开或重启后清除。</p></section></details>
  <footer>设备绑定与真实回应集中在此页 · 仅使用桌面 Chrome 的 USB 连接<br><a href="./setup.html#setup">体验图卡建库</a><span aria-hidden="true"> · </span><a href="./setup.html#dictionary">查看本机演示词典</a></footer>
</main></div>`;
function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
function now(){return performance.now();}
function live(){return pageActive && !!transport && !!report && now()-verifiedAt<15000;}
function nextId(){return 1+crypto.getRandomValues(new Uint32Array(1))[0]%999999999;}
function matchingDraft(){return !!dictionary && draft.open_palm===dictionary.bindings.open_palm && draft.v_sign===dictionary.bindings.v_sign;}
function clearCamera(){++camera.sequence;camera.frame=null;camera.match=null;camera.busy=false;camera.error='';camera.progress=0;$('camera-canvas').width=160;$('camera-canvas').height=120;}
function cancelDictionary(message){const p=dictPending;dictPending=null;p?.reject(Error(message));}
function resetSession(message='连接设备后读取当前绑定。'){
  ++sessionRevision;cancelDictionary('设备连接状态变化，请重新读取');dictionary=null;agentStream.reset();
  handStream.reset();diagnostics.reset(sessionRevision);lastCounts=null;eventBaseline=null;eventDelta=0;dictStatus=message;clearCamera();
}
function render(){
  const connected=live(),at=now(),maxAge=dictionary?.max_age_ms ?? HAND_MAX_AGE_MS;
  $('connection-state').textContent=connected ? '● USB 已连接 · 设备已响应' : transport ? probe ? '正在等待设备启动…' : 'USB 已打开 · 等待新回执' : '尚未连接设备';
  $('serial-connect').hidden=!!transport;$('serial-connect').disabled=connecting||closing;
  $('disconnect').hidden=!transport;$('refresh').disabled=!transport||saving||dictLoading||camera.busy;
  const locked=!connected||saving||dictLoading||scanRearming||camera.busy||!!dictPending;
  $('save-bindings').disabled=locked||!dictionary||!validMeaning(draft.open_palm)||!validMeaning(draft.v_sign);
  $('read-bindings').disabled=locked;
  $('meaning-palm').disabled=$('meaning-v').disabled=saving;
  $('save-bindings').textContent=saving ? '正在写入并核对…' : '保存到设备并核对';
  $('binding-badge').textContent=!dictionary ? '未读取' : !connected ? '历史回读' : !matchingDraft() ? '有未保存修改' : dictionary.persisted ? '设备已保存' : '设备当前配置';
  $('device-palm').textContent='设备当前绑定：'+(dictionary ? dictionary.bindings.open_palm||'未绑定' : '未读取');
  $('device-v').textContent='设备当前绑定：'+(dictionary ? dictionary.bindings.v_sign||'未绑定' : '未读取');
  $('dictionary-status').textContent=dictStatus;
  const h=!camera.busy&&handStream.enabled ? handStream.hand : null,elapsed=h?at-handStream.receivedAt:0;
  const scanSupported=dictionary?.scan_supported===true,scanPaused=scanSupported&&!dictionary.scan_armed;
  const lastGesture=({open_palm:'张掌',v_sign:'V 字',closed_fist:'握拳'})[dictionary?.last_gesture];
  const counts=scanSupported?{palm:dictionary.palm_count,second:dictionary.v_count}:h?handCompletionCounts(h):null;
  $('hand-candidate').textContent=scanPaused&&lastGesture?lastGesture+' · 本轮已确认':h?handCandidate(h,elapsed,maxAge):'—';
  $('hand-status').textContent=scanPaused?'设备已锁定本轮结果，识别已暂停。':camera.busy?'取图期间暂停诊断':h?handState(h,elapsed,maxAge):'等待设备诊断';
  $('palm-count').textContent=counts?String(counts.palm):'—';$('v-count').textContent=counts?String(counts.second):'—';
  $('gesture-status').textContent=scanSupported?`设备回读累计：张掌 ${counts.palm} / V 字 ${counts.second}。暂停后保留本轮确认，保持手势不会再次触发。`:counts ? `${handFresh(h,elapsed,maxAge)?'设备本次启动累计':'最近收到的累计值'}；本次连接后观察到 ${eventDelta} 次新增张掌完成。` : '等待本次连接之后的设备观测。';
  $('hand-progress').textContent=scanPaused?'设备已暂停本轮识别；保留已确认结果，不再用过期单帧清除它。Agent 失败也不会自动重试。':camera.busy?'取图期间暂停确认状态显示，原始观测继续缓存。':handProgress(h,elapsed,maxAge);
  $('scan-state').textContent=!dictionary?'等待设备识别状态':!scanSupported?'此固件未确认支持单次识别':dictionary.agent_busy?'Agent 正在处理本轮表达':dictionary.scan_armed?'可以识别 · 等待一次确认':'本轮已锁定 · 识别暂停';
  $('scan-detail').textContent=!scanSupported?'请使用支持单次识别的固件；页面不会假装已暂停设备。':`设备轮次 ${dictionary.scan_generation}。${dictionary.agent_busy?'等待语音事务结束后，才能开始下一次。':dictionary.scan_armed?'只有完整确认的手势会锁定本轮。':'放下手并准备好后，再手动开始下一次。'}`;
  $('scan-next').disabled=locked||!scanSupported||dictionary.scan_armed||dictionary.agent_busy;
  $('scan-next').textContent=scanRearming?'正在确认下一轮…':'开始下一次';
  const a=agentStream.current;
  $('agent-badge').textContent=!a?'等待':a.state==='failed'||a.state==='cleanup_failed'?'失败':a.terminal?'已结束':'处理中';
  $('agent-state').textContent=agentStateLabel(a);
  $('agent-reply').textContent=a?.text||'真实回复会显示在这里。';
  $('agent-detail').textContent=a?`请求 ${a.id} · ${Math.max(0,Math.floor((at-a.at)/1000))} 秒前更新${a.code?' · 代码 '+a.code:''}。${a.detail?AGENT_DETAILS[a.detail]+'。':''}${a.truncated?'回复文本不完整。':''}${a.state==='playback_completion_unsupported'?'设备不提供播完回执，请以实际听到的声音为准。':'文本来自设备语音事务；实际声音请通过扬声器确认。'}`:'文本来自设备语音事务；实际声音请通过扬声器确认。';
  $('agent-note').textContent=!connected&&a?'连接回执已过期；以上是最近收到的事务状态。':agentStream.note;
  $('classifier').textContent=h?h.classifier_ready?(h.classifier||'已加载'):'未加载':'—';
  $('infer-time').textContent=h?h.infer_ms+' ms':'—';$('frame-age').textContent=h?h.age_ms+' ms':'—';
  $('age-limit').textContent=maxAge+' ms'+(dictionary?' · 设备报告':' · 兼容默认值');
  $('boot-reason').textContent=report?resetReason(report.reset_reason):'—';$('receipt-age').textContent=report?Math.floor((at-verifiedAt)/1000)+' 秒前':'—';
  $('camera-capture').disabled=!connected||camera.busy||saving||dictLoading||!!dictPending||!!requests.pending;
  $('camera-capture').textContent=camera.busy?'正在接收…':'获取一帧画面';$('camera-canvas').hidden=!camera.frame;$('camera-empty').hidden=!!camera.frame;
  $('camera-progress').hidden=!camera.busy;$('camera-progress').value=camera.progress;
  $('camera-stamp').textContent=camera.frame?`${camera.frame.width} × ${camera.frame.height} · ${Math.floor((at-camera.receivedAt)/1000)} 秒前接收`:'';
  $('camera-status').textContent=camera.error|| (camera.busy?`接收画面 ${camera.progress}%`:'画面只保留在本页，接收时暂停手部观测显示。');
  const matched=camera.match;
  $('camera-match').textContent=!camera.frame?'尚无可配对画面。':matched
    ? `已精确配对同帧：captured_ms ${matched.hand.captured_ms} · seq ${matched.hand.seq} · 检测框 [${matched.hand.box.join(', ')}] · ${matched.hand.gesture} · detection valid=${matched.hand.valid}。这是检测框，分类器按此框裁剪。`
    : '尚未收到同一采集时间与尺寸的 HG 观测，不把当前分类贴到这张历史图上。';
  renderHandDiagnostics(at,maxAge);
}
function renderHandDiagnostics(at,maxAge){
  const entry=diagnostics.records.at(-1),h=entry?.hand,scores=handScores(h);
  const value=v=>v===undefined?'未提供':String(v),percent=v=>(v*100).toFixed(1)+'%';
  $('hand-debug-age').textContent=h?`seq ${h.seq} · epoch ${h.epoch} · captured_ms ${h.captured_ms} · ${((at-entry.received_ms)/1000).toFixed(1)} 秒前接收${entry.during_camera?'（取图期间）':''} · ${handFresh(h,at-entry.received_ms,maxAge)?'帧龄范围内':'已过期，仅历史诊断'}`:'等待当前连接的已确认设备观测。';
  $('hand-raw').textContent=h?`${h.gesture} / ${scores?.top.label??'无有效分数'}`:'—';
  $('hand-score').textContent=scores?`${percent(scores.top.score)} / ${percent(scores.margin)}`:'—';
  $('hand-detect').textContent=h?`${h.detect_score.toFixed(3)} / ${h.hands}`:'—';
  $('hand-gap').textContent=entry?`${entry.capture_gap_ms??'—'} ms / ${entry.receipt_gap_ms===null?'—':Math.round(entry.receipt_gap_ms)} ms`:'—';
  $('hand-validity').textContent=h?`${value(h.valid)} / ${value(h.classification_valid)}`:'—';
  $('hand-flags').textContent=h?`${value(h.classifier_status)} / ${value(h.confirmed)}`:'—';
  $('hand-gate').textContent=h?`${value(h.gate_visible)} / ${value(h.gate_latched)}`:'—';
  $('hand-samples').textContent=h?`${value(h.candidate_samples)} / [${h.box.join(', ')}]`:'—';
  $('hand-top3').textContent=scores?'前三类：'+scores.top3.map(v=>`${v.label} ${percent(v.score)}`).join(' · '):'未提供可用分类分数。';
  $('hand-export').disabled=!diagnostics.records.length;
  $('hand-log-status').textContent=`本页已缓存 ${diagnostics.records.length}/200 条手部观测（包含取图期间）；导出仅含这些字段与同帧配对元数据，不含画面、绑定内容、Agent 文本或云端凭据，不上传。断开或重启后清除。`;
}
function exportHandDiagnostics(){
  if(!diagnostics.records.length)return;
  const text=diagnostics.exportJsonl(camera.frame,camera.match);
  const url=URL.createObjectURL(new Blob([text],{type:'application/x-ndjson;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='gesture-hand-diagnostics.jsonl';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function sendStatus(){
  if(!transport||requests.pending||camera.busy||dictPending) return;
  const id=nextId(),current=transport;
  try{const wire=requests.begin(id,'get',null,now());await current.send(wire);}
  catch(e){if(current===transport&&requests.pending?.id===id){requests.pending=null;notice('读取失败：'+e.message,true);}}
}
function receiveReport(raw){
  const result=requests.receive(raw,now());
  if(!result.matched) return;
  if(result.restarted) resetSession('设备已重启，正在重新读取绑定。');
  report=result.report;verifiedAt=now();lastPoll=now();probe=null;
  diagnostics.confirm(report.boot);
  if(!camera.busy)handStream.confirm(report);
  if(!dictionary&&!dictPending&&!dictLoading&&!saving) void readDictionary();
  render();
}
function receiveHand(raw){
  const entry=diagnostics.receive(raw,now(),camera.busy);
  if(entry&&camera.frame&&entry.hand.captured_ms===camera.frame.capturedMs)camera.match=diagnostics.matchFrame(camera.frame);
  if(!live()||camera.busy){if(entry)render();return;}
  const result=handStream.receive(raw,now());
  if(result.invalidated){lastCounts=null;eventBaseline=null;eventDelta=0;void sendStatus();}
  if(result.accepted){
    const c=handCompletionCounts(handStream.hand);
    if(c){if(eventBaseline===null)eventBaseline=c.palm;eventDelta=Math.max(0,c.palm-eventBaseline);lastCounts=c;}
  }
  if(result.accepted||result.invalidated)render();
}
function receiveDictionary(raw){
  const r=parseDictionary(raw),p=dictPending;
  if(!r||!p||r.id!==p.id||now()-p.at>=10000||!live())return;
  if(p.boot&&r.boot!==p.boot){resetAfterBoot('词典启动标识已变化');return;}
  dictPending=null;
  if(!r.ok)p.reject(Error(`设备拒绝词典操作：${r.code}`));else p.resolve(r);
}
function requestDictionary(verb='get',key,value){
  if(!live()||dictPending||camera.busy||typeof transport?.dictionary!=='function')return Promise.reject(Error('设备尚未就绪，请先重新读取状态。'));
  const id=nextId(),current=transport;let wire;
  try{wire=dictionaryCommand(id,verb,key,value);}catch(e){return Promise.reject(e);}
  return new Promise((resolve,reject)=>{
    dictPending={id,verb,key,value,at:now(),boot:dictionary?.boot??null,resolve,reject};
    void current.dictionary(wire).catch(e=>{if(current===transport&&dictPending?.id===id){dictPending=null;reject(e);}});
  });
}
function installDictionary(r){
  dictionary=r;lastDictionaryPoll=now();agentStream.confirm(r.boot);
  if(!editDirty){draft.open_palm=r.bindings.open_palm;draft.v_sign=r.bindings.v_sign;$('meaning-palm').value=draft.open_palm;$('meaning-v').value=draft.v_sign;}
}
async function readDictionary(silent=false){
  if(dictLoading||saving||scanRearming||dictPending||!live())return;
  dictLoading=true;lastDictionaryPoll=now();const revision=sessionRevision;if(!silent)dictStatus='正在读取设备词典…';render();
  try{const r=await requestDictionary();if(revision!==sessionRevision)return;installDictionary(r);if(!silent)dictStatus=r.persisted?'已读取设备持久化词典。':'已读取设备当前绑定；尚无成功保存到存储的确认。';}
  catch(e){if(revision===sessionRevision){dictStatus=e.message;notice(e.message,true);}}
  finally{dictLoading=false;render();}
}
async function startNext(){
  if(!live()||dictPending||dictLoading||saving||scanRearming||camera.busy||dictionary?.scan_supported!==true||dictionary.scan_armed||dictionary.agent_busy)return;
  scanRearming=true;const revision=sessionRevision;render();
  try{
    const ack=await requestDictionary('arm');if(revision!==sessionRevision)return;
    if(!ack.scan_supported||!ack.scan_armed)throw Error('设备未确认开始下一轮。');
    const readback=await requestDictionary();if(revision!==sessionRevision)return;
    installDictionary(readback);
    if(!readback.scan_supported||!readback.scan_armed||readback.scan_generation!==ack.scan_generation)throw Error('下一轮状态未通过回读核对，请重新读取；不会自动重发。');
    handStream.reset();eventBaseline=null;eventDelta=0;void sendStatus();notice('设备已开始下一轮。准备好后做出一次手势。');
  }catch(e){if(revision===sessionRevision)notice(e.message+' 操作结果需以设备回读为准。',true);}
  finally{scanRearming=false;render();}
}
async function saveBindings(){
  if(saving||dictLoading||scanRearming||dictPending||!dictionary||!live()||camera.busy)return;
  if(!validMeaning(draft.open_palm)||!validMeaning(draft.v_sign)){notice('含义过长或含控制字符，请修改后重试。',true);return;}
  saving=true;const revision=sessionRevision,target={...draft};dictStatus='正在将含义写入设备…';render();
  try{
    // Always store both bindings so a first save also persists firmware defaults.
    for(const key of ['open_palm','v_sign']){
      const r=await requestDictionary('set',key,target[key]);
      if(revision!==sessionRevision)return;
      if(!r.persisted||r.bindings[key]!==target[key])throw Error('设备未确认持久化写入，结果尚未核对。');
    }
    dictStatus='写入已回应，正在重新读取核对…';render();
    const r=await requestDictionary();if(revision!==sessionRevision)return;
    installDictionary(r);
    if(!r.persisted||r.bindings.open_palm!==target.open_palm||r.bindings.v_sign!==target.v_sign)throw Error('设备回读与本次设置不一致，请检查当前绑定。');
    editDirty=false;dictStatus='已写入设备，并通过重新读取确认。重启后保留。';notice('绑定已保存。现在可以做出手势，查看真实回应。');
  }catch(e){if(revision===sessionRevision){dictionary=null;agentStream.reset();dictStatus=e.message+' 请重新读取；此前成功写入的项目可能已保留。';notice(dictStatus,true);}}
  finally{saving=false;render();}
}
function receiveAgent(raw){if(live()&&dictionary&&agentStream.receive(raw,now()))render();}
function resetAfterBoot(message){
  const writing=saving;requests.invalidateBoot();report=null;verifiedAt=-Infinity;resetSession(message+'，等待新回执。');
  lastPoll=now();probe={until:now()+20000,nextAt:now()+2000};void sendStatus();
  notice(message+'。'+(writing?'上次写入结果未知，请重新读取。':'正在重新确认设备。'),true);render();
}
async function connect(){
  if(!pageActive||navigating||transport||connecting||closing)return;
  connecting=true;const token=++generation;render();
  const only=fn=>value=>{if(token===generation)fn(value);};
  try{
    const candidate=await connectSerial(only(receiveReport),only(message=>{void disconnect(message);}),{
      onHand:only(receiveHand),onDictionary:only(receiveDictionary),onAgent:only(receiveAgent),onReset:only(resetAfterBoot)});
    if(token!==generation){await candidate.close();return;}
    transport=candidate;requests.reset();resetSession();report=null;verifiedAt=-Infinity;
    probe={until:now()+20000,nextAt:now()+2000};lastPoll=now();await sendStatus();notice('USB 已打开，正在读取设备状态。');
  }catch(e){if(token===generation){
    const message=e.name==='NotFoundError'?'未选择 USB 设备。'
      : e.name==='NetworkError'||/Failed to open serial port/i.test(e.message??'')
      ? '无法打开 USB 串口，可能正被烧录程序或其他调试窗口占用。关闭占用程序后重试。'
      : e.message;
    notice(message,true);
  }}
  finally{connecting=false;render();}
}
async function disconnect(message='已断开连接。'){
  if(disconnectTask)return disconnectTask;
  const old=transport;transport=null;++generation;requests.reset();probe=null;report=null;verifiedAt=-Infinity;resetSession();closing=true;render();notice(message);
  disconnectTask=(async()=>{try{await old?.close();}catch{}finally{closing=false;disconnectTask=null;render();}})();
  return disconnectTask;
}
async function navigatePanel(event){
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const link=event.target.closest?.('a[href]'),href=link?.getAttribute('href');
  if(!link||link.hasAttribute('download')||(link.target&&link.target!=='_self')||!/^\.\/(?:index\.html|setup\.html(?:#(?:setup|dictionary))?)$/.test(href??''))return;
  if(href==='./index.html'){event.preventDefault();$('workbench').focus({preventScroll:true});return;}
  if(saving||dictLoading||scanRearming||dictPending||camera.busy||connecting||closing||navigating){
    event.preventDefault();notice('当前操作正在进行，请等待完成后再切换页面。',true);return;
  }
  if(!transport)return;
  event.preventDefault();navigating=true;
  await disconnect('USB 连接已关闭，正在切换页面。');
  if(pageActive&&navigating)window.location.assign(href);
}
function suspendPage(){
  pageActive=false;navigating=false;clearInterval(pollTimer);pollTimer=null;
  void disconnect('已离开设备控制。返回后请重新连接 USB 设备。');
}
function resumePage(){
  if(pageActive)return;
  pageActive=true;navigating=false;startPolling();render();
}
async function captureCamera(){
  if(!live()||camera.busy||dictPending||saving||dictLoading||requests.pending)return;
  const current=transport,token=generation,sequence=++camera.sequence;
  const source=handStream.hand?'inputjpeg':undefined;
  camera.busy=true;camera.error='';camera.progress=0;handStream.reset();eventBaseline=null;eventDelta=0;render();
  const active=()=>current===transport&&token===generation&&sequence===camera.sequence;
  try{
    const frame=await current.snapshot({source,onProgress:({received,total})=>{if(active()){camera.progress=total?Math.floor(received/total*100):0;render();}}});
    if(!active())return;
    const canvas=$('camera-canvas');canvas.width=frame.width;canvas.height=frame.height;
    const context=canvas.getContext('2d');if(!context)throw Error('浏览器无法绘制画面');
    const pixels=context.createImageData(frame.width,frame.height);pixels.data.set(frame.rgba);context.putImageData(pixels,0,0);
    camera.frame={...frame,source,session:sessionRevision,hp_boot:diagnostics.boot};camera.match=diagnostics.matchFrame(camera.frame);camera.receivedAt=now();
  }catch(e){if(active())camera.error=e.message;}
  finally{if(active()){camera.busy=false;lastPoll=now();void sendStatus();render();}}
}
$('meaning-palm').oninput=e=>{draft.open_palm=e.target.value;editDirty=true;render();};
$('meaning-v').oninput=e=>{draft.v_sign=e.target.value;editDirty=true;render();};
$('serial-connect').onclick=()=>connect();$('disconnect').onclick=()=>disconnect();
$('save-bindings').onclick=()=>saveBindings();$('read-bindings').onclick=()=>readDictionary();
$('camera-capture').onclick=()=>captureCamera();
$('hand-export').onclick=()=>exportHandDiagnostics();
$('scan-next').onclick=()=>startNext();
$('refresh').onclick=()=>{if(!transport||saving||dictLoading||camera.busy)return;void sendStatus();if(live())void readDictionary();};
$('workbench-font').onclick=()=>{
  const large=document.body.classList.toggle('large-text');
  $('workbench-font').setAttribute('aria-pressed',String(large));
};
document.addEventListener('click',navigatePanel);
window.addEventListener('pagehide',suspendPage);
window.addEventListener('pageshow',resumePage);
function poll(){
  if(!pageActive)return;
  const at=now();
  if(dictPending&&at-dictPending.at>=10000){cancelDictionary('10 秒内未收到词典回执。请检查设备固件是否支持，写入不自动重试。');}
  if(probe){
    if(at>=probe.until){probe=null;requests.pending=null;verifiedAt=-Infinity;notice('20 秒内未收到设备回执，请检查供电与固件后重新读取。',true);}
    else if(at>=probe.nextAt){requests.pending=null;probe.nextAt=at+2000;void sendStatus();}
  }else{
    if(requests.expire(at)){verifiedAt=-Infinity;notice('设备状态回执超时，请检查连接。',true);}
    if(transport&&!requests.pending&&!dictPending&&!camera.busy&&at-lastPoll>=8000){lastPoll=at;void sendStatus();}
    if(dictionary?.scan_supported===true&&!camera.busy&&at-lastDictionaryPoll>=2000)void readDictionary(true);
  }
  render();
}
function startPolling(){if(pollTimer===null)pollTimer=setInterval(poll,250);}
startPolling();
render();

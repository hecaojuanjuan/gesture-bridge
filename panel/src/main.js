import './style.css';
import {MODES, RequestTracker, PoseStream, poseState, resetReason, reportState} from './protocol.mjs';
import {connectSerial} from './serial.js';
import {HandStream, handState, handCandidate, handFresh, handCompletionCounts} from './hand.mjs';
const $ = id => document.getElementById(id);
const swatches = [{name:'湖蓝',rgb:[80,190,255]}, {name:'薄荷',rgb:[75,220,160]},
  {name:'暖橙',rgb:[255,145,60]}, {name:'玫红',rgb:[240,80,130]}, {name:'柔紫',rgb:[160,115,255]}, {name:'白色',rgb:[255,255,255]}];
let draft = {mode:1, brightness:20, rgb:[80,190,255]}, transport = null;
let report = null, receivedAt = 0, verifiedAt = -Infinity, lastPoll = 0, serialNumber = 0;
let connecting = false, closing = false, dirty = false, reportRoundTrip = 0, restarts = 0;
let initialProbe = null;
let transportKind = null, poseMessage = '等待匹配设备回执后接收诊断观测';
const poseStream = new PoseStream();
const handStream = new HandStream();
let visionBackend = null;
const camera = {frame:null, receivedAt:0, busy:false, auto:false, progress:0,
  error:'', nextAt:0, sequence:0};
const requests = new RequestTracker();
document.querySelector('#app').innerHTML = `
<header><a class="brand" href="#"><span class="brand-mark">颔</span><span>颔语 <small>HEADVOICE</small></span></a><a href="./setup.html" style="color:#236555;font-size:14px;text-underline-offset:5px">手势建库 · 设计预览 ↗</a><span class="device-tag">XJWB03 · PID 11785</span></header>
<main>
  <section class="intro"><div><span class="eyebrow">DEVICE STUDIO / 01</span><h1>看见状态，<br>让表达有回应。</h1><p>灯光控制与视觉诊断，汇集在这里。</p></div>
  <aside class="connection"><span id="connection-state" class="connection-label">○ 尚未连接设备</span><p id="connection-detail">连接后读取设备状态。颜色预览不会发送指令。</p><div class="connection-actions"><button id="serial-connect" class="primary">连接 USB 设备 ↗</button><button id="cloud-connect">连接灵机</button><button id="disconnect" hidden>断开</button></div></aside></section>
  <div id="notice" role="status" aria-live="polite">选择颜色，连接设备后应用。</div>
  <section class="card camera-card" aria-labelledby="camera-heading">
    <div class="card-heading"><div><span class="eyebrow">CAMERA VIEW</span><h2 id="camera-heading">摄像头画面</h2></div><span class="pill">USB · 低帧率预览</span></div>
    <div class="camera-layout"><div class="camera-screen" id="camera-screen" aria-busy="false">
      <canvas id="camera-canvas" width="160" height="120" role="img" aria-label="开发板摄像头最近一次接收的画面" hidden></canvas>
      <div class="camera-empty" id="camera-empty"><span class="camera-icon" aria-hidden="true">◎</span><strong>尚未获取画面</strong><span>连接 USB 后，读取开发板摄像头。</span></div>
      <span class="camera-stamp" id="camera-stamp" hidden>最近接收的画面</span>
    </div><div class="camera-controls"><p id="camera-status" role="status" aria-live="polite">连接 USB 后可获取画面。</p>
      <progress id="camera-progress" value="0" max="100" aria-label="画面接收进度" hidden></progress>
      <p class="camera-details" id="camera-details">画面仅保留在本页，不会上传。</p>
      <div class="camera-actions"><button id="camera-capture" class="primary" disabled>获取画面</button><button id="camera-auto" aria-pressed="false" disabled>自动刷新</button></div>
      <p class="hint">每张画面通过 USB 传输需要几秒。接收期间本页无法调灯，设备状态灯和试灯计时继续运行。自动刷新可随时停止，切到其他页面时也会停止。</p>
      <p class="hint">画面预览不代表手势或姿态识别已启用。手机灵机云端暂不支持此画面入口。</p>
    </div></div>
  </section>
  <div class="workspace">
    <section class="card light-card"><div class="card-heading"><div><span class="eyebrow">RGB LIGHT</span><h2>灯光工作台</h2></div><span class="pill">8 颗 WS2812</span></div>
      <div class="light-stage"><div class="ring" id="ring" aria-label="灯光颜色预览">${Array.from({length:8},(_,i)=>`<i style="--i:${i}"></i>`).join('')}<div class="ring-center"><span>COLOR PREVIEW</span><strong id="hex-label">#50BEFF</strong><small>颜色预览</small></div></div><div class="stage-caption"><span id="draft-label">自选颜色 · 20%</span><span id="draft-status">待应用</span></div></div>
      <fieldset><legend>灯光模式</legend><div class="mode-group">${MODES.map((name,i)=>`<button type="button" data-mode="${i}" aria-pressed="${i===1}">${name}</button>`).join('')}</div></fieldset>
      <div id="color-controls"><div class="label-line"><label for="color">选择颜色</label><input id="color" type="color" value="#50beff" aria-label="自定义颜色"></div><div class="swatches">${swatches.map((s,i)=>`<button data-color="${i}" aria-label="${s.name}" title="${s.name}" style="--swatch:rgb(${s.rgb})" aria-pressed="${i===0}"></button>`).join('')}</div><div class="label-line"><label for="brightness">亮度</label><output id="brightness-value">20%</output></div><input id="brightness" type="range" min="0" max="100" step="1" value="20"></div>
      <p class="hint" id="mode-help">调节完成后应用。亮度已限制在适合联调的范围。</p>
      <div class="bottom-actions"><button class="primary" id="apply" disabled>应用到灯板</button><button id="test" disabled>试灯 5 秒</button></div>
      <p class="hint">试灯顺序：红 → 绿 → 蓝 → 白 → 灭，结束后自动恢复。</p>
    </section>
    <div class="right-stack"><section class="card"><div class="card-heading"><div><span class="eyebrow">DEVICE REPORT</span><h2>设备回执</h2></div><button id="refresh" class="text-button" disabled>刷新 ↻</button></div><div class="report-state"><span class="status-dot" id="report-dot"></span><strong id="report-title">等待设备回应</strong></div><dl class="readings"><div><dt>当前模式</dt><dd id="actual-mode">—</dd></div><div><dt>设定亮度</dt><dd id="actual-brightness">—</dd></div><div><dt>最近回执</dt><dd id="actual-time">—</dd></div></dl><p class="hint" id="actual-boot">上次启动：—</p><p class="hint">驱动回执表示设备已处理指令，灯板是否亮起仍需目视确认。</p></section>
    <section class="card pose-card"><div class="card-heading"><div><span class="eyebrow">VISION CHECK</span><h2 id="vision-title">视觉诊断</h2></div><span class="pill" id="stage">未连接</span></div><div class="pose-visual" id="pose-visual" aria-hidden="true" hidden><div class="face" id="face"><b></b><b></b><i></i></div><div class="zero-line"></div><span>眼线倾角</span></div><div class="hand-summary" id="hand-visual" hidden><strong id="hand-readiness">等待手部观测</strong><span id="hand-detection">—</span></div><div class="pose-stats"><div><strong id="pose-tilt">—</strong><span id="pose-primary-label">诊断值</span></div><div><strong id="pose-infer">—</strong><span>推理耗时</span></div><div><strong id="pose-age">—</strong><span>设备报告帧龄</span></div></div><div class="pose-stats pose-stat-pair"><div><strong id="pose-people">—</strong><span id="pose-count-label">检测目标数</span></div><div><strong id="pose-received">—</strong><span>本页最近接收</span></div></div><p id="pose-status" class="pose-status">等待诊断观测</p>
      <div id="hand-completions" class="hand-completions" hidden aria-labelledby="hand-completions-title">
        <h3 id="hand-completions-title">设备本次启动累计</h3>
        <p id="hand-completions-missing" class="hint">设备未提供累计计数。</p>
        <dl id="hand-completions-values" class="hand-counts" hidden><div><dt>张掌</dt><dd id="hand-palm-count">—</dd></div><div><dt id="hand-second-label">—</dt><dd id="hand-second-count">—</dd></div></dl>
        <p id="hand-completions-note" class="hint" hidden>设备确认的累计次数，不是本页观察次数；持续保持同一手势不会重复计数。计数不证明灯圈实际亮起。</p>
      </div>
      <p id="pose-source" class="hint">连接后显示诊断数据来源。</p><p class="hint" id="vision-help">等待设备提供诊断类型。检测到目标不代表动作已识别或播报已生效。</p></section></div>
  </div>
  <section class="legend"><span class="eyebrow">状态指示模式</span><span id="legend-pose" hidden>白 · 中立校准　黄 · 等待确认　蓝 · 正在播放</span><span id="legend-hand" hidden>绿 · 已确认张掌　蓝 · 已确认握拳</span><small id="legend-help">状态灯含义由当前固件决定，等待诊断类型确认。</small></section>
  <footer><span>颔语 / 让细小的动作被听见</span><span>控制设置在设备重启后恢复默认</span></footer>
</main>`;
function notice(text, error=false) { $('notice').textContent=text; $('notice').classList.toggle('error',error); }
function resetPose(message='等待匹配设备回执后接收诊断观测') {
  poseStream.reset(); handStream.reset(); visionBackend=null; poseMessage=message;
}
function receivePose(raw) {
  if (transportKind!=='serial' || camera.busy) return;
  const result=poseStream.receive(raw,performance.now());
  if (result.invalidated) resetPose('诊断时间不连续，等待匹配设备回执重新确认');
  if (result.accepted) {
    if (visionBackend && visionBackend!=='pose') resetPose('诊断类型变化，等待匹配设备回执重新确认');
    else visionBackend='pose';
  }
  if (result.accepted || result.invalidated) render();
}
function receiveHand(raw) {
  if (transportKind!=='serial' || camera.busy) return;
  const result=handStream.receive(raw,performance.now());
  if (result.invalidated) resetPose('手部诊断状态变化，等待匹配设备回执重新确认');
  if (result.accepted) {
    if (visionBackend && visionBackend!=='hand') resetPose('诊断类型变化，等待匹配设备回执重新确认');
    else visionBackend='hand';
  }
  if (result.accepted || result.invalidated) render();
}
function renderPose(now,live) {
  const usb=transportKind==='serial';
  const confirmed=report && requests.boot===report.boot;
  const hand=usb && !camera.busy && visionBackend==='hand' && handStream.enabled ? handStream.hand : null;
  const elapsed=hand ? Math.max(0,now-handStream.receivedAt) : 0;
  let pose=null, at=0;
  if (usb && !camera.busy && visionBackend==='pose' && poseStream.enabled && poseStream.pose) {
    const p=poseStream.pose;
    pose={age_ms:p.age_ms,people:p.people,tilt:p.tilt,tracking:p.tracking_valid,
      valid:p.valid,infer_ms:p.infer_ms};
    at=poseStream.receivedAt;
  } else if (!usb && transport && live && confirmed && report.stage>=2 && report.pose.age_ms<4294967295) {
    pose=report.pose; at=receivedAt;
  }
  const knownPose=!!pose;
  $('vision-title').textContent=hand ? '手部诊断' : knownPose ? '姿态诊断' : '视觉诊断';
  $('stage').textContent=!confirmed ? '未确认' : hand ? '手部检测' : knownPose ? '姿态诊断'
    : report.stage<2 ? ['基线','采集'][report.stage] : '诊断类型未确认';
  $('pose-visual').hidden=!knownPose;
  $('hand-visual').hidden=!hand;
  $('hand-readiness').textContent=hand?.classifier_ready
    ? hand.classifier==='espdl_gesture11' ? '11 类分类器已加载' : '分类器已加载' : '分类器未加载';
  $('hand-detection').textContent=hand
    ? `单手检测${hand.valid ? '有效' : '无效'} · 分数 ${hand.detect_score>0 ? hand.detect_score.toFixed(2) : '—'}${handFresh(hand,elapsed) ? '' : ' · 上次观测已过期'}` : '—';
  // Counts are device telemetry from the accepted observation, never a sum of
  // raw candidates, confirmed flags, or how many messages this page received.
  const counts=hand ? handCompletionCounts(hand) : null;
  $('hand-completions').hidden=!hand;
  $('hand-completions-title').textContent=counts && !handFresh(hand,elapsed)
    ? '最近收到的累计值' : '设备本次启动累计';
  $('hand-completions-missing').hidden=!!counts;
  $('hand-completions-values').hidden=!counts;
  $('hand-completions-note').hidden=!counts;
  $('hand-palm-count').textContent=counts ? String(counts.palm) : '—';
  $('hand-second-label').textContent=counts?.secondLabel ?? '—';
  $('hand-second-count').textContent=counts ? String(counts.second) : '—';
  $('pose-primary-label').textContent=hand ? '分类原始候选' : knownPose ? '二维眼线倾角' : '诊断值';
  $('pose-count-label').textContent=hand ? '手部候选数' : '检测目标数';
  $('pose-tilt').textContent=hand ? handCandidate(hand,elapsed) : pose?.tracking ? pose.tilt.toFixed(1)+'°' : '—';
  $('pose-infer').textContent=hand ? hand.infer_ms+' ms' : pose ? pose.infer_ms+' ms' : '—';
  $('pose-age').textContent=hand ? hand.age_ms+' ms' : pose ? pose.age_ms+' ms' : '—';
  $('pose-people').textContent=hand ? String(hand.hands) : pose ? String(pose.people) : '—';
  $('pose-received').textContent=hand ? (elapsed/1000).toFixed(1)+' 秒前' : pose ? (Math.max(0,now-at)/1000).toFixed(1)+' 秒前' : '—';
  $('face').style.transform=`rotate(${pose?.tracking ? Math.max(-45,Math.min(45,pose.tilt)) : 0}deg)`;
  $('pose-status').textContent=usb && camera.busy ? '画面传输期间暂停视觉诊断显示'
    : hand ? handState(hand,elapsed)
    : pose ? poseState({stage:report.stage,pose},Math.max(0,now-at))
    : !transport ? '等待诊断观测'
    : confirmed && report.stage<2 ? '当前阶段未提供视觉诊断'
    : usb ? poseMessage : '当前云端回执未提供识别后端，无法判断手部模型状态';
  $('pose-source').textContent=hand ? 'USB 手部诊断流 · 检测结果与分类原始候选分开显示；本页不将观测记为动作完成事件。'
    : usb ? 'USB 被动诊断流 · 设备采样时间与本页接收时间分开记录；检测目标的含义由当前模型决定。'
    : transport ? '云端姿态快照 · 每 8 秒查询，不提供实时姿态流；旧回执未标明识别后端，不据阶段推断手势状态。'
    : '连接后显示诊断数据来源。';
  $('vision-help').textContent=hand ? '设备帧龄与本页停留合计超过 600 ms 时，候选清空并标为过期；USB 传输延迟未计入，不能据此保证实时有效。'
    : knownPose ? '设备报告帧龄不包含传输及本页等待时间。400 ms 条件保持不变；诊断观测不代表动作窗口连续，也不表示动作或播报已生效。'
    : '等待设备提供诊断类型。检测到目标不代表动作已识别或播报已生效。';
  $('legend-hand').textContent=hand?.classifier==='espdl_gesture11'
    ? '绿 · 已确认张掌　蓝 · 已确认V字' : '绿 · 已确认张掌　蓝 · 已确认握拳';
  $('legend-hand').hidden=!hand || !hand.classifier_ready;
  $('legend-pose').hidden=!knownPose || report.stage!==3;
  $('legend-help').textContent=hand ? hand.classifier_ready
    ? '训练版状态灯跟随板端稳定确认；原始候选不直接点灯，实际灯效仍需目视核对。'
    : `当前仅检测手部，尚无${hand.classifier==='espdl_gesture11' ? '张掌／V字' : '张掌／握拳'}分类灯效。`
    : knownPose ? report.stage===3 ? '状态灯由动作固件驱动，诊断观测不等于播放完成。' : '当前为姿态诊断阶段，不承诺动作灯效。'
    : '状态灯含义由当前固件决定，尚未确认识别后端。';
}

function clearCamera() {
  ++camera.sequence;
  camera.frame=null; camera.receivedAt=0; camera.busy=false;
  camera.auto=false; camera.progress=0; camera.error=''; camera.nextAt=0;
  // Reset the canvas backing store so a disconnected image is not retained.
  $('camera-canvas').width=160; $('camera-canvas').height=120;
}
function renderCamera(now, live) {
  const supported=typeof transport?.snapshot==='function';
  $('camera-capture').disabled=!supported || !live || camera.busy || !!requests.pending;
  $('camera-auto').disabled=!camera.auto && (!supported || !live || camera.busy || !!requests.pending);
  $('camera-auto').textContent=camera.auto ? '停止刷新' : '自动刷新';
  $('camera-auto').setAttribute('aria-pressed',String(camera.auto));
  $('camera-capture').textContent=camera.busy ? '正在接收…' : '获取画面';
  $('camera-screen').setAttribute('aria-busy',String(camera.busy));
  $('camera-canvas').hidden=!camera.frame;
  $('camera-empty').hidden=!!camera.frame;
  $('camera-stamp').hidden=!camera.frame;
  const ago=Math.max(0,Math.floor((now-camera.receivedAt)/1000));
  $('camera-stamp').textContent=`最近画面 · ${ago} 秒前接收`;
  $('camera-progress').hidden=!camera.busy;
  $('camera-progress').value=camera.progress;
  let status=!transport ? '连接 USB 后可获取画面。' : !supported ? '此连接暂不支持画面，请使用桌面 Chrome 的 USB 连接。'
    : camera.busy ? (camera.progress ? `正在接收画面：${camera.progress}%` : '正在等待摄像头画面…')
    : camera.error ? `获取失败：${camera.error}${camera.frame ? '（保留上次画面）' : ''}`
    : !live ? '等待设备状态确认后可获取画面。'
    : camera.frame ? (camera.auto ? '自动刷新中；每次接收完整画面后更新。' : '已停止刷新；显示最近一次完整画面。')
    : '设备已连接，可以获取画面。';
  $('camera-status').textContent=status;
  $('camera-status').classList.toggle('error',!!camera.error);
  $('camera-details').textContent=camera.frame
    ? `${camera.frame.width} × ${camera.frame.height} · 获取用时 ${(camera.frame.transferMs/1000).toFixed(1)} 秒 · 仅保留在本页`
    : '画面仅保留在本页，不会上传。';
}
async function captureCamera() {
  if (typeof transport?.snapshot!=='function' || camera.busy || requests.pending ||
      performance.now()-verifiedAt>=15000 || document.hidden) return;
  const current=transport, generation=serialNumber, sequence=++camera.sequence;
  const currentRequest=()=>current===transport && generation===serialNumber && sequence===camera.sequence;
  const source=visionBackend==='hand' && handStream.enabled && handStream.hand ? 'inputjpeg' : undefined;
  camera.busy=true; camera.error=''; camera.progress=0;
  resetPose('画面传输结束后，等待匹配设备回执重新接收诊断'); render();
  try {
    const frame=await current.snapshot({source,onProgress:({received,total})=>{
      if (currentRequest()) {camera.progress=total ? Math.floor(received/total*100) : 0;render();}
    }});
    if (!currentRequest()) return;
    const canvas=$('camera-canvas'); canvas.width=frame.width; canvas.height=frame.height;
    const context=canvas.getContext('2d');
    if (!context) throw Error('浏览器无法绘制画面');
    const pixels=context.createImageData(frame.width,frame.height);
    pixels.data.set(frame.rgba); context.putImageData(pixels,0,0);
    camera.frame=frame; camera.receivedAt=performance.now();
  } catch(e) {
    if (currentRequest()) {camera.error=e.message; camera.auto=false;}
  } finally {
    if (currentRequest()) {
      camera.busy=false; camera.nextAt=performance.now()+3000;
      lastPoll=performance.now(); void send('get'); render();
    }
  }
}
function toggleCameraAuto() {
  if (camera.auto) {camera.auto=false;render();return;}
  if (typeof transport?.snapshot!=='function' || camera.busy || requests.pending ||
      performance.now()-verifiedAt>=15000 || document.hidden) return;
  camera.auto=true; void captureCamera();
}
function updateDraft() {
  const hex = '#'+draft.rgb.map(n=>n.toString(16).padStart(2,'0')).join('');
  $('ring').style.setProperty('--light', `rgb(${draft.rgb})`);
  $('ring').classList.toggle('off',draft.mode!==1 || draft.brightness===0);
  $('hex-label').textContent=draft.mode===1 ? hex.toUpperCase() : MODES[draft.mode];
  $('draft-label').textContent=MODES[draft.mode]+(draft.mode===1 ? ` · ${draft.brightness}%` : '');
  $('color').value=hex; $('brightness').value=draft.brightness;
  $('brightness-value').textContent=draft.brightness+'%';
  document.querySelectorAll('[data-mode]').forEach(el=>el.setAttribute('aria-pressed',Number(el.dataset.mode)===draft.mode));
  document.querySelectorAll('[data-color]').forEach(el=>el.setAttribute('aria-pressed',swatches[el.dataset.color].rgb.every((n,i)=>n===draft.rgb[i])));
  $('color-controls').classList.toggle('muted',draft.mode!==1);
  $('color').disabled=$('brightness').disabled=draft.mode!==1;
  document.querySelectorAll('[data-color]').forEach(el=>el.disabled=draft.mode!==1);
  $('mode-help').textContent=['灯光跟随当前固件的状态；确认诊断类型后，下方显示对应说明。','调节完成后应用。亮度已限制在适合联调的范围。','关闭状态指示和自选灯光；试灯仍可单独运行。'][draft.mode];
}
function render() {
  const now=performance.now(), live=!!transport && now-verifiedAt < 15000;
  const synced=live && report?.ok && requests.boot===report.boot &&
    draft.mode===report.mode && draft.brightness===report.brightness &&
    draft.rgb.every((v,i)=>v===report.rgb[i]);
  $('draft-status').textContent=requests.pending?.verb==='set' ? '等待回执' : synced ? '已同步' : '待应用';
  $('connection-state').textContent=transport ? `${live ? '●' : '○'} ${transport.name}${live ? ' · 设备已响应' : initialProbe ? ' · 设备启动中，等待回执' : ' · 等待设备回执'}` : '○ 尚未连接设备';
  $('connection-detail').textContent=initialProbe ? 'USB 已打开，正在读取状态；设备启动期间会在 20 秒内重试读取。' : transport ? '以设备返回的状态为准；无回执时不会显示执行成功。' : '连接后读取设备状态。颜色预览不会发送指令。';
  $('serial-connect').hidden=$('cloud-connect').hidden=!!transport;
  $('serial-connect').disabled=$('cloud-connect').disabled=connecting || closing;
  $('disconnect').hidden=!transport;
  $('apply').disabled=$('test').disabled=!live || !!requests.pending || camera.busy;
  $('refresh').disabled=!transport || !!requests.pending || camera.busy;
  $('report-dot').classList.toggle('live',live && report?.ok);
  $('report-title').textContent=reportState(report,live,now-receivedAt,reportRoundTrip);
  $('actual-mode').textContent=report ? MODES[report.mode] : '—';
  $('actual-brightness').textContent=report ? report.brightness+'%' : '—';
  $('actual-time').textContent=report ? `${Math.floor((now-receivedAt)/1000)} 秒前` : '—';
  $('actual-boot').textContent=report && requests.boot===report.boot
    ? `上次启动：${resetReason(report.reset_reason)}${restarts ? ` · 本次连接已确认 ${restarts} 次重启` : ''}`
    : '上次启动：等待匹配回执';
  renderPose(now,live);
  renderCamera(now,live);
}
function receive(raw) {
  const now=performance.now();
  const result=requests.receive(raw,now);
  if (!result.report) return;
  // Cloud snapshots may arrive out of order or from a previous device boot.
  // Only correlated replies may replace an already displayed report.
  if (report && !result.matched) return;
  report=result.report; receivedAt=now;
  reportRoundTrip=result.matched ? result.roundTripMs : 0;
  // Preserve the device-reported age. Receipt elapsed time is shown separately;
  // neither value is a claim about current freshness across transport delays.
  if (result.matched) {
    verifiedAt=receivedAt;
    if (initialProbe) { initialProbe=null; lastPoll=now; }
    if (result.restarted) {++restarts; clearCamera(); resetPose();}
    if (transportKind==='serial' && !camera.busy) {
      const poseConfirmed=poseStream.confirm(report), handConfirmed=handStream.confirm(report);
      if (poseConfirmed || handConfirmed) poseMessage='等待此状态确认之后采样的 USB 诊断观测';
    }
    if (!dirty && result.verb==='get') { draft={mode:report.mode,brightness:report.brightness,rgb:[...report.rgb]}; updateDraft(); }
    const outcome=result.applied ? (result.verb==='get' ? '已收到设备当前状态。' : result.verb==='test' ? '已收到试灯回执；设备计时 5 秒后恢复，以刷新后的回执为准。' : '设备已执行灯光设置，请目视核对灯板。') : '设备未成功执行，请检查固件与 RGB 接线。';
    notice((result.restarted ? `设备已重新启动（${resetReason(report.reset_reason)}）。` : '')+outcome,!result.applied);
    if (result.applied && result.verb==='set') dirty=!(draft.mode===report.mode &&
      draft.brightness===report.brightness && draft.rgb.every((v,i)=>v===report.rgb[i]));
  }
  render();
}
async function send(verb) {
  if (!transport || requests.pending || camera.busy) return;
  const id = 1 + (crypto.getRandomValues(new Uint32Array(1))[0] % 999999999);
  const current=transport;
  try {
    const wire=requests.begin(id,verb,draft,performance.now());
    notice(verb==='get' ? initialProbe ? '正在等待设备启动并读取状态…' : '正在读取设备状态…' : '指令已提交，等待设备回执…'); render();
    await current.send(wire);
  } catch(e) { if (current===transport && requests.pending?.id===id) { requests.pending=null; notice('发送失败：'+e.message,true); render(); } }
}
async function disconnect(message='已断开连接。') {
  const old=transport; transport=null; transportKind=null; ++serialNumber; requests.reset(); verifiedAt=-Infinity; initialProbe=null;
  resetPose();
  clearCamera();
  closing=true;
  render(); notice(message);
  try { await old?.close(); } catch { /* A removed serial port may already be closed. */ }
  finally { closing=false; render(); }
}
async function connect(kind) {
  if (connecting || closing || transport) return;
  connecting=true; const generation=++serialNumber; render();
  const onReport=data=>{ if (generation===serialNumber) receive(data); };
  const lost=message=>{ if (generation===serialNumber) void disconnect(message); };
  const onPose=data=>{ if (generation===serialNumber) receivePose(data); };
  const onHand=data=>{ if (generation===serialNumber) receiveHand(data); };
  const onReset=message=>{ if (generation===serialNumber) {
    const writePending=requests.pending && requests.pending.verb!=='get';
    requests.invalidateBoot(); report=null; receivedAt=0; reportRoundTrip=0;
    verifiedAt=-Infinity; lastPoll=performance.now();
    resetPose(message+'，等待匹配设备回执重新确认'); clearCamera();
    if (transportKind==='serial') {
      initialProbe={until:lastPoll+20000,nextAt:lastPoll+2000};
      void send('get');
    }
    notice(message+'，等待新的设备回执。'+
      (writePending ? '上一条写入结果未知，不会自动重发。' : ''),true);
    render();
  }};
  try {
    const candidate=kind==='serial' ? await connectSerial(onReport,lost,{onPose,onHand,onReset}) :
      (await import('./cloud.js')).connectCloud(onReport,lost,()=>{ if (transport && generation===serialNumber) void send('get'); });
    // A loss callback may fire while opening the port or initializing the SDK.
    // Such a candidate must be closed instead of becoming a ghost connection.
    if (generation!==serialNumber) { await candidate.close(); return; }
    transport=candidate; transportKind=kind; resetPose();
    requests.reset(); report=null; verifiedAt=-Infinity; restarts=0; reportRoundTrip=0; lastPoll=performance.now();
    // Opening USB can reset the board and lose the first command. Keep the
    // same port open and probe only the side-effect-free get while it boots.
    initialProbe=kind==='serial' ? {until:lastPoll+20000,nextAt:lastPoll+2000} : null;
    await send('get');
  } catch(e) { if (generation===serialNumber) notice(e.name==='NotFoundError' ? '未选择串口，尚未连接。' : e.message,true); }
  finally { connecting=false; render(); }
}
document.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>{draft.mode=Number(el.dataset.mode);dirty=true;updateDraft();});
document.querySelectorAll('[data-color]').forEach(el=>el.onclick=()=>{draft.rgb=[...swatches[el.dataset.color].rgb];dirty=true;updateDraft();});
$('color').oninput=e=>{draft.rgb=e.target.value.slice(1).match(/../g).map(s=>parseInt(s,16));dirty=true;updateDraft();};
$('brightness').oninput=e=>{draft.brightness=Number(e.target.value);dirty=true;updateDraft();};
$('apply').onclick=()=>send('set'); $('test').onclick=()=>send('test'); $('refresh').onclick=()=>send('get');
$('serial-connect').onclick=()=>connect('serial'); $('cloud-connect').onclick=()=>connect('cloud');
$('disconnect').onclick=()=>disconnect();
$('camera-capture').onclick=()=>captureCamera();
$('camera-auto').onclick=()=>toggleCameraAuto();
document.addEventListener?.('visibilitychange',()=>{
  if (document.hidden) {camera.auto=false;render();}
});
setInterval(()=>{
  const now=performance.now();
  if (initialProbe) {
    if (now>=initialProbe.until) {
      initialProbe=null;
      if (requests.pending?.verb==='get') requests.pending=null;
      verifiedAt=-Infinity; lastPoll=now;
      notice('20 秒内未收到设备回执。USB 已打开，请检查供电与固件后刷新。',true);
    } else if (now>=initialProbe.nextAt && (!requests.pending || requests.pending.verb==='get')) {
      requests.pending=null; initialProbe.nextAt=now+2000;
      void send('get');
    }
  } else {
    if(requests.expire(now)) {
      verifiedAt=-Infinity; lastPoll=now;
      notice('10 秒内未收到匹配回执，执行结果未知。请检查设备后刷新。',true);
    }
    if(transport && !requests.pending && !camera.busy && now-lastPoll>=8000) {lastPoll=now;void send('get');}
  }
  if (camera.auto && !camera.busy && now>=camera.nextAt && !document.hidden) void captureCamera();
  render();
},250);
updateDraft(); render();
if (window.ReactNativeWebView || window.__wxjs_environment==='miniprogram' || /MicroMessenger/i.test(navigator.userAgent)) void connect('cloud');

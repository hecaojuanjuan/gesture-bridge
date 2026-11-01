export const HAND_MAX_AGE_MS = 600;
export const GESTURE11_LABELS = Object.freeze(['one','two','three','four','five','like','ok','no_gesture','call','dislike','no_hand']);
const LEGACY_CLASSES = ['open_palm','closed_fist','other'];
const LEGACY_LABELS = new Set(['untrained','unknown','no_hand',...LEGACY_CLASSES]);
const NATIVE_LABELS = new Set(['untrained','unknown','unavailable',...GESTURE11_LABELS]);
const GATE_LABELS = new Set(['unknown','no_hand','open_palm','closed_fist','other','v_sign']);
const integer = (n,max=Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(n) && n>=0 && n<=max;
const score = n => Number.isFinite(n) && n>=0 && n<=1;

// HG observations are diagnostics, not completed gesture events. The original
// detector-only firmware omits every optional classifier/gate field below.
export function parseHand(raw) {
  let h;
  try { h=typeof raw==='string' ? JSON.parse(raw) : raw; } catch { return null; }
  const native=h?.classifier==='espdl_gesture11';
  if (h?.classifier!==undefined && !['espdl_gesture11','tiny_cnn3'].includes(h.classifier)) return null;
  const classes=native ? GESTURE11_LABELS : LEGACY_CLASSES;
  const labels=native ? NATIVE_LABELS : LEGACY_LABELS;
  if (!h || h.v!==1 || h.event!=='observation' || !integer(h.seq,4294967295) ||
      !integer(h.captured_ms) || !integer(h.age_ms) || !integer(h.captured_ms+h.age_ms) ||
      !integer(h.epoch,4294967295) || !integer(h.width,4096) || !integer(h.height,4096) ||
      !integer(h.hands,4294967295) || typeof h.valid!=='boolean' ||
      typeof h.classifier_ready!=='boolean' || !labels.has(h.gesture) || !score(h.detect_score) ||
      !integer(h.infer_ms,4294967295) || !Array.isArray(h.box) || h.box.length!==4 ||
      h.box.some(n=>!integer(n,4096))) return null;
  const [x1,y1,x2,y2]=h.box;
  const boxValid=x1<x2 && y1<y2 && x2<=h.width && y2<=h.height;
  if ((!boxValid && h.box.some(n=>n!==0)) ||
      (h.valid && (h.hands!==1 || !boxValid || h.detect_score<.5))) return null;
  if (['conversion_ms','detect_ms','classifier_ms','candidate_samples','palm_count','fist_count','v_count']
      .some(key=>h[key]!==undefined && !integer(h[key],4294967295)) ||
      ['classification_valid','confirmed'].some(key=>h[key]!==undefined && typeof h[key]!=='boolean') ||
      ['gate_visible','gate_latched'].some(key=>h[key]!==undefined && !GATE_LABELS.has(h[key])) ||
      (h.classifier_status!==undefined && !integer(h.classifier_status,255)) ||
      ((native || h.scores!==undefined) && (!Array.isArray(h.scores) || h.scores.length!==classes.length || !h.scores.every(score)))) return null;
  if (!h.classifier_ready && (!(h.gesture==='untrained' || (native && ['unknown','unavailable'].includes(h.gesture))) || h.classification_valid===true || h.confirmed===true ||
      h.scores?.some(n=>n!==0))) return null;
  if (h.classifier_ready && ['untrained','unavailable'].includes(h.gesture)) return null;
  if (h.classification_valid===true) {
    const index=classes.indexOf(h.gesture);
    if (!h.valid || !h.classifier_ready || index<0 || !h.scores ||
        (h.classifier_status!==undefined && h.classifier_status!==0)) return null;
    const total=h.scores.reduce((a,b)=>a+b,0);
    // Both adapters emit float probabilities. Native logits are int8, but
    // its postprocessor applies softmax before telemetry. Allow six-decimal
    // printing error without normalizing or changing the raw winning label.
    if (Math.abs(total-1)>.001 ||
        h.scores[index]+.000002<Math.max(...h.scores)) return null;
  }
  // A retained gate_latched may describe an earlier action. Never treat it,
  // candidate counters, or raw gesture labels as a new completion event.
  if (h.confirmed===true && h.classification_valid!==true) return null;
  return h;
}

// Firmware increments these counters only when its confirmation gate emits an
// event. They belong to the device's inference task (one per boot), not this
// page or the number of observations. A stale observation can still describe
// historical totals; the caller must label it as the last received value.
export function handCompletionCounts(raw) {
  const h=parseHand(raw);
  if (!h) return null;
  const native=h.classifier==='espdl_gesture11';
  const second=native ? h.v_count : h.fist_count;
  if (!integer(h.palm_count,4294967295) || !integer(second,4294967295)) return null;
  return {palm:h.palm_count,second,secondLabel:native ? 'V字' : '握拳'};
}

export function handFresh(h,elapsed=0,maxAge=HAND_MAX_AGE_MS) {
  return !!h && Number.isFinite(elapsed) && elapsed>=0 && Number.isFinite(maxAge) && maxAge>0 && h.age_ms+elapsed<=maxAge;
}
export function handCandidate(h,elapsed=0,maxAge=HAND_MAX_AGE_MS) {
  if (!handFresh(h,elapsed,maxAge) || !h.classifier_ready || !h.valid || h.classification_valid!==true) return '—';
  if (h.classifier==='espdl_gesture11') return ({one:'单指（非目标）',two:'V字',three:'三指（非目标）',
    four:'四指（非目标）',five:'张掌',like:'点赞（非目标）',ok:'OK（非目标）',
    no_gesture:'其他手型（非目标）',call:'电话手势（非目标）',dislike:'倒拇指（非目标）',
    no_hand:'模型判无手（非目标）'})[h.gesture] ?? '—';
  return ({open_palm:'张掌',closed_fist:'握拳',other:'其他'})[h.gesture] ?? '—';
}
export function handState(h,elapsed=0,maxAge=HAND_MAX_AGE_MS) {
  if (!h) return '等待手部诊断观测';
  const native=h.classifier==='espdl_gesture11';
  const classifier=h.classifier_ready
    ? native ? '11 类分类器已加载；目标为张掌和V字，原始候选不代表动作完成' : '分类器已加载；原始候选不代表动作完成'
    : `分类器未加载，尚不能识别${native ? '张掌或V字' : '张掌或握拳'}`;
  if (!handFresh(h,elapsed,maxAge)) return `观测已过期：设备帧龄与本页停留合计超过 ${maxAge} ms；${classifier}`;
  const detection=h.hands===0 ? '本帧未检出手' : h.hands!==1 ? `本帧有 ${h.hands} 个候选，不作单手分类`
    : h.valid ? '本帧检测到有效单手' : '本帧单手候选未通过有效性检查';
  return `${detection}；${classifier}`;
}

export class HandStream {
  constructor() { this.reset(); }
  reset() {
    this.enabled=false; this.boot=null; this.hand=null; this.receivedAt=0;
    this.afterCapture=0; this.lastCapture=null; this.lastReportedAt=null; this.lastSequence=null; this.epoch=null;
    this.lastCounts=null; this.classifierSchema=null;
  }
  confirm(report) {
    if (!report || !integer(report.boot,4294967295) || !integer(report.uptime_ms) || !integer(report.stage,3) || report.stage<2) {
      this.reset(); return false;
    }
    if (this.enabled && this.boot===report.boot) return false;
    this.reset(); this.enabled=true; this.boot=report.boot; this.afterCapture=report.uptime_ms;
    return true;
  }
  receive(raw,receivedAt) {
    const h=parseHand(raw);
    if (!h || !this.enabled || !Number.isFinite(receivedAt) || receivedAt<0) return {accepted:false};
    const reportedAt=h.captured_ms+h.age_ms;
    const schema=h.classifier==='espdl_gesture11' ? 'native11' : 'legacy3';
    const counts=handCompletionCounts(h);
    const countsBackwards=counts && this.lastCounts?.secondLabel===counts.secondLabel &&
      (counts.palm<this.lastCounts.palm || counts.second<this.lastCounts.second);
    if ((this.lastCapture!==null && h.captured_ms<=this.lastCapture) ||
        (this.lastReportedAt!==null && reportedAt<this.lastReportedAt) ||
        (this.lastSequence!==null && h.seq<=this.lastSequence) ||
        (this.epoch!==null && h.epoch!==this.epoch) || receivedAt<this.receivedAt || countsBackwards ||
        (this.classifierSchema!==null && this.classifierSchema!==schema)) {
      this.reset(); return {accepted:false,invalidated:true};
    }
    if (h.captured_ms<=this.afterCapture) return {accepted:false};
    this.hand=h; this.receivedAt=receivedAt; this.lastCapture=h.captured_ms;
    this.lastReportedAt=reportedAt; this.lastSequence=h.seq; this.epoch=h.epoch;
    this.classifierSchema=schema;
    // A missing counter stays missing in the UI; retain the last complete pair
    // only as an ordering guard, never as replacement data for this observation.
    if (counts) this.lastCounts=counts;
    return {accepted:true};
  }
}

// Capture only known hand telemetry. Never export arbitrary serial lines,
// device/cloud configuration, text replies, image pixels or unknown fields.
const HAND_EXPORT_FIELDS=['v','event','seq','captured_ms','age_ms','epoch','width','height','hands','box',
  'detect_score','valid','classifier','classifier_ready','gesture','scores','classification_valid',
  'classifier_status','confirmed','gate_visible','gate_latched','candidate_samples','palm_count','fist_count',
  'v_count','infer_ms','conversion_ms','detect_ms','classifier_ms'];
export function handScores(h) {
  if(!h?.scores?.length || !h.scores.every(score) || !h.scores.some(n=>n>0)) return null;
  const labels=h.classifier==='espdl_gesture11'?GESTURE11_LABELS:LEGACY_CLASSES;
  if(h.scores.length!==labels.length)return null;
  const ranked=h.scores.map((value,index)=>({label:labels[index],score:value})).sort((a,b)=>b.score-a.score);
  return {top:ranked[0],second:ranked[1],margin:ranked[0].score-ranked[1].score,top3:ranked.slice(0,3)};
}
export function handProgress(h,elapsed=0,maxAge=HAND_MAX_AGE_MS) {
  if(!h)return '等待观测；单帧候选不等于手势完成。';
  if(!handFresh(h,elapsed,maxAge))return '最近观测已过期，不能据此判断当前保持状态；累计值只代表设备已报告的历史完成次数。';
  if(!h.classifier_ready)return '设备报告分类器未就绪，尚不能确认手势。';
  if(h.classification_valid!==true)return '设备未报告本帧分类有效；请结合检测、帧龄与分类状态查看，不能只凭画面推断原因。';
  const target=h.classifier==='espdl_gesture11'?{five:'open_palm',two:'v_sign'}[h.gesture]:{open_palm:'open_palm',closed_fist:'closed_fist'}[h.gesture];
  if(!target)return `原始分类 ${h.gesture} 不是当前目标手势，本帧不会触发表达。`;
  if(h.confirmed===true)return '设备报告处于已确认状态；持续保持不会重复计数。新增完成以设备累计变化为准。';
  if(h.gate_latched===target)return '设备仍保留此手势的锁存状态，不能将它当作新的完成；请结合后续移开手与累计变化观察。';
  return `当前只是单帧候选；设备尚未报告确认${h.candidate_samples!==undefined?`，候选样本数 ${h.candidate_samples}`:''}。持续保持与连续输入是否满足，需结合后续观测判断。`;
}
export class HandDiagnostics {
  constructor(limit=200){this.limit=Math.max(1,Math.min(200,Math.floor(limit)||200));this.reset(0);}
  reset(session){this.session=session;this.boot=null;this.records=[];this.segment=0;}
  confirm(bootId){
    if(!integer(bootId,4294967295))return false;
    if(this.boot!==null&&this.boot!==bootId){this.records=[];this.segment=0;}
    this.boot=bootId;return true;
  }
  receive(raw,receivedAt,duringCamera=false){
    const h=parseHand(raw);
    if(!h||this.boot===null||!Number.isFinite(receivedAt)||receivedAt<0)return null;
    const previous=this.records.at(-1);
    const continuous=previous&&previous.hand.epoch===h.epoch&&previous.hand.seq<h.seq&&
      previous.hand.captured_ms<h.captured_ms&&previous.received_ms<=receivedAt;
    if(previous&&!continuous)++this.segment;
    const hand=Object.fromEntries(HAND_EXPORT_FIELDS.filter(key=>h[key]!==undefined)
      .map(key=>[key,Array.isArray(h[key])?[...h[key]]:h[key]]));
    const record={type:'hand_observation',session:this.session,hp_boot:this.boot,segment:this.segment,
      received_ms:receivedAt,during_camera:!!duringCamera,
      capture_gap_ms:continuous?h.captured_ms-previous.hand.captured_ms:null,
      receipt_gap_ms:continuous?receivedAt-previous.received_ms:null,hand};
    this.records.push(record);if(this.records.length>this.limit)this.records.shift();return record;
  }
  matchFrame(frame){
    if(!frame||frame.encoding!=='jpeg'||frame.source!=='inputjpeg'||frame.session!==this.session||frame.hp_boot!==this.boot)return null;
    const matches=this.records.filter(r=>r.session===frame.session&&r.hp_boot===frame.hp_boot&&
      r.hand.captured_ms===frame.capturedMs&&r.hand.width===frame.width&&r.hand.height===frame.height);
    // A duplicate timestamp across segments is ambiguous; never pick a box.
    return matches.length===1?matches[0]:null;
  }
  exportJsonl(frame,matched){
    const rows=[{type:'hand_diagnostics',v:1,session:this.session,hp_boot:this.boot,count:this.records.length,
      scope:'Current USB connection only; hand observations and camera metadata; no image, cloud configuration or reply text.'},...this.records];
    if(frame&&frame.session===this.session&&frame.hp_boot===this.boot){
      const exact=frame.source==='inputjpeg'&&frame.encoding==='jpeg'&&matched&&matched.session===frame.session&&matched.hp_boot===frame.hp_boot&&
        matched.hand.captured_ms===frame.capturedMs&&matched.hand.width===frame.width&&matched.hand.height===frame.height;
      rows.push({type:'camera_metadata',session:frame.session,hp_boot:frame.hp_boot,source:frame.source,
        encoding:frame.encoding,width:frame.width,height:frame.height,captured_ms:frame.capturedMs,
        matched:exact?{seq:matched.hand.seq,epoch:matched.hand.epoch,box:[...matched.hand.box],valid:matched.hand.valid,
          gesture:matched.hand.gesture,classification_valid:matched.hand.classification_valid}:null});
    }
    return rows.map(row=>JSON.stringify(row)).join('\n')+'\n';
  }
}

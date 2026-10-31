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

export function handFresh(h,elapsed=0) {
  return !!h && Number.isFinite(elapsed) && elapsed>=0 && h.age_ms+elapsed<=HAND_MAX_AGE_MS;
}
export function handCandidate(h,elapsed=0) {
  if (!handFresh(h,elapsed) || !h.classifier_ready || !h.valid || h.classification_valid!==true) return '—';
  if (h.classifier==='espdl_gesture11') return ({one:'单指（非目标）',two:'V字',three:'三指（非目标）',
    four:'四指（非目标）',five:'张掌',like:'点赞（非目标）',ok:'OK（非目标）',
    no_gesture:'其他手型（非目标）',call:'电话手势（非目标）',dislike:'倒拇指（非目标）',
    no_hand:'模型判无手（非目标）'})[h.gesture] ?? '—';
  return ({open_palm:'张掌',closed_fist:'握拳',other:'其他'})[h.gesture] ?? '—';
}
export function handState(h,elapsed=0) {
  if (!h) return '等待手部诊断观测';
  const native=h.classifier==='espdl_gesture11';
  const classifier=h.classifier_ready
    ? native ? '11 类分类器已加载；目标为张掌和V字，原始候选不代表动作完成' : '分类器已加载；原始候选不代表动作完成'
    : `分类器未加载，尚不能识别${native ? '张掌或V字' : '张掌或握拳'}`;
  if (!handFresh(h,elapsed)) return `观测已过期：设备帧龄与本页停留合计超过 600 ms；${classifier}`;
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

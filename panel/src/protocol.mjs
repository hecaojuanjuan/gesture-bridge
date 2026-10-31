export const MODES = ['状态指示', '自选颜色', '熄灯'];
export function parseReport(raw) {
  let r;
  try { r = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { return null; }
  const integer = (n, min, max) => Number.isInteger(n) && n >= min && n <= max;
  const rgb = a => Array.isArray(a) && a.length === 3 && a.every(n => integer(n, 0, 255));
  if (!r || r.v !== 1 || !integer(r.id, 0, 999999999) || !integer(r.boot, 0, 4294967295) ||
      typeof r.ok !== 'boolean' || !integer(r.uptime_ms, 0, Number.MAX_SAFE_INTEGER) ||
      !integer(r.mode, 0, 2) || !integer(r.brightness, 0, 100) || !rgb(r.rgb) || !rgb(r.output) ||
      !integer(r.test_ms, 0, 5000) || !integer(r.stage, 0, 3) || !r.pose ||
      (r.reset_reason !== undefined && !integer(r.reset_reason, 0, 255)) ||
      !integer(r.pose.age_ms, 0, Number.MAX_SAFE_INTEGER) || !integer(r.pose.people, 0, 1000) ||
      !Number.isFinite(r.pose.tilt) || typeof r.pose.tracking !== 'boolean' ||
      typeof r.pose.valid !== 'boolean' || !integer(r.pose.infer_ms, 0, 4294967295)) return null;
  return r;
}
export function command(id, verb, draft) {
  if (!Number.isInteger(id) || id < 1 || id > 999999999) throw Error('无效请求编号');
  if (verb === 'get' || verb === 'test') return `${id} ${verb}`;
  if (verb !== 'set' || !Number.isInteger(draft?.mode) || draft.mode < 0 || draft.mode > 2 ||
      !Number.isInteger(draft.brightness) || draft.brightness < 0 || draft.brightness > 100 ||
      !Array.isArray(draft.rgb) || draft.rgb.length !== 3 ||
      draft.rgb.some(n => !Number.isInteger(n) || n < 0 || n > 255)) throw Error('灯光参数无效');
  return `${id} set ${draft.mode} ${draft.brightness} ${draft.rgb.join(' ')}`;
}
/* A transport send is not execution. Only a matching, validated device report
 * settles a request; stale cloud snapshots and SDK optimistic data cannot. */
export class RequestTracker {
  constructor() { this.reset(); }
  reset() { this.pending = null; this.boot = null; this.uptime = 0; this.invalidBoot = null; }
  invalidateBoot() {
    this.pending = null;
    // A ROM startup marker retires this boot. Keep its identity for restart
    // accounting, but never let its buffered replies re-establish readiness.
    this.invalidBoot = this.boot;
  }
  begin(id, verb, draft, now) {
    if (this.pending) throw Error('正在等待设备回执');
    const wire = command(id, verb, draft);
    this.pending = {id, verb, draft: draft ? structuredClone(draft) : null, at: now};
    return wire;
  }
  receive(raw, now = 0) {
    const r = parseReport(raw);
    if (r && this.invalidBoot !== null && r.boot === this.invalidBoot)
      return {report: null, matched: false};
    if (!r || r.id !== this.pending?.id) return {report: r, matched: false};
    // The browser may throttle the expiry timer in a background tab. The
    // receive path must enforce the same deadline before confirming success.
    if (now - this.pending.at >= 10000) return {report: r, matched: false};
    if (r.boot === this.boot && r.uptime_ms < this.uptime) return {report: r, matched: false};
    const p = this.pending; this.pending = null;
    const restarted = this.boot !== null && r.boot !== this.boot;
    this.boot = r.boot; this.uptime = r.uptime_ms; this.invalidBoot = null;
    const applied = r.ok && (p.verb !== 'set' || (r.mode === p.draft.mode &&
      r.brightness === p.draft.brightness && r.rgb.every((v,i) => v === p.draft.rgb[i])));
    return {report: r, matched: true, applied, restarted, verb: p.verb,
      roundTripMs: Math.max(0, now - p.at)};
  }
  expire(now) {
    if (this.pending && now - this.pending.at >= 10000) {
      this.pending = null; return true;
    }
    return false;
  }
}
// ESP-IDF 5.4 esp_reset_reason_t. New reasons remain visible without treating
// an unknown code as proof of a particular hardware or firmware fault.
export function resetReason(reason) {
  if (reason === undefined) return '固件未提供';
  return ['未知', '上电启动', '外部复位', '软件重启', '异常复位（panic）',
    '中断看门狗', '任务看门狗', '其他看门狗', '深睡唤醒', '欠压复位',
    'SDIO 复位', 'USB 复位', 'JTAG 复位', 'eFuse 错误', '电源毛刺',
    'CPU 锁死'][reason] ?? `未知原因（${reason}）`;
}
export function reportState(report, live, elapsed = 0, roundTrip = 0) {
  if (!report) return '等待设备回应';
  if (!live) return '回执未确认或已过期';
  if (!report.ok) return 'RGB 驱动执行失败';
  if (report.test_ms > 0) return elapsed + roundTrip >= report.test_ms
    ? '试灯可能已结束，等待刷新确认' : '设备回执：试灯中';
  return '设备状态已同步';
}
export function poseState(report, elapsed = 0) {
  if (!report || report.stage < 2) return '未运行姿态识别';
  if (!report.pose.tracking) return '设备报告：未取得有效关键点';
  if (!report.pose.valid || report.pose.age_ms > 400) return '设备报告：此帧无效或已过期';
  if (elapsed > 400) return '本页超过 400 ms 未收到新观测；仅保留上次诊断';
  return '设备报告：此帧满足 400 ms 帧龄条件；仅诊断观测';
}

export function parsePose(raw) {
  let p;
  try { p=typeof raw==='string' ? JSON.parse(raw) : raw; } catch { return null; }
  const integer=(n,max=Number.MAX_SAFE_INTEGER)=>Number.isInteger(n) && n>=0 && n<=max;
  if (!p || p.event!=='pose' || !integer(p.captured_ms) || !integer(p.age_ms) ||
      !Number.isSafeInteger(p.captured_ms+p.age_ms) || !integer(p.people,1000) ||
      !Number.isFinite(p.tilt) || Math.abs(p.tilt)>90 || !integer(p.infer_ms,4294967295) ||
      typeof p.tracking_valid!=='boolean' || typeof p.valid!=='boolean' ||
      (p.valid && !p.tracking_valid) || (p.tracking_valid && p.people!==1) ||
      ['conversion_ms','model_ms'].some(key=>p[key]!==undefined && !integer(p[key],4294967295)) ||
      (p.eye_span_px!==undefined && (!Number.isFinite(p.eye_span_px) || p.eye_span_px<0))) return null;
  return p;
}

// USB diagnostics have no boot/request ID. Require a matching HP barrier and
// only accept subsequently captured samples; never use host receipt as capture.
export class PoseStream {
  constructor() { this.reset(); }
  reset() {
    this.enabled=false; this.boot=null; this.pose=null; this.receivedAt=0;
    this.afterCapture=0; this.lastCapture=null; this.lastReportedAt=null;
  }
  confirm(report) {
    if (report.stage<2) { this.reset(); return false; }
    if (this.enabled && this.boot===report.boot) return false;
    this.reset(); this.enabled=true; this.boot=report.boot; this.afterCapture=report.uptime_ms;
    return true;
  }
  receive(raw,receivedAt) {
    const pose=parsePose(raw);
    if (!pose || !this.enabled) return {accepted:false};
    const reportedAt=pose.captured_ms+pose.age_ms;
    if ((this.lastCapture!==null && pose.captured_ms<=this.lastCapture) ||
        (this.lastReportedAt!==null && reportedAt<this.lastReportedAt)) {
      this.reset();
      return {accepted:false,invalidated:true};
    }
    if (pose.captured_ms<=this.afterCapture) return {accepted:false};
    this.pose=pose; this.receivedAt=receivedAt;
    this.lastCapture=pose.captured_ms; this.lastReportedAt=reportedAt;
    return {accepted:true};
  }
}

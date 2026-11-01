export const MAX_MEANING_BYTES = 180;
const integer=(n,max=Number.MAX_SAFE_INTEGER)=>Number.isSafeInteger(n) && n>=0 && n<=max;
const boot=value=>typeof value==='string' && /^[0-9a-f]{16}$/i.test(value);
const read=raw=>{try{return typeof raw==='string' ? JSON.parse(raw) : raw;}catch{return null;}};
export function validMeaning(value) {
  return typeof value==='string' && !/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u.test(value) &&
    new TextEncoder().encode(value).length<=MAX_MEANING_BYTES &&
    !/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/u.test(value);
}
export function dictionaryCommand(id,verb,key,value) {
  if (!integer(id,999999999) || !id) throw Error('无效请求编号');
  if (verb==='get' || verb==='arm') return `${id} ${verb}`;
  if (verb!=='set' || !['open_palm','v_sign'].includes(key) || !validMeaning(value))
    throw Error('含义不能含换行或控制字符，最多 180 个 UTF-8 字节（约 60 个汉字）。');
  const hex=Array.from(new TextEncoder().encode(value),n=>n.toString(16).padStart(2,'0')).join('');
  return `${id} set ${key} ${hex || '-'}`;
}
export function parseDictionary(raw) {
  const r=read(raw);
  if (!r || r.v!==1 || !boot(r.boot) || !integer(r.id,999999999) || !r.id ||
      typeof r.ok!=='boolean' || typeof r.code!=='string') return null;
  // Allocation failures intentionally carry only the correlation envelope.
  if (!r.ok) return r;
  if (r.code!=='ok' || typeof r.persisted!=='boolean' || !r.bindings ||
      !validMeaning(r.bindings.open_palm) || !validMeaning(r.bindings.v_sign) ||
      !integer(r.max_age_ms,10000) || r.max_age_ms<1) return null;
  if(r.scan_supported!==undefined && typeof r.scan_supported!=='boolean')return null;
  if(r.scan_supported===true && (typeof r.scan_armed!=='boolean'||typeof r.agent_busy!=='boolean'||
      !integer(r.scan_generation,4294967295)||r.scan_generation<1||!integer(r.palm_count,4294967295)||
      !integer(r.v_count,4294967295)||!['none','open_palm','v_sign','closed_fist'].includes(r.last_gesture)))return null;
  return r;
}
export const AGENT_LABELS=Object.freeze({ready:'设备语音链路已初始化',not_configured:'固件尚未配置语音链路',
  connecting:'正在建立语音会话',sending:'正在提交表达',accepted:'Agent 已接受表达',
  speaking:'设备已开始播放',playback_complete:'设备报告播放完成',
  playback_completion_unsupported:'已返回播放状态，设备不提供播完回执',failed:'本次表达失败',
  cleanup_failed:'会话清理失败',busy:'上一条表达仍在处理，本次未提交',
  unavailable:'语音会话不可用',unbound:'这个手势尚未绑定含义',expired:'手势事件已过期',reply:'收到 Agent 回复文本'});
export const AGENT_DETAILS=Object.freeze({cancelled:'会话已取消',no_session:'尚无可用会话',waiting_remote:'等待远端加入',
  waiting_running:'等待会话运行',audio_active:'音频流仍占用',thinking:'Agent 正在思考',speaking:'仍在播报',ready:'会话已就绪',
  not_initialized:'语音链路尚未初始化',lifecycle_busy:'会话正在切换，请稍后重试',cloud_disconnected:'设备尚未连接云端',
  voice_session_active:'已有语音会话占用',tts_pending:'上一段语音仍在结束',resource_active:'本地音频播放占用',
  gesture_session_active:'上一条手势会话尚未释放',start_failed:'语音组件拒绝启动'});
export function agentStateLabel(state){
  if(!state)return '等待已确认手势触发';
  if(state.state==='failed'&&state.code===-2)return ({connecting:'建立语音会话超时',sending:'提交表达超时',reply:'等待回复超时'})[state.phase]??'本次表达超时';
  return AGENT_LABELS[state.state];
}
export function parseAgent(raw) {
  const r=read(raw);
  if (!r || r.v!==1 || !boot(r.boot) || !integer(r.id,4294967295) ||
      !Object.hasOwn(AGENT_LABELS,r.state) || !Number.isSafeInteger(r.code)) return null;
  if (r.state==='reply' && (typeof r.text!=='string' || !r.text || r.text.length>2048 ||
      (r.truncated!==undefined && typeof r.truncated!=='boolean'))) return null;
  return r;
}
const terminal=new Set(['playback_complete','playback_completion_unsupported','failed','cleanup_failed','unavailable','unbound','expired']);
export class AgentStream {
  constructor(){this.reset();}
  reset(){this.boot=null;this.current=null;this.highest=0;this.note='';}
  confirm(bootId){if(this.boot!==bootId){this.reset();this.boot=bootId;}}
  receive(raw,now=0){
    const r=parseAgent(raw);
    if(!r || !this.boot || r.boot!==this.boot) return false;
    if(r.state==='ready' || r.state==='not_configured') return false;
    if(!r.id) return false;
    if(r.state==='busy') {
      if(r.id<=this.highest) return false;
      this.highest=r.id;this.note=`请求 ${r.id}：${AGENT_LABELS.busy}`;return true;
    }
    const active=this.current;
    if(!active || r.id!==active.id) {
      if(r.id<=this.highest || !['connecting','unavailable','unbound','expired'].includes(r.state)) return false;
      this.highest=r.id;this.current={id:r.id,state:r.state,code:r.code,text:'',lastFragment:'',truncated:false,
        phase:['connecting','sending','reply'].includes(r.phase)?r.phase:null,
        detail:Object.hasOwn(AGENT_DETAILS,r.detail)?r.detail:null,at:now,terminal:terminal.has(r.state)};
      this.note='';return true;
    }
    if(r.state==='reply') {
      if(active.terminal || !['sending','accepted','speaking'].includes(active.state)) return false;
      if(r.truncated) active.truncated=true;
      if(r.text===active.lastFragment) return !!r.truncated;
      active.lastFragment=r.text;
      if(r.text.startsWith(active.text)) active.text=r.text.slice(0,2048);
      else if(!active.text.endsWith(r.text)) {const combined=active.text+r.text;active.truncated||=combined.length>2048;active.text=combined.slice(0,2048);}
      active.at=now;return true;
    }
    if(active.terminal && r.state!=='cleanup_failed') return false;
    const rank={connecting:1,sending:2,accepted:3,speaking:4};
    if(rank[r.state] && rank[active.state] && rank[r.state]<rank[active.state]) return false;
    active.state=r.state;active.code=r.code;active.phase=['connecting','sending','reply'].includes(r.phase)?r.phase:null;
    active.detail=Object.hasOwn(AGENT_DETAILS,r.detail)?r.detail:null;active.at=now;active.terminal=terminal.has(r.state);return true;
  }
}

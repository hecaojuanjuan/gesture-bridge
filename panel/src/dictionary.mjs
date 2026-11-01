// This store is deliberately separate from device settings and production dictionaries.
export const STORAGE_KEY = 'headvoice:dictionary-prototype:v1';
export const GESTURES = [
  {id:'open_palm', title:'张开手掌', subtitle:'五指自然张开，掌心朝向摄像头', icon:'palm'},
  {id:'v_sign', title:'V 字手势', subtitle:'伸出食指和中指，其余手指收起', icon:'victory'},
];
export const PHRASES = [
  {id:'water', text:'我想喝水', caption:'喝一点水', icon:'water', tone:'blue'},
  {id:'rest', text:'我想休息', caption:'安静地休息一会儿', icon:'rest', tone:'lilac'},
  {id:'help', text:'请过来帮我', caption:'需要有人在身边', icon:'help', tone:'peach'},
  {id:'toilet', text:'我想上厕所', caption:'需要协助去洗手间', icon:'toilet', tone:'sand'},
  {id:'cold', text:'我觉得冷', caption:'想加一件衣服', icon:'cold', tone:'mint'},
  {id:'company', text:'陪我坐一会儿', caption:'想和你待在一起', icon:'company', tone:'rose'},
];
export function blankDraft() { return {text:'', phraseId:null, gesture:null, samples:0, confirmed:false, editId:null}; }
export function validateBinding(draft, entries) {
  if (!draft.text?.trim() || draft.text.trim().length > 60) return '请填写 1–60 字的表达。';
  if (!GESTURES.some(g=>g.id===draft.gesture)) return '请选择一种手势。';
  if (entries.some(e=>e.gesture===draft.gesture && e.id!==draft.editId)) return '这个手势已有含义，请编辑原词条或选择另一种手势。';
  if (draft.samples!==3) return '请完成三次演示采集。';
  if (draft.confirmed!==true) return '请先核对手势和表达，再确认保存。';
  return null;
}
export function readEntries(storage) {
  try {
    const raw=storage.getItem(STORAGE_KEY);
    if (!raw) return {entries:[],error:null};
    const saved=JSON.parse(raw), gestures=new Set(), ids=new Set();
    if (saved.version!==1 || !Array.isArray(saved.entries)) throw new Error('invalid');
    for (const e of saved.entries) {
      if (!e || typeof e.id!=='string' || !e.id || ids.has(e.id) || typeof e.text!=='string' || !e.text.trim() || e.text.length>60 ||
          !GESTURES.some(g=>g.id===e.gesture) || gestures.has(e.gesture) || e.status!=='demo' ||
          typeof e.updatedAt!=='string' || !Number.isFinite(Date.parse(e.updatedAt))) throw new Error('invalid');
      ids.add(e.id); gestures.add(e.gesture);
    }
    return {entries:saved.entries,error:null};
  } catch { return {entries:[],error:'无法读取本机演示词典。原数据未覆盖，请检查浏览器存储。'}; }
}
export function writeEntries(storage, entries) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify({version:1, entries})); return null; }
  catch { return '浏览器未能保存，请允许本地存储后重试。'; }
}

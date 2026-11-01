import './setup.css';
import {STORAGE_KEY, GESTURES, PHRASES, blankDraft, validateBinding, readEntries, writeEntries} from './dictionary.mjs';
import {icon, illustration} from './setup-art.mjs';

const root=document.querySelector('#setup-app');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let storage;
try { storage=window.localStorage; } catch { storage={getItem(){throw Error();},setItem(){throw Error();}}; }
let {entries,error:storageError}=readEntries(storage);
let draft=blankDraft(), view='setup', step=1, mode='cards', large=false, busy=false, saved=null;
let scanning=false, scanIndex=-1, scanTimer=null, captureTimer=null, toastTimer=null;
const gesture=()=>GESTURES.find(g=>g.id===draft.gesture);
const phrase=()=>PHRASES.find(p=>p.id===draft.phraseId);

root.innerHTML=`
  <a class="skip-link" href="#content">跳到主要内容</a>
  <aside class="sidebar">
    <a class="brand" href="./setup.html"><span class="brand-emblem">颔</span><span>颔语<small>GESTURE BRIDGE</small></span></a>
    <div class="nav-caption">我的沟通空间</div>
    <nav aria-label="主导航">
      <button class="nav-item active" data-nav="setup">${icon('plus')}<span>手势建库</span><i></i></button>
      <button class="nav-item" data-nav="dictionary">${icon('book')}<span>我的词典</span><b id="dictionary-count">0</b></button>
      <a class="nav-item" href="./index.html">${icon('monitor')}<span>设备控制</span>${icon('arrow',16)}</a>
    </nav>
    <div class="sidebar-bottom"><div class="gentle-note"><span class="note-symbol">“</span><p>每一个小动作，<br>都有想说的话。</p><span class="little-line"></span></div>
    <button class="help-link" data-action="help">${icon('help',19)} 建库使用说明</button>
    <div class="sidebar-foot">HEADVOICE <span>设计预览 · v1</span></div></div>
  </aside>
  <div class="app-body">
    <header class="topbar"><div class="breadcrumb">控制面板 <span>/</span> <strong id="crumb">手势建库</strong></div><div class="top-actions"><span class="demo-tag"><i></i>交互原型</span><button class="size-toggle" data-action="font" aria-pressed="false" aria-label="切换大字模式">A<span>大字</span></button><span class="profile-dot" aria-label="个人词典">${icon('person',19)}</span></div></header>
    <main id="content" tabindex="-1"></main>
    <footer class="page-footer"><span>颔语 · 让表达更简单</span><span>${icon('shield',14)} 演示数据仅保存在此浏览器</span></footer>
  </div>
  <div class="toast" id="toast" role="status" aria-live="polite" hidden></div>
  <dialog id="dialog" aria-labelledby="dialog-title"><div id="dialog-content"></div></dialog>`;

function notify(message) {
  const toast=document.querySelector('#toast'); toast.textContent=message; toast.hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>{toast.hidden=true;},5000);
}
function stopScan() { scanning=false; scanIndex=-1; clearInterval(scanTimer); scanTimer=null; }
function stopCapture() { clearTimeout(captureTimer); captureTimer=null; busy=false; }
function stopSpeech() { window.speechSynthesis?.cancel(); }
function speak(text) {
  if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) { notify('此浏览器无法朗读，请查看文字或由照护者协助。'); return; }
  stopSpeech();
  const u=new SpeechSynthesisUtterance(text); u.lang='zh-CN'; u.rate=.85;
  u.onerror=()=>notify('朗读未完成，请查看文字或由照护者协助。');
  window.speechSynthesis.speak(u);
  notify('正在请求浏览器朗读，请核对声音。');
}
function showDialog(title, body, actions='') {
  stopScan(); stopCapture();
  document.querySelector('#dialog-content').innerHTML=`<div class="dialog-head"><h2 id="dialog-title">${title}</h2><button class="icon-button" data-action="close-dialog" aria-label="关闭">${icon('close')}</button></div>${body}<div class="dialog-actions">${actions||'<button class="primary" data-action="close-dialog">知道了</button>'}</div>`;
  document.querySelector('#dialog').showModal();
}
function focusHeading() { document.querySelector('#screen-title')?.focus({preventScroll:true}); }
function reset() { stopScan(); stopCapture(); stopSpeech(); draft=blankDraft(); step=1; mode='cards'; saved=null; view='setup'; }
function navigate(next) {
  stopScan(); stopCapture(); stopSpeech(); view=next; render(); focusHeading();
}
function stepper() {
  return `<ol class="steps" aria-label="建库进度">${['选择含义','录入手势','确认绑定'].map((label,i)=>`<li class="${step===i+1?'current':step>i+1?'done':''}" ${step===i+1?'aria-current="step"':''}><span class="step-number">${step>i+1?icon('check',16):`0${i+1}`}</span><span>${label}</span>${i<2?'<span class="step-line"></span>':''}</li>`).join('')}</ol>`;
}
function summary() {
  const p=phrase(), g=gesture();
  return `<aside class="summary-column"><section class="binding-card"><div class="card-overline">这一次，想说的话</div><div class="summary-picture ${p?.tone||'mint'}">${p?illustration(p.icon):illustration('help')}</div><h3 id="summary-text">${esc(draft.text)||'等待选择含义'}</h3><p id="summary-caption">${draft.text?'这句话将与一个手势固定绑定。':'从左边选一张图卡，慢慢来。'}</p><div class="binding-divider"><span></span>${icon('link',18)}<span></span></div><div class="summary-gesture"><span>${g?illustration(g.icon):icon('plus',24)}</span><div><small>对应手势</small><strong>${g?g.title:'下一步录入'}</strong></div></div><div class="summary-state">${icon('shield',15)} ${saved?'已存为本机演示词条':'未写入设备词典'}</div></section>
    <section class="tip-card"><span class="tip-icon">${icon('help',20)}</span><div><h3>让老人参与决定</h3><p>可以指一指、点一点，或由照护者协助。没有回应时，先等一等。</p></div></section>
    <p class="prototype-note">当前为设计预览。录入使用模拟样本，不采集摄像头画面，也不改变设备设置。</p></aside>`;
}
function phraseCard(p,i) {
  return `<button class="phrase-card ${p.tone} ${draft.phraseId===p.id?'selected':''} ${scanIndex===i?'scanning':''}" data-phrase="${p.id}" aria-pressed="${draft.phraseId===p.id}" aria-label="${p.text}"><span class="selection-mark">${icon('check',14)}</span><span class="phrase-art">${illustration(p.icon)}</span><strong>${p.text}</strong><span class="phrase-caption">${p.caption}</span></button>`;
}
function meaningScreen() {
  return `<div class="screen-heading"><div><span class="eyebrow">第一步 · 选一句想说的话</span><h2 id="screen-title" tabindex="-1">您想用手势表达什么？</h2><p>选中一张图卡，就可以开始。不需要开口说话。</p></div><button class="quiet-button read-button" data-action="read">${icon('sound',19)} 朗读提示</button></div>
    <div class="mode-switch" role="group" aria-label="选择含义的方式"><button data-mode="cards" aria-pressed="${mode==='cards'}">${icon('grid',17)} 图卡选择</button><button data-mode="caregiver" aria-pressed="${mode==='caregiver'}">${icon('edit',17)} 照护者填写</button></div>
    ${mode==='cards'?`<div class="phrase-grid">${PHRASES.map(phraseCard).join('')}</div>
    <div class="scan-bar"><span>${icon('play',17)} 不方便点击图卡？</span><button class="text-button" data-action="scan">${scanning?'暂停轮播':'试试逐项轮播'}</button>${scanning?'<button class="scan-pick" data-action="scan-pick">选中当前项</button>':''}</div><p class="scan-explanation">轮播可用“选中当前项”按钮或空格键选择；当前未接入手势选择。</p>`:
    `<div class="caregiver-form"><span class="form-icon">${icon('edit',28)}</span><h3>替老人记下想说的话</h3><p>可以填写熟悉的称呼和日常表达，再请老人核对。</p><label for="custom-text">想表达的完整句子</label><textarea id="custom-text" rows="3" maxlength="60" placeholder="例如：请帮我拿一下眼镜">${esc(draft.text)}</textarea><div class="input-count"><span>简短、明确，保留老人的意思。</span><output id="text-count">${draft.text.length} / 60</output></div><div class="form-note">${icon('sound',18)} 本版支持文字填写与浏览器朗读；照护者语音录入待接入。</div></div>`}
    <div class="step-actions"><button class="quiet-button" data-action="none">${icon('close',18)} 都不是 / 暂不设置</button><button class="primary" id="next-button" data-action="next" ${!draft.text.trim()?'disabled':''}>下一步：录入手势 ${icon('arrow',19)}</button></div>`;
}
function captureScreen() {
  const conflict=entries.find(e=>e.gesture===draft.gesture && e.id!==draft.editId);
  return `<div class="screen-heading"><div><span class="eyebrow">第二步 · 为这句话选一个动作</span><h2 id="screen-title" tabindex="-1">选一个做起来舒服的手势</h2><p>以后做出这个手势，就表达「${esc(draft.text)}」。</p></div></div>
    <div class="gesture-options">${GESTURES.map(g=>`<button class="gesture-option ${draft.gesture===g.id?'selected':''}" data-gesture="${g.id}" aria-pressed="${draft.gesture===g.id}" ${busy?'disabled':''}><span>${illustration(g.icon)}</span><strong>${g.title}</strong><small>${entries.some(e=>e.gesture===g.id && e.id!==draft.editId)?'已有词条绑定':'可选择'}</small>${draft.gesture===g.id?icon('check',19):''}</button>`).join('')}</div>
    ${conflict?`<div class="inline-alert" role="alert">${gesture().title}已绑定「${esc(conflict.text)}」。请选择另一手势，或到“我的词典”编辑原词条。</div>`:''}
    <section class="capture-panel"><div class="capture-demo"><span class="sample-tag">${icon('monitor',14)} 手势示意 · 非摄像头画面</span><div class="capture-frame ${busy?'capturing':''}"><i></i><i></i><i></i><i></i>${illustration(gesture()?.icon||'palm')}</div><strong>${busy?'正在演示采集…':draft.samples===3?'三次演示采集已完成':gesture()?.subtitle||'请先选择一种手势'}</strong><span>真实录入时由开发板摄像头采集</span></div>
    <div class="capture-controls"><h3>每次做完，放松一下</h3><p>重复三次，体验录入流程。这里不会训练模型或判断动作是否正确。</p><ol class="sample-slots">${[1,2,3].map(n=>`<li class="${draft.samples>=n?'complete':''}"><span>${draft.samples>=n?icon('check',15):n}</span>第 ${n} 次<small>${draft.samples>=n?'模拟完成':'等待演示'}</small></li>`).join('')}</ol>
    <button class="primary full" data-action="capture" ${!draft.gesture||conflict||busy||draft.samples===3?'disabled':''}>${icon('play',18)} ${busy?'演示中…':draft.samples===3?'演示采集已完成':'演示采集一次'}</button><button class="quiet-button full" data-action="recapture" ${!draft.samples||busy?'disabled':''}>${icon('reset',16)} 重新采集</button></div></section>
    <p class="under-note">当前仅展示张掌与 V 字。录入新动作所需的个性化学习尚未实现；演示完成不代表设备已学会。</p>
    <div class="step-actions"><button class="quiet-button" data-action="back">${icon('back',18)} 返回选含义</button><button class="primary" data-action="next" ${draft.samples!==3||conflict?'disabled':''}>下一步：确认绑定 ${icon('arrow',19)}</button></div>`;
}
function confirmScreen() {
  return `<div class="screen-heading"><div><span class="eyebrow">第三步 · 一起核对一下</span><h2 id="screen-title" tabindex="-1">这个手势，是这个意思吗？</h2><p>确认后，同一手势固定对应同一句表达。</p></div></div>
    <div class="review-binding"><div class="review-hand">${illustration(gesture().icon)}<strong>${gesture().title}</strong></div><span class="review-arrow">${icon('arrow',28)}<small>表示</small></span><div class="review-meaning ${phrase()?.tone||'mint'}">${illustration(phrase()?.icon||'help')}<strong>${esc(draft.text)}</strong></div></div>
    <button class="read-review" data-action="read">${icon('sound',20)} 听听这句话</button>
    <div class="confirmation-box"><h3>请先核对，再保存</h3><p>实际使用时，请通过老人可用的沟通方式确认。此处的点击只用于演示，不记录为老人本人已确认。</p><label><input id="confirmed" type="checkbox" ${draft.confirmed?'checked':''}><span>我已核对这条演示绑定</span></label></div>
    <div class="save-destination">${icon('monitor',18)} 保存位置：此浏览器的演示词典 <span>设备同步待接入</span></div>
    <div class="step-actions"><button class="quiet-button" data-action="back">${icon('back',18)} 返回修改</button><button class="primary" id="save-button" data-action="save" ${!draft.confirmed||storageError?'disabled':''}>${icon('check',19)} 保存演示词条</button></div>`;
}
function successScreen() {
  return `<section class="success-screen"><span class="success-icon">${icon('check',34)}</span><span class="eyebrow">已保存到本机演示词典</span><h2 id="screen-title" tabindex="-1">一个手势，多了一句表达。</h2><p>${gesture().title} <span>→</span> <strong>${esc(saved.text)}</strong></p><div class="success-note">这是本机演示记录，尚未同步到开发板。<br>真实识别、设备播报和老人独立使用仍需接入并验证。</div><div class="success-actions"><button class="primary" data-nav="dictionary">查看我的词典 ${icon('arrow',19)}</button><button class="secondary" data-action="new">${icon('plus',19)} 再添加一句</button></div></section>`;
}
function dictionaryScreen() {
  return `<div class="page-title-row"><div><span class="eyebrow">MY DICTIONARY</span><h1 id="screen-title" tabindex="-1">把想说的话，留在这里。</h1><p>每个手势对应一个固定含义，可以随时回来修改。</p></div><button class="primary" data-action="new">${icon('plus',19)} 添加表达</button></div>
    <div class="dictionary-notice">${icon('monitor',19)} 本机演示词典 <span>${entries.length} 个词条 · 未同步设备</span></div>
    ${entries.length?`<div class="dictionary-list">${entries.map(e=>{const g=GESTURES.find(g=>g.id===e.gesture);return `<article class="entry-card"><div class="entry-gesture">${illustration(g.icon)}</div><div class="entry-words"><span>${g.title} ${icon('arrow',15)}</span><h2>${esc(e.text)}</h2><small>演示词条 · ${new Date(e.updatedAt).toLocaleDateString('zh-CN')}</small></div><div class="entry-actions"><button class="icon-button" data-speak="${esc(e.id)}" aria-label="朗读：${esc(e.text)}">${icon('sound')}</button><button class="icon-button" data-edit="${esc(e.id)}" aria-label="编辑：${esc(e.text)}">${icon('edit')}</button><button class="icon-button" data-delete="${esc(e.id)}" aria-label="删除：${esc(e.text)}">${icon('trash')}</button></div></article>`;}).join('')}</div>`:
    `<section class="empty-dictionary"><span>${icon('book',43)}</span><h2>从一句常用的话开始</h2><p>还没有演示词条。可以先为“我想喝水”选一个手势。</p><button class="primary" data-action="new">${icon('plus',18)} 建立第一个词条</button></section>`}
    <section class="dictionary-footnote">${icon('shield',18)} 已绑定的手势不会自动换成别的意思。修改需重新核对；删除仅影响本机演示数据。</section>`;
}
function render() {
  document.querySelector('#dictionary-count').textContent=entries.length;
  document.querySelector('#crumb').textContent=view==='setup'?'手势建库':'我的词典';
  document.querySelectorAll('[data-nav]').forEach(n=>{n.classList.toggle('active',n.dataset.nav===view); if(n.classList.contains('nav-item')) n.setAttribute('aria-current',n.dataset.nav===view?'page':'false');});
  document.querySelector('#content').innerHTML=(storageError?`<div class="inline-alert" role="alert">${esc(storageError)}</div>`:'')+(view==='dictionary'?dictionaryScreen():`
    <div class="page-title-row"><div><span class="eyebrow">PERSONAL GESTURE DICTIONARY</span><h1>让熟悉的手势，<span>有自己的意思。</span></h1><p>一起建立专属于您的表达方式。</p></div><button class="quiet-button" data-action="help">${icon('help',18)} 如何开始</button></div>
    ${stepper()}<div class="setup-layout"><section class="workflow-card">${saved?successScreen():step===1?meaningScreen():step===2?captureScreen():confirmScreen()}</section>${summary()}</div>`);
}
function selectPhrase(id) {
  const p=PHRASES.find(p=>p.id===id); if(!p)return;
  stopScan(); stopSpeech();
  if(draft.text!==p.text){draft.samples=0; draft.confirmed=false;}
  draft.text=p.text; draft.phraseId=p.id; render();
  document.querySelector(`[data-phrase="${id}"]`)?.focus({preventScroll:true});
}
function tickScan() {
  scanIndex=(scanIndex+1)%PHRASES.length;
  document.querySelectorAll('[data-phrase]').forEach((node,i)=>node.classList.toggle('scanning',i===scanIndex));
  notify(`当前选项：${PHRASES[scanIndex].text}。可按空格键选择。`);
}
function commit() {
  if(storageError){notify(storageError);return;}
  // Re-read before every mutation so an open tab cannot silently overwrite another tab.
  const current=readEntries(storage); if(current.error){storageError=current.error; render();return;}
  if(draft.editId && !current.entries.some(e=>e.id===draft.editId)){notify('原词条已被删除，请重新添加。');return;}
  const problem=validateBinding(draft,current.entries); if(problem){notify(problem);return;}
  const entry={id:draft.editId||crypto.randomUUID(), text:draft.text.trim(), gesture:draft.gesture,
    phraseId:draft.phraseId, status:'demo', updatedAt:new Date().toISOString()};
  const next=current.entries.filter(e=>e.id!==entry.id).concat(entry);
  const error=writeEntries(storage,next); if(error){notify(error);return;}
  entries=next; saved=entry; render(); focusHeading();
}
root.addEventListener('input',event=>{
  if(event.target.id==='custom-text') {
    draft.text=event.target.value; draft.phraseId=null; draft.confirmed=false; draft.samples=0;
    document.querySelector('#text-count').textContent=`${draft.text.length} / 60`;
    const summaryNode=document.querySelector('.summary-column');
    if(summaryNode) summaryNode.outerHTML=summary();
    document.querySelector('#next-button').disabled=!draft.text.trim();
  }
});
root.addEventListener('change',event=>{
  if(event.target.id==='confirmed') {draft.confirmed=event.target.checked;document.querySelector('#save-button').disabled=!draft.confirmed||!!storageError;}
});
root.addEventListener('click',event=>{
  const b=event.target.closest('button'); if(!b||b.disabled)return;
  if(b.dataset.nav){navigate(b.dataset.nav);return;}
  if(b.dataset.phrase){selectPhrase(b.dataset.phrase);return;}
  if(b.dataset.mode){stopScan();stopSpeech();mode=b.dataset.mode;render();document.querySelector(`[data-mode="${mode}"]`)?.focus();return;}
  if(b.dataset.gesture){if(draft.gesture!==b.dataset.gesture){draft.gesture=b.dataset.gesture;draft.samples=0;draft.confirmed=false;}render();document.querySelector(`[data-gesture="${draft.gesture}"]`)?.focus();return;}
  if(b.dataset.speak){const e=entries.find(e=>e.id===b.dataset.speak);if(e)speak(e.text);return;}
  if(b.dataset.edit){const e=entries.find(e=>e.id===b.dataset.edit);if(!e)return;reset();draft={...blankDraft(),text:e.text,gesture:e.gesture,phraseId:PHRASES.some(p=>p.id===e.phraseId)?e.phraseId:null,editId:e.id};mode=draft.phraseId?'cards':'caregiver';render();focusHeading();return;}
  if(b.dataset.delete){const e=entries.find(e=>e.id===b.dataset.delete);if(e)showDialog('删除这条演示词条？',`<p>「${esc(e.text)}」将从此浏览器移除，不会改变开发板。</p>`,`<button class="secondary" data-action="close-dialog">保留词条</button><button class="danger-button" data-remove="${esc(e.id)}">删除词条</button>`);return;}
  if(b.dataset.remove){const current=readEntries(storage);if(current.error){notify(current.error);return;}const next=current.entries.filter(e=>e.id!==b.dataset.remove),error=writeEntries(storage,next);if(error){notify(error);return;}entries=next;document.querySelector('#dialog').close();render();notify('已删除本机演示词条。');return;}
  switch(b.dataset.action){
    case 'font':large=!large;document.body.classList.toggle('large-text',large);b.setAttribute('aria-pressed',large);break;
    case 'help':showDialog('从一句话、一个手势开始',`<ol class="help-steps"><li><strong>选含义</strong><p>老人看图选择，或请照护者填写一句话。</p></li><li><strong>录手势</strong><p>选择舒服的动作。本版用三次模拟采集展示流程。</p></li><li><strong>核对并保存</strong><p>回读绑定后保存为本机演示词条。以后可在“我的词典”修改。</p></li></ol><div class="dialog-note">本版没有设备写入、摄像头采集和手势自动选择。不会将演示操作记为老人独立确认。</div>`);break;
    case 'close-dialog':document.querySelector('#dialog').close();break;
    case 'read':speak(step===1?(draft.text||'请选择您想用手势表达的话。可以选择喝水、休息、需要帮助，也可以暂不设置。'):draft.text);break;
    case 'none':stopScan();showDialog('可以稍后再设置',`<p>没有合适的图卡，可以请照护者填写一句话，也可以先休息。当前内容尚未保存。</p>`,`<button class="secondary" data-action="pause-setup">暂不设置</button><button class="primary" data-action="custom">请照护者填写</button>`);break;
    case 'pause-setup':document.querySelector('#dialog').close();reset();navigate('dictionary');break;
    case 'custom':document.querySelector('#dialog').close();mode='caregiver';render();document.querySelector('#custom-text').focus();break;
    case 'new':reset();render();focusHeading();break;
    case 'next':stopScan();stopSpeech();if(step===1&&draft.text.trim()){step=2;}else if(step===2&&draft.samples===3&&!entries.some(e=>e.gesture===draft.gesture&&e.id!==draft.editId)){step=3;}render();focusHeading();break;
    case 'back':stopScan();stopCapture();stopSpeech();draft.confirmed=false;step=Math.max(1,step-1);render();focusHeading();break;
    case 'scan':if(scanning){stopScan();render();}else{scanning=true;render();tickScan();scanTimer=setInterval(tickScan,3500);}document.querySelector('[data-action="scan"]')?.focus();break;
    case 'scan-pick':if(scanning&&scanIndex>=0)selectPhrase(PHRASES[scanIndex].id);break;
    case 'capture':if(!draft.gesture||draft.samples>=3||busy)return;busy=true;render();captureTimer=setTimeout(()=>{busy=false;draft.samples++;draft.confirmed=false;captureTimer=null;render();notify(`第 ${draft.samples} 次模拟采集完成。`);document.querySelector(draft.samples===3?'[data-action="next"]':'[data-action="capture"]')?.focus({preventScroll:true});},850);break;
    case 'recapture':stopCapture();draft.samples=0;draft.confirmed=false;render();break;
    case 'save':commit();break;
  }
});
document.addEventListener('keydown',event=>{
  if(scanning&&event.code==='Space'&&!['INPUT','TEXTAREA'].includes(event.target.tagName)){event.preventDefault();selectPhrase(PHRASES[scanIndex].id);}
  if(scanning&&event.code==='Escape'){stopScan();render();}
});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stopScan();stopCapture();stopSpeech();render();}});
window.addEventListener('pagehide',()=>{stopScan();stopCapture();stopSpeech();});
window.addEventListener('storage',event=>{if(event.key===STORAGE_KEY||event.key===null){stopScan();stopCapture();const current=readEntries(storage);entries=current.entries;storageError=current.error;draft.confirmed=false;saved=null;render();notify('演示词典已在其他页面更新，请重新核对。');}});
render();

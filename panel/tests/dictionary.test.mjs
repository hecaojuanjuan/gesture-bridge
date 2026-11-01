import test from 'node:test';
import assert from 'node:assert/strict';
import {STORAGE_KEY, blankDraft, validateBinding, readEntries, writeEntries} from '../src/dictionary.mjs';
const entry={id:'one',gesture:'open_palm',text:'我想喝水',status:'demo',updatedAt:'2026-11-01T08:00:00.000Z'};
const complete={...blankDraft(),text:'我想休息',gesture:'v_sign',samples:3,confirmed:true};
const storage=raw=>({value:raw,getItem(key){assert.equal(key,STORAGE_KEY);return this.value;},setItem(key,value){assert.equal(key,STORAGE_KEY);this.value=value;}});
test('saving requires an explicit check after all three sample demonstrations',()=>{
  assert.match(validateBinding({...complete,samples:2},[]),/三次/);
  assert.match(validateBinding({...complete,confirmed:false},[]),/核对/);
  assert.equal(validateBinding(complete,[]),null);
});
test('a gesture cannot silently acquire a second meaning; an explicit edit may reuse its own gesture',()=>{
  assert.match(validateBinding({...complete,gesture:'open_palm'},[entry]),/已有含义/);
  assert.equal(validateBinding({...complete,gesture:'open_palm',editId:'one'},[entry]),null);
});
test('unknown gestures and empty or excessive meanings cannot be saved',()=>{
  assert.match(validateBinding({...complete,gesture:'arbitrary-new-gesture'},[]),/请选择/);
  for(const text of ['', '  ', '词'.repeat(61)]) assert.match(validateBinding({...complete,text},[]),/1–60/);
});
test('stored demo entries round trip without being promoted to device-confirmed entries',()=>{
  const s=storage(null); assert.deepEqual(readEntries(s),{entries:[],error:null});
  assert.equal(writeEntries(s,[entry]),null);
  assert.deepEqual(readEntries(s),{entries:[entry],error:null});
});
test('corrupt, duplicate and non-demo storage remains untouched and reports a read failure',()=>{
  const inputs=['{broken',JSON.stringify({version:2,entries:[]}),
    JSON.stringify({version:1,entries:[entry,{...entry,id:'two'}]}),
    JSON.stringify({version:1,entries:[entry,{...entry,gesture:'v_sign'}]}),
    JSON.stringify({version:1,entries:[{...entry,status:'device-confirmed'}]}),
    JSON.stringify({version:1,entries:[{...entry,updatedAt:'invalid'}]})];
  for(const raw of inputs){const s=storage(raw);assert.ok(readEntries(s).error);assert.equal(s.value,raw);}
});
test('unavailable browser storage does not claim a successful save',()=>{
  const s={getItem(){throw Error('denied');},setItem(){throw Error('full');}};
  assert.ok(readEntries(s).error); assert.match(writeEntries(s,[entry]),/未能保存/);
});

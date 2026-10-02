// 편집실 효과음(2026-10-02): 효과음 줄 · 왼쪽 [효과음] 목록 · 오른쪽 칸.
// 자동 효과음(내레이션 시작 · 라벨 · 강조 줄)은 엔진이 렌더 때 고르고 sfx.json(tikitaka_sfx/v1)에 남긴다. 여기서는 보여 주고 뺄 수만 있다.
// 직접 넣은 효과음은 원본 시각(src)에 붙어서 구간을 고쳐도 그 장면을 따라간다(내레이션 · 텍스트와 같은 규칙).
// 제출: overrides.sfx = {add:[{id, at, vol, dur?}], off:[열쇠]} — at 은 지금 완성본 시각(ai-video apply_edit.editor_sfx).
// 이름은 사람마다 따로(user_sfx_names · 0131). 분류는 고정.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const CATS=[
 ['삐',[['beep','삐']]],
 ['타격',[['hit3','퍽'],['punch','펀치'],['gunshot','탕'],['impact-thud','쿵'],['thud-impact-sound-sfx','둔탁한 쿵'],['whip-crack','찰싹'],['low-thumpy-kick-reverb-hit','둥']]],
 ['휙',[['whoosh-1','휙 1'],['whoosh-2','휙 2'],['whoosh-3','휙 3'],['whoosh-effect','휙 4'],['swoosh-fight-2','빠른 휙'],['swoosh-015-tight','짧은 휙'],['movement-swipe-whoosh-3','스와이프'],['whoosh-transition-6-tight','전환 휙'],['riser-swoosh-transition-tight','올라가는 휙']]],
 ['뽕',[['happy-pop-3','뽕'],['bubble-pop-02','뽁 1'],['bubble-pop-04','뽁 2'],['sharp-pop','톡'],['pop-e','팝 1'],['pop-f','팝 2'],['pop-g','팝 3'],['pop-sound','팝 4'],['ui-pop-sound','딸깍'],['pop-up-something','띠링'],['funny-boing-flexatone-wobble','띠용']]],
 ['웅장',[['cinematic-boom','쾅 1'],['impact-cinematic-boom-02','쾅 2'],['cinematic-impact-boom-03','쾅 3'],['cinematic-impact-boom-05','쾅 4'],['huge-cinematic-tom-hit','두둥'],['hit-low-gravity-absorber','웅']]],
];
const LEN={beep:5,'bubble-pop-02':.81,'bubble-pop-04':.95,'cinematic-boom':2.97,'cinematic-impact-boom-03':2.68,'cinematic-impact-boom-05':2.01,'funny-boing-flexatone-wobble':3.04,gunshot:.98,'happy-pop-3':1.01,'hit-low-gravity-absorber':4.06,hit3:.4,'huge-cinematic-tom-hit':1.66,'impact-cinematic-boom-02':2.53,'impact-thud':1.32,'low-thumpy-kick-reverb-hit':1.73,'movement-swipe-whoosh-3':.97,'pop-e':.61,'pop-f':.07,'pop-g':.74,'pop-sound':1.66,'pop-up-something':.21,punch:1.44,'riser-swoosh-transition-tight':.72,'sharp-pop':.99,'swoosh-015-tight':.73,'swoosh-fight-2':.32,'thud-impact-sound-sfx':2.06,'ui-pop-sound':1.3,'whip-crack':.95,'whoosh-1':.7,'whoosh-2':.7,'whoosh-3':.83,'whoosh-effect':.47,'whoosh-transition-6-tight':6.56};
const BASE=Object.fromEntries(CATS.flatMap(([,l])=>l));
const KNOWN=new Set(Object.keys(BASE));
const VOL=[[-1,'작게'],[0,'보통'],[1,'크게']];
const VOL_GAIN={'-1':0.35,'0':0.6,'1':0.85};          // 미리듣기 크기(엔진 -12 · -6 · -3dB 와 비슷한 차이)
const KIND={narration:'내레이션이 시작될 때',label:'텍스트가 뜰 때',emphasis:'강조 자막에'};
const DUR_DEFAULT=0.5,DUR_MIN=0.1,DUR_MAX=5;
const PEN='<svg class="ei" viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>';
const PLAY='<svg class="ei" viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z"/></svg>';

let client=null,canEdit=false,names={},cat=CATS[0][0],renaming=null;
export const nameOf=id=>names[id]||BASE[id]||id;
export function setup({client:c,editable}){
 client=c;canEdit=!!editable;
 if(!client)return;
 client.from('user_sfx_names').select('sfx_id,name').then(({data})=>{
  (data||[]).forEach(r=>{names[r.sfx_id]=r.name;});
  if(Object.keys(names).length)window.__edRedraw?.();
 }).catch(()=>{});
}
export const editable=()=>canEdit;

// ── 모델 ──────────────────────────────────────────────────────────────
// 렌더가 남긴 시각(완성본) → 원본 시각: 렌더 때 구간표(cur.row.timeline.clips)로 되짚는다
export function renderToSrc(cur,t){
 let off=0;
 for(const c of (cur.row.timeline&&cur.row.timeline.clips)||[]){
  const sp=+c.playback_speed||1,moving=(+c.end_sec-+c.start_sec)/sp,d=moving+(+c.hold_sec||0);
  if(t>=off-1e-3&&t<off+d)return +c.start_sec+Math.min(t-off,moving)*sp;
  off+=d;
 }
 return null;
}
const sig=s=>JSON.stringify({a:(s.add||[]).map(x=>[x.id,+(+x.src).toFixed(3),x.vol,x.dur??null]),o:[...(s.off||[])].sort()});
export function load(cur,d){
 const doc=cur.row.sfx||[];
 cur.sfxAuto=doc.filter(x=>x.kind!=='user'&&x.key).map(x=>({...x,src:renderToSrc(cur,+x.at)}));
 const base={add:doc.filter(x=>x.kind==='user'&&KNOWN.has(x.id)).map(x=>({id:x.id,src:renderToSrc(cur,+x.at),vol:+x.vol||0,dur:x.id==='beep'?(+x.dur||DUR_DEFAULT):null})).filter(x=>x.src!=null),
  off:doc.filter(x=>x.off&&x.key).map(x=>x.key)};
 cur.orig.sfx=sig(base);
 const ds=d&&d.sfx;
 cur.model.sfx=ds&&Array.isArray(ds.add)?{add:ds.add.filter(x=>KNOWN.has(x.id)).map(x=>({id:x.id,src:+x.src,vol:+x.vol||0,dur:x.dur??null})),off:[...(ds.off||[])]}:base;
}
export function collect(cur,forDraft,H,clipsChanged){
 const s=cur.model&&cur.model.sfx;if(!s||!cur.orig||cur.orig.sfx==null)return {};
 const changed=sig(s)!==cur.orig.sfx;
 if(!changed&&!(clipsChanged&&s.add.length))return forDraft&&cur.row.draft&&cur.row.draft.sfx?{sfx:null}:{};
 if(forDraft)return {sfx:{add:s.add.map(x=>({id:x.id,src:+(+x.src).toFixed(3),vol:x.vol,dur:x.dur})),off:[...s.off]}};
 const add=[];
 s.add.forEach(x=>{const at=H.srcToOut(+x.src);if(at==null)return;
  add.push({id:x.id,at:+at.toFixed(3),vol:x.vol,...(x.dur!=null?{dur:+(+x.dur).toFixed(2)}:{})});});
 return {sfx:{add,off:[...s.off]}};
}
// 지금 완성본 자리 — 직접 넣은 것은 원본 시각에서, 자동은 원본 시각(없으면 렌더 시각)에서
export function items(cur,H){
 const s=cur.model.sfx||{add:[],off:[]},out=[];
 (cur.sfxAuto||[]).forEach((x,i)=>{const at=x.src!=null?H.srcToOut(x.src):null;if(at==null)return;
  out.push({k:'sfxa',i,at,dur:+x.dur||LEN[x.id]||0.6,name:nameOf(x.id),id:x.id,off:s.off.includes(x.key),auto:true});});
 s.add.forEach((x,i)=>{const at=H.srcToOut(+x.src);if(at==null)return;
  out.push({k:'sfx',i,at,dur:x.dur??(LEN[x.id]||0.6),name:nameOf(x.id),id:x.id,vol:x.vol});});
 return out;
}

// ── 효과음 줄 ─────────────────────────────────────────────────────────
export function laneHtml(cur,px,H){
 let h='<div class="track sfx" data-lab="lsfx" style="height:26px">';
 items(cur,H).forEach(x=>{
  h+=`<div class="blk fx${x.auto?' auto':''}${x.off?' off':''}" data-k="${x.k}" data-i="${x.i}" title="${esc(`${H.fmt(x.at)} ${x.name}${x.auto?' · 자동으로 붙은 소리':''}${x.off?' · 뺐어요':''}`)}"
   style="left:${x.at*px}px;width:${Math.max(18,Math.min(x.dur,3)*px)}px">${esc(x.name)}</div>`;
 });
 return h+'</div>';
}
export function count(cur){const s=cur.model.sfx;return s?s.add.length:0;}

// ── 왼쪽 [효과음] ─────────────────────────────────────────────────────
export function railHtml(cur,editMode){
 const list=CATS.find(c=>c[0]===cat)[1],on=editMode&&canEdit;
 const chip='display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:20px;border-radius:5px;font-size:10px;padding:0 6px;flex-shrink:0';
 return `<h3>효과음 <span class="faint">${count(cur)}</span></h3>
  <div class="sfx-cats">${CATS.map(([c])=>`<button type="button" class="${c===cat?'on':''}" onclick="__edSfx.setCat('${c}')">${c}</button>`).join('')}</div>
  <div class="drawList">${list.map(([id])=>`<div class="tplItem sfx-row">${renaming===id
   ?`<input class="sfx-name" data-ren="${id}" value="${esc(nameOf(id))}" maxlength="30" onkeydown="if(event.key==='Enter')this.blur();if(event.key==='Escape'){this.dataset.cancel=1;this.blur();}" onblur="__edSfx.rename('${id}',this.dataset.cancel?null:this.value)">`
   :`<span class="tx"><b>${esc(nameOf(id))}</b></span><button class="pvb" title="이름 바꾸기" aria-label="이름 바꾸기" onclick="__edSfx.startRename('${id}')">${PEN}</button>`}
   <button class="pvb" title="들어보기" aria-label="들어보기" onclick="__edSfx.preview('${id}')">${PLAY}</button>
   <button class="sfx-add" ${on?'':'disabled'} onclick="__edSfx.add('${id}')">넣기</button></div>`).join('')}</div>
  <div class="sfx-legend">
   <div><span style="${chip};background:var(--panel);color:var(--faint)">휙</span><span>강조 자막 · 내레이션 · 텍스트에 자동으로 붙은 소리</span></div>
   <div><span style="${chip};background:var(--sfx);color:#fff">삐</span><span>직접 넣은 소리</span></div>
   <div><span style="${chip}">${PEN}</span><span>이름 바꾸기 · 바꾼 이름은 나한테만 보여요</span></div>
  </div>
  ${canEdit?(on?'':'<div class="small faint">넣고 빼려면 편집 잠금을 풀어 주세요.</div>'):'<div class="small faint">이 영상은 아직 여기서 효과음을 바꿀 수 없어요.</div>'}`;
}

// ── 오른쪽 칸 ─────────────────────────────────────────────────────────
export function sideHtml(cur,kind,i,editMode,H){
 const on=editMode&&canEdit,s=cur.model.sfx;
 if(kind==='sfxa'){
  const x=(cur.sfxAuto||[])[i];if(!x)return '';
  const off=s.off.includes(x.key);
  return `<div class="khead"><span class="sw" style="background:var(--faint)"></span><span class="ttl">자동으로 붙은 소리</span></div>
   <div class="kv"><span class="k">소리</span><span class="v" style="font-family:inherit">${esc(nameOf(x.id))}</span>
    <span class="k">붙은 곳</span><span class="v" style="font-family:inherit">${esc(KIND[x.kind]||'')}${x.text?` · ${esc(x.text)}`:''}</span></div>
   <div class="ebtns"><button onclick="__edSfx.preview('${x.id}')">${PLAY}들어보기</button>
    <button ${on?'':'disabled'} class="${off?'':'danger'}" onclick="__edSfx.toggleOff(${i})">${off?'다시 넣기':'이 소리 빼기'}</button></div>
   ${off?'<div class="small faint">다시 렌더하면 이 소리가 빠져요.</div>':''}`;
 }
 const x=s.add[i];if(!x)return '';
 const at=H.srcToOut(+x.src);
 return `<div class="khead"><span class="sw" style="background:var(--sfx)"></span><span class="ttl">효과음${at!=null?` · ${H.fmt(at)}`:''}</span></div>
  ${at==null?'<div class="alert warn ck-bad">이 효과음은 빠져요. 붙어 있던 장면이 지금 구간에 없어요.</div>':''}
  <label class="dfld"><span>소리</span><select ${on?'':'disabled'} onchange="__edSfx.set(${i},'id',this.value)">${CATS.map(([c,l])=>`<optgroup label="${c}">${l.map(([id])=>`<option value="${id}"${id===x.id?' selected':''}>${esc(nameOf(id))}</option>`).join('')}</optgroup>`).join('')}</select></label>
  <label class="dfld"><span>크기</span><span class="sfx-seg">${VOL.map(([v,t])=>`<button type="button" ${on?'':'disabled'} class="${x.vol===v?'on':''}" onclick="__edSfx.set(${i},'vol',${v})">${t}</button>`).join('')}</span></label>
  ${x.id==='beep'?`<label class="dfld"><span>길이</span><span class="steprow"><button type="button" ${on?'':'disabled'} onclick="__edSfx.set(${i},'dur',-0.1)" aria-label="짧게"><svg class="ei" viewBox="0 0 24 24"><path d="M5 12h14"/></svg></button><input value="${(+x.dur||DUR_DEFAULT).toFixed(1)}초" readonly><button type="button" ${on?'':'disabled'} onclick="__edSfx.set(${i},'dur',0.1)" aria-label="길게"><svg class="ei" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></button></span></label>`:''}
  <div class="ebtns"><button onclick="__edSfx.preview('${x.id}',${i})">${PLAY}들어보기</button><button ${on?'':'disabled'} class="danger" onclick="__edSfx.del(${i})">빼기</button></div>
  <div class="small faint">효과음 줄에서 끌어 자리를 옮길 수 있어요.</div>`;
}

// ── 소리 ──────────────────────────────────────────────────────────────
const cache=new Map();
function audio(id){
 if(!cache.has(id)){const a=new Audio(new URL(`../assets/sfx/${id}.mp3`,import.meta.url).href);a.preload='auto';cache.set(id,a);}
 return cache.get(id);
}
let stopAt=null;
function play(id,vol=0,dur=null,from=0){
 const a=audio(id).cloneNode();a.volume=VOL_GAIN[String(vol)]??0.6;
 a.currentTime=Math.max(0,from);a.play().catch(()=>{});
 const len=dur??(id==='beep'?DUR_DEFAULT:null);
 if(len!=null){clearTimeout(stopAt);stopAt=setTimeout(()=>a.pause(),Math.max(0,(len-from)*1000));}
 return a;
}
export function preview(id,i){
 const x=i!=null&&window.tlCur?.()?.model?.sfx?.add[i];
 play(id,x?x.vol:0,x&&x.id==='beep'?(+x.dur||DUR_DEFAULT):null);
}
// 재생 중: 지나간 자리의 효과음을 울린다(뺀 자동 효과음은 조용히)
let lastT=null;
export function paint(cur,outT,playing,H){
 if(!playing||outT==null){lastT=outT;return;}
 const prev=lastT;lastT=outT;
 if(prev==null||outT<prev||outT-prev>0.6)return;      // 시크 · 되감기는 소리 없이
 for(const x of items(cur,H)){
  if(x.off||!(x.at>prev&&x.at<=outT))continue;
  const add=x.k==='sfx'?cur.model.sfx.add[x.i]:null;
  play(x.id,add?add.vol:-1,add&&add.id==='beep'?(+add.dur||DUR_DEFAULT):null);
 }
}

// ── 바꾸기(ves-editor 의 __edMut 로 실행 취소 · 다시 그리기를 함께) ──
function mut(fn,kind,i){if(canEdit&&window.__edMut)window.__edMut(fn,kind,i);}
export function add(id){
 const H=window.__edTime;if(!H||!canEdit)return;
 const hit=H.outToSrc(Math.max(0,H.curOut()??0));
 if(!hit){window.__edToast?.('재생 헤드를 영상 안에 두고 넣어 주세요');return;}
 let at=0;
 mut(m=>{m.sfx.add.push({id,src:+hit.src.toFixed(3),vol:0,dur:id==='beep'?DUR_DEFAULT:null});at=m.sfx.add.length-1;},'sfx',window.tlCur().model.sfx.add.length);
 play(id);
}
export function set(i,what,val){
 mut(m=>{const x=m.sfx.add[i];if(!x)return;
  if(what==='id'){x.id=val;x.dur=val==='beep'?(x.dur??DUR_DEFAULT):null;}
  else if(what==='vol')x.vol=+val;
  else if(what==='dur')x.dur=Math.min(DUR_MAX,Math.max(DUR_MIN,+((+x.dur||DUR_DEFAULT)+ +val).toFixed(1)));
 },'sfx',i);
}
export function moveTo(i,src){mut(m=>{const x=m.sfx.add[i];if(x)x.src=+(+src).toFixed(3);},'sfx',i);}
export function del(i){mut(m=>{m.sfx.add.splice(i,1);},null,null);window.closeSide?.();}
export function toggleOff(i){
 const x=(window.tlCur().sfxAuto||[])[i];if(!x)return;
 mut(m=>{const k=m.sfx.off.indexOf(x.key);if(k>=0)m.sfx.off.splice(k,1);else m.sfx.off.push(x.key);},'sfxa',i);
}
export function setCat(c){cat=c;window.renderRailPanel?.('sfx');}
export function startRename(id){renaming=id;window.renderRailPanel?.('sfx');const el=document.querySelector(`[data-ren="${id}"]`);if(el){el.focus();el.select();}}
export function rename(id,val){
 if(renaming!==id)return;renaming=null;
 const v=val==null?null:String(val).trim().slice(0,30);
 if(v!=null&&v!==nameOf(id)){
  const reset=!v||v===BASE[id];
  if(reset)delete names[id];else names[id]=v;
  if(client)(reset?client.from('user_sfx_names').delete().eq('sfx_id',id)
   :client.from('user_sfx_names').upsert({sfx_id:id,name:v,updated_at:new Date().toISOString()},{onConflict:'user_id,sfx_id'}))
   .then(({error})=>{if(error)window.__edToast?.('이름을 저장하지 못했어요');});
 }
 window.__edRedraw?.();window.renderRailPanel?.('sfx');
}

window.__edSfx={renderToSrc,setup,editable,load,collect,items,laneHtml,count,railHtml,sideHtml,paint,preview,add,set,moveTo,del,toggleOff,setCat,startRename,rename,nameOf};

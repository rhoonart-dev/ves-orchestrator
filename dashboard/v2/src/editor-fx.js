// 편집실 강조·줌: 대사 자막 줄의 강조(1차·2차·직접)와 구간 줌(단계별 배율·당기는 쪽)을 사람이 걸고 뺀다.
// 값은 편집실 모델의 자막(sub.emph)·구간(clip.zoom)에 붙어 다녀서 실행 취소·구간 나누기·초안에 그대로 실린다.
// 제출할 때는 자막·구간과 따로 overrides.emphasis·zooms 로 나간다(ves-editor.js collectOv 가 잇는다).
// 규칙은 ai-video app/v3/stage4.py 와 같다: 강조 한 편 6줄, 노랑 없음, 크기 1.05~1.45배 / 줌 한 편 4곳, 한 구간 3단, 1.1~1.6배.
// 강조마다 '줌도 같이'(emph.zoom)를 고른다. 기본은 2차 강조만 켬 — 켜면 엔진이 그 줄 시작에 줌을 붙인다
// (그 구간에 줌이 없으면 1.2배, 있으면 그 시점에 한 단계 +0.1배 · ai-video db9a3511).
// 엔진이 아직 이 두 키를 받지 않으면(meta.fx_edit=false) 지금 값만 보여 주고 바꾸지 못하게 둔다.
const EMPH_MAX=6,ZOOM_MAX=4,STAGE_MAX=3;
const LEVELS={1:{scale:1.18,color:'white',label:'1차 강조'},2:{scale:1.35,color:'red',label:'2차 강조'}};
const COLORS={white:['#FFFFFF','흰색'],red:['#FF5540','빨강'],blue:['#7ED0FF','파랑'],orange:['#FFB637','주황']};
const FACTORS=[1.1,1.15,1.2,1.25,1.3,1.4,1.5,1.6];
const ANCHORS={left:'왼쪽',center:'가운데',right:'오른쪽'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let canEdit=false;
export function setEditable(on){canEdit=!!on;}

const look=e=>e&&(e.level?{scale:LEVELS[e.level].scale,color:LEVELS[e.level].color}:{scale:+e.scale||1.23,color:COLORS[e.color]?e.color:'red'});
const emphSig=subs=>JSON.stringify((subs||[]).filter(s=>!s.del&&s.emph).map(s=>[s.i0??null,s.text,s.emph]));
const zoomSig=clips=>JSON.stringify((clips||[]).map((c,i)=>c.zoom?[i,+c.start,+c.end,c.zoom]:null).filter(Boolean));

// buildModel 끝: 렌더 값을 붙이고, 초안이 있으면 그 위에 얹는다. 비교 기준(cur.orig.fx)은 렌더 값이다.
export function load(cur,tl,d){
 const m=cur.model,tlSubs=tl.subtitles||[],tlClips=tl.clips||[];
 m.subs.forEach(s=>{const o=s.i0!=null&&tlSubs[s.i0];s.emph=o&&o.emph?{...o.emph}:null;});
 m.clips.forEach(c=>{const o=tlClips.find(x=>Math.abs(+x.start_sec-c.start)<1e-3&&Math.abs(+x.end_sec-c.end)<1e-3);c.zoom=o&&o.zoom?JSON.parse(JSON.stringify(o.zoom)):null;});
 const base={subs:tlSubs.map((s,i)=>({i0:i,text:s.text||'',del:false,emph:s.emph||null})),
  clips:tlClips.map(c=>({start:+c.start_sec,end:+c.end_sec,zoom:c.zoom||null}))};
 cur.orig.fx={emph:emphSig(base.subs),zoom:zoomSig(base.clips)};
 if(Array.isArray(d.emphasis)){            // 초안: 원본 줄 번호(i0) 먼저, 없으면 같은 문구 중 가까운 시각
  m.subs.forEach(s=>{s.emph=null;});
  d.emphasis.forEach(e=>{
   const at=+e.start_sec||0;
   const s=(e.i0!=null&&m.subs.find(x=>x.i0===e.i0&&!x.del))||m.subs.filter(x=>!x.del&&x.text===e.text&&!x.emph)
    .sort((a,b)=>Math.abs(a.start-at)-Math.abs(b.start-at))[0];
   if(s)s.emph=e.level?{level:e.level,zoom:!!e.zoom}:{color:e.color,scale:e.scale,zoom:!!e.zoom};
  });
 }
 if(Array.isArray(d.zooms)){
  m.clips.forEach(c=>{c.zoom=null;});
  d.zooms.forEach(z=>{const c=m.clips[z.clip];if(c&&Array.isArray(z.stages))c.zoom={stages:z.stages.map(x=>({...x}))};});
 }
}

// collectOv: 바뀐 것만 {emphasis, zooms}. 편집본 시각은 runEngineRules 가 옮겨 둔 자막 자리.
export function collect(cur,forDraft){
 if(!cur.orig||!cur.orig.fx)return {};
 const m=cur.model,out={};
 if(emphSig(m.subs)!==cur.orig.fx.emph)
  out.emphasis=m.subs.filter(s=>!s.del&&s.emph&&String(s.text).trim()).map(s=>({text:String(s.text).trim(),start_sec:+(+s.start).toFixed(3),
   ...(s.emph.level?{level:s.emph.level}:{color:s.emph.color,scale:+s.emph.scale}),zoom:!!s.emph.zoom,...(forDraft&&s.i0!=null?{i0:s.i0}:{})}));
 if(zoomSig(m.clips)!==cur.orig.fx.zoom)
  out.zooms=m.clips.map((c,i)=>c.zoom?{clip:i,stages:c.zoom.stages.map(x=>({from_sec:+(+x.from_sec).toFixed(3),factor:+x.factor,anchor:x.anchor||'center'}))}:null).filter(Boolean);
 return out;
}

// ── 화면 ──────────────────────────────────────────────────────────────
export const subClass=s=>s&&s.emph?(s.emph.level===2||(!s.emph.level&&s.emph.color==='red')?' fx-emph2':' fx-emph'):'';
const ZOOM_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5M11 8v6M8 11h6"/></svg>';
export const clipBadge=c=>c&&c.zoom?`<span class="fx-zoom" title="줌 ${c.zoom.stages.map(x=>x.factor+'배').join(' → ')}">${ZOOM_ICON}</span>`:'';

// 미리보기 자막: 강조 줄은 렌더처럼 크게·색을 바꿔 보인다
export function subLook(s){const l=look(s&&s.emph);return l&&{scale:l.scale,color:COLORS[l.color][0]};}

// 미리보기 줌: 지금 구간의 단계 배율로 영상을 당긴다
let zoomNow='';
export function paint(cur,outT,H){
 // 줌은 영상을 감싼 칸(#vzoom)에 건다 — 영상(#vid) 자체는 자르기(editor-frame.js)가 옮긴다
 const v=document.getElementById('vzoom')||document.getElementById('vid');if(!v)return;
 let tf='';
 if(outT!=null&&cur.model){
  const f=(cur.model.final||[]).find(c=>!c.dead&&outT>=c.out&&outT<c.out+H.clipDur(c));
  const z=f&&cur.model.clips[f.i]&&cur.model.clips[f.i].zoom;
  if(f){
   const rel=outT-f.out,st=z&&z.stages.filter(x=>+x.from_sec<=rel+1e-3).pop();
   let k=st?+st.factor:1,a=(st&&st.anchor)||'center';
   // 줌도 같이 건 강조: 그 줄 시작부터 이 구간에 줌이 없으면 1.2배, 있으면 한 단계 +0.1배(엔진 짝 채움과 같은 규칙)
   const end=f.out+H.clipDur(f);
   const pair=(cur.model.subs||[]).some(s=>!s.del&&s.emph&&s.emph.zoom&&s.start>=f.out-1e-3&&s.start<end&&s.start<=outT);
   if(pair)k=k>1?Math.min(1.6,+(k+0.1).toFixed(2)):1.2;
   if(k>1)tf=`${k}|${a}`;
  }
 }
 if(tf===zoomNow)return;zoomNow=tf;
 if(!tf){v.style.transform='';v.style.transformOrigin='';return;}
 const [k,a]=tf.split('|');
 v.style.transformOrigin={left:'0% 50%',right:'100% 50%'}[a]||'50% 50%';v.style.transform=`scale(${k})`;
}

function lockNote(){return canEdit?'':'<div class="small faint">강조와 줌은 아직 여기서 바꿀 수 없어요.</div>';}

export function subPanel(cur,i,editMode){
 const s=cur.model.subs[i];if(!s||s.del)return '';
 const on=editMode&&canEdit,used=cur.model.subs.filter(x=>!x.del&&x.emph&&x!==s).length,full=used>=EMPH_MAX&&!s.emph;
 const cur1=s.emph&&s.emph.level,custom=s.emph&&!s.emph.level;
 const btn=(val,label,active)=>`<button class="fx-seg${active?' on':''}" ${on&&(!full||val==='none')?'':'disabled'} onclick="__edFx.setEmph(${i},'${val}')">${label}</button>`;
 let h=`<div class="fx-box"><div class="fx-head">강조</div><div class="fx-segs">${btn('none','없음',!s.emph)}${btn('1',LEVELS[1].label,cur1===1)}${btn('2',LEVELS[2].label,cur1===2)}${btn('custom','직접',custom)}</div>`;
 if(custom)h+=`<div class="fx-row"><label>색<select ${on?'':'disabled'} onchange="__edFx.setEmph(${i},'color',this.value)">${Object.entries(COLORS).map(([k,[,n]])=>`<option value="${k}" ${s.emph.color===k?'selected':''}>${n}</option>`).join('')}</select></label>
  <label>크기<select ${on?'':'disabled'} onchange="__edFx.setEmph(${i},'scale',this.value)">${[1.05,1.1,1.15,1.2,1.23,1.3,1.35,1.4,1.45].map(x=>`<option value="${x}" ${Math.abs(+s.emph.scale-x)<0.005?'selected':''}>${x}배</option>`).join('')}</select></label></div>`;
 if(s.emph)h+=`<label class="fx-check"><input type="checkbox" ${s.emph.zoom?'checked':''} ${on?'':'disabled'} onchange="__edFx.setEmph(${i},'zoom',this.checked)"> 줌도 같이</label>
  <div class="small faint">줌도 같이 켜면 이 줄이 시작할 때 화면을 한 번 더 당겨요. 강조 줄에는 효과음이 함께 붙어요.</div>`;
 if(full)h+=`<div class="small faint">강조는 한 편에 ${EMPH_MAX}줄까지예요. 다른 줄을 빼면 걸 수 있어요.</div>`;
 return h+lockNote()+`</div>`;
}

export function clipPanel(cur,i,editMode,H){
 const c=cur.model.clips[i];if(!c)return '';
 const on=editMode&&canEdit,used=cur.model.clips.filter(x=>x.zoom&&x!==c).length,full=used>=ZOOM_MAX&&!c.zoom;
 const len=H.clipDur(c);
 let h=`<div class="fx-box"><div class="fx-head">줌</div><div class="fx-segs">
  <button class="fx-seg${c.zoom?'':' on'}" ${on?'':'disabled'} onclick="__edFx.setZoom(${i},'off')">없음</button>
  <button class="fx-seg${c.zoom?' on':''}" ${on&&!full?'':'disabled'} onclick="__edFx.setZoom(${i},'on')">줌</button></div>`;
 if(c.zoom){
  h+=c.zoom.stages.map((x,k)=>`<div class="fx-row"><label>시작<input type="number" step="0.1" min="0" max="${len.toFixed(1)}" value="${(+x.from_sec).toFixed(1)}" ${on?'':'disabled'} onchange="__edFx.setZoom(${i},'from',this.value,${k})"><span>초</span></label>
   <label>배율<select ${on?'':'disabled'} onchange="__edFx.setZoom(${i},'factor',this.value,${k})">${(k===0?[1,...FACTORS]:FACTORS).map(f=>`<option value="${f}" ${Math.abs(+x.factor-f)<0.001?'selected':''}>${f}배</option>`).join('')}</select></label>
   <label>쪽<select ${on?'':'disabled'} onchange="__edFx.setZoom(${i},'anchor',this.value,${k})">${Object.entries(ANCHORS).map(([a,n])=>`<option value="${a}" ${(x.anchor||'center')===a?'selected':''}>${n}</option>`).join('')}</select></label>
   ${k>0&&on?`<button class="lnk" onclick="__edFx.setZoom(${i},'del',null,${k})">빼기</button>`:''}</div>`).join('');
  if(on&&c.zoom.stages.length<STAGE_MAX)h+=`<button class="lnk" onclick="__edFx.setZoom(${i},'add')">단계 더하기</button>`;
  h+=`<div class="small faint">시작은 이 구간 안에서 몇 초부터인지예요. 단계를 더하면 계단처럼 한 번 더 당겨요. 쪽은 인물이 있는 쪽으로 두면 얼굴이 가장자리로 밀리지 않아요.</div>`;
 }
 if(full)h+=`<div class="small faint">줌은 한 편에 ${ZOOM_MAX}곳까지예요.</div>`;
 return h+lockNote()+`</div>`;
}

// ── 바꾸기(ves-editor 의 __edMut 로 실행 취소·다시 그리기를 함께 한다) ──
function mut(fn,kind,i){if(canEdit&&window.__edMut)window.__edMut(fn,kind,i);}
export function setEmph(i,what,val){
 mut(m=>{const s=m.subs[i];if(!s)return;
  if(what==='none')s.emph=null;
  else if(what==='1'||what==='2')s.emph={level:+what,zoom:what==='2'};      // 기본: 2차만 줌도 같이
  else if(what==='custom')s.emph={color:(s.emph&&look(s.emph).color)||'red',scale:(s.emph&&look(s.emph).scale)||1.23,zoom:false};
  else if(what==='color'&&s.emph)s.emph={color:val,scale:look(s.emph).scale,zoom:!!s.emph.zoom};
  else if(what==='scale'&&s.emph)s.emph={color:look(s.emph).color,scale:Math.min(1.45,Math.max(1.05,+val||1.23)),zoom:!!s.emph.zoom};
  else if(what==='zoom'&&s.emph)s.emph={...s.emph,zoom:!!val};
 },'sub',i);
}
export function setZoom(i,what,val,k){
 mut(m=>{const c=m.clips[i];if(!c)return;
  if(what==='off'){c.zoom=null;return;}
  if(what==='on'){if(!c.zoom)c.zoom={stages:[{from_sec:0,factor:1.2,anchor:'center'}]};return;}
  if(!c.zoom)return;
  const st=c.zoom.stages;
  if(what==='add'&&st.length<STAGE_MAX){const last=st[st.length-1];st.push({from_sec:+(+last.from_sec+0.8).toFixed(1),factor:Math.min(1.6,+(+last.factor+0.1).toFixed(2)),anchor:last.anchor});}
  else if(what==='del'&&k>0)st.splice(k,1);
  else if(what==='from'&&st[k])st[k].from_sec=Math.max(0,+val||0);
  else if(what==='factor'&&st[k])st[k].factor=+val;
  else if(what==='anchor'&&st[k])st[k].anchor=val;
  st.sort((a,b)=>a.from_sec-b.from_sec);
  if(st.length>1||+st[0].factor>1)return;
  c.zoom=null;                          // 1배 한 단계뿐이면 줌이 아니다
 },'clip',i);
}

window.__edFx={load,collect,subClass,clipBadge,subLook,paint,subPanel,clipPanel,setEmph,setZoom,setEditable};

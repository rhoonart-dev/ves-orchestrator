// 구간 화면 위치 — 미리보기를 완성본과 같은 자리로 자르고, 구간마다 가로 위치를 끌어서 정한다(2026-09-29).
// 자르기 기록: 묶음 videos/<vN>/framing.json(tikitaka_framing/v1, ai-video ffe1002f). 원본 px 사각형을 원본 초 구간마다 적는다.
//   source(원본 크기) · active(검은 띠 뺀 그림 영역) · band(완성본 영상 칸) · clips[i].segs[{t0,t1,x,y,w,h}] · mode auto|manual.
// 보내는 값: overrides.clips[i].frame_x 0~1 = 그림 영역 폭 기준 크롭 가운데의 가로 위치. 없으면 자동(얼굴 따라가기).
//   '자동으로 되돌리기' = 키를 뺀다. 앞 제출에서 고정한 구간은 framing 의 manual 로 돌아와 그 값으로 시작한다.
// 자동 구간의 미리보기는 원본 시각으로 사각형을 찾는다 — 나누거나 옮겨도 같은 샷이면 같은 자리다.
// 줌(editor-fx.js)은 바깥 칸 #vzoom 에, 자르기는 안쪽 영상 #vid 에 건다(둘 다 transform 을 쓰면 서로 덮는다).
// framing.json 이 없는 판(다시 렌더 전)은 자동 구간은 지금처럼 가운데 채우기, 직접 지정 구간만 대략으로 보인다.
let F=null,canEdit=false,sig='',last=null,mounted=false;
const ok=f=>f&&f.schema==='tikitaka_framing/v1'&&f.source&&f.active&&f.band&&Array.isArray(f.clips);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const MOVE='<svg viewBox="0 0 24 24"><path d="M4 12h16M8 8l-4 4 4 4M16 8l4 4-4 4"/></svg>';

export function setup(framing,editable){F=ok(framing)?framing:null;sig='';mount();setEditable(editable);}
export const hasFraming=()=>!!F;

// 렌더 기준값 — 앞 제출에서 사람이 고정한 구간(mode manual)은 그 사각형 가운데로 frame_x 를 되살린다
export function baseX(i){
 const c=F&&F.clips[i];if(!c||c.mode!=='manual'||!c.segs||!c.segs.length)return null;
 const g=c.segs[0],a=F.active;return +clamp((g.x+g.w/2-a.x)/a.w,0,1).toFixed(4);
}

// 원본 단위(원본 px, 없으면 미리보기 사본 px)의 크기·그림 영역
function space(v){
 if(F)return {sw:F.source.w,sh:F.source.h,a:F.active};
 const sw=v.videoWidth,sh=v.videoHeight;if(!sw||!sh)return null;
 return {sw,sh,a:{x:0,y:0,w:sw,h:sh}};
}
function segAt(s){   // 이 원본 시각에 완성본이 잘라 쓴 사각형 — 자동 구간 것을 먼저
 if(!F)return null;let hit=null;
 for(const c of F.clips)for(const g of c.segs||[])
  if(s>=g.t0-1e-3&&s<g.t1+1e-3){if(c.mode!=='manual')return {g,auto:true};hit=hit||{g,auto:false};}
 return hit;
}
// 구간 i 의 원본 시각 s 에서 영상 칸에 보이는 사각형(원본 단위). null = 가운데 채우기(지금 방식)
function rectAt(clip,s,v,slot){
 const sp=space(v);if(!sp)return null;const a=sp.a,hit=segAt(s);
 let w,h,y;
 if(hit){w=hit.g.w;h=hit.g.h;y=hit.g.y;}
 else{const asp=slot.clientWidth/Math.max(1,slot.clientHeight);h=a.h;w=Math.min(a.w,h*asp);y=a.y;}
 if(clip.frame_x!=null){const cx=a.x+clip.frame_x*a.w;return {x:clamp(cx-w/2,a.x,a.x+a.w-w),y,w,h,sp};}
 if(hit&&hit.auto)return {x:hit.g.x,y,w,h,sp};
 if(!F)return null;
 return {x:a.x+(a.w-w)/2,y,w,h,sp};   // 고정했다가 자동으로 되돌린 구간 — 다시 렌더 전에는 자동 자리를 모른다(가운데로 보인다)
}
function apply(v,slot,r){
 if(!r){if(v.dataset.fr){v.removeAttribute('style');delete v.dataset.fr;}return;}
 const k=slot.clientWidth/r.w;
 Object.assign(v.style,{position:'absolute',maxWidth:'none',maxHeight:'none',objectFit:'fill',
  width:r.sp.sw*k+'px',height:r.sp.sh*k+'px',left:-r.x*k+'px',top:-r.y*k+'px'});
 v.dataset.fr='1';
}
function finalAt(cur,outT,H){return (cur.model.final||[]).find(c=>!c.dead&&outT>=c.out&&outT<c.out+H.clipDur(c));}

export function paint(cur,outT,H,force){
 const v=document.getElementById('vid'),slot=document.getElementById('vslot');if(!v||!slot)return;
 let r=null,f=null;
 if(outT!=null&&cur&&cur.model){f=finalAt(cur,outT,H);
  if(f){const clip=cur.model.clips[f.i];if(clip)r=rectAt(clip,H.clipSrcAt(f,f.out,outT),v,slot);}}
 last={cur,outT,H,i:f?f.i:-1,r};
 const s=r?[r.x,r.y,r.w,r.h,slot.clientWidth].map(n=>Math.round(n*10)).join(','):'';
 if(!force&&s===sig)return;sig=s;apply(v,slot,r);
}

export function clipBadge(c){
 return c&&c.frame_x!=null?`<span class="fr-man" title="화면 위치를 직접 정한 구간">${MOVE}</span>`:'';
}
export function clipPanel(cur,i,editMode){
 const c=cur.model.clips[i];if(!c)return'';const man=c.frame_x!=null;
 // 안내는 한 줄만 — 바꿀 수 없으면 그 이유, 바꿀 수 있으면 방법(자르기 기록이 없으면 그 사실을 덧붙인다)
 const tip=!canEdit?'이 영상은 아직 여기서 바꿀 수 없어요.'
  :editMode?'영상을 좌우로 끌어서 바꿔요.'+(F?'':' 다시 렌더하기 전이라 완성본과 조금 다를 수 있어요.')
  :F?'':'다시 렌더하기 전이라 완성본과 조금 다를 수 있어요.';
 const note=tip?`<div class="small faint">${tip}</div>`:'',miss='';
 return `<div class="fr-row"><span class="k">화면 위치</span><span class="v">${man?'직접 정함':'자동 (얼굴 따라가기)'}</span>
  ${man&&editMode&&canEdit?`<button type="button" class="lnk" onclick="__edFrame.reset(${i})">자동으로 되돌리기</button>`:''}</div>${note}${miss}`;
}
export function reset(i){
 if(!window.__edEditing||!window.__edEditing())return;
 const cur=window.__edCur&&window.__edCur(),c=cur&&cur.model&&cur.model.clips[i];if(!c||c.frame_x==null)return;
 window.__edSnap();c.frame_x=null;window.__edRefresh('clip',i,true);
 if(last&&last.cur)paint(last.cur,last.outT,last.H,true);
}

// 끌기 — 편집 중, 영상 칸(자막·제목 같은 글자 위가 아닌 곳)을 좌우로. 한 번 끌기 = ⌘Z 한 번
function mount(){
 if(mounted)return;mounted=true;
 const slot=()=>document.getElementById('vslot');
 new ResizeObserver(()=>{if(last&&last.cur)paint(last.cur,last.outT,last.H,true);}).observe(slot());
 document.addEventListener('mousedown',e=>{
  const sl=slot();if(!canEdit||!sl||!sl.contains(e.target)||e.button!==0)return;
  if(!window.__edEditing||!window.__edEditing())return;
  const cur=window.__edCur&&window.__edCur();if(!cur||!cur.model)return;
  const H=last&&last.H;const outT=window.__edOutNow();if(!H||outT==null)return;
  paint(cur,outT,H,true);
  const i=last.i,clip=cur.model.clips[i],v=document.getElementById('vid');if(!clip)return;
  const r0=last.r||rectAt({...clip,frame_x:.5},H.clipSrcAt(finalAt(cur,outT,H),finalAt(cur,outT,H).out,outT),v,sl);
  if(!r0)return;
  e.preventDefault();e.stopPropagation();
  const a=r0.sp.a,k=sl.clientWidth/r0.w,cx0=r0.x+r0.w/2,x0=e.clientX,half=Math.min(.5,r0.w/2/a.w);
  let moved=false;
  const mv=ev=>{
   const dx=ev.clientX-x0;if(!moved){if(Math.abs(dx)<10)return;moved=true;window.__edSnap();}   // 10px 넘게 끌어야 옮긴다 — 3px 이면 영상을 누르다 손이 밀려 크롭이 고정됐다(2026-10-02 v6)
   clip.frame_x=+clamp((cx0-dx/k-a.x)/a.w,half,1-half).toFixed(4);
   paint(cur,outT,H,true);
  };
  const up=()=>{removeEventListener('mousemove',mv);removeEventListener('mouseup',up);sl.classList.remove('fr-drag');
   if(!moved)return;window.__ovDragged=true;window.__edRefresh('clip',i,true);};
  sl.classList.add('fr-drag');addEventListener('mousemove',mv);addEventListener('mouseup',up);
 },true);
}
export function setEditable(on){canEdit=!!on;document.getElementById('vslot')?.classList.toggle('fr-ok',canEdit);}

window.__edFrame={setup,hasFraming,baseX,paint,clipBadge,clipPanel,reset,setEditable};

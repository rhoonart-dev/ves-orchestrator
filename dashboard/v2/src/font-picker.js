// 폰트 고르기 — 기본 선택 상자는 크롬이 목록 글꼴을 못 바꾸게 해서, 폰트 칸만 직접 그린 목록으로 바꾼다(2026-10-02 사용자).
// <select data-font data-default="기본값 이름" data-default-value="기본값 폰트"> 을 두면 저절로 바뀐다.
// 템플릿 고르기처럼 값이 폰트가 아닌 목록은 option 에 data-ff(그 줄 글꼴) · data-c1 · data-c2(제목 두 줄 색)를 단다. 고르면 원래 select 의 값을 바꾸고 change 를 보내므로
// 편집실(dsSet) · 채널 템플릿 화면의 기존 처리가 그대로 돈다. 글꼴은 엔진 폰트 이름(src/editor-shell.css · src/engine-fonts.js).
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const W=[['6SemiBold','세미볼드'],['7Bold','볼드'],['8ExtraBold','엑스트라볼드'],['9Black','블랙']];
// 값(엔진 파일 이름 · 편집실 한글 이름) → [글꼴, 정식 이름]
const FONT={
 'Jalnan':['EngineJalnan','여기어때 잘난체 2'],'여기어때 잘난체 2 TTF':['EngineJalnan','여기어때 잘난체 2'],
 'JalnanGothic':['EngineJalnanGothic','여기어때 잘난체 고딕'],'여기어때 잘난체 고딕 TTF':['EngineJalnanGothic','여기어때 잘난체 고딕'],
 'mulmaru':['EngineMulmaru','물마루'],'물마루':['EngineMulmaru','물마루'],
 'Griun':['EngineGriun','그리운 경찰공평체'],'그리운 경찰공평체':['EngineGriun','그리운 경찰공평체'],
 'NotoSansCJKkr-Black':['EngineNotoBlack','Noto Sans CJK KR Black'],'Noto Sans CJK KR':['EngineNotoBlack','Noto Sans CJK KR Black'],
 'WAGURI':['EngineWaguri','와구리체'],'와구리체':['EngineWaguri','와구리체'],
};
for(const [f,ko] of [['Paperlogy','페이퍼로지'],['Freesentation','프리젠테이션'],['A2Z','에이투지체']])
 for(const [st,kw] of W){const v=[`Engine${f}${st}`,`${ko} ${kw}`];FONT[`${f}-${st}`]=v;FONT[`${ko} ${kw}`]=v;}
export const fontFull=v=>(FONT[v]||[])[1]||v||'';
const family=v=>`${(FONT[v]||[])[0]||'inherit'},Pretendard,-apple-system,sans-serif`;
const CHEVRON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

function enhance(sel){
 if(sel.dataset.fp)return;sel.dataset.fp='1';
 const box=document.createElement('div');box.className='fp';
 sel.style.display='none';sel.after(box);
 const def=sel.dataset.default||'';
 const opts=()=>[...sel.options].map(o=>({v:o.value,t:o.textContent.trim(),ff:o.dataset.ff??o.value,c:[o.dataset.c1,o.dataset.c2].filter(Boolean)}));
 const dots=o=>o.c.length?`<i class="fp-dots">${o.c.map(c=>`<b style="background:${esc(c)}"></b>`).join('')}</i>`:'';
 const draw=open=>{
  const cur=opts().find(o=>o.v===sel.value)||opts()[0]||{v:'',t:''};
  box.innerHTML=`<button type="button" class="fp-btn" ${sel.disabled?'disabled':''} style="font-family:${family(cur.ff||sel.dataset.defaultValue)}">${esc(cur.t)}${CHEVRON}</button>
   <div class="fp-list" role="listbox" ${open?'':'hidden'}>${opts().map(o=>`<button type="button" role="option" class="fp-item${o.v===sel.value?' on':''}" data-v="${esc(o.v)}"
    style="font-family:${family(o.ff||sel.dataset.defaultValue)}"><span>${esc(o.t)}</span>${dots(o)}${!o.v&&def?`<small>${esc(def)}</small>`:''}</button>`).join('')}</div>`;
  box.querySelector('.fp-btn').onclick=e=>{e.preventDefault();e.stopPropagation();const l=box.querySelector('.fp-list');draw(l.hidden);
   if(!l.hidden)return;box.querySelector('.fp-item.on')?.scrollIntoView({block:'nearest'});};
  box.querySelectorAll('.fp-item').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();
   if(sel.value!==b.dataset.v){sel.value=b.dataset.v;sel.dispatchEvent(new Event('change',{bubbles:true}));}
   draw(false);});
 };
 draw(false);
 box.__close=()=>{const l=box.querySelector('.fp-list');if(l&&!l.hidden)draw(false);};
 sel.addEventListener('change',()=>draw(false));
}
// 바깥을 누르면 펼친 목록을 닫는다(하나의 듣기만 — 패널을 다시 그려도 쌓이지 않게)
document.addEventListener('mousedown',e=>{document.querySelectorAll('.fp').forEach(b=>{if(!b.contains(e.target))b.__close?.();});});
export function enhanceAll(root=document){root.querySelectorAll('select[data-font]:not([data-fp])').forEach(enhance);}
// 패널은 다시 그려질 때마다 새 select 가 생긴다 — 들어오는 대로 바꾼다(한 프레임에 한 번만 찾는다)
let queued=false;
new MutationObserver(()=>{if(queued)return;queued=true;setTimeout(()=>{queued=false;enhanceAll();},0);})
 .observe(document.documentElement,{childList:true,subtree:true});
enhanceAll();
window.__fontFull=fontFull;

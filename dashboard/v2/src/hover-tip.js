// 마우스를 올리면 바로 뜨는 작은 설명 — 브라우저 기본 title 은 1초쯤 늦게 뜨고 모양을 못 바꿔서 워크스페이스 모양으로.
// data-tip="설명" 을 달거나, 예전처럼 title 을 달아도 된다(올리는 순간 title 을 data-tip 으로 옮겨 기본 설명이 같이 뜨지 않게).
// 마우스를 올리거나 키보드로 고르면 그 아래(자리가 없으면 위)에 뜬다. 워크스페이스 · 편집실 둘 다 쓴다.
let tip=null,cur=null,timer=0;
// 단축키 설명은 맥 기호로 적어 두고(⌘Z · ⇧⌘Z), 윈도우 · 리눅스에서는 Ctrl 로 바꿔 보여 준다(다시 실행은 윈도우에 익숙한 Ctrl+Y)
const MAC=/Mac|iPhone|iPad/.test(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent);
const keys=t=>MAC?t:t.replace(/⇧⌘Z/g,'Ctrl+Y').replace(/⇧⌘(\w)/g,'Ctrl+Shift+$1').replace(/⌘⇧(\w)/g,'Ctrl+Shift+$1').replace(/⌘\+?/g,'Ctrl+').replace(/⌥\+?/g,'Alt+').replace(/⇧\+?/g,'Shift+');
const SEL='[data-tip],[title]';
// title → data-tip. 글자 없는 아이콘 버튼은 title 이 이름이었으니 aria-label 로, 나머지는 설명(aria-description)으로 남긴다
function adopt(el){
 if(!el.hasAttribute('title'))return;
 const t=el.getAttribute('title').trim();el.removeAttribute('title');
 if(!t){delete el.dataset.tip;return;}
 el.dataset.tip=keys(t);
 if(!el.getAttribute('aria-label')&&!el.textContent.trim())el.setAttribute('aria-label',t);
 else el.setAttribute('aria-description',t);
}
function target(e){const el=e.target?.closest?.(SEL);if(el)adopt(el);return el?.dataset.tip?el:null;}
function show(el){
 const text=el.dataset.tip;if(!text||!el.isConnected)return;
 if(!tip){tip=document.createElement('div');tip.className='ws-hint';tip.setAttribute('role','tooltip');tip.id='ws-hint';document.body.append(tip);}
 tip.textContent=keys(text);cur=el;el.setAttribute('aria-describedby','ws-hint');tip.classList.add('on');
 const r=el.getBoundingClientRect(),vw=document.documentElement.clientWidth,m=8,w=tip.offsetWidth,h=tip.offsetHeight;
 const up=r.bottom+8+h>innerHeight-m;
 tip.style.left=Math.min(Math.max(r.left+r.width/2-w/2,m),vw-w-m)+'px';
 tip.style.top=(up?r.top-8-h:r.bottom+8)+'px';
}
function hide(){clearTimeout(timer);if(cur)cur.removeAttribute('aria-describedby');cur=null;tip?.classList.remove('on');}
export function setupHoverTips(){
 injectStyle();
 document.addEventListener('pointerover',e=>{
  const el=target(e);
  if(el&&el===cur)return;hide();if(!el||e.pointerType==='touch')return;
  timer=setTimeout(()=>show(el),150);   // 지나가기만 할 때는 안 뜨게 아주 조금만 기다린다
 });
 document.addEventListener('focusin',e=>{const el=target(e);if(el&&el.matches(':focus-visible'))show(el);});
 document.addEventListener('focusout',hide);
 document.addEventListener('pointerdown',hide,true);
 addEventListener('scroll',hide,true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
}
// 모양 — 워크스페이스는 검은 알약(--solid), 편집실(다크)은 --hint-bg 로 바꾼다(editor-shell.css)
function injectStyle(){
 if(document.querySelector('style[data-ws-hint]'))return;
 const el=document.createElement('style');el.dataset.wsHint='';
 el.textContent=`.ws-hint{position:fixed;z-index:1000;max-width:min(320px,calc(100vw - 16px));padding:7px 12px;border-radius:10px;background:var(--hint-bg,var(--solid,#17181c));color:var(--hint-ink,var(--on-solid,#fff));font-size:12px;font-weight:500;line-height:1.45;white-space:pre-line;box-shadow:0 8px 24px #00000033;pointer-events:none;opacity:0;transform:translateY(-2px);transition:opacity .12s ease,transform .12s ease}
.ws-hint.on{opacity:1;transform:none}
@media(prefers-reduced-motion:reduce){.ws-hint{transition:none}}`;
 document.head.append(el);
}

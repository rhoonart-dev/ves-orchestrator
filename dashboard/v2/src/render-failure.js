import {nodeRobot} from './node-robots.js';
// 다시 렌더 실패 — 한 줄은 짧게(이유), '자세히'를 누르면 말풍선에 이유 · 할 일 · 렌더한 맥미니 로봇이 직접 남긴 말.
// 작업 화면(workbench) · 편집실 목록(local-videos) · 편집실 알림 창(editor-notes)이 같이 쓴다. 모양은 여기서 스스로 넣는다(두 페이지 공용).
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// 엔진 · 오케스트레이터가 남긴 원문에서 맨 안쪽 말만 — '다시 렌더하지 못했어요: {"error": "…"}' → '…'
export function engineSaid(raw){
 let s=String(raw||'').trim();
 for(let i=0;i<3;i++){
  s=s.replace(/^(다시 렌더 실패|다시 렌더하지 못했어요|수정 기록을 남기지 못했어요)\s*[:：]\s*/,'').trim();
  const m=s.match(/\{[^{}]*"error"\s*:\s*"((?:[^"\\]|\\.)*)"[^{}]*\}/);
  if(m){try{s=JSON.parse(`"${m[1]}"`);}catch{s=m[1];}}
 }
 return s.split('\n').map(x=>x.trim()).filter(Boolean).pop()||'';
}

// 원문 → 사람이 읽을 이유(title) · 할 일(todo). where: '맥미니' | '작업 컴퓨터'
const KNOWN=[
 [/원본 영상을 찾을 수 없어요|원본 캐시가 이 노드에 없어요|원본 영상이 이 노드에 없어요/,w=>`${w}에 원본 영상이 없어요`,w=>w==='맥미니'?'다시 제출하면 원본을 다시 받아 렌더해요.':'원본 파일이 제자리에 있는지 확인한 뒤 다시 제출해 주세요.'],
 [/최신 판이 아니에요/,()=>'그 사이 영상이 새로 만들어졌어요',()=>'편집실을 새로 열어 최신 판에서 고쳐 주세요.'],
 [/잡 폴더가 없어요/,w=>`이 영상을 만든 ${w}에 작업 폴더가 없어요`,()=>'관리자에게 알려 주세요.'],
 [/렌더가 묶음과 달라요/,w=>`${w}가 이 영상을 다시 만드는 중이에요`,()=>'끝난 뒤 다시 제출해 주세요.'],
];
export function failureInfo(raw,{node=null,at=null,restorable=false}={}){
 const said=engineSaid(raw),where=node?'맥미니':'작업 컴퓨터';
 const hit=KNOWN.find(([re])=>re.test(said));
 const title=hit?hit[1](where):'다시 렌더하지 못했어요';
 const todo=hit?hit[2](where):'잠시 뒤 다시 제출해 주세요. 계속되면 관리자에게 알려 주세요.';
 return {title,todo:(restorable?'고친 내용은 그대로 남아 있어요. ':'')+todo,said,node,at};
}

const kst=v=>{if(!v)return '';const d=new Date(v);return Number.isNaN(+d)?'':d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',hour:'numeric',minute:'2-digit'});};   // 9월 30일 오후 7:52
// 렌더한 기계가 직접 남긴 말 — 왼쪽에 그 맥미니의 로봇(맥·배포 탭과 같은 로봇), 이름표는 mm-02 그대로
// 로봇 머리 바로 위 파란 물음표 — 잠든 로봇의 zZ 처럼 한 칸 1px 도트로 가늘게
const Q=['.##.','#..#','..#.','.#..','....','.#..'].flatMap((r,y)=>[...r].flatMap((c,x)=>c==='#'?[`M${x} ${y}h1v1h-1z`]:[])).join('');
// 로봇 그림(16칸) 안에 넣는다 — 잠든 로봇의 zZ 와 같은 방식(반 칸 도트). 머리 맨 윗줄 바로 위 가운데
function robotWithQ(node){
 const svg=nodeRobot(node,'awake'),top=Math.min(...[...svg.matchAll(/ y="(\d+)"/g)].map(m=>+m[1]));
 return svg.replace('</svg>',`<path class="rf-q" transform="translate(6.8 ${top-4.2}) scale(.6)" d="${Q}"/></svg>`);
}
export function saidHtml(info){
 if(!info.said)return '';
 const who=info.node||'작업 컴퓨터';
 return `<div class="rf-say">${info.node?`<span class="rf-bot">${robotWithQ(info.node)}</span>`:''}<div class="rf-said"><small>${esc([who,kst(info.at)].filter(Boolean).join(' · '))}</small><div class="rf-bubble">${esc(info.said)}</div></div></div>`;
}
export const detailHtml=info=>`<h3 class="rf-title">${esc(info.title)}</h3><p class="rf-todo">${esc(info.todo)}</p>${saidHtml(info)}`;
// 한 줄 — 이유 + [자세히]. 자세히는 data-rf 로 찾아 openFailurePop 에 넘긴다
export const lineHtml=(info,id='')=>`<span class="rf-line"><span>${esc(info.title)}</span><button type="button" class="rf-why" data-rf="${esc(id)}" aria-haspopup="dialog" aria-expanded="false">자세히<svg viewBox="0 0 12 12" aria-hidden="true"><path d="m4 5 2 2 2-2"/></svg></button></span>`;

let pop=null;
export function openFailurePop(anchor,info,{action=null}={}){
 const same=pop?.anchor===anchor;closePop();if(same)return;
 injectStyle();
 pop=document.createElement('div');pop.className='rf-pop';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','다시 렌더 실패');
 pop.innerHTML=`${detailHtml(info)}${action?`<footer><a class="rf-act" href="${esc(action.href)}">${esc(action.label)}</a></footer>`:''}<i class="rf-tail" aria-hidden="true"></i>`;
 document.body.append(pop);pop.anchor=anchor;anchor.setAttribute('aria-expanded','true');place();
 setTimeout(()=>{document.addEventListener('pointerdown',outside);document.addEventListener('keydown',onKey);addEventListener('resize',place);addEventListener('scroll',place,true);});
}
function place(){
 if(!pop)return;const a=pop.anchor.getBoundingClientRect(),vw=document.documentElement.clientWidth,vh=innerHeight,m=16;
 if(!pop.anchor.isConnected||a.bottom<0||a.top>vh)return closePop();
 const w=Math.min(340,vw-m*2);pop.style.width=w+'px';
 const cx=a.left+a.width/2,left=Math.min(Math.max(cx-w/2,m),vw-w-m),h=pop.offsetHeight,up=a.bottom+10+h>vh-m&&a.top-10-h>m;
 pop.style.left=left+'px';pop.style.top=(up?a.top-10-h:a.bottom+10)+'px';pop.classList.toggle('up',up);
 pop.querySelector('.rf-tail').style.left=Math.min(Math.max(cx-left,18),w-18)+'px';
}
function outside(e){if(pop&&!pop.contains(e.target)&&!pop.anchor.contains(e.target))closePop();}
function onKey(e){if(e.key==='Escape'&&pop){const a=pop.anchor;closePop();a.focus();}}
export function closePop(){
 if(!pop)return;pop.anchor.setAttribute('aria-expanded','false');pop.remove();pop=null;
 document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',onKey);removeEventListener('resize',place);removeEventListener('scroll',place,true);
}

// 모양 — 워크스페이스 토큰이 없으면(편집실) 편집실 토큰으로
let styled=false;
export function injectStyle(){
 if(styled)return;styled=true;
 const css=`
.rf-line{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap}
.rf-why{display:inline-flex;align-items:center;gap:3px;height:24px;padding:0 8px 0 10px;border:0;border-radius:999px;font:inherit;font-size:11px;font-weight:600;white-space:nowrap;cursor:pointer;background:color-mix(in srgb,var(--danger,#E5484D) 10%,var(--surface,var(--panel,#fff)));color:var(--danger,#E5484D)}
.rf-why:hover,.rf-why[aria-expanded="true"]{background:color-mix(in srgb,var(--danger,#E5484D) 18%,var(--surface,var(--panel,#fff)))}
.rf-why svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;transition:transform .15s}
.rf-why[aria-expanded="true"] svg{transform:rotate(180deg)}
.rf-pop{position:fixed;z-index:70;background:var(--surface,var(--panel,#fff));color:var(--ink,var(--text,#191a1d));border-radius:16px;padding:18px 20px 20px;box-shadow:0 12px 34px #00000026;text-align:left}
.rf-tail{position:absolute;top:-6px;width:12px;height:12px;margin-left:-6px;background:inherit;transform:rotate(45deg);border-radius:2px}
.rf-pop.up .rf-tail{top:auto;bottom:-6px}
.rf-title{margin:0 0 8px;font-size:14px;font-weight:700;color:inherit}
.rf-todo{margin:0;font-size:12px;line-height:1.75;color:var(--secondary,var(--muted,#707177))}
.rf-say{display:flex;align-items:flex-end;gap:10px;margin-top:18px}
.rf-bot{flex:none;width:30px;height:30px;color:var(--ink,var(--text,#191a1d));position:relative}
.rf-q{fill:var(--accent,#2456E8);animation:rf-q 1.2s steps(1,end) infinite}   /* 두 프레임 — 한 칸씩 톡톡 */
@keyframes rf-q{0%{translate:0 0}50%{translate:0 -1px}}
@media(prefers-reduced-motion:reduce){.rf-q{animation:none}}
.rf-bot .node-robot{width:30px;height:30px;fill:currentColor;overflow:visible}
.rf-bot .nb1{fill:currentColor}.rf-bot .nb2{fill:var(--secondary,var(--muted,#707177))}.rf-bot .nb3{fill:var(--muted,#929299)}.rf-bot .nbg{fill:var(--accent,#3b82f6)}.rf-bot .nbw{fill:#fff}
.rf-said{min-width:0;display:flex;flex-direction:column;gap:6px}
.rf-said small{font-size:10px;color:var(--muted,#929299);padding-left:4px}
.rf-bubble{background:var(--inset,var(--panel2,#f7f7f8));border-radius:14px 14px 14px 4px;padding:10px 14px;font-size:12px;line-height:1.55;overflow-wrap:anywhere;color:inherit}
.rf-pop footer{display:flex;justify-content:flex-end;margin-top:16px}
.rf-act{display:inline-flex;align-items:center;height:28px;padding:0 12px;border-radius:999px;font-size:11px;font-weight:700;text-decoration:none;background:var(--solid,#17181c);color:var(--on-solid,#fff)}`;
 const el=document.createElement('style');el.dataset.rf='';el.textContent=css;document.head.append(el);
}

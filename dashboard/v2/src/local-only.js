import {icon} from './icons.js';
// 웹 주소(기존 대시보드의 /v2/)로 열었을 때와 작업 컴퓨터에서 로컬 서버(scripts/serve.py)로 열었을 때를 가른다.
// 로컬 서버가 있어야 하는 기능(레이블리 조회 · 이 컴퓨터의 영상과 엔진)은 웹에서 숨기지 않고 흐리게 두고 이유를 한 줄 보여 준다.
// 작업 컴퓨터에서도 주소에 ?web 을 붙이면 웹에서 보이는 모습을 미리 본다.
//
// 웹 주소에서도 작업 컴퓨터면 그 컴퓨터의 로컬 서버(127.0.0.1:8769)를 바로 쓴다(serve.py 가 웹 주소 한 곳만 받는다).
// 아무 컴퓨터에서나 내 컴퓨터를 두드리면 크롬이 '로컬 네트워크 접근' 허락을 묻기 때문에, 처음에는 '작업 컴퓨터'를 눌렀을 때만
// 연결해 보고, 한 번 붙으면 이 브라우저에 기억해서 다음부터 열 때 바로 붙는다. 각 컴퓨터는 자기 로컬 작업만 보인다.
const PREVIEW_WEB=new URLSearchParams(location.search).has('web');
const SAME=['127.0.0.1','localhost'].includes(location.hostname)&&!PREVIEW_WEB;
export const LOCAL_ORIGIN='http://127.0.0.1:8769';
const KEY='ves-work-pc';
const remembered=()=>{try{return localStorage.getItem(KEY)==='1'}catch{return false}};
async function ping(ms=1500){
 try{const r=await fetch(LOCAL_ORIGIN+'/api/ping',{cache:'no-store',signal:AbortSignal.timeout(ms)});return r.ok&&(await r.json()).app==='ves-workspace';}
 catch{return false}
}
// 처음 열 때 한 번 — 웹이면 기억해 둔 브라우저에서만 두드린다
export const VIA_WEB=!SAME&&!PREVIEW_WEB&&location.protocol==='https:'&&remembered()&&await ping();
export const ON_WORK_PC=SAME||VIA_WEB;
// 로컬 서버 주소 — 같은 주소로 열었으면 그대로, 웹이면 127.0.0.1:8769 앞에 붙인다
export const apiUrl=path=>VIA_WEB&&String(path).startsWith('/api/')?LOCAL_ORIGIN+path:path;
// 로컬 서버 답 안의 미디어 주소('/api/local-videos/media?…')도 웹이면 127.0.0.1:8769 로
const deep=v=>typeof v==='string'?apiUrl(v):Array.isArray(v)?v.map(deep):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).map(([k,x])=>[k,deep(x)])):v;
export const localize=v=>VIA_WEB?deep(v):v;
// '작업 컴퓨터'를 눌렀을 때 — 붙으면 기억하고 true(화면은 다시 연다), 안 붙으면 false
export async function connectWorkPc(){
 if(SAME||PREVIEW_WEB)return false;
 const ok=await ping(8000);   // 크롬 허락 창이 뜨면 사람이 누를 때까지 기다린다
 try{ok?localStorage.setItem(KEY,'1'):localStorage.removeItem(KEY)}catch{}
 return ok;
}
export const LOCAL_ONLY='작업 컴퓨터에서만 쓸 수 있어요.';
export class LocalOnlyError extends Error{constructor(msg=LOCAL_ONLY){super(msg);this.name='LocalOnlyError';this.localOnly=true;}}
// 로컬 서버를 부르기 직전에 — 웹이면 알아볼 수 있는 이유로 멈춘다(엉뚱한 응답을 읽다 깨지지 않게)
export function needWorkPc(msg){if(!ON_WORK_PC)throw new LocalOnlyError(msg);}
export const localChip=(text='작업 컴퓨터에서만')=>`<span class="local-chip">${icon('laptop')}${text}</span>`;
export const localOnlyEmpty=(title,body='')=>`<div class="local-only-empty"><span class="local-only-ic">${icon('laptop')}</span><h3>${title}</h3>${body?`<p>${body}</p>`:''}</div>`;

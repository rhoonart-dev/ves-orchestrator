import {icon} from './icons.js';
// 웹 주소(기존 대시보드의 /v2/)로 열었을 때와 작업 컴퓨터에서 로컬 서버(scripts/serve.py)로 열었을 때를 가른다.
// 로컬 서버가 있어야 하는 기능(레이블리 조회 · 이 컴퓨터의 영상과 엔진)은 웹에서 숨기지 않고 흐리게 두고 이유를 한 줄 보여 준다.
// 작업 컴퓨터에서도 주소에 ?web 을 붙이면 웹에서 보이는 모습을 미리 본다
export const ON_WORK_PC=['127.0.0.1','localhost'].includes(location.hostname)&&!new URLSearchParams(location.search).has('web');
export const LOCAL_ONLY='작업 컴퓨터에서만 쓸 수 있어요.';
export class LocalOnlyError extends Error{constructor(msg=LOCAL_ONLY){super(msg);this.name='LocalOnlyError';this.localOnly=true;}}
// 로컬 서버를 부르기 직전에 — 웹이면 알아볼 수 있는 이유로 멈춘다(엉뚱한 응답을 읽다 깨지지 않게)
export function needWorkPc(msg){if(!ON_WORK_PC)throw new LocalOnlyError(msg);}
export const localChip=(text='작업 컴퓨터에서만')=>`<span class="local-chip">${icon('laptop')}${text}</span>`;
export const localOnlyEmpty=(title,body='')=>`<div class="local-only-empty"><span class="local-only-ic">${icon('laptop')}</span><h3>${title}</h3>${body?`<p>${body}</p>`:''}</div>`;

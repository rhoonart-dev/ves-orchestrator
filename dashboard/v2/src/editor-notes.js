// 편집실 알림 — 상단바 밝게·어둡게 버튼 왼쪽의 종 버튼과 그 창.
// 예전에는 편집 화면 위에 띠 두 개(영상 안내 한 줄 · 지난 수정 결과)를 깔았는데, 매번 화면을 밀어내고 읽히지 않았다(2026-09-29).
// 창에 모으는 것: 다시 렌더 실패(빨강, 열 때 창을 저절로 연다) · 지난 수정에서 달라진 점 · 편집 중 확인할 것(ves-editor drawWarns 의 #warns)
// · 예외 안내(이전 판 초안을 안 불러옴 등). 종의 숫자 = 지금 확인할 것 + 지난 수정 알림.
import {failureInfo,detailHtml,injectStyle as failureStyle} from './render-failure.js?v=7';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const BELL='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>';
const RECENT_MS=7*24*3600*1000;

export function mountNotes(meta){
 const anchor=document.getElementById('pvBtn')||document.getElementById('fsBtn');if(!anchor)return;   // 종 버튼은 미리보기 버튼 앞(Studio 는 다크 고정이라 테마 버튼이 없다)
 const btn=document.createElement('button');btn.id='bellBtn';btn.type='button';btn.title='알림';btn.setAttribute('aria-label','알림');
 btn.setAttribute('aria-haspopup','dialog');btn.setAttribute('aria-expanded','false');
 btn.innerHTML=BELL+'<b class="bell-n" hidden></b>';
 anchor.before(btn);
 if(meta.apply?.state==='failed')failureStyle();
 const pop=document.createElement('div');pop.id='notePop';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','알림');pop.hidden=true;
 document.body.append(pop);

 const a=meta.apply||null,failed=a&&a.state==='failed';
 const notes=a&&a.state==='done'&&Date.now()-new Date(a.finished_at)<RECENT_MS?(a.notes||[]):[];
 const extra=[meta.draft_note].filter(Boolean);
 const sec=(title,body,cls='')=>`<section class="np-sec ${cls}"><h3>${title}</h3>${body}</section>`;
 // 바깥(말풍선·꼬리) 안에 스크롤되는 몸통을 둔다 — 스크롤 상자에 꼬리를 달면 잘린다
 pop.innerHTML='<div class="np-body"><div class="np-head"><h2>알림</h2></div>'+
  // 이유 · 할 일 · 렌더한 맥미니 로봇이 남긴 말(작업 화면 · 편집실 목록의 '자세히' 말풍선과 같은 내용)
  (failed?sec('지난 제출 실패',`<div class="np-rf">${detailHtml(failureInfo(a.error,{node:a.node||meta.remote_node||null,at:a.finished_at,restorable:!!meta.restored_from}))}</div>${meta.restored_from
    ?'':'<p class="np-sub">제출했던 내용은 불러오지 못했어요. 고친 내용을 다시 넣어 주세요.</p>'}`,'np-fail'):'')+
  sec('편집 중 확인할 것','<div id="npWarns"></div>')+
  (notes.length?sec('지난 수정에서 달라진 점',`<div class="np-box"><ul>${notes.map(n=>`<li>${esc(n.text)}</li>`).join('')}</ul></div>`):'')+
  (extra.length?sec('안내',extra.map(t=>`<p>${esc(t)}</p>`).join('')):'')+'</div>';
 // 편집 중 경고 목록(ves-editor 가 계속 다시 그리는 #warns)을 창 안으로 옮긴다
 const warns=document.getElementById('warns');if(warns)pop.querySelector('#npWarns').append(warns);

 const count=()=>{const w=warns?warns.querySelectorAll('.alert.warn').length:0;return w+notes.length+(failed?1:0);};
 const badge=btn.querySelector('.bell-n');
 const paint=()=>{const n=count();badge.hidden=!n;badge.textContent=n>99?'99+':String(n);btn.classList.toggle('bad',!!failed);};
 paint();if(warns)new MutationObserver(paint).observe(warns,{childList:true,subtree:true});

 const place=()=>{const r=btn.getBoundingClientRect(),right=Math.max(12,innerWidth-r.right);
  // 테두리가 없으니 꼬리가 흰 상단바에 묻히지 않게, 창을 상단바 아래 회색 면 위에 띄운다
  const hb=(btn.closest('header')||btn).getBoundingClientRect().bottom;
  pop.style.top=(Math.max(r.bottom,hb)+14)+'px';pop.style.right=right+'px';
  pop.style.setProperty('--tail-right',Math.max(10,innerWidth-(r.left+r.width/2)-right-7)+'px');};   // 꼬리는 종 버튼 가운데를 가리킨다
 const open=on=>{pop.hidden=!on;btn.setAttribute('aria-expanded',String(on));if(on)place();};
 btn.onclick=e=>{e.stopPropagation();open(pop.hidden);};
 document.addEventListener('click',e=>{if(!pop.hidden&&!pop.contains(e.target)&&e.target!==btn)open(false);});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!pop.hidden)open(false);});
 addEventListener('resize',()=>{if(!pop.hidden)place();});
 // 경고를 눌러 블록으로 가면 창을 닫는다(오른쪽 칸이 그 자리를 보여 준다)
 pop.addEventListener('click',e=>{if(e.target.closest('#warns .alert'))open(false);});
 // 실패면 창을 저절로 연다 — 여는 중 막(로딩)이 걷힌 뒤에(editor-boot 가 부른다). 막 위로 창이 먼저 뜨던 것
 return {openIfFailed:()=>{if(failed)open(true);}};
}

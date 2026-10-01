// 편집실 맨 아래 안내 줄 — 타임라인 마지막 줄이 화면 끝(맥 Dock 자리)에 붙지 않게 한 줄을 두고,
// 왼쪽에 지금 쓸 수 있는 단축키, 오른쪽에 저장 상태(위 도구 줄의 #draftchip · #saveMsg 를 그대로 옮겨 온다 — ves-editor 가 계속 고쳐 쓴다).
// 구간을 고르면 그 구간에 쓰는 키가 앞에 밝게 나온다. 맥은 ⌘ 기호, 윈도우 · 리눅스는 Ctrl. 좁으면 덜 쓰는 키부터 통째로 숨긴다.
const MAC=/mac|iphone|ipad/i.test(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent);
const K=(k,label,ctx=false)=>`<span class="k${ctx?' ctx':''}"><kbd>${k}</kbd>${label}</span>`;
const SEP='<span class="sep" aria-hidden="true"></span>';

function keysHtml(){
 const editing=document.body.classList.contains('editing');
 const clip=document.querySelector('#inner .blk.c.sel'),any=document.querySelector('#inner .blk.sel');
 const groups=[];
 if(editing&&clip)groups.push(['g-ctx',K('S','나누기',true)+K('Delete','지우기',true)+K('E','여기서 끝',true)]);
 else if(editing&&any)groups.push(['g-ctx',K('Delete','지우기',true)]);
 else if(editing)groups.push(['g-mark',K('I','시작')+K('O','끝')+K('Enter','구간 추가')]);
 if(editing)groups.push(['g-undo',K(MAC?'⌘Z':'Ctrl+Z','실행 취소')+K(MAC?'⇧⌘Z':'Ctrl+Y','다시 실행')]);
 groups.push(['g-view',`<span class="k"><kbd>+</kbd><kbd>-</kbd>확대·축소</span>`+K(MAC?'⇧Z':'Shift+Z','전체 보기')+K('F','전체화면')]);
 return groups.map(([cls,h],i)=>(i?SEP:'')+`<span class="grp ${cls}">${h}</span>`).join('');
}

export function mountStatusBar(){
 const wrap=document.querySelector('#tlRoot > .wrap')||document.getElementById('tlRoot');if(!wrap||document.getElementById('edBar'))return;
 const bar=document.createElement('footer');bar.id='edBar';bar.setAttribute('aria-label','단축키 · 저장 상태');
 bar.innerHTML='<div class="eb-keys"></div><div class="eb-save" role="status" aria-live="polite"><i aria-hidden="true"></i></div>';
 wrap.append(bar);
 const keys=bar.querySelector('.eb-keys'),save=bar.querySelector('.eb-save');
 // 저장 상태: 위 도구 줄의 두 글자를 그대로 옮겨 온다(같은 id 라 편집실 코드는 그대로 고쳐 쓴다)
 const chip=document.getElementById('draftchip'),msg=document.getElementById('saveMsg');
 for(const el of [chip,msg])if(el)save.append(el);
 const paintSave=()=>{
  const t=[chip?.textContent.trim(),msg?.textContent.trim()].filter(Boolean);
  save.classList.toggle('empty',!t.length);
  save.classList.toggle('dirty',/저장 안 됨/.test(msg?.textContent||''));
 };
 new MutationObserver(paintSave).observe(save,{childList:true,characterData:true,subtree:true});paintSave();
 // 단축키: 고른 블록 · 편집 잠금이 바뀔 만한 때만 다시 그린다(재생 중 매 프레임 그리지 않게)
 let last='';const paintKeys=()=>{const h=keysHtml();if(h!==last){keys.innerHTML=h;last=h;}};
 let raf=0;const soon=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(paintKeys);};
 document.addEventListener('pointerup',soon);document.addEventListener('keyup',soon);
 new MutationObserver(soon).observe(document.body,{attributes:true,attributeFilter:['class']});
 paintKeys();
}

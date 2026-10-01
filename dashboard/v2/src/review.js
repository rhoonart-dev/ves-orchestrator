import {enhanceDropdowns} from './dropdowns.js';
import {ON_WORK_PC,connectWorkPc} from './local-only.js?v=web-1';
import {showToast} from './toast.js?v=1';
import {loadLocalMedia} from './media-catalog.js';
import {icon} from './icons.js';
import {filterOptions,visibleJobs} from './review-model.js';
import {loadLocalJobs} from './local-jobs.js?v=room-1';
import {workPosters} from './work-posters.js';
// 필터 목록 그림 — 채널은 유튜브 채널 아이콘(channels_mirror.avatar_url), 작품은 작품 탭과 같은 포스터. 없으면 첫 글자.
const norm=t=>String(t||'').replace(/\s/g,'');
const posterByTitle=new Map(Object.values(workPosters).map(p=>[norm(p.title),p.url]));
const pic=o=>o.avatar||posterByTitle.get(norm(o.name))||'';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modes=[['all','전체','grid'],['channel','채널','video'],['work','작품','library']];
let preview=false;try{preview=ON_WORK_PC&&sessionStorage.getItem('ves-workspace-review-preview')==='true'}catch{}   // 웹 주소에선 작업 컴퓨터 목록이 없다
const state={mode:'all',selected:null,query:'',listQuery:'',sort:'newest',preview};
const flatFolder='<svg class="flat-folder" viewBox="0 0 64 50" aria-hidden="true"><path d="M0 8a7 7 0 0 1 7-7h18l8 8h24a7 7 0 0 1 7 7v27a7 7 0 0 1-7 7H7a7 7 0 0 1-7-7Z"/></svg>';
// Data enters at this boundary. Preview rows are never saved or sent to VES.
export function mountReview(root,{jobs=[],connected=false,service=null,source=null,client=null}={}){
 if(source==='live'){state.preview=false;state.mode='all';state.selected=null;state.query='';state.listQuery='';}
 if(source==='local'&&ON_WORK_PC){state.preview=true;state.mode='all';state.selected=null;state.query='';state.listQuery='';try{sessionStorage.setItem('ves-workspace-review-preview','true')}catch{}}
 let disposed=false,catalog=null,refreshing=false,lastAttempt=0,localJobs=[],localState='idle',liveSync='',localSync='';
 const showSync=()=>{root.querySelector('.review-sync').textContent=state.preview?localSync:liveSync;};
 root.innerHTML=`<section class="review-page" aria-label="작업 폴더"><div class="review-toolbar"><div class="folder-context"><h2></h2><span class="folder-count"></span><span class="sample-badge" hidden>작업 컴퓨터에서 만든 영상</span></div><div class="review-toolbar-actions"><span class="review-sync" role="status"></span><button class="review-refresh preview-toggle" type="button">새로고침</button></div></div><div class="review-controls"><div class="review-controls-left"><div class="source-seg" role="radiogroup" aria-label="보는 목록"><button type="button" role="radio" data-src="live" aria-checked="${!state.preview}">${icon('server')}<span>맥미니</span></button><button type="button" role="radio" data-src="local" aria-checked="${state.preview}"${ON_WORK_PC?'':' class="is-local-only" title="작업 컴퓨터에서 로컬 서버를 켜면 볼 수 있어요"'}>${icon('laptop')}<span>작업 컴퓨터</span></button></div><div class="review-segments" role="radiogroup" aria-label="작업 분류"><span class="segment-highlight" aria-hidden="true"></span>${modes.map(([id,name,glyph])=>`<button type="button" role="radio" data-mode="${id}" aria-checked="false">${icon(glyph)}<span>${name}</span></button>`).join('')}</div></div><div class="folder-tools"><label class="folder-search">${icon('search')}<input type="search" aria-label="작업 검색" placeholder="작업 검색" value="${esc(state.query)}"></label><select aria-label="작업 정렬"><option value="newest">최신순</option><option value="oldest">오래된 순</option></select></div></div><div class="review-layout"><div class="filter-slot"><aside class="review-filter" aria-label="작업 필터"><div class="filter-heading"><h2></h2><button class="filter-close" type="button" aria-label="필터 닫기">${icon('close')}</button></div><label class="filter-search">${icon('search')}<input type="search" aria-label="필터 목록 검색" placeholder="검색"></label><div class="filter-options"></div></aside></div><section class="folder-area" aria-label="작업 목록"><div class="folder-results" aria-live="polite"></div></section></div></section>`;
 const $=s=>root.querySelector(s);
  // 맥미니(VES 작업 + 맥미니 새 방식 영상) | 작업 컴퓨터(이 컴퓨터에서 만든 영상만) — 만든 기계로 나눈다
 const data=()=>state.preview?localJobs.filter(j=>!j.remote):[...jobs,...localJobs.filter(j=>j.remote)];
 async function loadLocal(){
  if(!client){localState='error';localSync='로그인하면 작업 컴퓨터 영상을 볼 수 있어요.';showSync();return;}
  localState='loading';localSync='작업 컴퓨터 영상 불러오는 중…';showSync();
  try{localJobs=await loadLocalJobs(client);if(disposed)return;localState='ready';localSync='작업 컴퓨터 · '+new Date().toLocaleTimeString('ko-KR')+' 기준';}
  catch(e){if(disposed)return;localState='error';localSync=e.message||'작업 컴퓨터 영상을 불러오지 못했어요.';}
  showSync();
  renderList();renderCards();
 }
 async function refresh(){
  if(!service||refreshing||disposed)return;refreshing=true;lastAttempt=Date.now();$('.review-refresh').disabled=true;
  try{const loaded=await service.listJobs(true);if(disposed)return;jobs=loaded;connected=true;liveSync='Supabase · '+new Date().toLocaleTimeString('ko-KR')+' 갱신';showSync();renderList();renderCards();}
  catch{if(!disposed){liveSync='조회 실패 · 다시 시도해 주세요.';showSync();}}
  finally{refreshing=false;if(!disposed)$('.review-refresh').disabled=false;}
 }
 $('.review-refresh').hidden=!service;$('.review-refresh').onclick=refresh;
 const options=()=>filterOptions(data(),state.mode);
 function renderList(){
  const title=state.mode==='channel'?'채널':'작품';
  $('.filter-heading h2').textContent=title;
  $('.filter-search input').placeholder=`${title} 검색`;
  const q=state.listQuery.trim().toLocaleLowerCase('ko');
  const list=options().filter(o=>o.name.toLocaleLowerCase('ko').includes(q));
  $('.filter-options').innerHTML=`<button class="filter-option ${!state.selected?'selected':''}" type="button" data-filter="" aria-pressed="${!state.selected}"><span class="filter-avatar">${icon(state.mode==='channel'?'video':'library')}</span><span>전체 ${title}</span><small>${data().length}</small></button>${list.map(o=>`<button class="filter-option ${state.selected===o.id?'selected':''}" type="button" data-filter="${esc(o.id)}" aria-pressed="${state.selected===o.id}"><span class="filter-avatar${pic(o)?(state.mode==='channel'?' has-pic round':' has-pic'):''}">${pic(o)?`<img src="${esc(pic(o))}" alt="" loading="lazy" referrerpolicy="no-referrer">`:esc(o.name.slice(0,1))}</span><span>${esc(o.name)}</span><small>${o.count}</small></button>`).join('')}${!list.length?`<p class="filter-empty">${q?'검색 결과가 없습니다.':state.preview||connected?'등록된 항목이 없습니다.':'목록 연결 전입니다.'}</p>`:''}`;
  $('.filter-options').querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{state.selected=button.dataset.filter||null;renderList();renderCards();});
 }
 function renderCards(){
  const list=visibleJobs(data(),state);
  const selected=options().find(o=>o.id===state.selected);
  $('.folder-context h2').textContent=selected?.name||'전체 작업';
  $('.folder-count').textContent=state.preview?(localState==='ready'?`${list.length}개`:''):connected?`${list.length}개`:'';
  $('.sample-badge').hidden=!state.preview;
  if(!list.length){
   const disconnected=!connected&&!state.preview;
   const localEmpty=state.preview&&!state.query;
   $('.folder-results').innerHTML=`<div class="folder-empty">${flatFolder}<h3>${disconnected?'작업 목록 연결 전':localEmpty?(localState==='loading'?'작업 컴퓨터 영상 불러오는 중':'작업 컴퓨터에서 만든 영상이 없어요'):state.query?'검색 결과가 없습니다':'작업 폴더가 없습니다'}</h3><p>${disconnected?'작업 컴퓨터를 누르면 이 컴퓨터에서 만든 영상을 볼 수 있어요.':localEmpty?'파이프라인이 렌더를 마치면 영상별 묶음(videos/vN)이 자동으로 생겨요.':state.query?'다른 검색어로 찾아보세요.':'새 작업이 등록되면 여기에 표시됩니다.'}</p>${disconnected?'<button class="empty-preview" type="button">작업 컴퓨터</button>':''}</div>`;
   const preview=$('.empty-preview');if(preview)preview.onclick=togglePreview;
   return;
  }
  $('.folder-results').innerHTML=`<div class="folder-grid">${list.map(j=>`<button type="button" class="job-folder" data-job="${esc(j.id)}" aria-label="${esc(j.work+' · '+j.title+' · '+j.id)}"><div class="folder-top">${flatFolder}<span class="folder-status">${esc(j.status)}</span></div><p class="folder-work">${esc(j.work)}</p><h3>${esc(j.title)}</h3><span class="folder-job-id" title="${esc(j.id)}">${esc(j.note||j.id)}</span><div class="folder-bottom"><span>${icon('video')}${esc(j.channel)} · ${catalog?.[j.id]?'완성 영상':esc(j.fileCountLabel||'영상')} ${catalog?.[j.id]?.length??j.videos}개</span><time datetime="${esc(j.madeAt||j.createdAt)}">${new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'long',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(j.madeAt||j.createdAt))} 생성</time></div></button>`).join('')}</div>`;
  $('.folder-results').querySelectorAll('[data-job]').forEach(button=>button.onclick=()=>{
   const job=data().find(j=>j.id===button.dataset.job);
   location.hash=`review/${job.id}`;
  });
 }
 function syncMode(){
  const open=state.mode!=='all';
  $('.review-layout').classList.toggle('has-filter',open);
  $('.filter-slot').inert=!open;
  $('.filter-slot').setAttribute('aria-hidden',String(!open));
  $('.review-segments').style.setProperty('--selected',modes.findIndex(([id])=>id===state.mode));
  root.querySelectorAll('[data-mode]').forEach(b=>{b.setAttribute('aria-checked',String(b.dataset.mode===state.mode));b.tabIndex=b.dataset.mode===state.mode?0:-1;});
  if(open)renderList();renderCards();
 }
 function setMode(mode){if(state.mode===mode)return;state.mode=mode;state.selected=null;state.listQuery='';$('.filter-search input').value='';syncMode();}
 function togglePreview(){state.preview=!state.preview;if(state.preview&&localState!=='ready'&&localState!=='loading')loadLocal();showSync();try{sessionStorage.setItem('ves-workspace-review-preview',String(state.preview))}catch{}state.selected=null;root.querySelectorAll('.source-seg [data-src]').forEach(b=>b.setAttribute('aria-checked',String((b.dataset.src==='local')===state.preview)));renderList();renderCards();}
 root.querySelectorAll('[data-mode]').forEach(button=>{
  button.onclick=()=>setMode(button.dataset.mode);
  button.onkeydown=e=>{const i=modes.findIndex(([id])=>id===state.mode);const next=e.key==='ArrowRight'? (i+1)%3:e.key==='ArrowLeft'?(i+2)%3:e.key==='Home'?0:e.key==='End'?2:null;if(next===null)return;e.preventDefault();setMode(modes[next][0]);$(`[data-mode="${state.mode}"]`).focus();};
 });
 $('.filter-close').onclick=()=>{setMode('all');$('[data-mode="all"]').focus();};
 $('.filter-search input').oninput=e=>{state.listQuery=e.target.value;renderList();};
 $('.folder-search input').oninput=e=>{state.query=e.target.value;renderCards();};
 $('.folder-tools select').value=state.sort;
 $('.folder-tools select').onchange=e=>{state.sort=e.target.value;renderCards();};
 // 보는 목록 고르기(맥미니 | 작업 컴퓨터) — 지금 보는 쪽이 검정으로 채워진다
 root.querySelectorAll('.source-seg [data-src]').forEach(b=>b.onclick=()=>{
  // 웹 주소: 이 컴퓨터에 로컬 서버가 켜져 있으면 붙어서 이 컴퓨터의 작업을 보여 준다(한 번 붙으면 기억). 아니면 이유 한 줄
  if(b.dataset.src==='local'&&!ON_WORK_PC){
   if(b.dataset.busy)return;b.dataset.busy='1';showToast(root,'이 컴퓨터의 로컬 서버를 찾는 중이에요.');
   connectWorkPc().then(ok=>{delete b.dataset.busy;
    if(ok){try{sessionStorage.setItem('ves-workspace-review-preview','true')}catch{}location.reload();}
    else showToast(root,'이 컴퓨터에서 로컬 서버를 찾지 못했어요. 작업 컴퓨터에서 로컬 서버를 켠 뒤 다시 눌러 주세요.');});
   return;}
  if((b.dataset.src==='local')!==state.preview)togglePreview();});


 loadLocal();
 syncMode();
 loadLocalMedia().then(data=>{if(disposed)return;catalog=data;renderCards();}).catch(()=>{});
 const visible=()=>{if(document.visibilityState==='visible'&&Date.now()-lastAttempt>=3600000)refresh();};
 const timer=service?setInterval(visible,3600000):null;document.addEventListener('visibilitychange',visible);refresh();
 const releaseDropdowns=enhanceDropdowns(root);
 return ()=>{releaseDropdowns();disposed=true;clearInterval(timer);document.removeEventListener('visibilitychange',visible)};
}

import {mountWorkflowControls} from './workflow-controls.js?v=web-1';
import {openPremiereExport} from './premiere-export.js?v=4';
import {loadCatalog,loadGuide} from './work-catalog.js?v=hide-1';

import {openThumbnails} from './thumbnail-tool.js?v=rev-1';
import {workflowCardHtml,timelineHtml,reviewEvents} from './workflow-card.js?v=web-1';
import {mountTikitakaReview} from './tikitaka-review.js?v=gap-2';
import {score,reviewLabels} from './review-service.js?v=web-1';
import {icon} from './icons.js';
import {loadLocalMedia,timeLabel} from './media-catalog.js';
import {bundleItem} from './local-jobs.js?v=room-1';
import {failureInfo,lineHtml,openFailurePop,injectStyle as failureStyle} from './render-failure.js?v=7';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const remembered=new Map();
export function guideFragment(html){
 const parsed=new DOMParser().parseFromString(html||'','text/html');
 parsed.querySelectorAll('script,style,iframe,object,embed,form,input,button,svg,math').forEach(e=>e.remove());
 const allowed=new Set(['P','BR','DIV','SPAN','STRONG','B','EM','I','U','S','UL','OL','LI','H1','H2','H3','H4','TABLE','TBODY','THEAD','TR','TH','TD','BLOCKQUOTE','A','FONT']);
 for(const el of [...parsed.body.querySelectorAll('*')]){
  if(!allowed.has(el.tagName)){el.replaceWith(...el.childNodes);continue;}
  const href=el.getAttribute('href');
  const color=el.style.color||(el.tagName==='FONT'?el.getAttribute('color'):null);
  for(const attr of [...el.attributes])el.removeAttribute(attr.name);
  // Preserve original emphasis colors, not arbitrary CSS or event attributes.
  if(color&&CSS.supports('color',color))el.style.color=color;
  if(el.tagName==='A'&&href){try{const url=new URL(href);if(['https:','http:'].includes(url.protocol)){el.href=url.href;el.target='_blank';el.rel='noopener noreferrer';}}catch{}}
 }
 const fragment=document.createDocumentFragment();fragment.append(...parsed.body.childNodes);return fragment;
}
const rendering=b=>['queued','running'].includes(b?.apply?.state);
export function mountWorkbench(root,job,{service=null,role=null,refresh=null}={}){
 let disposed=false,video,observer,selectedId,selectionVersion=0,historyVersion=0,workflowState=null,historyRows=[];
 const live=job.source==='supabase',local=job.source==='local-bundle';
 const canReview=['reviewer','operator','admin'].includes(role);
 const canExport=['operator','admin'].includes(role);   // 프리미어로 내보내기는 우리 팀만 — 크리에이터는 편집실을 쓰게(2026-09-30)
 let releaseWorkflow=()=>{};
 root.innerHTML=`<section class="video-workspace"><div class="workbench-top"><div><a class="workbench-back" href="#review${local?'?source=local':''}">‹ 작업 목록</a><h2>${esc(job.work)}</h2><p>${esc(job.episode)} · 작업 ID ${esc(job.id)} <span>${live?'Supabase 검수 기록':job.remote?'':local?'작업 컴퓨터의 로컬 영상':'로컬 예시'}</span></p></div><button class="workbench-guide" type="button">${icon('file')}권리사 가이드</button></div><div class="mobile-video-controls"><button class="video-previous" type="button" aria-label="이전 영상">‹</button><button class="video-picker-open" type="button" aria-haspopup="dialog" aria-controls="video-picker-dialog"><span class="video-picker-label">영상 선택</span><strong class="mobile-current-title">불러오는 중…</strong></button><button class="video-next" type="button" aria-label="다음 영상">›</button></div><div class="workbench-body"><aside class="video-rail" aria-label="완성 영상 목록"><header><h3>완성 영상 <span class="video-total"></span></h3></header><div class="video-rail-list"><p class="workbench-note">영상을 불러오는 중…</p></div></aside><div class="video-column"><div class="video-stage" aria-label="영상 재생"><div class="video-frame"><video controls playsinline preload="metadata" controlslist="nofullscreen" aria-label="선택한 완성 영상"></video><button class="video-expand" type="button" aria-label="영상 전체화면"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg></button></div><div class="media-error" role="alert" hidden><p>영상을 불러오지 못했습니다.</p><button type="button">다시 시도</button></div><p class="player-message" role="status"></p></div></div><aside class="video-inspector workflow-inspector" aria-label="선택한 영상 검수"><div class="workflow-editor-actions" hidden><div class="editor-buttons"><button type="button" class="open-thumbs" hidden>${icon('image')}<span>썸네일 생성</span></button><button type="button" class="open-premiere" hidden>${icon('download')}<span>프리미어로 내보내기</span></button><a class="open-editor" aria-disabled="true">${icon('pencil')}편집실 열기</a></div><small class="editor-readiness"></small><details class="edit-notes" hidden><summary></summary><ul></ul></details></div><div class="workflow-operations"></div><details class="workflow-history"><summary>작업 이력 <small>한국 시간</small></summary><div class="workbench-history-content"></div></details></aside></div></section><dialog class="reject-dialog" aria-labelledby="reject-title"><form><div class="login-heading"><h2 id="reject-title">영상 반려</h2><button type="button" class="reject-close" aria-label="닫기">×</button></div><p>반려 사유를 작업 이력에 남깁니다. 자동으로 새 영상을 생성하지 않습니다.</p><label>반려 사유<textarea name="note" required maxlength="2000" rows="4"></textarea></label><p class="reject-error" role="alert"></p><button class="primary" type="submit">반려하기</button></form></dialog><dialog class="workbench-guide-dialog" aria-labelledby="workbench-guide-title"><div class="login-heading"><h2 id="workbench-guide-title">권리사 가이드</h2><button type="button" aria-label="가이드 닫기">×</button></div><div class="workbench-guide-content"></div></dialog><dialog id="video-picker-dialog" class="video-picker-dialog" aria-label="영상 선택"><button class="video-picker-close" type="button" aria-label="영상 목록 닫기">×</button></dialog>`;
 const $=s=>root.querySelector(s);
 const mobile=matchMedia('(max-width: 760px)');
 const rail=$('.video-rail'),railHome=document.createComment('video list');rail.before(railHome);
 const picker=$('.video-picker-dialog');
 const scrollHost=root.closest('main'),body=$('.workbench-body');
 const fitRail=()=>{
  if(disposed||!scrollHost)return;
  // Measure the grid's unscrolled position, so the rail keeps a steady height while sticky.
  const top=body.getBoundingClientRect().top-scrollHost.getBoundingClientRect().top+scrollHost.scrollTop;
  body.style.setProperty('--rail-visible-height',`${Math.max(160,scrollHost.clientHeight-Math.max(16,top)-16)}px`);
 };
 const railObserver=new ResizeObserver(fitRail);if(scrollHost)railObserver.observe(scrollHost);railObserver.observe($('.workbench-top'));

 const syncPicker=()=>{if(picker.open)picker.close();if(mobile.matches)picker.append(rail);else railHome.after(rail);};
 mobile.addEventListener('change',syncPicker);syncPicker();
 $('.video-picker-open').onclick=()=>{picker.showModal();$('.video-picker-close').focus();};
 $('.video-picker-close').onclick=()=>picker.close();
 picker.addEventListener('click',event=>{if(event.target!==picker)return;const rect=picker.getBoundingClientRect();if(event.clientY<rect.top||event.clientY>rect.bottom||event.clientX<rect.left||event.clientX>rect.right)picker.close();});

 video=$('video');const stage=$('.video-stage'),frame=$('.video-frame');
 const compact=matchMedia('(max-width:760px)'),editorActions=$('.workflow-editor-actions');
 function syncEditorPlacement(){
  if(compact.matches)$('.video-column').prepend(editorActions);
  else $('.workflow-inspector').prepend(editorActions);
  fit();
 }
 compact.addEventListener('change',syncEditorPlacement);syncEditorPlacement();

 function fit(){
  if(disposed)return;
  const style=getComputedStyle(stage);
  const width=stage.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),height=stage.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
  const ratio=video.videoWidth&&video.videoHeight?video.videoWidth/video.videoHeight:9/16;
  const w=Math.min(width,height*ratio);frame.style.width=`${w}px`;frame.style.height=`${w/ratio}px`;
  editorActions.style.width=compact.matches?`${w}px`:"";
 }
 observer=new ResizeObserver(fit);observer.observe(stage);video.addEventListener('loadedmetadata',fit);
 video.addEventListener('error',()=>{if(!disposed&&video.getAttribute('src'))$('.media-error').hidden=false;});
 $('.media-error button').onclick=()=>{const item=items.find(i=>i.id===selectedId);if(live&&item){selectedId=null;select(item);}else{$('.media-error').hidden=true;video.load();}};
 const fullscreenChanged=()=>{const expanded=document.fullscreenElement===stage;$('.video-expand').setAttribute('aria-label',expanded?'전체화면 종료':'영상 전체화면');fit();};
 document.addEventListener('fullscreenchange',fullscreenChanged);
 $('.video-expand').onclick=async()=>{try{if(document.fullscreenElement===stage)await document.exitFullscreen();else await stage.requestFullscreen();}catch{$('.player-message').textContent='전체화면을 열지 못했습니다. 다시 시도해 주세요.';}};
 function drawHistory(){
  const events=[...reviewEvents(historyRows),...(workflowState?.history||[])];
  const inspection=workflowState?.inspection;
  if(inspection?.reviewed_at)events.push({at:inspection.reviewed_at,label:inspection.status==='completed'&&!inspection.revision_outcome?'권리사 검수 승인':'권리사 검수 답변',note:inspection.revision_notes});
  $('.workbench-history-content').innerHTML=live?timelineHtml(events):local?localHistory():'<p class="workbench-note">로컬 예시에는 실제 작업 이력이 연결되지 않았어요.</p>';
 }
 function localHistory(){
  const b=items.find(i=>i.id===selectedId)?.bundle;if(!b)return '';
  const rows=[b.exported_at&&{at:b.exported_at,label:'영상 묶음 생성',note:b.render_recorded?'':'렌더 기록 없이 수동으로 묶음'},
   b.draft&&{at:b.draft.saved_at,label:'편집 초안 저장',note:[b.draft.saved_by,b.draft.stale?'이전 판 기준이라 이어서 할 수 없어요':''].filter(Boolean).join(' · ')}].filter(Boolean);
  const a=b.apply;
  if(a?.started_at)rows.push({at:a.started_at,label:'편집실 수정 다시 렌더 시작'});
  if(a?.finished_at)rows.push({at:a.finished_at,label:a.state==='done'?'다시 렌더 완료 · 새 영상으로 바뀜':'다시 렌더 실패',note:a.state==='done'?'':a.error});
  return timelineHtml(rows)+(rendering(b)?'<p class="workbench-note">다시 렌더하고 있어요. 끝나면 새 영상으로 바뀌어요.</p>':b.pending_edits?`<p class="workbench-note">반영 안 된 수정 ${b.pending_edits}건</p>`:'');
 }
 async function loadHistory(item){
  const ticket=++historyVersion;historyRows=[];drawHistory();
  if(!live)return;
  $('.workbench-history-content').innerHTML='<p class="workbench-note">작업 이력을 불러오는 중…</p>';
  try{const rows=await service.history(item);if(disposed||ticket!==historyVersion)return;historyRows=rows.filter(row=>row.id===item.id);drawHistory();}
  catch{if(!disposed&&ticket===historyVersion)$('.workbench-history-content').innerHTML='<p class="workbench-note">작업 이력을 불러오지 못했어요. 영상을 다시 선택해 주세요.</p>';}
 }
 function syncActions(item,view){
  const area=$('.workflow-editor-actions');area.hidden=live?!view?.canEdit:false;
  let reject=$('.reject-video');
  const allowed=live&&view?.stage==='new'&&!workflowState?.state?.internal_approved_at&&canReview;
  if(allowed&&!reject){reject=document.createElement('button');reject.type='button';reject.className='reject-video';reject.textContent='반려';$('.workflow-card-actions').append(reject);reject.onclick=openReject;}
  if(reject&&!allowed)reject.remove();
 }
 async function select(item){
  if(selectedId===item.id){if(picker.open)picker.close();return;}
  video.pause();selectedId=item.id;remembered.set(job.id,item.id);
  $('.media-error').hidden=true;$('.player-message').textContent='';
  const ticket=++selectionVersion;video.removeAttribute('src');video.poster=item.poster||'';
  if(!live){video.src=item.src;video.load();}
  $('.video-rail-list').querySelectorAll('[data-video]').forEach(button=>{const on=button.dataset.video===item.id;button.classList.toggle('selected',on);button.setAttribute('aria-pressed',String(on));});
  const index=items.findIndex(i=>i.id===item.id);
  $('.video-picker-label').textContent=`영상 선택 · ${index+1} / ${items.length}`;
  $('.mobile-current-title').textContent=item.title;
  $('.video-previous').disabled=index===0;$('.video-next').disabled=index===items.length-1;
  if(picker.open)picker.close();
  releaseWorkflow();workflowState=null;$('.workflow-editor-actions').hidden=true;$('.workflow-history').open=false;loadHistory(item);
  if(live)releaseWorkflow=mountWorkflowControls($('.workflow-operations'),{client:service.client,reviewId:item.id,item,canReview,onState:(data,view)=>{if(disposed||ticket!==selectionVersion)return;workflowState=data;drawHistory();syncActions(item,view);},onChange:()=>{prepareActions(item,ticket);loadHistory(item);}});
  // 맥미니 영상: 새 검수 흐름(0120) — 내부 검수 · 권리사 검수 신청 · 공개를 이 카드에서
  else if(item.bundle?.remote&&item.bundle.video_id&&service?.client){releaseWorkflow=mountTikitakaReview($('.workflow-operations'),{client:service.client,videoId:item.bundle.video_id,title:item.title,canReview,
   editHref:()=>$('.open-editor').getAttribute('href'),onChange:()=>loadHistory(item)});syncActions(item,null);}
  else{$('.workflow-operations').innerHTML=workflowCardHtml(item,{local:item.bundle?.remote?'remote':local?'bundle':true});releaseWorkflow=()=>{};syncActions(item,null);}
  prepareActions(item,ticket);fit();
  if(live){try{const src=await service.preview(item);if(disposed||ticket!==selectionVersion)return;video.src=src;video.load();}catch(error){if(disposed||ticket!==selectionVersion)return;$('.media-error p').textContent=error.message;$('.media-error').hidden=false;}}
 }
 // '제출하면 다시 렌더해요' — 편집실 열기 버튼 위에 한 번만 뜨는 말풍선. '확인'을 누르면 다시 안 뜬다(이 브라우저 기준)
 function renderTip(link){
  const KEY='ws-tip-editor-rerender';try{if(localStorage.getItem(KEY))return;}catch{}
  const box=link.closest('.workflow-editor-actions');if(!box||box.querySelector('.rerender-tip'))return;
  const tip=document.createElement('div');tip.className='rerender-tip';tip.setAttribute('role','note');
  tip.innerHTML='<p>제출하면 다시 렌더해요</p><button type="button">확인</button><i aria-hidden="true"></i>';
  tip.querySelector('button').onclick=()=>{try{localStorage.setItem(KEY,'1');}catch{}tip.remove();};
  box.append(tip);
  const place=()=>{if(!tip.isConnected)return;const b=link.getBoundingClientRect(),o=box.getBoundingClientRect();
   const row=link.closest('.editor-buttons')?.getBoundingClientRect()||b;   // 버튼이 두 줄로 접혀도 다른 버튼을 가리지 않게 버튼 묶음 위에
   // 말풍선 가운데를 편집실 열기 버튼 가운데에. 화면(넓은 화면은 오른쪽 스크롤 칸) 끝에 닿으면 안쪽으로 밀되,
   // 꼬리는 늘 버튼 가운데를 가리키고 알약의 둥근 끝이 아니라 평평한 부분에 붙는다
   const clip=box.closest('.workflow-inspector'),c=clip?.getBoundingClientRect(),w=tip.offsetWidth,r=tip.offsetHeight/2,mid=b.left+b.width/2;
   // 잘리는 칸: 넓은 화면은 오른쪽 스크롤 칸(스크롤 막대 자리는 빼고 보이는 폭만), 아니면 화면. 4px 여유
   const cut=clip&&getComputedStyle(clip).overflowX!=='visible';
   const lo=cut?c.left+clip.clientLeft+4:8,hi=(cut?c.left+clip.clientLeft+clip.clientWidth-4:document.documentElement.clientWidth-8)-w;
   // 꼬리를 평평한 곳에 두려고 먼저 맞추고, 잘리지 않게 하는 걸 마지막에(둘이 부딪히면 잘리지 않는 쪽)
   let left=Math.min(Math.max(mid-w/2,mid-(w-r-6)),mid-(r+6));left=Math.min(Math.max(left,lo),hi);
   // 위에 자리가 없으면(넓은 화면 오른쪽 칸은 스크롤 칸이라 위로 삐져나간 부분이 잘려 그림자만 비친다) 버튼 아래로
   const below=row.top-(c?c.top:-Infinity)<tip.offsetHeight+12;
   tip.classList.toggle('below',below);tip.style.right='auto';tip.style.left=(left-o.left)+'px';
   if(below){tip.style.bottom='auto';tip.style.top=(row.bottom-o.top+10)+'px';}else{tip.style.top='auto';tip.style.bottom=(o.bottom-row.top+10)+'px';}
   tip.querySelector('i').style.left=Math.min(Math.max(mid-left-6,12),w-24)+'px';};
  requestAnimationFrame(place);
  const ro=new ResizeObserver(()=>{if(!tip.isConnected)return ro.disconnect();place();setTimeout(place,450);});ro.observe(box);ro.observe(document.documentElement);   // 폭이 바뀌어 버튼 자리가 옮겨진 뒤에 다시 맞춘다
 }
 // 버튼 아래 한 줄 — 다시 렌더 실패는 이유 + [자세히](말풍선: 할 일 · 렌더한 맥미니 로봇의 말), 나머지는 글자 그대로
 const editLabel=(link,text)=>{const t=[...link.childNodes].find(n=>n.nodeType===3&&n.textContent.trim());if(t)t.textContent=text;};
 // 지난 수정에서 달라진 점 — 버튼 아래 긴 글 대신 아래 카드와 같은 폭의 접는 상자(처음엔 접힘)
 function editNotes(b){
  const d=$('.edit-notes'),notes=b?.apply?.state==='done'?(b.apply.notes||[]):[];
  d.hidden=!notes.length;d.open=false;if(!notes.length)return;
  d.querySelector('summary').innerHTML=`지난 수정에서 달라진 점 <small>${notes.length}가지</small>`;
  d.querySelector('ul').innerHTML=notes.map(n=>`<li class="${n.level==='warn'?'warn':''}">${esc(n.text)}</li>`).join('');
 }
 function failureNote(note,b,rest){
  const a=b.apply,parts=rest.filter(Boolean).map(esc);
  if(a?.state==='failed'){failureStyle();const info=failureInfo(a.error,{node:a.node||(b.remote?b.node:null),at:a.finished_at,restorable:a.restorable});
   note.innerHTML=[lineHtml(info),...parts].join(' · ');note.querySelector('.rf-why').onclick=e=>{const href=$('.open-editor').getAttribute('href');openFailurePop(e.currentTarget,info,{action:href?{href,label:'편집실 열기'}:null});};}
  else note.textContent=rest.filter(Boolean).join(' · ');
 }
 async function prepareActions(item,ticket){
  const link=$('.open-editor'),note=$('.editor-readiness'),thumbs=$('.open-thumbs'),premiere=$('.open-premiere');
  link.removeAttribute('href');link.setAttribute('aria-disabled','true');thumbs.hidden=true;link.hidden=false;premiere.hidden=true;editNotes(null);editLabel(link,'편집실 열기');delete link.dataset.tip;
  const thumbButton=b=>{
   const th=b.thumbs||{};thumbs.hidden=false;
   thumbs.querySelector('span').textContent=th.state==='running'?'썸네일 만드는 중':th.has_result?'썸네일 보기':'썸네일 생성';
   thumbs.onclick=()=>{video.pause();openThumbnails({client:service?.client,video:b,onChange:async()=>{
    if(!refresh)return;try{const next=(await refresh()).find(j=>j.id===job.id);if(disposed||!next)return;
     job.bundles=next.bundles;const nb=next.bundles.find(x=>x.key===b.key);if(nb){item.bundle=nb;if(selectedId===item.id)prepareActions(item,ticket);}}catch{}}})};
  };
  if(local){                                   // local bundle: open the local editor (edits are recorded, not rendered)
   const b=item.bundle;note.hidden=false;
   if(b.remote){                               // 맥미니 영상: 편집실은 여기서 열고, 제출하면 그 맥미니가 다시 렌더한다. 썸네일도 그 맥미니가 만든다(0129)
    if(!canReview){note.textContent='편집에는 검수자 권한이 필요합니다';return;}
    // 프리미어로 내보내기 — 서버 없이 브라우저가 만든다(웹 주소에서도 된다)
    const [,wo,suffix]=String(b.key||'').match(/^remote-([^/]+)\/(.+)$/)||[];
    if(wo&&canExport&&service?.client){premiere.hidden=false;premiere.onclick=()=>{video.pause();openPremiereExport(service.client,{wo,suffix});};}
    if(rendering(b)){note.textContent='다시 렌더하고 있어요. 끝나면 편집할 수 있어요.';return;}
    failureNote(note,b,[]);editNotes(b);
    thumbButton(b);   // 썸네일 — 그 맥미니가 만든다(0129)
    link.href=`editor.html?local=1&run=${encodeURIComponent(item.id)}&back=${encodeURIComponent(job.id)}`;link.setAttribute('aria-disabled','false');renderTip(link);
    return;
   }
   if(!canReview){note.textContent='편집에는 검수자 권한이 필요합니다';return;}
   if(b.status!=='ready'){note.textContent='전사 수정으로 낡은 영상이에요. 다시 렌더된 뒤 편집할 수 있어요.';return;}
   if(!b.source_ok){note.textContent='원본 영상을 찾을 수 없어 편집할 수 없어요.';return;}
   if(rendering(b)){note.textContent='다시 렌더하고 있어요. 끝나면 편집할 수 있어요.';return;}
   // 썸네일 — 편집실 열기와 같은 조건(묶음 ready·원본 있음·렌더 중 아님)에서만. 결과가 있으면 '썸네일 보기'.
   thumbButton(b);
   failureNote(note,b,[]);editNotes(b);
   // 이어서 할 초안이 있으면 버튼 이름으로 알린다(편집실 목록 카드와 같은 말) — 올리면 저장 시각
   if(b.draft&&!b.draft.stale){editLabel(link,'이어서 편집');const at=b.draft.saved_at?new Date(b.draft.saved_at):null;
    if(at&&!Number.isNaN(+at))link.dataset.tip=at.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',hour:'numeric',minute:'2-digit'})+' 저장'+(b.draft.saved_by?' · '+b.draft.saved_by:'');}
   link.href=`editor.html?local=1&run=${encodeURIComponent(item.id)}&back=${encodeURIComponent(job.id)}`;link.setAttribute('aria-disabled','false');renderTip(link);
   return;
  }
  // VES 검수 카드 영상은 Workspace 편집실에서 열지 않는다(2026-09-29 — 예전 방식 영상은 예전 대시보드 편집실에서). 버튼을 숨긴다.
  link.hidden=true;note.hidden=true;note.textContent='';
 }
 const rejectDialog=$('.reject-dialog');let rejectingId=null;
 function openReject(){rejectingId=selectedId;rejectDialog.querySelector('form').reset();$('.reject-error').textContent='';rejectDialog.showModal();rejectDialog.querySelector('textarea').focus();};
 $('.reject-close').onclick=()=>rejectDialog.close();
 rejectDialog.querySelector('form').onsubmit=async event=>{
  event.preventDefault();const item=items.find(i=>i.id===rejectingId);if(!item||!canReview)return;
  const submit=rejectDialog.querySelector('[type="submit"]');submit.disabled=true;
  try{await service.reject(item,rejectDialog.querySelector('textarea').value);if(disposed)return;rejectDialog.close();selectedId=null;load();}
  catch(error){if(!disposed)$('.reject-error').textContent=error.message||'반려 기록을 저장하지 못했습니다.';}
  finally{submit.disabled=false;}
 };
 let items=[];
 $('.video-previous').onclick=()=>{const index=items.findIndex(i=>i.id===selectedId);if(index>0)select(items[index-1]);};
 $('.video-next').onclick=()=>{const index=items.findIndex(i=>i.id===selectedId);if(index>=0&&index<items.length-1)select(items[index+1]);};
 function load(){
  $('.video-rail-list').innerHTML='<p class="workbench-note">영상을 불러오는 중…</p>';
  (live?service.loadItems(job):local?Promise.resolve(job.bundles.map(bundleItem)):loadLocalMedia().then(catalog=>catalog[job.id]||[])).then(loaded=>{
   if(disposed)return;items=loaded;$('.video-total').textContent=items.length;
   if(!items.length){$('.video-rail-list').innerHTML='<p class="workbench-note">연결된 완성 영상이 없습니다.</p>';frame.hidden=true;return;}
   $('.video-rail-list').innerHTML=items.map(item=>`<button type="button" class="video-list-card" data-video="${esc(item.id)}" aria-pressed="false"><span class="video-poster">${item.poster?`<img src="${esc(item.poster)}" alt="" loading="lazy">`:local?`<video src="${esc(item.src)}#t=1" muted playsinline preload="metadata" aria-hidden="true"></video>`:''}<small>${timeLabel(item.duration)}</small></span><span class="video-list-copy"><strong>${esc(item.title)}</strong>${local?`<span>${esc(item.bundle.suffix)}${item.bundle.labels?` · AI 보조 자막 ${item.bundle.labels}`:''}</span>`:`<span>LLM Judge <b>${live?score(item.judge?.quality_score):'연결 전'}</b></span>`}</span>${live?`<span class="video-card-state">${esc(reviewLabels[item.review.status]||item.review.status)}</span>`:local?`<span class="video-card-state">${item.bundle.remote?(rendering(item.bundle)?'다시 렌더 중':item.bundle.apply?.state==='failed'?'렌더 실패':'편집 가능'):item.bundle.status!=='ready'?'다시 렌더 필요':rendering(item.bundle)?'다시 렌더 중':item.bundle.apply?.state==='failed'?'렌더 실패':item.bundle.draft&&!item.bundle.draft.stale?'편집 중':'편집 가능'}</span>`:''}</button>`).join('');
   $('.video-rail-list').querySelectorAll('[data-video]').forEach(button=>button.onclick=()=>select(items.find(i=>i.id===button.dataset.video)));
   // 편집실에서 돌아오면 편집하던 영상을 고른다(#review/<작업>?video=<영상>) — 한 번 쓰고 주소에서 뺀다
   const wanted=new URLSearchParams(location.hash.split('?')[1]||'').get('video');
   if(wanted){remembered.set(job.id,wanted);history.replaceState(null,'',location.pathname+location.search+location.hash.split('?')[0]);}
   select(items.find(i=>i.id===remembered.get(job.id))||items[0]);
  }).catch(()=>{if(disposed)return;$('.video-rail-list').innerHTML='<p class="workbench-note">영상 목록을 불러오지 못했습니다.</p><button class="media-retry" type="button">다시 시도</button>';$('.media-retry').onclick=load;});
 }
 const guideDialog=$('.workbench-guide-dialog');
 $('.workbench-guide-dialog .login-heading button').onclick=()=>guideDialog.close();
 $('.workbench-guide').onclick=async()=>{
  const content=$('.workbench-guide-content');content.textContent='원문을 불러오는 중…';guideDialog.showModal();
  const note=text=>{const p=document.createElement('p');p.className='workbench-note';p.textContent=text;return p;};
  try{
   // 레이블리 작품 DB(licensed_video.guide) — 작품 관리 탭과 같은 원천(/api/work-catalog). 제목이 정확히 한 작품일 때만 쓴다.
   const client=service?.client;
   if(client){
    try{
     const data=await loadCatalog(client);if(disposed)return;
     const recs=data.works.filter(r=>r.title===job.work);
     const guide=recs.length===1?await loadGuide(client,recs[0].id):'';if(disposed)return;
     if(guide){
      const r=recs[0];content.replaceChildren(note(`레이블리 작품 DB 원문${r.identification_code?` · 식별코드 ${r.identification_code}`:''}`),guideFragment(guide));return;
     }
    }catch{}
   }
   // 레이블리에서 못 찾으면 예전에 받아 둔 원문(assets/local-guides.json)
   const response=await fetch('assets/local-guides.json');if(!response.ok)throw new Error('guide unavailable');const data=await response.json();if(disposed)return;
   content.replaceChildren(note(`${data.retrieved_at||''} 조회 원문 · 자동 갱신 전`));
   const guideId=({"로또 1등도 출근합니다":'lotto',"가왕쇼":'gawang',"지금 불륜이 문제가 아닙니다(c)":'affair',"신병":'sinbyeong'})[job.work]||job.workId;const guide=data.works[guideId]?.guide;if(guide)content.append(guideFragment(guide));else content.append('등록된 가이드 원문이 없습니다.');
  }catch{if(!disposed)content.textContent='원문을 불러오지 못했습니다. 창을 닫고 다시 열어주세요.';}
 };
 // 다시 렌더 중인 영상이 있으면 15초마다 상태를 본다 — 끝나면 목록을 새 판으로 다시 그린다(선택은 remembered 로 유지).
 let poll=0;
 const watchRenders=()=>{
  clearTimeout(poll);
  if(!local||!refresh||!job.bundles.some(rendering))return;
  poll=setTimeout(async()=>{
   try{const next=(await refresh()).find(j=>j.id===job.id);if(disposed||!next)return;
    const sig=bs=>JSON.stringify(bs.map(b=>[b.key,b.render_fingerprint,b.apply?.state]));
    if(sig(next.bundles)!==sig(job.bundles)){job.bundles=next.bundles;selectedId=null;load();}}
   catch{}
   if(!disposed)watchRenders();
  },15000);
 };
 load();fit();watchRenders();
 return ()=>{disposed=true;clearTimeout(poll);compact.removeEventListener('change',syncEditorPlacement);railObserver.disconnect();releaseWorkflow();if(rejectDialog.open)rejectDialog.close();mobile.removeEventListener('change',syncPicker);if(picker.open)picker.close();observer.disconnect();document.removeEventListener('fullscreenchange',fullscreenChanged);video.pause();video.removeAttribute('src');video.load();if(document.fullscreenElement===stage)document.exitFullscreen().catch(()=>{});if(guideDialog.open)guideDialog.close();};
}

import {fetchRights} from './rights-service.js';
import {ON_WORK_PC,localOnlyEmpty} from './local-only.js';
import {enhanceDropdowns} from './dropdowns.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={pending:'검수 대기',revision_requested:'수정 요청',resubmit_requested:'재제출 요청',completed:'검수 완료',cancelled:'취소'};
const date=v=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'—';
const link=(url,label)=>{try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?`<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`:''}catch{return ''}};
export function mountRights(root,client,initial={}){
 if(!ON_WORK_PC){   // 권리사 검수 목록은 레이블리에서 읽는데, 아직 작업 컴퓨터(로컬 서버)를 거친다
  root.innerHTML=localOnlyEmpty('권리사 검수는 작업 컴퓨터에서만 볼 수 있어요','검수 목록을 아직 작업 컴퓨터에서 레이블리로 읽어 와요. 웹에서도 볼 수 있게 옮기는 중이에요.');
  return()=>{};
 }
 let disposed=false,busy=false,records=[],selected=null,request=null,lastAttempt=0,page=1,pageCount=1,filterKey='';
 const pageSize=10;
 root.innerHTML=`<section class="rights-page"><div class="rights-head"><div class="rights-title"><h2>검수 목록</h2><span class="rights-result-count" role="status"></span></div><div class="rights-head-actions"><p class="rights-sync" role="status">불러오는 중…</p><button class="rights-refresh" type="button">새로고침</button></div></div><div class="rights-toolbar"><label class="rights-compact-filter">채널<select class="rights-channel"><option value="">전체</option></select></label><label class="rights-compact-filter">검수 상태<select class="rights-status"><option value="">전체</option>${Object.entries(labels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label class="rights-compact-filter rights-work-filter">작품<select class="rights-work"><option value="">전체</option></select></label><label class="rights-search-label">검색<input type="search" class="rights-search" placeholder="채널·작품·회차·검수 ID"></label></div><div class="rights-layout"><aside class="rights-filters" aria-label="검수 필터"></aside><section class="rights-results" aria-label="권리사 검수 기록"><div class="rights-list"></div><div class="rights-pagination" role="navigation" aria-label="검수 목록 페이지" hidden><button type="button" class="rights-page-prev" aria-label="이전 페이지"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12 5-5 5 5 5"/></svg></button><span class="rights-page-position" role="status" aria-live="polite"></span><button type="button" class="rights-page-next" aria-label="다음 페이지"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m8 5 5 5-5 5"/></svg></button></div></section></div><dialog class="rights-drawer" aria-labelledby="rights-detail-heading"><header class="rights-drawer-head"><h2 id="rights-detail-heading">검수 상세</h2><button type="button" class="rights-detail-close" aria-label="검수 상세 닫기">×</button></header><article class="rights-detail" aria-label="권리사 검수 상세"></article></dialog></section>`;
 const $=s=>root.querySelector(s);
 const drawer=$('.rights-drawer');
 // '권리사 요청' = 수정 요청 + 재제출 요청(홈 KPI 가 이걸로 연다). 칩은 따로 두고 둘 다 눌린 채로 보여 준다
 const REQUESTS=['revision_requested','resubmit_requested'];
 $('.rights-status').insertAdjacentHTML('beforeend','<option value="requests">권리사 요청(수정·재제출)</option>');
 if(Object.hasOwn(labels,initial.status)||initial.status==='requests')$('.rights-status').value=initial.status;
 let openInitialRecord=initial.record||null;
 const fields={status:'.rights-status',channel:'.rights-channel',work:'.rights-work'};
 const unique=key=>[...new Set(records.map(r=>r[key]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ko'));
 function updateOptions(){
  for(const [field,key] of [['channel','channel_name'],['work','video_title']]){
   const select=$(fields[field]),value=select.value;
   select.innerHTML='<option value="">전체</option>'+unique(key).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
   select.value=[...select.options].some(o=>o.value===value)?value:'';
   select.dispatchEvent(new Event('change'));
  }
 }
 function paintFilters(){
  const groups=[['status','상태',Object.entries(labels)],['channel','채널',unique('channel_name').map(v=>[v,v])],['work','작품',unique('video_title').map(v=>[v,v])]];
  $('.rights-filters').innerHTML=groups.map(([field,title,values])=>`<section><h3>${title}</h3><div class="rights-filter-group" role="group" aria-label="${title}">${[['','전체'],...values].map(([value,label])=>`<button type="button" data-filter="${field}" data-value="${esc(value)}" aria-pressed="${$(fields[field]).value===value||(field==='status'&&$(fields[field]).value==='requests'&&REQUESTS.includes(value))}" title="${esc(label)}">${field==='status'&&value?`<span class="rights-status-dot status-${value}" aria-hidden="true"></span>`:''}<span>${esc(label)}</span></button>`).join('')}</div></section>`).join('');
  $('.rights-filters').querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{
   const field=button.dataset.filter,value=button.dataset.value;
   $(fields[field]).value=value;$(fields[field]).dispatchEvent(new Event('change'));paint();
   [...$('.rights-filters').querySelectorAll('[data-filter]')].find(b=>b.dataset.filter===field&&b.dataset.value===value)?.focus({preventScroll:true});
  });
 }
 function paint(){
  const query=$('.rights-search').value.trim().toLowerCase(),channel=$('.rights-channel').value,status=$('.rights-status').value,work=$('.rights-work').value;
  const rows=records.filter(r=>(!channel||r.channel_name===channel)&&(!status||(status==='requests'?REQUESTS.includes(r.status):r.status===status))&&(!work||r.video_title===work)&&(!query||[r.video_title,r.channel_name,r.id,r.episode,r.episode_part].join(' ').toLowerCase().includes(query)));
  const nextFilterKey=JSON.stringify([query,channel,status,work]);
  if(nextFilterKey!==filterKey){page=1;filterKey=nextFilterKey;$('.rights-list').scrollTop=0;}
  pageCount=Math.max(1,Math.ceil(rows.length/pageSize));page=Math.min(page,pageCount);
  const pageRows=rows.slice((page-1)*pageSize,page*pageSize);
  $('.rights-pagination').hidden=rows.length===0;
  $('.rights-page-position').textContent=`${page}/${pageCount}`;
  $('.rights-page-prev').disabled=page===1;$('.rights-page-next').disabled=page===pageCount;
  paintFilters();$('.rights-result-count').textContent=`${rows.length}건`;
  const scroll=$('.rights-list').scrollTop;
  $('.rights-list').innerHTML=rows.length?`<table class="rights-table"><thead><tr><th scope="col">작품</th><th scope="col">채널 · 회차</th><th scope="col">검수 상태</th><th scope="col">신청일</th><th scope="col">링크</th></tr></thead><tbody>${pageRows.map(r=>`<tr data-id="${esc(r.id)}" class="${r.id===selected?'selected':''}"><td class="rights-work-cell"><button type="button" class="rights-open" aria-label="${esc(r.video_title)} ${esc(r.episode??'—')}화 ${esc(r.episode_part??'—')}편 검수 상세"><strong>${esc(r.video_title||'작품명 미기재')}</strong><small>${esc(r.round??'—')}차 검수 <span aria-hidden="true">↗</span></small></button></td><td class="rights-channel-cell"><span>${esc(r.channel_name)}</span><small>${r.episode==null?'회차 미기재':esc(r.episode)+'화'} · ${esc(r.episode_part??'—')}편</small></td><td class="rights-state-cell"><span class="rights-badge status-${esc(r.status)}">${esc(labels[r.status]||r.status)}</span></td><td class="rights-date-cell"><time datetime="${esc(r.created_at||'')}" title="${esc(date(r.created_at))}">${r.created_at?new Date(r.created_at).toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul'}):'—'}</time></td><td class="rights-link-cell">${link(r.youtube_url,'영상')}${link(r.file_link||r.original_file_url,'파일')}${!r.youtube_url&&!r.file_link&&!r.original_file_url?'<span class="rights-no-link">—</span>':''}</td></tr>`).join('')}</tbody></table>`:'<p class="rights-empty">해당하는 검수 기록이 없습니다.</p>';
  $('.rights-list').scrollTop=scroll;
  $('.rights-list').querySelectorAll('[data-id]').forEach(row=>row.onclick=e=>{
   if(e.target.closest('a'))return;
   selected=row.dataset.id;drawDetail();
   $('.rights-list').querySelectorAll('[data-id]').forEach(r=>r.classList.toggle('selected',r.dataset.id===selected));
   if(!drawer.open)drawer.showModal();
  });
  if(drawer.open)drawDetail();
 }
 function drawDetail(){
  const r=records.find(r=>r.id===selected);
  if(!r){$('.rights-detail').innerHTML='<p class="workbench-note">검수 기록을 찾을 수 없습니다.</p>';return;}
  const previous=records.find(x=>x.id===r.supersedes_inspection_id);
  const subsequent=records.filter(x=>x.supersedes_inspection_id===r.id);
  $('.rights-detail').innerHTML=`<span class="rights-badge status-${esc(r.status)}">${esc(labels[r.status]||r.status)}${r.auto_approved_at?' · 자동 승인':''}</span><h2>${esc(r.video_title)}</h2><p>${esc(r.channel_name)} · ${esc(r.company)}</p><dl><dt>회차 · 영상</dt><dd>${esc(r.episode??'—')}화 · ${esc(r.episode_part??'—')}편</dd><dt>검수 차수</dt><dd>${esc(r.round??'—')}차</dd><dt>신청</dt><dd>${date(r.created_at)}</dd><dt>검수</dt><dd>${date(r.reviewed_at)}</dd><dt>최종 변경</dt><dd>${date(r.updated_at)}</dd></dl><section><h3>수정 요청 원문</h3><p class="rights-original">${esc(r.revision_notes||'등록된 수정 요청이 없습니다.')}</p></section>${r.remarks?`<section><h3>비고 원문</h3><p class="rights-original">${esc(r.remarks)}</p></section>`:''}${r.revision_outcome?`<section><h3>수정 결과</h3><p class="rights-original">${esc(r.revision_outcome)}</p></section>`:''}${r.revision_items?`<details><summary>수정 항목 원본</summary><pre>${esc(JSON.stringify(r.revision_items,null,2))}</pre></details>`:''}<div class="rights-links">${link(r.youtube_url,'신청 영상')}${link(r.file_link||r.original_file_url,'첨부 파일')}${link(r.published_youtube_url,'발행 영상')}</div>${previous||subsequent.length?`<section><h3>연결된 검수 이력</h3>${[previous,...subsequent].filter(Boolean).map(x=>`<button type="button" class="rights-related" data-related="${esc(x.id)}">${esc(x.round)}차 · ${esc(labels[x.status]||x.status)} · ${date(x.created_at)}</button>`).join('')}</section>`:''}<details><summary>검수 기록 정보</summary><p class="rights-original">ID ${esc(r.id)}</p>${r.supersedes_inspection_id&&!previous?`<p>이전 검수 ID ${esc(r.supersedes_inspection_id)}</p>`:''}<p>레이블리 원본 · 영상과의 자동 매칭 없음</p></details>`;
  $('.rights-detail').querySelectorAll('[data-related]').forEach(b=>b.onclick=()=>{selected=b.dataset.related;drawDetail();$('.rights-detail').scrollTop=0;});
 }
 async function refresh(){
  if(disposed||busy)return;busy=true;lastAttempt=Date.now();$('.rights-refresh').disabled=true;
  request=new AbortController();
  try{
   const result=await fetchRights(client,request.signal);
   if(disposed)return;records=result.records;updateOptions();paint();if(openInitialRecord){selected=openInitialRecord;openInitialRecord=null;drawDetail();drawer.showModal();}$('.rights-sync').textContent=`${records.length}건 · ${date(result.fetched_at)} 갱신 · 1시간마다 자동 갱신`;
  }catch(error){if(disposed)return;$('.rights-sync').textContent=`${error.message}${records.length?' · 이전 조회 결과를 표시합니다.':''}`;}
  finally{busy=false;if(!disposed)$('.rights-refresh').disabled=false;}
 }
 $('.rights-detail-close').onclick=()=>drawer.close();
 drawer.addEventListener('click',e=>{if(e.target===drawer){const r=drawer.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)drawer.close();}});
 drawer.addEventListener('close',()=>{[...$('.rights-list').querySelectorAll('[data-id]')].find(row=>row.dataset.id===selected)?.querySelector('button')?.focus({preventScroll:true});});
 function turnPage(step){
  const next=Math.max(1,Math.min(pageCount,page+step));if(next===page)return;
  page=next;$('.rights-list').scrollTop=0;paint();
  if($('.rights-results').getBoundingClientRect().top<0)$('.rights-results').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
 }
 $('.rights-page-prev').onclick=()=>turnPage(-1);
 $('.rights-page-next').onclick=()=>turnPage(1);
 $('.rights-refresh').onclick=refresh;
 for(const selector of ['.rights-channel','.rights-status','.rights-work','.rights-search'])$(selector).addEventListener('input',paint);
 const visible=()=>{if(document.visibilityState==='visible'&&Date.now()-lastAttempt>=3600000)refresh();};
 document.addEventListener('visibilitychange',visible);const timer=setInterval(visible,3600000);refresh();
 const releaseDropdowns=enhanceDropdowns(root);
 return ()=>{if(drawer.open)drawer.close();releaseDropdowns();disposed=true;request?.abort();clearInterval(timer);document.removeEventListener('visibilitychange',visible);};
}

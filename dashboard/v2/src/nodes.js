import {nodeHealth} from './home-model.js';
import {nodeRobot,nodeRobotState} from './node-robots.js';
import {createNodesService,canManageNodes,versionMatch} from './nodes-service.js?v=web-1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const name=id=>String(id).replace(/^mm-(\d+)$/,'Mac mini $1');
const date=value=>value?new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'기록 없음';
const engineNames={ai_video:'영상 제작',brain:'영상 분석',localization:'현지화',orchestrator:'작업 관리'};
const kinds={generate:'영상 제작',evaluate:'자동 검사',localize:'현지화',publish:'발행',acquire:'소스 준비',upload_artifacts:'결과 업로드',ingest:'기록 적재',editor_assets:'편집실 준비'};
const statusNames={active:'가동',draining:'작업 마무리',disabled:'비활성'};
const short=sha=>sha?String(sha).slice(0,7):'—';
export function mountNodes(root,{client=null,role=null,authStatus='loading',service=null}={}){
 if(!client&&!service){root.innerHTML=`<section class="empty-state"><h2>맥·배포</h2><p>${authStatus==='signed-out'?'로그인 후 맥 상태와 배포 정보를 확인할 수 있습니다.':'계정 권한을 확인하고 있습니다.'}</p></section>`;return ()=>{};}
 service ||= createNodesService(client,role);
 const manage=canManageNodes(role);
 let disposed=false,busy=false,saving=false,data=null,lastAttempt=0,request=null,action=null;
 const visibleCards=new Set();
 const robotObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting)visibleCards.add(entry.target);else visibleCards.delete(entry.target);entry.target.classList.toggle('robots-moving',entry.isIntersecting&&!document.hidden);}},{threshold:0});
 root.innerHTML=`<section class="nodes-page"><div class="nodes-toolbar"><div><h2>운영 현황</h2><p>맥의 상태와 배포 버전을 한곳에서 확인하세요.</p></div><button type="button" class="nodes-refresh">새로고침</button></div><p class="nodes-notice" role="status"></p><div class="nodes-summary"></div><section class="nodes-section"><header><h2>맥 현황</h2><span class="nodes-count"></span></header><div class="nodes-grid"><p class="nodes-empty">맥 정보를 불러오는 중…</p></div></section><section class="nodes-section"><header><div><h2>엔진 버전 비교</h2><p>마지막 보고 버전 · 고정 버전이 있으면 해당 버전과 비교합니다.</p></div><span class="nodes-legend"><i></i>기준과 다름</span></header><div class="nodes-matrix nodes-table-wrap"></div></section><section class="nodes-section"><header><div><h2>배포 설정</h2><p>엔진별 자동 업데이트와 고정 버전을 관리합니다.</p></div>${manage?'':'<span class="nodes-readonly">조회 권한</span>'}</header><div class="nodes-deployments nodes-table-wrap"></div></section><p class="nodes-sync" role="status"></p><dialog class="nodes-dialog" aria-labelledby="nodes-dialog-title"><form><header><h2 id="nodes-dialog-title"></h2><button type="button" class="nodes-dialog-close" aria-label="닫기">×</button></header><p class="nodes-dialog-copy"></p><label class="nodes-sha-field" hidden>커밋 SHA<input name="sha" autocomplete="off" spellcheck="false" placeholder="7~40자리 커밋 SHA" minlength="7" maxlength="40" pattern="[a-fA-F0-9]{7,40}"></label><p class="nodes-dialog-error" role="alert"></p><footer><button type="button" class="nodes-dialog-cancel">취소</button><button type="submit" class="nodes-confirm"></button></footer></form></dialog></section>`;
 const $=selector=>root.querySelector(selector),dialog=$('.nodes-dialog');
 function shaCell(sha,target){const match=versionMatch(sha,target);return `<span class="nodes-sha ${match}" title="${esc(sha||'버전 미보고')}"${match==='different'?' aria-label="'+esc(short(sha))+' · 기준 버전과 다름"':''}>${esc(short(sha))}${match==='different'?'<i aria-hidden="true"></i>':''}</span>`;}
 function render(){
  if(!data)return;
  const {nodes,deployments,running}=data;
  const different=nodes.filter(n=>deployments.some(d=>versionMatch(n.engine_versions?.[d.engine],d.pinned_sha||d.last_seen_sha)==='different')).length;
  $('.nodes-summary').innerHTML=[['등록된 맥',nodes.length],['응답 정상',nodes.filter(n=>nodeHealth(n).online).length],['실행 중인 작업',running.length],['버전 차이 있는 맥',different]].map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join('');
  $('.nodes-count').textContent=`${nodes.length}대`;
  const openDetails=new Set([...$('.nodes-grid').querySelectorAll('details[open]')].map(d=>d.dataset.node));
  robotObserver.disconnect();visibleCards.clear();
  $('.nodes-grid').innerHTML=nodes.map(n=>{
   const health=nodeHealth(n),jobs=running.filter(j=>j.node_id===n.node_id),versions=Object.entries(n.engine_versions||{}),slots=n.gemini_slots;
   const acts=manage?`<footer class="nodes-actions">${n.status!=='active'?`<button data-node="${esc(n.node_id)}" data-status="active">활성화</button>`:''}${n.status==='active'?`<button data-node="${esc(n.node_id)}" data-status="draining">작업 마무리</button>`:''}${n.status!=='disabled'?`<button class="nodes-danger" data-node="${esc(n.node_id)}" data-status="disabled">비활성화</button>`:''}</footer>`:'';
   return `<article class="nodes-card"><header><span class="home-node-symbol">${nodeRobot(n.node_id,nodeRobotState(n,health,jobs.length))}</span><div><h3>${esc(name(n.node_id))}</h3><small>${esc(statusNames[n.status]||n.status)}${n.updating_since?' · 업데이트 중':''}</small></div><span class="nodes-health ${health.tone}"><i></i>${esc(health.label)}</span></header><div class="nodes-current">${jobs.length?jobs.map(j=>`<div><span class="nodes-job-stage">${esc(kinds[j.kind]||j.kind)}</span><strong>${esc(j.order?.work_title||j.work||'작품 미등록')}</strong>${j.order?.episode!=null?`<small>${esc(j.order.episode)}화</small>`:''}</div>`).join(''):`<span>${health.online?'쉬는 중':n.status==='disabled'?'쉬는 중':'작업 상태 확인 필요'}</span>`}</div><dl class="nodes-facts"><div><dt>디스크 여유</dt><dd>${n.disk_free_gb==null?'—':`${Math.round(Number(n.disk_free_gb))} GB`}</dd></div><div><dt>최근 응답</dt><dd>${date(n.last_seen_at)}</dd></div>${Array.isArray(slots)?`<div><dt>Gemini 예비 키</dt><dd>${slots.includes('fallback')?'있음':'없음'}</dd></div>`:''}</dl><details class="nodes-versions" data-node="${esc(n.node_id)}" ${openDetails.has(n.node_id)?'open':''}><summary>설치된 엔진 <span>${versions.length}</span></summary><div>${versions.map(([eng,sha])=>{const dep=deployments.find(d=>d.engine===eng);return `<div><span>${esc(engineNames[eng]||eng)}</span>${shaCell(sha,dep?.pinned_sha||dep?.last_seen_sha)}</div>`;}).join('')||'<p>엔진 버전 미보고</p>'}</div></details>${acts}</article>`;
  }).join('')||'<p class="nodes-empty">등록된 맥이 없습니다.</p>';
  $('.nodes-grid').querySelectorAll('.nodes-card').forEach(card=>robotObserver.observe(card));
  $('.nodes-matrix').innerHTML=deployments.length?`<table><caption class="sr-only">맥별 설치된 엔진 버전과 배포 기준</caption><thead><tr><th>엔진</th>${nodes.map(n=>`<th>${esc(name(n.node_id))}</th>`).join('')}<th>배포 기준</th></tr></thead><tbody>${deployments.map(d=>`<tr><th>${esc(engineNames[d.engine]||d.engine)}<small>${esc(d.engine)}</small></th>${nodes.map(n=>`<td>${shaCell(n.engine_versions?.[d.engine],d.pinned_sha||d.last_seen_sha)}</td>`).join('')}<td>${shaCell(d.pinned_sha||d.last_seen_sha)}${d.pinned_sha?'<small>고정 버전</small>':'<small>최신 버전</small>'}</td></tr>`).join('')}</tbody></table>`:'<p class="nodes-empty">등록된 엔진이 없습니다.</p>';
  $('.nodes-deployments').innerHTML=deployments.length?`<table><thead><tr><th>엔진</th><th>최신 버전</th><th>업데이트</th><th>고정 버전</th>${manage?'<th><span class="sr-only">관리</span></th>':''}</tr></thead><tbody>${deployments.map(d=>`<tr><th>${esc(engineNames[d.engine]||d.engine)}<small>${esc(d.engine)}</small></th><td>${shaCell(d.last_seen_sha)}</td><td><span class="nodes-mode">${d.auto_update?'자동':'수동'}</span></td><td>${shaCell(d.pinned_sha)}</td>${manage?`<td><button data-engine="${esc(d.engine)}" data-action="${d.pinned_sha?'unpin':'pin'}">${d.pinned_sha?'고정 해제':'버전 고정'}</button></td>`:''}</tr>`).join('')}</tbody></table>`:'<p class="nodes-empty">배포 설정이 없습니다.</p>';
 }
 async function refresh(){
  if(disposed||busy)return;busy=true;lastAttempt=Date.now();$('.nodes-refresh').disabled=true;request=new AbortController();
  try{data=await service.read(request.signal);if(disposed)return;render();$('.nodes-sync').textContent=`${date(new Date().toISOString())} 조회 · 1시간마다 자동 갱신`;$('.nodes-sync').classList.remove('nodes-error');}
  catch(error){if(disposed)return;$('.nodes-sync').textContent='맥·배포 정보를 불러오지 못했습니다. 새로고침으로 다시 확인해 주세요.';$('.nodes-sync').classList.add('nodes-error');if(!data)$('.nodes-grid').innerHTML='<p class="nodes-empty">조회에 실패했습니다.</p>';}
  finally{busy=false;if(!disposed)$('.nodes-refresh').disabled=false;}
 }
 function openAction(next){
  if(!manage||saving)return;action=next;
  const pin=next.type==='pin';$('.nodes-sha-field').hidden=!pin;const input=$('input[name="sha"]');input.required=pin;input.disabled=!pin;input.value='';
  const current=data.deployments.find(d=>d.engine===next.engine);
  let title,label,copy;
  if(next.type==='status'){
   label={active:'활성화',draining:'작업 마무리',disabled:'비활성화'}[next.status];title=`${name(next.node)} ${label}`;
   copy={active:'새 작업을 받을 수 있도록 운영 상태를 가동으로 바꿉니다.',draining:'새 작업을 받지 않고 진행 중인 작업을 마무리하도록 설정합니다.',disabled:'이 맥미니를 비활성 상태로 바꿉니다. 실행 중인 작업의 취소는 별도로 관리됩니다.'}[next.status];
  }else if(pin){title=`${engineNames[next.engine]||next.engine} 버전 고정`;label='버전 고정';copy='이 엔진을 사용하는 모든 맥의 배포 기준을 지정한 커밋으로 고정하고 자동 업데이트를 끕니다.';}
  else{title=`${engineNames[next.engine]||next.engine} 고정 해제`;label='고정 해제';copy=`고정 버전 ${short(current?.pinned_sha)}을 해제하고 자동 업데이트를 다시 켭니다.`;}
  $('.nodes-dialog h2').textContent=title;$('.nodes-dialog-copy').textContent=copy;$('.nodes-confirm').textContent=label;$('.nodes-dialog-error').textContent='';dialog.showModal();
  if(pin)input.focus();else $('.nodes-dialog-cancel').focus();
 }
 const click=e=>{
  const nodeButton=e.target.closest('[data-status]'),engineButton=e.target.closest('[data-action]');
  if(nodeButton&&data?.nodes.some(n=>n.node_id===nodeButton.dataset.node))openAction({type:'status',node:nodeButton.dataset.node,status:nodeButton.dataset.status});
  if(engineButton&&data?.deployments.some(d=>d.engine===engineButton.dataset.engine))openAction({type:engineButton.dataset.action,engine:engineButton.dataset.engine});
 };
 root.addEventListener('click',click);$('.nodes-refresh').onclick=refresh;
 const close=()=>{if(!saving)dialog.close();};$('.nodes-dialog-close').onclick=close;$('.nodes-dialog-cancel').onclick=close;
 dialog.addEventListener('cancel',e=>{if(saving)e.preventDefault();});
 $('.nodes-dialog form').onsubmit=async e=>{
  e.preventDefault();if(!action||saving||!manage)return;saving=true;$('.nodes-dialog-error').textContent='';
  dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{
   if(action.type==='status')await service.setStatus(action.node,action.status);
   else if(action.type==='pin')await service.pin(action.engine,$('input[name="sha"]').value);
   else await service.unpin(action.engine);
   if(disposed)return;dialog.close();$('.nodes-notice').textContent='설정을 변경했습니다.';await refresh();
  }catch(error){if(!disposed)$('.nodes-dialog-error').textContent=error.message||'변경하지 못했습니다. 다시 시도해 주세요.';}
  finally{saving=false;if(!disposed)dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
 };
 const visibility=()=>{for(const card of visibleCards)card.classList.toggle('robots-moving',!document.hidden);if(!document.hidden&&Date.now()-lastAttempt>=3600000)refresh();};
 document.addEventListener('visibilitychange',visibility);const timer=setInterval(visibility,3600000);refresh();
 return ()=>{disposed=true;request?.abort();clearInterval(timer);robotObserver.disconnect();visibleCards.clear();document.removeEventListener('visibilitychange',visibility);root.removeEventListener('click',click);if(dialog.open)dialog.close();};
}

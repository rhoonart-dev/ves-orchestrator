import {esc} from './review-details.js?v=web-1';
import {pagerHtml} from './pager.js';
import {askConfirm} from './confirm-dialog.js';
import {hiddenChannels} from './channel-visibility.js';
import {enhanceDropdowns} from './dropdowns.js';
import {jobKindKo} from './job-kinds.js';
// 작업 이력 — 예전 VES '작업 내역'(renderJobsTab)을 옮겼다. 맥미니 잡(job_queue)을 상태·맥·채널로 거르고,
// 다시 시도 중이거나 끝난 잡의 오류는 앞 시도의 기록이라 '지난 시도 오류'로 흐리게 보인다(지금 실패한 것처럼 보이지 않게).
// 운영자는 재시도 · 잡 취소 · 작업지시 취소를 할 수 있다(RPC retry_job · cancel_job · cancel_work_order).
// 아래는 최근 상태 변화(job_events 40건). 홈의 '실행 중' 칸이 ?status=running 으로 들어온다.
const STATUS={all:'전체',pending:'대기',running:'실행',failed:'실패',dead:'중단',blocked:'보류',succeeded:'완료',cancelled:'취소'};
const TONE={pending:'mut',running:'info',succeeded:'good',failed:'crit',dead:'crit',blocked:'warn',cancelled:'mut'};
const kindKo=jobKindKo;
const EDITORS=['operator','admin'];
const LIMIT=200,PAGE=20;   // 최근 200건을 받아 20개씩 쪽으로 나눠 보여 준다
function ago(t){
 if(!t)return '';
 const s=Math.max(0,(Date.now()-Date.parse(t))/1000);
 return s<60?'방금':s<3600?`${Math.floor(s/60)}분 전`:s<86400?`${Math.floor(s/3600)}시간 전`:`${Math.floor(s/86400)}일 전`;
}
const kst=t=>t?new Date(t).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'';

export function mountHistory(root,{client=null,role=null,params=new URLSearchParams()}={}){
 const canEdit=EDITORS.includes(role);
 const st={status:STATUS[params.get('status')]?params.get('status'):'all',node:'all',chan:'all',page:0};
 let data=null,error='',dead=false,timer=0,releaseDrop=()=>{},pop=null,stale=false;   // pop: 열린 오류 말풍선(열려 있는 동안 30초 새로 읽기를 화면에 안 그린다)
 root.innerHTML='<div class="hist-page"><p class="hist-note">작업 이력을 불러오는 중…</p></div>';
 if(!client){root.innerHTML='<div class="hist-page"><p class="hist-note">로그인하면 작업 이력을 볼 수 있어요.</p></div>';return()=>{};}

 async function load(){
  clearTimeout(timer);
  try{
   const [jobs,nodes,chans,events]=await Promise.all([
    client.from('job_queue').select('id,work_order_id,kind,status,attempt,max_attempts,node_id,error,error_class,required_caps,params,updated_at,progress')
     .order('updated_at',{ascending:false}).limit(LIMIT).then(r=>{if(r.error)throw r.error;return r.data||[];}),
    client.from('node_registry').select('node_id').order('node_id').then(r=>r.data||[]),
    client.from('channels_mirror').select('token_slug,name').order('name').then(r=>r.data||[]),
    client.from('job_events').select('job_id,node_id,from_status,to_status,detail,at').order('at',{ascending:false}).limit(40).then(r=>r.data||[]),
   ]);
   const ids=[...new Set(jobs.map(j=>j.work_order_id).filter(Boolean))];
   const wos=ids.length?(await client.from('work_orders').select('id,work_title,episode,channel_slug,status').in('id',ids)).data||[]:[];
   const hidden=await hiddenChannels(client),woMap=new Map(wos.map(w=>[w.id,w]));
   const shown=jobs.filter(j=>!hidden.has(woMap.get(j.work_order_id)?.channel_slug||j.params?.channel_slug));   // 숨긴 채널 작업은 뺀다
   data={jobs:shown,nodes,chans:chans.filter(c=>!hidden.has(c.token_slug)),events,wo:woMap,byId:new Map(jobs.map(j=>[j.id,j]))};error='';
  }catch(e){error=e.message||'작업 이력을 불러오지 못했어요.';}
  if(dead)return;
  if(pop)stale=true;else render();
  timer=setTimeout(load,30000);   // 실행 중인 잡이 끝나는 걸 따라가려고 30초마다 다시 읽는다
 }
 const chName=slug=>data.chans.find(c=>c.token_slug===slug)?.name||slug;
 const chOf=j=>data.wo.get(j.work_order_id)?.channel_slug||j.params?.channel_slug||null;

 function render(){
  if(!data){root.innerHTML=`<div class="hist-page"><p class="hist-note">${esc(error)}</p></div>`;return;}
  const rows=data.jobs.filter(j=>(st.status==='all'||j.status===st.status)
   &&(st.node==='all'||j.node_id===st.node||(!j.node_id&&(j.required_caps||[]).includes('node:'+st.node)))
   &&(st.chan==='all'||chOf(j)===st.chan));
  const count=k=>k==='all'?data.jobs.length:data.jobs.filter(j=>j.status===k).length;
  const pages=Math.max(1,Math.ceil(rows.length/PAGE));st.page=Math.min(st.page,pages-1);
  const shown=rows.slice(st.page*PAGE,st.page*PAGE+PAGE);
  releaseDrop();
  root.innerHTML=`<div class="hist-page">
   <section class="hist-card">
    <header class="hist-head"><h2>작업 이력 <small class="hist-idx">최근 ${LIMIT}건 · 30초마다 새로</small></h2>
     <div class="hist-selects"><select data-f="node" aria-label="맥별 보기"><option value="all">맥 전체</option>${data.nodes.map(n=>`<option value="${esc(n.node_id)}" ${st.node===n.node_id?'selected':''}>${esc(n.node_id)}</option>`).join('')}</select>
      <select data-f="chan" aria-label="채널별 보기"><option value="all">채널 전체</option>${data.chans.map(c=>`<option value="${esc(c.token_slug)}" ${st.chan===c.token_slug?'selected':''}>${esc(c.name||c.token_slug)}</option>`).join('')}</select></div></header>
    <div class="hist-chips hscroll">${Object.entries(STATUS).map(([k,l])=>`<button type="button" data-s="${k}" aria-pressed="${st.status===k}">${l}<small>${count(k)}</small></button>`).join('')}</div>
    ${error?`<p class="hist-error">${esc(error)}</p>`:''}<p class="hist-msg" role="status"></p>
    <div class="hist-table"><table class="hist-jobs"><colgroup><col class="c-kind"><col class="c-st"><col class="c-try"><col class="c-node"><col><col class="c-ago"><col class="c-note">${canEdit?'<col class="c-acts">':''}</colgroup><thead><tr><th>단계</th><th>상태</th><th>시도</th><th>맥</th><th>작품 · 채널</th><th>경과</th><th>비고</th>${canEdit?'<th></th>':''}</tr></thead><tbody>${
     shown.map(j=>{const wo=data.wo.get(j.work_order_id)||{},pin=(j.required_caps||[]).find(c=>c.startsWith('node:'));
      const ep=wo.episode??j.params?.episode;const work=wo.work_title||j.params?.work_title||j.params?.folder_name||'';
      const acts=canEdit?[['failed','dead','cancelled'].includes(j.status)?`<button type="button" data-act="retry" data-id="${j.id}">재시도</button>`:'',
       ['pending','running','blocked'].includes(j.status)?`<button type="button" class="danger" data-act="cancel" data-id="${j.id}">취소</button>`:'',
       j.work_order_id&&wo.status&&wo.status!=='cancelled'?`<button type="button" class="danger" data-act="cancel-wo" data-id="${j.work_order_id}" title="이 잡이 속한 작업지시를 통째로 취소해요. 남은 잡과 검수 대기 카드가 같이 닫히고, 소스 소진에서도 빠져요">작업지시 취소</button>`:''].join(''):'';
      return `<tr><td>${esc(kindKo(j.kind))}</td><td><span class="hist-st ${TONE[j.status]||'mut'}"${j.status==='running'&&j.progress?.label?` data-tip="${esc(j.progress.label)}"`:''}>${STATUS[j.status]||esc(j.status)}</span></td>
       <td class="tnum">${j.attempt??0}/${j.max_attempts??3}</td>
       <td class="mono">${esc(j.node_id||'')}${pin?` <small title="이 맥에서만 돌아요">${esc(pin.replace('node:',''))} 고정</small>`:''}</td>
       <td>${esc(work)}${ep!=null?` <small>· ${esc(ep)}회차</small>`:''}${wo.channel_slug?`<small class="hist-ch">${esc(chName(wo.channel_slug))}</small>`:''}</td>
       <td class="tnum" title="${esc(kst(j.updated_at))}">${ago(j.updated_at)}</td>
       <td>${j.error?`<button type="button" class="hist-why${j.status==='cancelled'?' is-cancel':['running','pending','succeeded'].includes(j.status)?' is-past':''}" data-err="${j.id}">${j.status==='cancelled'?'취소 이유':['running','pending','succeeded'].includes(j.status)?'지난 시도 오류':'오류 보기'}<svg viewBox="0 0 12 12" aria-hidden="true"><path d="m4 5 2 2 2-2"/></svg></button>`:''}</td>
       ${canEdit?`<td class="hist-acts"><div class="hist-acts-in">${acts}</div></td>`:''}</tr>`;}).join('')||`<tr><td colspan="8" class="hist-empty">해당하는 작업이 없어요</td></tr>`}</tbody></table></div>
    ${pagerHtml({cur:st.page,pages,label:'작업 이력 페이지',prev:`data-page="${st.page-1}"`,next:`data-page="${st.page+1}"`})}
   </section>
   <section class="hist-card"><header class="hist-head"><h2>최근 상태 변화 <small class="hist-idx">40건</small></h2></header>
    <div class="hist-table"><table><thead><tr><th>시각</th><th>단계</th><th>맥</th><th>변화</th><th>비고</th></tr></thead><tbody>${
     data.events.map(e=>{const j=data.byId.get(e.job_id);const note=String(e.detail?.error||e.detail?.note||'').slice(0,140);
      return `<tr><td class="tnum" title="${esc(kst(e.at))}">${ago(e.at)}</td><td>${esc(j?kindKo(j.kind):(e.job_id||'').slice(0,8))}</td><td class="mono">${esc(e.node_id||'')}</td>
       <td>${STATUS[e.from_status]||esc(e.from_status||'')} → ${STATUS[e.to_status]||esc(e.to_status||'')}</td><td class="hist-err">${esc(note)}</td></tr>`;}).join('')||'<tr><td colspan="5" class="hist-empty">상태 변화가 없어요</td></tr>'}</tbody></table></div></section>
  </div>`;
  root.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{st.page=+b.dataset.page;render();root.querySelector('.hist-table')?.scrollIntoView({block:'nearest'});});
  root.querySelectorAll('[data-err]').forEach(b=>b.onclick=e=>{e.stopPropagation();openPop(b,data.byId.get(b.dataset.err));});
  root.querySelectorAll('[data-s]').forEach(b=>b.onclick=()=>{st.status=b.dataset.s;st.page=0;history.replaceState(null,'',st.status==='all'?'#history':`#history?status=${st.status}`);render();});
  root.querySelectorAll('select[data-f]').forEach(s=>s.onchange=()=>{st[s.dataset.f]=s.value;st.page=0;render();});
  root.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>act(b));
  releaseDrop=enhanceDropdowns(root);
 }
 // 오류 말풍선 — 누른 글자 바로 아래(자리가 없으면 위)에 붙고, 화면 가장자리를 넘지 않게 좌우를 맞춘다. 꼬리는 누른 글자 가운데
 function openPop(anchor,j){
  closePop();if(!j)return;
  pop=document.createElement('div');pop.className='hist-pop'+(j.status==='cancelled'?' is-cancel':'');pop.setAttribute('role','dialog');pop.setAttribute('aria-label',j.status==='cancelled'?'취소 이유':'오류');
  pop.innerHTML=`<p class="hist-pop-text"></p><div class="hist-pop-foot"><span></span><button type="button">복사</button></div><i class="hist-pop-tail" aria-hidden="true"></i>`;
  pop.querySelector('.hist-pop-text').textContent=j.error;
  pop.querySelector('.hist-pop-foot span').textContent=[j.node_id,`${j.attempt??0}/${j.max_attempts??3}번째 시도`,kst(j.updated_at)].filter(Boolean).join(' · ');
  const copy=pop.querySelector('button');copy.onclick=async()=>{try{await navigator.clipboard.writeText(j.error);copy.textContent='복사했어요';}catch{copy.textContent='복사 안 됨';}};
  document.body.append(pop);pop.anchor=anchor;anchor.setAttribute('aria-expanded','true');place();
  setTimeout(()=>{document.addEventListener('pointerdown',outside);document.addEventListener('keydown',esc_);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);});
 }
 function place(){
  if(!pop)return;const a=pop.anchor.getBoundingClientRect(),vw=document.documentElement.clientWidth,vh=window.innerHeight,m=16;
  if(!pop.anchor.isConnected||a.bottom<0||a.top>vh)return closePop();
  const w=Math.min(340,vw-m*2);pop.style.width=w+'px';
  const cx=a.left+a.width/2,left=Math.min(Math.max(cx-w/2,m),vw-w-m),h=pop.offsetHeight,up=a.bottom+10+h>vh-m&&a.top-10-h>m;
  pop.style.left=left+'px';pop.style.top=(up?a.top-10-h:a.bottom+10)+'px';pop.classList.toggle('up',up);
  pop.querySelector('.hist-pop-tail').style.left=Math.min(Math.max(cx-left,16),w-16)+'px';
 }
 function outside(e){if(pop&&!pop.contains(e.target)&&e.target!==pop.anchor)closePop();}
 function esc_(e){if(e.key==='Escape'){const a=pop?.anchor;closePop();a?.focus();}}
 function closePop(){
  if(!pop)return;pop.anchor.removeAttribute('aria-expanded');pop.remove();pop=null;
  document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',esc_);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);
  if(stale){stale=false;render();}   // 열려 있는 동안 새로 읽은 것을 이제 그린다
 }
 async function act(b){
  const kind=b.dataset.act,id=b.dataset.id,msg=t=>{const m=root.querySelector('.hist-msg');if(m)m.textContent=t;};
  const ask={retry:{title:'이 작업을 다시 돌릴까요?',ok:'다시 돌리기'},cancel:{title:'이 작업을 취소할까요?',body:'하던 일은 여기서 멈추고, 다시 돌리려면 새로 걸어야 해요.',ok:'작업 취소',cancel:'닫기',danger:true},
   'cancel-wo':{title:'이 작업지시를 통째로 취소할까요?',body:'남은 작업과 검수 대기 카드가 같이 닫혀요.',ok:'통째로 취소',cancel:'닫기',danger:true}}[kind];
  if(!await askConfirm(ask))return;
  b.disabled=true;
  const [fn,args,done]={retry:['retry_job',{p_job:id},'다시 돌리도록 넣었어요.'],cancel:['cancel_job',{p_job:id,p_note:'workspace'},'취소했어요.'],
   'cancel-wo':['cancel_work_order',{p_wo:id,p_note:'워크스페이스 작업 이력에서 취소'},'작업지시를 취소했어요.']}[kind];
  const {error:e}=await client.rpc(fn,args);
  if(e){b.disabled=false;msg('하지 못했어요: '+e.message);return;}
  await load();msg(done);
 }
 load();
 return()=>{dead=true;clearTimeout(timer);releaseDrop();closePop();};
}

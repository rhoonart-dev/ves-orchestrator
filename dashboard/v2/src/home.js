import {icon} from './icons.js';
import {nodeRobot,nodeRobotState} from './node-robots.js';
import {fetchRights} from './rights-service.js';
import {loadOperations} from './home-service.js?v=web-1';
import {summarizeHome,nodeHealth} from './home-model.js';
import {loadWeek,weekHtml,todayMetric} from './home-week.js?v=rev-1';
import {loadLocalJobs} from './local-jobs.js?v=room-1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const format=n=>n==null?'—':n.toLocaleString('ko-KR');
const date=v=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
const stage={acquire:'소스 준비',generate:'영상 제작',upload_artifacts:'결과 업로드',ingest:'기록 적재',evaluate:'자동 검사',publish:'발행',localize:'영상 현지화',sync_drive_folder:'드라이브 인입',register_playlist:'유튜브 소스 등록',zanmang_autopilot:'잔망루피 자동화',zanmang_decision:'잔망루피 검수 반영',editor_assets:'편집실 준비',register_sources:'소스 등록'};
const rightsLabels={pending:'검수 대기',completed:'검수 완료',revision_requested:'수정 요청',resubmit_requested:'재제출 요청',cancelled:'취소'};
export function mountHome(root,{client=null,service=null,authStatus='loading'}={}){
 let disposed=false,busy=false,lastAttempt=0,request,jobs=null,localJobs=null,rights=null,ops=null,week=null,errors={};
 const connected=!!client&&!!service;
 const emptyText=connected?'불러오는 중…':authStatus==='signed-out'?'로그인 후 확인할 수 있습니다.':['denied','error'].includes(authStatus)?'계정 권한 확인이 필요합니다.':'계정 권한을 확인하고 있습니다.';
 root.innerHTML=`<section class="home-page"><div class="home-toolbar"><h2>작업 현황</h2><div><span class="home-date">${new Date().toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',weekday:'long'})}</span><button type="button" class="home-refresh" ${connected?'':'disabled'}>새로고침</button></div></div><div class="home-metrics"></div><section class="home-panel home-week"><header><div><h2>이번 주 발행</h2><p class="hw-range"></p></div><div class="hw-head-side"><span class="hw-legend"><span><i class="lg-work"></i>작품 공개</span><span><i class="lg-video"></i>우리 영상</span></span><a href="#schedule">발행 일정 ${icon('chevron')}</a></div></header><div class="home-week-content"></div></section><div class="home-main-grid"><section class="home-panel home-tasks"><header><h2>확인할 작업</h2><a href="#review?source=live">작업 목록 ${icon('chevron')}</a></header><div class="home-task-list"></div></section><section class="home-panel home-rights"><header><h2>권리사 검수</h2><a href="#rights">전체 보기 ${icon('chevron')}</a></header><div class="home-rights-content"></div></section></div><section class="home-panel home-channels"><header><div><h2>채널별 진행</h2><p>내부 검수 기록 기준</p></div></header><div class="home-channel-content"></div></section><section class="home-panel home-machines"><header><h2>맥미니 현황</h2><span class="home-node-note">최근 응답 · 실행 작업</span></header><div class="home-node-grid"></div></section><section class="home-panel home-ops"><header><div><h2>운영 확인</h2><p>발행 누락 · 실패 · 마감 임박</p></div><span class="home-connection">연결 전</span></header><div class="home-ops-grid"><article><span class="home-ops-label">발행 누락</span><strong>—</strong><small>발행 일정에 있는데 올라가지 않은 영상</small><p class="home-ops-empty">대시보드 발행이 연결되면 여기에 나와요</p></article><article><span class="home-ops-label">발행 실패</span><strong>—</strong><small>예약·업로드가 실패한 영상</small><p class="home-ops-empty">대시보드 발행이 연결되면 여기에 나와요</p></article><article><span class="home-ops-label">마감 임박</span><strong>—</strong><small>권리사 답변 기한 · 작품 공개가 3일 안에 다가오는 것</small><p class="home-ops-empty">마감 기록이 연결되면 여기에 나와요</p></article></div></section><p class="home-sync" role="status"></p></section>`;
 const $=s=>root.querySelector(s);
 const message=(source,text=emptyText)=>`<p class="home-empty ${errors[source]?'home-error':''}">${errors[source]?esc(errors[source]):text}</p>`;
 function render(){
  const summary=summarizeHome(jobs||[],rights||[]);
  const chanSummary=summarizeHome([...(jobs||[]),...(localJobs||[])],[]).channels;   // 채널별 진행은 로컬 영상 묶음도 합친다
  const online=ops?.nodes.filter(n=>nodeHealth(n).online).length;
  const todayNow=todayMetric(week);
  const metrics=[
   // 셋째 값 = 이 숫자가 무엇을 센 건지 — 숫자 아래에, 칸에 마우스를 올리거나(키보드는 초점) 할 때만 보인다
   ['내부 검수 대기',jobs?summary.waiting:null,'검수를 기다리는 영상','list','#review?source=live',''],
   ['권리사 검수 중',rights?summary.rightsWaiting:null,'권리사가 보고 있는 영상','file','#rights?status=pending',''],
   // 권리사 요청 = 수정 요청 + 재제출 요청. 누르면 권리사 검수에서 두 칩이 같이 눌린 채로 열린다
   ['권리사 요청',rights?summary.changes:null,'수정·재제출 요청 영상','pencil','#rights?status=requests',summary.changes?'attention':''],
   ['오늘 발행',todayNow.value,week?'오늘 올라간 우리 영상':todayNow.unit,'calendar',week?`#schedule?date=${week.today}`:null,''],
   ['실행 중',ops?ops.running.length:null,'맥미니에서 도는 작업','video','#history?status=running',''],
   ['응답 확인 노드',ops?`${online} / ${ops.nodes.length}`:null,'8분 안에 응답한 맥미니','grid','#nodes',''],
  ];
  $('.home-metrics').innerHTML=metrics.map(([label,value,unit,glyph,href,tone])=>`<${href?'a':'article'} ${href?`href="${href}"`:''} class="home-metric ${tone}" aria-label="${label} ${typeof value==='string'?value:format(value)} — ${unit}" ${href?'':'tabindex="0"'}><div><span>${label}</span></div><strong>${typeof value==='string'?value:format(value)}</strong><small class="home-metric-tip">${unit}</small></${href?'a':'article'}>`).join('');
  if(week){$('.hw-range').textContent=`${+week.days[0].slice(5,7)}월 ${+week.days[0].slice(8)}일 – ${+week.days[6].slice(5,7)}월 ${+week.days[6].slice(8)}일`;$('.home-week-content').innerHTML=weekHtml(week);}
  else $('.home-week-content').innerHTML=message('week');
  // 확인할 작업 = 내부 검수 대기가 남은 VES 작업 + 작업 컴퓨터에서 만든 로컬 영상 묶음. 최근에 만든 순으로 4개
  const tasks=[...summary.tasks,...(localJobs||[])].sort((a,b)=>String(b.createdAt).localeCompare(String(a.createdAt)));
  $('.home-task-list').innerHTML=jobs||localJobs?tasks.slice(0,4).map(j=>{const local=j.source==='local-bundle';
   return `<a class="home-task" href="#review/${encodeURIComponent(j.id)}"><span class="home-task-icon">${icon('folder')}</span><span class="home-task-copy"><small>${esc(j.channel)} · ${esc(j.episode||'회차 미정')}</small><strong>${esc(j.work)}${local&&!j.remote?'<em class="home-task-local">로컬</em>':''}</strong><span>${date(j.createdAt)} · ${local?(j.remote?esc((j.nodeId||'').replace(/^mm-(\d+)$/, 'Mac mini $1')||'맥미니'):'작업 컴퓨터'):esc(j.nodeId ? j.nodeId.replace(/^mm-(\d+)$/, 'Mac mini $1') : '맥 정보 없음')}</span></span><span class="home-task-wait">${local?`완성 영상 <b>${j.videos}</b>`:`검수 대기 <b>${j.reviews.filter(r=>r.status==='waiting').length}</b>`}</span>${icon('chevron')}</a>`;}).join('')||message('jobs','확인할 작업이 없습니다.'):message('jobs');
  if(rights){
   const requests=rights.filter(r=>['revision_requested','resubmit_requested'].includes(r.status));
   const pending=rights.filter(r=>r.status==='pending');
   const focus=[...requests,...pending].slice(0,3);
   const recent=rights.filter(r=>!['revision_requested','resubmit_requested','pending'].includes(r.status)).sort((a,b)=>(b.updated_at||b.created_at||'').localeCompare(a.updated_at||a.created_at||'')).slice(0,2);
   const row=r=>`<a class="home-rights-row" href="#rights?record=${encodeURIComponent(r.id)}"><span class="rights-badge status-${esc(r.status)}">${esc(rightsLabels[r.status]||r.status)}</span><strong>${esc(r.video_title)}</strong><small>${esc(r.channel_name)} · ${esc(r.episode??'—')}화 · ${esc(r.episode_part??'—')}편</small></a>`;
   $('.home-rights-content').innerHTML=`<p class="home-scope">재미쇼츠 · 부먹?찍먹?</p>${focus.map(row).join('')||message('rights','대기·수정 요청이 없습니다.')}${recent.length?'<h3>최근 변경</h3>'+recent.map(row).join(''):''}`;
  }else $('.home-rights-content').innerHTML=message('rights');
  $('.home-channel-content').innerHTML=(jobs||localJobs)?(chanSummary.length?`<div class="home-table-wrap"><table class="home-channel-table"><thead><tr><th>채널</th><th>작품</th><th>검수 대기</th><th>작업</th><th>최근 기록</th></tr></thead><tbody>${chanSummary.map(ch=>`<tr><td><strong>${esc(ch.name)}</strong></td><td class="home-channel-works">${esc([...ch.works].join(' · '))}</td><td><span class="${ch.waiting?'home-count-active':''}">${ch.waiting}</span></td><td>${ch.jobs}</td><td>${date(ch.latest)}</td></tr>`).join('')}</tbody></table></div>`:message('jobs','검수 기록이 있는 채널이 없습니다.')):message('jobs');
  if(ops){
   $('.home-node-grid').innerHTML=ops.nodes.map(n=>{
    const health=nodeHealth(n),running=ops.running.filter(j=>j.node_id===n.node_id);
    return `<article class="home-node"><div><span class="home-node-symbol">${nodeRobot(n.node_id,nodeRobotState(n,health,running.length))}</span><strong>${esc(n.node_id)}</strong></div><span class="home-node-state ${health.tone}"><i></i>${health.label}</span><div class="home-node-work">${running.map(j=>{const group=jobs?.find(x=>x.workOrderId===j.work_order_id);return `<p><strong>${esc(stage[j.kind]||j.kind)}</strong><small>${esc(group?.work||j.work||'작품 미등록')}</small></p>`;}).join('')||`<p class="home-node-idle">${health.online?'쉬는 중':'실행 작업 기록 없음'}</p>`}</div><small class="home-last-seen">최근 응답 ${date(n.last_seen_at)}</small></article>`;
   }).join('')||message('ops','등록된 노드가 없습니다.');
  }else $('.home-node-grid').innerHTML=message('ops');
 }
 async function refresh(){
  if(!connected||busy||disposed)return;busy=true;lastAttempt=Date.now();$('.home-refresh').disabled=true;
  request=new AbortController();
  const results=await Promise.allSettled([service.listJobs(true),fetchRights(client,request.signal),loadOperations(client),loadWeek(client)]);
  localJobs=await loadLocalJobs(client).catch(()=>null);   // 로컬 영상은 작업 컴퓨터에서만 — 못 읽어도 홈은 그대로
  if(disposed)return;
  const names=['jobs','rights','ops','week'],descriptions=['내부 검수','권리사 검수','노드 상태','발행 일정 데이터'];
  results.forEach((r,i)=>{if(r.status==='fulfilled'){delete errors[names[i]];if(i===0)jobs=r.value;if(i===1)rights=r.value.records;if(i===2)ops=r.value;if(i===3)week=r.value;}else errors[names[i]]=`${descriptions[i]}를 불러오지 못했습니다.`;});
  render();const failed=Object.keys(errors).length;
  $('.home-sync').textContent=failed?Object.values(errors).join(' ')+' 새로고침으로 다시 확인해 주세요.':`${date(new Date().toISOString())} 조회 · 1시간마다 자동 갱신`;
  $('.home-sync').classList.toggle('home-error',!!failed);busy=false;$('.home-refresh').disabled=false;
 }
 $('.home-refresh').onclick=refresh;render();refresh();
 const machines=$('.home-machines');
 let machinesVisible=false;
 const syncRobotMotion=()=>machines.classList.toggle('robots-moving',machinesVisible&&!document.hidden);
 const robotObserver=new IntersectionObserver(([entry])=>{machinesVisible=entry.isIntersecting;syncRobotMotion();},{threshold:0});
 robotObserver.observe(machines);
 const visible=()=>{syncRobotMotion();if(document.visibilityState==='visible'&&Date.now()-lastAttempt>=3600000)refresh();};
 document.addEventListener('visibilitychange',visible);const timer=connected?setInterval(visible,3600000):null;
 return ()=>{disposed=true;request?.abort();clearInterval(timer);robotObserver.disconnect();document.removeEventListener('visibilitychange',visible);};
}

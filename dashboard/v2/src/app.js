import {mountChannels} from './channels.js?v=status-1';
import {mountChannelTemplates} from './channel-templates.js?v=web-1';
import {mountPerformance} from './performance.js?v=copy-1';
import {mountTrends} from './trends.js?v=copy-1';
import {mountArchive} from './archive.js?v=pager-2';
import {mountAccess} from './access.js?v=3';
import {avatarRobot,userRobotIndex,ROBOT_COUNT} from './avatar-robots.js';
import {mountHistory} from './history.js?v=web-1';
import {mountWorks} from './works.js?v=room-1';
import {mountHome} from './home.js?v=rev-1';
import {mountNodes} from './nodes.js?v=web-1';
import {mountLocalVideos} from './local-videos.js?v=rev-1';
import {mountSchedule} from './schedule.js?v=rev-1';
import {createReviewService} from './review-service.js?v=web-1';
import {mountRights} from './rights.js?v=web-2';
import {setupMobileNavigation} from './mobile-navigation.js';
import {setupScrollbars} from './scrollbars.js';
import {setupHoverTips} from './hover-tip.js?v=4';
import {setupWheelScroll} from './wheel-scroll.js';
import {setupLayoutMotion} from './layout-motion.js';
import {mountWorkbench} from './workbench.js?v=list-2';
import {sampleJobs} from './review-model.js';
import {loadLocalJobs} from './local-jobs.js?v=room-1';
import {mountReview} from './review.js?v=room-1';
import {config} from './config.js';
import {icon} from './icons.js';
import {groups,routes} from './navigation.js';
import {createAuthController} from './auth.js';
const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('brand-icon').innerHTML=icon('brand');$('login-brand-icon').innerHTML=icon('brand');
$('navigation').innerHTML=groups.map(g=>`<section><h2>${g.name}</h2>${g.items.map(([id,title,name])=>`<a href="#${id}" data-route="${id}">${icon(name)}<span>${title}</span></a>`).join('')}</section>`).join('');
setupMobileNavigation();
setupScrollbars();setupWheelScroll();setupHoverTips();
setupLayoutMotion();
let authState={status:'loading',user:null,role:null};
const emptyCopy={review:['작업 목록 연결 전','작업 ID별 영상과 내부 검수 정보를 연결할 예정입니다.'],rights:['권리사 검수 연결 전','레이블리의 검수 상태와 수정 요청 원문을 연결할 예정입니다.'],videos:['영상 연결 전','완성 영상의 조회와 재생을 연결할 예정입니다.'],editor:['편집실 연결 전','기존 편집실의 자막·크롭·내레이션 편집 기능을 연결할 예정입니다.'],history:['작업 이력 연결 전','작업과 검수 결정 이력을 연결할 예정입니다.'],channels:['채널 연결 전','채널 등록과 작품 매핑을 연결할 예정입니다.'],'channel-templates':['채널 템플릿 준비 중','채널별 제목·자막·영상 디자인을 관리하는 화면입니다.'],performance:['성과 연결 전','채널·영상의 실제 성과를 연결할 예정입니다.'],works:['작품 연결 전','작품 목록, 원문 가이드, 작업 폴더를 연결할 예정입니다.'],schedule:['발행 일정 연결 전','예약 일정과 발행 상태를 연결할 예정입니다.'],nodes:['운영 정보 연결 전','맥미니 상태와 배포 버전을 연결할 예정입니다.'],sources:['소스 연결 전','작품·회차별 소스 등록을 연결할 예정입니다.'],trends:['트렌드 연결 전','기획에 참고할 트렌드 조회를 연결할 예정입니다.']};
let releaseView=()=>{};
let reviewService=null,workspaceClient=null;
// Only a signed-in account with a registered role sees the workspace.
function showGate(){
 const s=authState.status,signedIn=s==='ready';
 // 저장된 로그인을 확인하는 동안(연결·권한 확인)은 로그인 창을 띄우지 않는다 — 로그인된 사람에게 로그인 화면이 깜빡 보이던 문제
 document.body.classList.toggle('auth-loading',s==='loading'||s==='checking-role');
 document.body.classList.toggle('signed-in',signedIn);
 $('login-status').textContent=s==='loading'?'연결 확인 중…':s==='checking-role'?'권한 확인 중…':'기존 VES 계정으로 로그인하세요.';
 $('login-error').textContent=['denied','error'].includes(s)?authState.message:'';
 if(!signedIn&&s!=='loading')$('email').focus({preventScroll:true});
 return signedIn;
}
function draw(){
 releaseView();releaseView=()=>{};
 if(!showGate()){$('content').innerHTML='';return;}
 const [path,search='']=location.hash.slice(1).split('?');
 const [requested,jobId]=path.split('/');const params=new URLSearchParams(search);
 if(requested==='sources'){location.replace('#works');return;}   // 소스 창고는 작품 탭으로 합쳤다
 const id=routes.has(requested)?requested:'home',route=routes.get(id);
 document.title=`${route.title} · VES Workspace`;$('page-title').textContent=route.title;
 document.querySelectorAll('[data-route]').forEach(a=>{const active=a.dataset.route===id;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 if(id==='home'){
  releaseView=mountHome($('content'),{client:authState.status==='ready'?workspaceClient:null,service:authState.status==='ready'?reviewService:null,authStatus:authState.status});
 }else if(id==='works'){
  releaseView=mountWorks($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role});
 }else if(id==='nodes'){
  releaseView=mountNodes($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role,authStatus:authState.status});
 }else if(id==='review'){
  const job=sampleJobs.find(j=>j.id===jobId);
  if(job)releaseView=mountWorkbench($('content'),job);
  else if(jobId&&(jobId.startsWith('LV-')||jobId.startsWith('MV-'))){      // local bundle job folder (ai-video videos/vN)
   let cancelled=false,cleanup=()=>{};
   $('content').innerHTML='<p class="workbench-note">로컬 작업을 불러오는 중…</p>';
   loadLocalJobs(workspaceClient).then(jobs=>{
    if(cancelled)return;const local=jobs.find(j=>j.id===jobId);
    if(local)cleanup=mountWorkbench($('content'),local,{service:reviewService,role:authState.role,refresh:()=>loadLocalJobs(workspaceClient)});
    else $('content').innerHTML='<p class="workbench-note">로컬 작업을 찾을 수 없습니다. <a href="#review">작업 목록</a></p>';
   }).catch(e=>{if(!cancelled)$('content').innerHTML=`<p class="workbench-note">${escape(e.message||'로컬 작업을 불러오지 못했습니다.')} <a href="#review">작업 목록</a></p>`;});
   releaseView=()=>{cancelled=true;cleanup();};
  }
  else if(jobId&&authState.status==='ready'){
   let cancelled=false,cleanup=()=>{};
   $('content').innerHTML='<p class="workbench-note">검수 작업을 불러오는 중…</p>';
   reviewService.listJobs().then(jobs=>{
    if(cancelled)return;const actual=jobs.find(j=>j.id===jobId);
    if(actual)cleanup=mountWorkbench($('content'),actual,{service:reviewService,role:authState.role});
    else $('content').innerHTML='<p class="workbench-note">작업을 찾을 수 없습니다. <a href="#review">작업 목록</a></p>';
   }).catch(()=>{if(!cancelled)$('content').innerHTML='<p class="workbench-note">검수 작업 조회에 실패했습니다. <a href="#review">작업 목록으로 돌아가기</a></p>';});
   releaseView=()=>{cancelled=true;cleanup();};
  }else releaseView=mountReview($('content'),{service:authState.status==='ready'?reviewService:null,client:workspaceClient,source:params.get('source')});
 }else if(id==='schedule'){
  releaseView=mountSchedule($('content'),{params,client:workspaceClient,role:authState.role});
 }else if(id==='editor'){
  releaseView=mountLocalVideos($('content'),{client:workspaceClient,role:authState.role});
 }else if(id==='channels'){
  releaseView=mountChannels($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role});
 }else if(id==='history'){
  releaseView=mountHistory($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role,params});
 }else if(id==='trends'){
  releaseView=mountTrends($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role});
 }else if(id==='access'){
  releaseView=mountAccess($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role,email:authState.user?.email});
 }else if(id==='archive'){
  releaseView=mountArchive($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role});
 }else if(id==='performance'){
  releaseView=mountPerformance($('content'),{client:authState.status==='ready'?workspaceClient:null});
 }else if(id==='channel-templates'){
  releaseView=mountChannelTemplates($('content'),{client:authState.status==='ready'?workspaceClient:null,role:authState.role,channel:params.get('channel')});
 }else if(id==='rights'&&authState.status==='ready'){
  releaseView=mountRights($('content'),workspaceClient,{status:params.get('status'),record:params.get('record')});
 }else{
  const [title,description]=emptyCopy[id];$('content').innerHTML=`<section class="empty-state">${icon(route.icon)}<h2>${title}</h2><p>${description}</p></section>`;
 }
}
window.addEventListener('hashchange',draw);
const memory=new Map();let storage;let persistent=false;
try{const local=window.localStorage;local.setItem('ves-workspace-probe','1');local.removeItem('ves-workspace-probe');storage=local;persistent=true;}catch{storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}}
let auth;
try{
 const client=window.supabase.createClient(config.supabaseUrl,config.publishableKey,{auth:{storage,storageKey:config.storageKey,persistSession:persistent,autoRefreshToken:true,detectSessionInUrl:false}});
 workspaceClient=client;reviewService=createReviewService(client);
 auth=createAuthController(client,next=>{
  authState=next;
  // 계정 — 오른쪽 위 동그란 로봇(사람마다 하나, avatar-robots.js). 누르면 이메일·권한·로그아웃
  $('account-state').textContent=next.status==='ready'||next.status==='signed-out'?'':next.status==='checking-role'?'권한 확인 중':next.message||'연결 확인 중';
  $('account-button').textContent=next.user?'로그아웃':'로그인';
  drawAccountRobot(next.user);
  // 저장된 로그인 정보는 탭마다 옛 계정 정보를 들고 있을 수 있다 — 서버에서 한 번 새로 읽어 고른 로봇을 맞춘다
  if(next.status==='ready')client.auth.getUser().then(({data})=>{if(data?.user)drawAccountRobot(data.user);},()=>{});
  $('account-email').textContent=next.user?.email||'';
  $('account-role').textContent=({viewer:'보기만',reviewer:'검수',operator:'운영',admin:'관리자'})[next.role]||'';
  if(next.status==='ready')$('password').value='';
  draw();
 });
}catch{authState={status:'error',user:null,role:null,message:'로그인 서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.'};$('submit-login').disabled=true;}
// 내 로봇 — 계정 창에서 8개 중 고른다. 계정 정보(user_metadata.avatar_robot)에 남아 어느 컴퓨터에서 열어도 같다
function drawAccountRobot(user){
 const pick=user?userRobotIndex(user):null,bot=user?avatarRobot(user.id,pick):'';
 $('account-avatar').innerHTML=bot;$('account-pop-av').innerHTML=bot;
 const box=document.querySelector('.account-robots');if(!box)return;
 box.innerHTML=user?Array.from({length:ROBOT_COUNT},(_,i)=>`<button type="button" role="radio" data-robot="${i}" aria-checked="${i===pick}" aria-label="로봇 ${i+1}">${avatarRobot('',i)}</button>`).join(''):'';
 box.querySelectorAll('[data-robot]').forEach(b=>b.onclick=async e=>{
  e.stopPropagation();const i=Number(b.dataset.robot);if(i===pick||!workspaceClient)return;
  const {data,error}=await workspaceClient.auth.updateUser({data:{avatar_robot:i}});
  if(error){$('account-state').textContent='로봇을 바꾸지 못했어요. 다시 해 주세요.';return;}
  $('account-state').textContent='';drawAccountRobot(data.user);
 });
}
// 계정 창 — 동그라미를 누르면 열리고, 바깥을 누르거나 Esc 면 닫힌다
const accountPop=$('account-pop'),accountAvatar=$('account-avatar');
const setAccountPop=open=>{accountPop.hidden=!open;accountAvatar.setAttribute('aria-expanded',String(open));};
accountAvatar.onclick=e=>{e.stopPropagation();setAccountPop(accountPop.hidden);};
document.addEventListener('click',e=>{if(!accountPop.hidden&&!accountPop.contains(e.target))setAccountPop(false);});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!accountPop.hidden){setAccountPop(false);accountAvatar.focus();}});
$('account-button').onclick=async()=>{
 try{await auth.signOut()}catch{$('account-state').textContent='로그아웃하지 못했습니다. 다시 시도해 주세요.';}
};
$('login-form').onsubmit=async e=>{
 e.preventDefault();$('submit-login').disabled=true;$('submit-login').textContent='로그인 중…';$('login-error').textContent='';
 try{await auth.signIn($('email').value,$('password').value);$('password').value='';}
 catch{$('login-error').textContent='로그인하지 못했습니다. 이메일·비밀번호와 연결 상태를 확인해 주세요.';}
 finally{$('submit-login').disabled=false;$('submit-login').textContent='로그인';}
};
draw();

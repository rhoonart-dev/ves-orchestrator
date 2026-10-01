import {config} from './config.js';
import {setupScrollbars} from './scrollbars.js';
import {createLocalEditorClient,loadLocalVideo} from './local-editor-client.js?v=web-1';
import {confirmSubmit} from './editor-submit-dialog.js?v=render-123';
import './editor-checks.js?v=render-123';   // window.__edChecks — 제출 전 검사(ves-editor.js 가 부른다)
import './editor-fx.js?v=render-123';
import './editor-frame.js?v=render-123';   // window.__edFrame — 구간 화면 위치(미리보기 자르기·끌기)       // window.__edFx — 강조·줌 편집
import {mountNotes} from './editor-notes.js?v=rf-2';   // 상단바 종 버튼(알림 창)
import {mountSafeArea} from './editor-safe.js?v=render-123';   // 미리보기 옆 쇼츠 안전 영역 버튼
import {mountAccount} from './editor-account.js?v=render-123';   // 오른쪽 위 계정 로봇(이메일·로그아웃)
import {icon} from './icons.js';
const gate=document.getElementById('editor-gate'),message=gate.querySelector('p');
// 여는 중 진행 표시: 단계마다 목표치까지 천천히 차오른다(오래 걸리는 영상 자료 단계에서도 멈춘 것처럼 보이지 않게).
const STEPS=[['로그인 확인하는 중',12],['편집 권한 확인하는 중',24],['영상 자료 불러오는 중',72],['편집 화면 여는 중',96]];
const bar=document.createElement('div');bar.className='gate-progress';bar.setAttribute('role','progressbar');
bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');bar.innerHTML='<i></i>';
const stepNote=document.createElement('span');stepNote.className='gate-step';
message.after(bar,stepNote);
let pos=0,from=0,goal=0,tick=0;
function step(i){
 from=Math.max(pos,i?STEPS[i-1][1]:0);goal=STEPS[i][1];pos=from;
 message.textContent=STEPS[i][0]+'…';stepNote.textContent=`${i+1} / ${STEPS.length} 단계`;
 clearInterval(tick);paint();
 tick=setInterval(()=>{pos+=(goal-pos)*0.06;paint();},120);   // 목표에 다가가기만 하고 넘지 않는다
}
function paint(){const v=Math.round(pos);bar.firstChild.style.width=pos+'%';bar.setAttribute('aria-valuenow',String(v));}
// 막 색은 처음 뜬 바탕 그대로(편집 화면이 테마를 바꿔도 여는 동안은 같은 색)
{const cs=getComputedStyle(gate),root=document.documentElement.style;   // 카드 색도 처음 그대로 고정(편집 화면이 밝은 테마를 켜도 여는 동안은 안 바뀐다)
 root.setProperty('--gate-bg',getComputedStyle(document.body).backgroundColor);
 gate.style.background=cs.backgroundColor;gate.style.color=cs.color;
 bar.style.background=getComputedStyle(bar).backgroundColor;stepNote.style.color=getComputedStyle(stepNote).color;}
function done(after){clearInterval(tick);pos=100;paint();
 setTimeout(()=>{gate.classList.add('leaving');setTimeout(()=>{gate.hidden=true;after?.();},260);},200);}
function failed(text){clearInterval(tick);gate.classList.add('failed');message.textContent=text;stepNote.textContent='';}
document.querySelectorAll('.studio-mark').forEach(el=>{el.innerHTML=icon('studio');});
const params=new URLSearchParams(location.search),rid=params.get('rid');
const back=params.get('back'),localKey=params.get('local')==='1'?params.get('run'):null;
// 목록·제출 뒤에는 온 곳으로 돌아간다: 편집실 메뉴에서 열었으면(from=editor) 편집실 목록, 작업 목록에서 열었으면
// 그 작업 화면으로 가서 편집하던 영상을 다시 고른다(#review/<작업>?video=<영상>, workbench.js 가 읽는다).
const origin=params.get('from'),jobOk=!!back&&/^[\w-]{1,80}$/.test(back),videoId=localKey||rid;
const backUrl=origin==='editor'?'index.html#editor'
 :jobOk?'index.html#review/'+encodeURIComponent(back)+(videoId?'?video='+encodeURIComponent(videoId):'')
 :localKey?'index.html#editor':'index.html#review';
window.__workspaceBack=backUrl;   // ves-editor.js 가 제출 뒤 이리로 간다
gate.querySelector('a').href=backUrl;gate.querySelector('a').innerHTML='<svg class="ei" viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>'+(backUrl.endsWith('#editor')?'편집실 목록으로':'작업 목록으로');
window.tlClose=()=>{location.href=backUrl;}; // beforeunload in the editor protects unsaved work.
async function bootLocal(client){
 step(2);
 const payload=await loadLocalVideo(client,localKey);
 if(payload.meta.status!=='ready')throw new Error('이 영상은 대본이 바뀌어서 새로 만들어야 해요. 새로 만든 뒤 열어 주세요.');
 const {sb,local}=createLocalEditorClient(client,payload);
 window.__workspaceLocal=local;window.__workspaceEditorCheck=local.check;
 // 도구 줄 이름표 — 작업 컴퓨터 영상은 파일 이름(작업 폴더/vN), 맥미니 영상은 이 컴퓨터에 파일이 없으니 작품·회차·판
 {const m=payload.meta,node=m.remote_node;   // 맥미니 이름은 mm-02 그대로(실패 말풍선의 로봇 이름표와 같게)
  window.__edRunLabel=node?{pill:String(node),name:[m.work,m.episode,String(m.key||'').split('/').pop()].filter(Boolean).join(' · ')}
   :{pill:'작업 컴퓨터',name:String(m.key||'')};}
 window.__edLogos=payload.meta.logos||{};window.__edWorkName=payload.meta.work||'';   // 미리보기 로고 그림·작품명
 // 작품 관리 로고 목록(로고 탭·미리보기 그림 주소) — 느려도 편집실은 먼저 연다
 window.__edLogoUrls={};
 window.__edLoadLogos=()=>local.logos().then(r=>{window.__edLogoList=r;
   [...r.work_logos,...r.platform_logos].forEach(l=>{window.__edLogoUrls[l.path]=l.url;});
   window.layoutShorts?.();if(window.__railOn==='logo')window.renderRailPanel?.('logo');return r;})
  .catch(e=>{window.__edLogoList={error:e.message};if(window.__railOn==='logo')window.renderRailPanel?.('logo');});
 window.__edLoadLogos();
 window.__edFx?.setEditable(payload.meta.fx_edit);   // 엔진이 강조·줌을 받을 때만 바꿀 수 있다
 window.__edFrame?.setup(payload.meta.framing,payload.meta.frame_edit);   // 구간 모델을 만들기 전에(렌더 때 고정한 구간을 되살린다)
 window.__edPhraseEdit=!!payload.meta.phrase_edit;   // 내레이션 문구 줄바꿈 = 자막 구절 경계(엔진 ae8cc2f7)
 window.__edRenderLayout=payload.meta.render_layout||{};   // 완성본 실제 배치(안전 구역 맞춤 뒤 영상 칸 y·로고 정렬)
 window.__sbMain=sb;window.__workspaceReviewId='local';
 window.__workspaceConfirmSubmit=(keys,pre={})=>confirmSubmit(keys,{...pre,version:String(payload.meta.key||'').split('/').pop()});
 return payload;
}
function showLocalNotes(payload){
 const btn=document.querySelector('#renderBtn span');if(btn)btn.textContent='제출';
 // 예전의 위 띠(영상 안내·지난 수정 결과)는 없앴다 — 상단바 종 버튼 창으로 모은다(src/editor-notes.js)
 const notes=mountNotes(payload.meta);
 mountSafeArea();
 return notes;
}
async function boot(){
 // 편집실은 작업 컴퓨터 영상(?local=1&run=<작업>/<vN>)만 연다 — 예전 VES 검수 카드(?rid=) 편집은 2026-09-29 뺐다
 if(!localKey)throw new Error(rid?'예전 방식으로 만든 영상은 편집실에서 열 수 없어요.':'작업 목록에서 편집할 영상을 골라 주세요.');
 step(0);
 const client=window.supabase.createClient(config.supabaseUrl,config.publishableKey,{auth:{storageKey:config.storageKey,detectSessionInUrl:false}});
 const {data,error}=await client.auth.getUser();
 if(error||!data.user)throw new Error('Workspace에 로그인한 뒤 다시 열어 주세요.');
 step(1);
 const roles=await client.from('user_roles').select('role').eq('user_id',data.user.id);
 if(roles.error)throw roles.error;
 if(!roles.data.some(r=>['reviewer','operator','admin'].includes(r.role)))throw new Error('편집하려면 검수자나 관리자 권한이 필요해요.');
 const payload=await bootLocal(client);
 step(3);
 await import('./ves-editor.js?v=rf-1');
 const root=document.getElementById('tlRoot');root.style.display='flex';root.style.flexDirection='column';
 const notes=showLocalNotes(payload);setupScrollbars();
 mountAccount(client,data.user,roles.data.map(r=>r.role));
 await window.__tlEnter({});
 done(()=>notes?.openIfFailed());   // 실패 알림 창은 막이 걷힌 뒤에
}
boot().catch(error=>{failed(error.message||'편집실 연결을 확인해 주세요.');});

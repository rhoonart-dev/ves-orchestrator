import {statusIcon,timelineHtml} from './workflow-card.js';
import {scenarios} from './workflow-demo-data.js';
import {initialDemo,transitionDemo} from './workflow-demo-model.js';
import {setupScrollbars} from './scrollbars.js';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let scenario,state,timer,modalAction;
const video=$('video'),dialog=$('#demo-dialog');
setupScrollbars();
$('.scenarios').innerHTML=scenarios.map(s=>`<button type="button" data-scenario="${s.id}" aria-pressed="false"><strong>${s.label}</strong><small>${esc(s.work)}</small></button>`).join('');
function select(id){
 clearTimeout(timer);if(dialog.open)dialog.close();scenario=scenarios.find(s=>s.id===id)||scenarios[0];state=initialDemo(scenario);
 history.replaceState(null,'','#'+scenario.id);
 document.querySelectorAll('[data-scenario]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scenario===scenario.id)));
 $('#work-name').textContent=scenario.work;$('#channel-name').textContent=scenario.channel+' · 예시 채널 배정';
 video.pause();video.poster=scenario.media.poster;video.src=scenario.media.src;video.load();$('#media-error').hidden=true;draw();
}
video.addEventListener('error',()=>{$('#media-error').hidden=false;});
const labels={new:['LLM Judge','예시 평가예요. 실제 영상의 분석 결과는 아닙니다.'],uploading:['일부공개로 올리는 중','자동 처리 과정을 재현하고 있어요. 잠시만 기다려 주세요.'],attaching:['완성본을 자동으로 연결하는 중','일부공개 링크와 해당 버전의 파일을 신청에 묶고 있어요.'],pending:['권리사 답변을 기다리고 있어요','아래에서 승인 또는 수정 요청을 직접 도착시켜 보세요.'],approved:['검수가 승인됐어요','승인된 이 버전으로 예약발행할 수 있어요.'],revision:['수정 요청이 도착했어요','제목의 강한 표현을 부드럽게 바꿔 주세요.'],rendering:['수정한 영상 만드는 중','재렌더가 끝나면 새 버전으로 다시 검수해요.'],error:['완성본 파일 확인이 필요해요','파일이 없어 신청을 멈췄어요. 아래에서 복구 상황을 재현해 보세요.'],scheduled:['예약 발행 설정 완료!','체험을 마쳤어요. 실제 유튜브에는 아무것도 발행되지 않습니다.'],rejected:['내부 검수에서 반려했어요','반려 사유가 이력에 남았어요. 처음부터 다시 체험할 수 있어요.']};
function button(action,label,primary=false){return `<button type="button" class="${primary?'primary':'soft'}" data-action="${action}">${label}</button>`;}
function draw(){
 $('#version').textContent=`v${state.version} · ${state.round?state.round+'차 검수':'내부 검수'}`;
 $('#video-title').textContent=state.title;
 $('#policy').textContent=state.policy==='required'?'권리사 검수 필요 · 작품 사용 승인 가정':'권리사 검수 불필요 · 내부 승인 후 바로 예약';
 const steps=state.policy==='required'?['내부 검수','자동 신청','권리사 검수','예약발행']:['내부 검수','예약발행'];
 const index=state.stage==='scheduled'?steps.length-1:['pending','revision','approved'].includes(state.stage)?2:['uploading','attaching','error'].includes(state.stage)?1:0;
 $('#steps').innerHTML=steps.map((text,i)=>`<li ${index===i?'aria-current="step"':''}>${text}</li>`).join('');
 const [title,help]=labels[state.stage];
 $('#status').dataset.stage=state.stage;
 $('#status').classList.toggle('is-error',state.stage==='error');
 $('#status').innerHTML=`<strong>${statusIcon(state.stage)}<span>${title}</span>${state.stage==='new'?'<small class="demo-judge-label">예시 평가</small>':''}</strong>${state.stage==='new'?'<div class="demo-judge-scores"><div><span>품질</span><b>0.82</b></div><div><span>신뢰도</span><b>0.94</b></div></div>':''}<p>${esc(help)}</p>`;
 $('#connections').innerHTML=state.policy==='required'?`<div><span>일부공개 링크</span><b>${state.linked?'자동 연결됨 · v'+state.version:'아직 없음'}</b></div><div><span>완성본 파일</span><b>${state.attached?'자동 첨부됨 · v'+state.version:'아직 없음'}</b></div>`:'';
 if(state.publishAt)$('#connections').innerHTML+=`<div><span>예약 시각</span><b>${esc(new Date(state.publishAt).toLocaleString('ko-KR'))}</b></div>`;
 let actions='';
 if(state.stage==='new')actions+=(state.policy==='required'?button('submit',state.round?'수정본 권리사 검수 재신청':'권리사 검수 신청',true):button('schedule','내부 승인 · 예약발행',true))+button('reject','반려');
 $('#editor-actions').innerHTML=['new','revision'].includes(state.stage)?button('edit',state.stage==='revision'?'편집실에서 수정하기':'편집실 열기'):'';
 $('#editor-actions').hidden=!['new','revision'].includes(state.stage);
 if(state.stage==='approved')actions+=button('schedule','예약발행',true);
 if(state.stage==='error')actions+=button('recover','파일 복구 후 다시 시도',true);
 if(['scheduled','rejected'].includes(state.stage))actions+=button('restart','다시 체험하기',true);
 $('#actions').innerHTML=actions;$('#response-card').hidden=state.stage!=='pending';
 $('#history').innerHTML=timelineHtml(state.history);
}
function advance(event,value){
 state=transitionDemo(state,event,value);draw();clearTimeout(timer);
 const next={uploading:'uploaded',attaching:'attached',rendering:'rendered'}[state.stage];
 if(next)timer=setTimeout(()=>advance(next),1500);
}
function open(action){
 modalAction=action;$('#dialog-error').textContent='';
 const edit=action==='edit',schedule=action==='schedule';
 $('#dialog-title').textContent=edit?'편집실 체험':schedule?'예약발행 체험':'영상 반려 체험';
 $('#dialog-submit').textContent=edit?'저장하고 재렌더':schedule?'예약하기':'반려하기';
 $('#dialog-body').innerHTML=edit?'<p>제목을 바꿔 보고 재렌더를 눌러 보세요. 영상 파일은 그대로 두고 새 버전이 생기는 흐름을 재현해요.</p><label>영상 제목<textarea name="title" required maxlength="150"></textarea></label>':schedule?'<p>체험용 예약입니다. 실제 발행 일정은 생성되지 않아요.</p><label>예약 공개 시각<input type="datetime-local" name="publish_at" required></label>':'<label>반려 사유<textarea name="note" required maxlength="500" placeholder="반려 이유를 적어 주세요"></textarea></label>';
 if(edit)dialog.querySelector('textarea').value=state.title;
 if(schedule){const date=new Date(Date.now()+86400000);date.setHours(9,0,0,0);dialog.querySelector('input').value=new Date(date-date.getTimezoneOffset()*60000).toISOString().slice(0,16);}
 dialog.showModal();
}
$('.scenarios').onclick=e=>{const b=e.target.closest('[data-scenario]');if(b)select(b.dataset.scenario);};
$('#reset').onclick=()=>select(scenario.id);$('#close-dialog').onclick=()=>dialog.close();
$('.demo-right').onclick=e=>{
 const action=e.target.closest('[data-action]')?.dataset.action;if(!action)return;
 if(['edit','schedule','reject'].includes(action))open(action);
 else if(action==='restart')select(scenario.id);
 else advance(action);
};
dialog.querySelector('form').onsubmit=e=>{
 e.preventDefault();const values=new FormData(e.target);
 try{
  if(modalAction==='edit')advance('render',values.get('title'));
  else if(modalAction==='schedule')advance('schedule',new Date(values.get('publish_at')).toISOString());
  else advance('reject',values.get('note'));
  dialog.close();
 }catch(error){$('#dialog-error').textContent=error.message;}
};
select(location.hash.slice(1));

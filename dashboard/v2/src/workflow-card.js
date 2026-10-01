import {inspectionRoute} from './workflow-model.js';
import {esc,judgeHtml} from './review-details.js?v=web-1';
export function statusIcon(stage){
 const marks={new:'M8 15v-3m4 3V8m4 7v-5',uploading:'M12 17V7m-3.5 3.5L12 7l3.5 3.5',attaching:'m10 14 4-4m-3.5-.5 1-1a2.8 2.8 0 0 1 4 4l-1 1m-1 1-1 1a2.8 2.8 0 0 1-4-4l1-1',pending:'M12 7v5l3 2',revision:'m8 13 5-5 3 3-5 5H8Zm4-4 3 3',approved:'m7.5 12 3 3 6-6',rendering:'M8 9h8m-8 3h5m-5 3h8',error:'M12 7.5v5M12 16h.01',scheduled:'m7.5 12 3 3 6-6',rejected:'m9 9 6 6m0-6-6 6'};
 return `<svg class="status-icon" viewBox="0 0 24 24" aria-hidden="true"><circle class="status-ring" pathLength="1" cx="12" cy="12" r="9.5"/><path ${stage==='scheduled'?'class="status-check" pathLength="1"':''} d="${marks[stage]||marks.new}"/></svg>`;
}
export function workflowView(data){
 const {state={},inspection,upload,work={},application}=data;
 const route=inspectionRoute(work.inspection_policy,{isAired:state.is_aired});
 let stage='new',title='',help='',action=null,label='';
 if(state.stage==='scheduled'||(state.stage==='schedule_uploading'&&upload?.status==='succeeded')){
  stage='scheduled';title='예약 발행 설정 완료!';help='설정한 시각에 영상이 공개돼요.';
 }else if(state.stage==='schedule_uploading'){
  stage=['failed','dead','cancelled'].includes(upload?.status)?'error':'uploading';title=stage==='error'?'예약발행 업로드를 확인해 주세요':'예약발행을 준비하고 있어요';help='업로드 결과를 확인하고 있어요.';
 }else if(state.automation_status==='needs_attention'){
  stage='error';title='검수 신청을 확인해 주세요';help=state.automation_error||'신청을 완료하지 못했어요.';action='request_inspection';label='권리사 검수 신청 다시 시도';
 }else if(['queued','waiting_upload'].includes(state.automation_status)){
  stage=upload?.status==='succeeded'?'attaching':'uploading';title=stage==='attaching'?'완성본을 자동으로 연결하는 중':'일부공개로 올리는 중';help='링크와 완성본 파일을 연결해 권리사 검수를 신청해요.';
 }else if(upload&&['pending','running','blocked'].includes(upload.status)){
  stage='uploading';title='일부공개로 올리는 중';help='업로드가 끝나면 다음 단계로 진행할 수 있어요.';
 }else if(upload&&['failed','dead','cancelled'].includes(upload.status)){
  stage='error';title='업로드를 확인해 주세요';help='유튜브와 작업한 맥의 업로드 결과를 확인해 주세요.';
 }else if(inspection){
  if(inspection.status==='completed'&&!inspection.revision_outcome){stage='approved';title='검수가 승인됐어요';help='승인된 이 버전으로 예약발행할 수 있어요.';action='schedule';label='예약발행';}
  else if(inspection.revision_outcome||['revision_requested','resubmit_requested'].includes(inspection.status)){stage='revision';title='수정 요청이 도착했어요';help=inspection.revision_notes||'편집실에서 수정하고 재렌더한 새 영상으로 다시 신청해 주세요.';}
  else if(inspection.status==='pending'){stage='pending';title='권리사 답변을 기다리고 있어요';help='답변이 도착하면 여기에서 확인할 수 있어요.';}
  else {stage='error';title='권리사 검수 상태를 확인해 주세요';help=inspection.status==='cancelled'?'취소된 검수 신청이에요.': '현재 검수 상태를 확인해야 해요.';}
 }else if(route==='direct'){action='schedule';label='내부 승인 · 예약발행';}
 else if(route==='rights'){action='request_inspection';label='권리사 검수 신청';}
 else if(route==='check-airing'){action='choose-airing';label='방영 여부 확인';}
 else help='작품 검수 정책을 먼저 확인해 주세요.';
 let notice='';
 if(!application||application.status!==true||application.rejected_bool){action=null;notice='이 채널의 작품 사용 신청 승인을 먼저 확인해 주세요.';}
 if(data.review_status!=='waiting'&&!['scheduled','schedule_uploading'].includes(state.stage)){action=null;stage='rejected';title=data.review_status==='rejected'?'내부 검수에서 반려했어요':'내부 검수가 종료됐어요';help='최신 영상에서 진행해 주세요.';}
 return {stage,title,help,action,label,route,notice,canEdit:data.review_status==='waiting'&&['new','revision'].includes(stage)};
}
export function workflowCardHtml(item,{data=null,view=null,local=false}={}){
 const state=data?.state||{},v=view||{stage:'new',route:'check-policy'},direct=v.route==='direct';
 const steps=direct?['내부 검수','예약발행']:['내부 검수','자동 신청','권리사 검수','예약발행'];
 const index=v.stage==='scheduled'||state.stage==='schedule_uploading'?steps.length-1:['pending','revision','approved'].includes(v.stage)?2:['uploading','attaching','error'].includes(v.stage)?1:0;
 const policy=local==='remote'?'검수 신청은 VES 연결 후':local==='bundle'?'작업 컴퓨터의 로컬 영상 · 검수 신청은 VES 연결 후':local?'로컬 예시 · 검수 정책 연결 전':({rights:'권리사 검수 필요',direct:'내부 승인 후 바로 예약발행','check-airing':'방영 여부에 따라 권리사 검수','check-policy':'검수 정책 확인 필요'}[v.route]);
 return `<section class="workflow-card"><div class="workflow-card-top"><span>${local==='remote'?'검수 진행':local==='bundle'?'로컬 영상':local?'로컬 완성본':'검수 진행'}</span><span>${state.inspection_round?esc(state.inspection_round)+'차 검수':'내부 검수'}</span></div><h3>${esc(item.title)}</h3><p class="workflow-card-policy">${esc(policy)}${data?.channel_name?' · '+esc(data.channel_name):''}</p><ol class="workflow-steps" aria-label="진행 단계">${steps.map((text,i)=>`<li ${index===i?'aria-current="step"':''}>${text}</li>`).join('')}</ol>${v.stage==='new'?judgeHtml(item):`<div class="workflow-status" data-stage="${v.stage}" role="status"><strong>${statusIcon(v.stage)}<span>${esc(v.title)}</span></strong><p>${esc(v.help)}</p></div>`}${!direct?`<div class="workflow-connections"><div><span>일부공개 링크</span>${state.youtube_id?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(state.youtube_id)}" target="_blank" rel="noopener noreferrer">연결됨 ↗</a>`:'<b>아직 없음</b>'}</div><div><span>완성본 파일</span><b>${state.attachment_key||state.attachment_url?'자동 첨부됨':'아직 없음'}</b></div></div>`:''}${state.publish_at?`<p class="workflow-schedule">예약 시각 · ${esc(historyTime(state.publish_at))}</p>`:''}${v.notice||v.stage==='new'&&v.help?`<p class="workflow-notice">${esc(v.notice||v.help)}</p>`:''}<div class="workflow-card-actions">${v.action?`<button type="button" class="workflow-next primary">${esc(v.label)}</button>`:''}${local?'<p class="workbench-note">실제 검수 작업에서 신청·발행할 수 있어요.</p>':''}</div></section>`;
}
export function historyTime(value){
 const date=new Date(value);return value&&Number.isFinite(date.getTime())?date.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}):'시간 기록 없음';
}
export function timelineHtml(events){
 return events.length?`<ol class="workflow-timeline">${[...events].sort((a,b)=>(Date.parse(b.at)||0)-(Date.parse(a.at)||0)).map(e=>`<li><span>${esc(e.label)}</span><time ${e.at?`datetime="${esc(e.at)}"`:''}>${esc(historyTime(e.at))}</time>${e.note?`<p>${esc(e.note)}</p>`:''}</li>`).join('')}</ol>`:'<p class="workbench-note">아직 기록된 작업 이력이 없어요.</p>';
}
export function reviewEvents(rows){
 return rows.flatMap(r=>[{label:'내부 검수 시작',at:r.created_at},...(r.decided_at?[{label:r.status==='rejected'?'내부 검수 반려':'내부 검수 결정',at:r.decided_at,note:r.decision_note}]:[])]);
}

import {workflowView,workflowCardHtml} from './workflow-card.js';
import {needWorkPc} from './local-only.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function mountWorkflowControls(root,{client,reviewId,canReview,item,onState=()=>{},onChange=()=>{}}){
 let disposed=false,data=null,dialog=null,poll=null,lastCard=null;const abort=new AbortController();
 async function request(method='GET',body=null,file=false){
  needWorkPc();
  const {data:auth,error}=await client.auth.getSession();if(error||!auth.session)throw new Error('로그인이 필요합니다.');
  const response=await fetch('/api/workflow/'+encodeURIComponent(reviewId)+(file?'/file':''),{method,headers:{Authorization:'Bearer '+auth.session.access_token,...(body&&!file?{'Content-Type':'application/json'}:{})},body:body?(file?body:JSON.stringify(body)):null,signal:abort.signal});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'작업을 처리하지 못했습니다.');return result;
 }
 async function refresh(quiet=false){
  clearTimeout(poll);
  if(!quiet){lastCard=null;root.innerHTML='<p class="workbench-note">진행 상태 확인 중…</p>';onState(null);}
  try{data=await request();if(disposed)return;draw();poll=setTimeout(()=>refresh(true),['queued','waiting_upload'].includes(data.state.automation_status)||data.state.stage==='schedule_uploading'?5000:30000);}
  catch(error){if(disposed)return;lastCard=null;onState(null);root.innerHTML=workflowCardHtml(item,{view:{stage:'new',route:'check-policy',notice:error.message}});const retry=document.createElement('button');retry.type='button';retry.className='workflow-refresh';retry.textContent='다시 확인';retry.onclick=()=>refresh();root.querySelector('.workflow-card-actions').append(retry);}
 }
 function draw(){
  const view=workflowView(data),{action,label}=view;
  const html=workflowCardHtml(item,{data,view});
  if(html!==lastCard){root.innerHTML=html;lastCard=html;if(action){root.querySelector('.workflow-next').disabled=!canReview;root.querySelector('.workflow-next').onclick=()=>open(action,label);}}
  onState(data,view);
 }

 function open(action,label){
  const choose=action==='choose-airing';
  dialog=document.createElement('dialog');dialog.className='workflow-dialog';dialog.setAttribute('aria-label',label);
  dialog.innerHTML=`<form><div class="login-heading"><h2>${label}</h2><button type="button" class="workflow-close" aria-label="닫기">×</button></div><p>${esc(data.work.title)}${data.channel_name?` · ${esc(data.channel_name)}`:""}</p>${choose?'<label>방영 여부<select name="is_aired"><option value="no">미방영분 · 권리사 검수 필요</option><option value="yes">방영분 · 내부 검수 후 예약발행</option></select></label>':''}${action==='schedule'||choose?'<label class="publish-time">예약 공개 시각<input type="datetime-local" name="publish_at" required></label>':''}${action==='request_inspection'||choose?'<label>영상 번호<input type="number" min="1" step="1" name="episode_part" required placeholder="같은 회차의 몇 번째 영상인지 입력"></label><label>전달할 내용<textarea name="remarks" rows="3" maxlength="3000"></textarea></label>':''}<p class="workflow-error" role="alert"></p><button class="primary" type="submit">${choose?'다음 단계 진행':label}</button></form>`;
  document.body.append(dialog);const active=dialog;
  active.querySelector('.workflow-close').onclick=()=>active.close();
  active.addEventListener('close',()=>{active.remove();if(dialog===active)dialog=null;});
  if(choose){const update=()=>{const aired=active.querySelector('select').value==='yes';active.querySelector('.publish-time').hidden=!aired;active.querySelector('[name=publish_at]').required=aired;active.querySelector('[name=episode_part]').disabled=aired;active.querySelector('[name=episode_part]').required=!aired;};active.querySelector('select').onchange=update;update();}
  active.querySelector('form').onsubmit=async e=>{
   e.preventDefault();const fields=new FormData(e.target),button=active.querySelector('[type=submit]');button.disabled=true;
   const aired=choose?fields.get('is_aired')==='yes':data.state.is_aired;
   const operation=choose?(aired?'schedule':'request_inspection'):action;
   try{
    const date=fields.get('publish_at');button.textContent='요청 중…';
    await request('POST',{action:operation,work_id:data.work.id,is_aired:aired,publish_at:date?new Date(date).toISOString():null,episode_part:fields.get('episode_part'),remarks:fields.get('remarks')});
    if(disposed)return;active.close();onChange();await refresh();
   }catch(error){if(!disposed)active.querySelector('.workflow-error').textContent=error.message||'작업을 완료하지 못했습니다.';}
   finally{button.disabled=false;button.textContent=label;}
  };
  active.showModal();
 }
 refresh();
 return ()=>{disposed=true;clearTimeout(poll);abort.abort();if(dialog)dialog.close();};
}

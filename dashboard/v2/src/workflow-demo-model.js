// In-memory simulator only. No auth, API clients, queues or database writes.
export function initialDemo(scenario,now=Date.now()){
 return {policy:scenario.policy,stage:scenario.revision?'revision':'new',version:1,round:scenario.revision?1:0,title:scenario.media.title,note:scenario.revision?'제목의 강한 표현을 부드럽게 바꿔 주세요.':null,linked:!!scenario.revision,attached:!!scenario.revision,missing:!!scenario.missing,approvedVersion:null,publishAt:null,history:[{label:scenario.revision?'1차 검수에서 수정 요청이 도착했어요.':'새로 생성된 영상을 확인할 차례예요.',at:new Date(now).toISOString()}]};
}
export function transitionDemo(state,event,value,now=Date.now()){
 const s={...state,history:[...state.history]};
 const fail=()=>{throw new Error('현재 단계에서는 진행할 수 없어요.');};
 const log=label=>s.history.push({label,at:new Date(now).toISOString()});
 switch(event){
  case 'submit':
   if(s.policy!=='required'||!['new','error'].includes(s.stage))return fail();
   s.stage='uploading';s.note=null;log(`v${s.version} 내부 승인 · 권리사 검수 신청 시작`);break;
  case 'uploaded':
   if(s.stage!=='uploading')return fail();s.linked=true;s.stage='attaching';log('일부공개 업로드 완료 · 링크 자동 연결 (가상)');break;
  case 'attached':
   if(s.stage!=='attaching')return fail();
   if(s.missing){s.stage='error';log('완성본 파일을 찾지 못해 신청을 멈췄어요.');}
   else{s.attached=true;s.round++;s.stage='pending';log(`완성본 자동 첨부 · ${s.round}차 권리사 검수 신청 완료 (가상)`);}break;
  case 'recover':
   if(s.stage!=='error')return fail();s.missing=false;s.stage='attaching';log('파일 연결 복구 · 기존 링크로 이어서 진행');break;
  case 'approve':
   if(s.stage!=='pending')return fail();s.stage='approved';s.approvedVersion=s.version;log(`${s.round}차 검수 승인 · v${s.version}`);break;
  case 'revision':
   if(s.stage!=='pending')return fail();s.stage='revision';s.note='제목의 강한 표현을 부드럽게 바꿔 주세요.';log(`${s.round}차 검수 · 제목 수정 요청 도착`);break;
  case 'render':
   if(!['new','revision'].includes(s.stage)||!String(value||'').trim())return fail();
   s.title=String(value).trim();s.stage='rendering';s.approvedVersion=null;log('편집 내용 저장 · 재렌더 시작 (가상)');break;
  case 'rendered':
   if(s.stage!=='rendering')return fail();s.stage='new';s.version++;s.linked=false;s.attached=false;s.note=null;log(`수정본 v${s.version} 준비 완료 · 내부 검수로 돌아왔어요.`);break;
  case 'schedule':
   if(!(s.policy==='none'&&s.stage==='new')&&!(s.stage==='approved'&&s.approvedVersion===s.version))return fail();
   if(!Number.isFinite(new Date(value).getTime())||new Date(value).getTime()<now+600000)throw new Error('현재보다 10분 이상 뒤로 선택해 주세요.');
   s.stage='scheduled';s.publishAt=value;log(`예약발행 설정 완료 (가상) · ${new Date(value).toLocaleString('ko-KR')}`);break;
  case 'reject':
   if(s.stage!=='new'||!String(value||'').trim())return fail();s.stage='rejected';log('내부 반려 · '+String(value).trim());break;
  default:return fail();
 }
 return s;
}

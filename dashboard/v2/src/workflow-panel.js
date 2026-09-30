import {inspectionRoute,policyForWork,permissionForWork} from './workflow-model.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function workflowHtml(job,data){
 const work=policyForWork(data.works,job.work);
 const route=inspectionRoute(work?.inspection_policy);
 const permission=work?permissionForWork(data.applications,job.youtubeChannelId,work.id):null;
 const labels={rights:'권리사 검수 필요',direct:'내부 검수 후 예약발행','check-airing':'방영 여부 확인 필요','check-policy':'작품 검수 정책 확인 필요'};
 const steps={rights:'내부 검수 → 일부공개 → 권리사 승인 → 예약발행',direct:'내부 검수 → 예약발행','check-airing':'미방영분은 권리사 검수를 거칩니다. 방영 여부를 먼저 확인해 주세요.','check-policy':'미지정이거나 작품을 정확하게 연결하지 못했습니다. 검수 생략 여부를 먼저 확인해 주세요.'};
 let application='이 채널의 작품 사용 신청을 확인하지 못했습니다.';
 if(permission)application=permission.rejected_bool?'작품 사용 신청 반려':permission.status===true?'작품 사용 신청 승인': '작품 사용 신청 확인 중';
 return `<section class="workflow-policy"><strong>${labels[route]}</strong><p>${steps[route]}</p><small>${esc(job.channel)} · ${application}</small>${permission?`<a href="#rights">권리사 검수 보기 ›</a>`:''}</section>`;
}

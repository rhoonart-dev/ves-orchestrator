import {score,reviewLabels} from './review-service.js?v=web-1';
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=v=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'—';
const names={pacing:'전개 속도',hook_3s:'초반 몰입',visual_hook:'화면 주목도',completion_pull:'끝까지 볼 동기'};
export function judgeHtml(item){
 const j=item.judge,r=j?.rubric_scores||{},pay=item.review?.payload||{};
 const details=[['권리 지침·기획 방향',pay.editorial],['이번 편 추가 지시',pay.editorial_run],['재생성 내역',pay.regen],['편집 내역',pay.editor]].filter(([,v])=>v&&Object.keys(v).length);
 return `<section class="judge-card"><div><h4>LLM Judge</h4><span>${j?'실제 평가':'평가 없음'}</span></div><div class="judge-values"><div><small>품질</small><strong>${score(j?.quality_score)}</strong></div><div><small>신뢰도</small><strong>${score(j?.confidence)}</strong></div></div>${Object.entries(r).filter(([,v])=>typeof v==='number').map(([k,v])=>`<p>${esc(names[k]||k)} <strong>${score(v)}</strong></p>`).join('')}${r.hallucination_flag?'<p class="review-warning">환각 의심 표시가 있습니다.</p>':''}${r.sensitive_flag?`<p class="review-warning">민감한 내용 · ${esc(r.sensitive_note)}</p>`:''}${r.rationale?`<details><summary>Judge 사유</summary><p class="rights-original">${esc(r.rationale)}</p></details>`:''}${!j?'<p>이 영상에 연결된 평가 결과가 없습니다.</p>':''}</section>${details.map(([title,value])=>`<details class="review-detail-block"><summary>${title}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`).join('')}`;
}
export function historyHtml(rows){
 return `<section class="review-history"><h4>같은 작업 지시의 검수 이력</h4>${rows.map(r=>`<article><strong>${esc(reviewLabels[r.status]||r.status)}</strong><small>${date(r.decided_at||r.created_at)} · ${esc(r.kind)}</small><p class="rights-original">${esc(r.decision_note||'기록된 사유 없음')}</p><small>검수 ID ${esc(r.id)}</small>${r.decided_by?`<small>결정자 ${esc(r.decided_by)}</small>`:''}</article>`).join('')}</section>`;
}

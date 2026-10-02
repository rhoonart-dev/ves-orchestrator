// 맥미니(새 파이프라인) 영상 검수 — 작업 화면 오른쪽 카드(오케스트레이터 0120 tikitaka_reviews).
// 내부 검수 → (권리사 검수 필요 작품) 일부공개 업로드 · 레이블리 신청 → 권리사 검수 → 스튜디오에서 공개
//            (검수 필요 없는 작품) 내부 검수에서 바로 비공개 + 예약 시각으로 올리기
// 읽기는 Supabase 에서 바로(레이블리는 우리 사본 laeebly_*), 쓰기는 RPC. 올리기 · 레이블리 신청은 맥미니가 한다.
// 유튜브 연결이 '올리기' 권한뿐인 채널이 많아 올린 영상의 공개 상태는 못 바꾼다 — 권리사 승인 뒤 공개는 사람이 스튜디오에서.
import {statusIcon,historyTime} from './workflow-card.js?v=web-1';
import {showToast} from './toast.js?v=1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pad=n=>String(n).padStart(2,'0');
const kst=d=>{const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',weekday:'short'}).formatToParts(new Date(d)).map(x=>[x.type,x.value]));return {date:`${p.year}-${p.month}-${p.day}`,time:`${p.hour}:${p.minute}`};};
const fromKst=(date,time)=>new Date(`${date}T${time||'00:00'}:00+09:00`);
const longTime=v=>new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',weekday:'short',hour:'numeric',minute:'2-digit'});
// '19:00' → '저녁 7:00'
const clock=t=>{const [h,m]=t.split(':').map(Number);const part=h<6?'새벽':h<12?'오전':h<18?'오후':'저녁';return `${part} ${h%12||12}:${pad(m)}`;};
const epNo=e=>{const m=String(e??'').match(/\d+/);return m?+m[0]:null;};
const BUSY=['pending','running','blocked'],DEAD=['failed','dead','cancelled'];

async function rows(q){const {data,error}=await q;if(error)throw Error(error.message);return data||[];}
async function one(q){return (await rows(q.limit(1)))[0]||null;}

// 카드에 필요한 것 한 번에
async function load(client,videoId){
 const video=await one(client.from('tikitaka_videos').select('id,work_order_id,suffix,channel_slug,work_title,episode,title,render_fingerprint,publish,node_id').eq('id',videoId));
 if(!video)throw Error('영상을 찾지 못했어요.');
 const [review,channel,works,policy]=await Promise.all([
  one(client.from('tikitaka_reviews').select('*').eq('video_id',videoId)),
  one(client.from('channels_mirror').select('token_slug,name,channel_id').eq('token_slug',video.channel_slug)),
  rows(client.from('laeebly_works').select('id,title,inspection_policy,company,geo_block_required,required_hashtags_description,required_hashtags_notice').eq('title',video.work_title)),
  one(client.from('channel_work_policies').select('inspection_policy').eq('token_slug',video.channel_slug).eq('work_title',video.work_title)).catch(()=>null)]);
 // 채널 + 작품 검수 정책(0126)이 있으면 작품 정책을 덮는다 — 예: 재미쇼츠 × 로또는 권리사 검수 없이 바로 예약
 const work=works.length===1?{...works[0],...(policy?.inspection_policy?{inspection_policy:policy.inspection_policy}:{})}:null;
 const ep=epNo(video.episode);
 const [application,inspection,job,parts,release,channelTimes]=await Promise.all([
  work&&channel?.channel_id?one(client.from('laeebly_applications').select('id,status,rejected_bool').eq('video_id',work.id).eq('youtube_channel_id',channel.channel_id).order('synced_at',{ascending:false})):null,
  review?.inspection_id?one(client.from('laeebly_inspections').select('id,status,round,revision_notes,revision_outcome,revision_items,reviewed_at,created_at,youtube_url').eq('id',review.inspection_id)):null,
  review?.upload_job_id?one(client.from('job_queue').select('id,status,error,node_id,finished_at').eq('id',review.upload_job_id)):null,
  channel?.channel_id&&ep!=null?rows(client.from('laeebly_inspections').select('episode_part').eq('youtube_channel_id',channel.channel_id).eq('video_title',video.work_title).eq('episode',ep)):[],
  work&&ep!=null?one(client.from('work_release_schedule').select('release_at,platform,status,episode_label').eq('work_id',work.id).eq('episode_no',ep).neq('status','cancelled').order('release_at')):null,
  rows(client.from('tikitaka_reviews').select('publish_at,tikitaka_videos!inner(channel_slug)').eq('tikitaka_videos.channel_slug',video.channel_slug).not('publish_at','is',null).order('publish_at',{ascending:false}).limit(40))]);
 return {video,review,channel,work,works:works.length,application,inspection,job,parts,release,channelTimes};
}

// 공개 시각 추천: 이 채널이 평소 올리던 시각(가장 잦은 시:분, 없으면 저녁 7시) · 예약이 없는 가장 가까운 날(내일부터)
export function suggestTime(times,now=new Date()){
 const count=new Map();for(const t of times){const k=kst(t).time;count.set(k,(count.get(k)||0)+1);}
 const usual=[...count].sort((a,b)=>b[1]-a[1])[0]?.[0]||'19:00';
 const taken=new Set(times.map(t=>kst(t).date));
 let d=new Date(now.getTime()+24*3600e3);
 for(let i=0;i<60&&taken.has(kst(d).date);i++)d=new Date(d.getTime()+24*3600e3);
 return {date:kst(d).date,time:usual,known:count.size>0};
}
// 유튜브 제목 · 설명 기본값 — 영상을 만들 때 정한 값(publish.json) + 레이블리 필수 표기
function metaDefault(video,work){
 const p=video.publish||{};
 const tags=(p.hashtags||[]).map(h=>String(h).replace(/^#/,'').trim()).filter(Boolean);
 const head=[p.work||video.work_title,p.copy].filter(Boolean);   // 첫 줄은 작품명만 — 회차는 두 회차 합본이면 엔진이 마지막 회차만 적어서 뺐다
 // required_hashtags_notice 는 레이블리가 만드는 사람에게 주는 안내(예: '식별코드는 꼭 설명란에')라 설명란에 넣지 않는다
 const line=[...tags.map(t=>'#'+t),...String(work?.required_hashtags_description||'').split(/\s+/).filter(Boolean).map(t=>t.startsWith('#')?t:'#'+t)];
 return {title:String(p.title||video.title||'').replace(/\s*\n\s*/g,' ').trim(),description:[head.join('\n'),[...new Set(line)].join(' ')].filter(Boolean).join('\n\n'),tags};
}

// 지금 어느 단계인가
function stageOf(d){
 const {video,review:r,job,inspection:i}=d;
 const current=r&&r.fingerprint===video.render_fingerprint;
 if(!r||!current)return {key:'internal',newVersion:!!r};
 if(r.stage==='rejected')return {key:'rejected'};
 if(['uploading','scheduling'].includes(r.stage))return {key:job&&DEAD.includes(job.status)?'upload_failed':'uploading'};
 if(r.stage==='submitting')return {key:'submitting'};
 if(r.stage==='needs_attention')return {key:'attention'};
 if(r.stage==='scheduled')return {key:'scheduled'};
 if(r.stage==='rights_pending'){
  if(!i)return {key:'submitted'};
  if(i.revision_outcome||['revision_requested','resubmit_requested'].includes(i.status))return {key:'revision'};
  if(i.status==='completed')return {key:'approved'};
  if(i.status==='cancelled')return {key:'cancelled'};
  return {key:'waiting'};
 }
 return {key:'internal'};
}

export function mountTikitakaReview(root,{client,videoId,title,canReview,editHref=()=>null,onChange=()=>{}}){
 let disposed=false,poll=0,d=null,rejecting=false;
 const busy=b=>{root.querySelectorAll('button').forEach(x=>x.disabled=b);};
 async function refresh(quiet){
  clearTimeout(poll);
  if(!quiet)root.innerHTML='<p class="workbench-note">검수 상태를 불러오는 중…</p>';
  try{d=await load(client,videoId);if(disposed)return;draw();}
  catch(e){if(disposed)return;root.innerHTML=`<section class="workflow-card"><p class="workflow-notice">${esc(e.message)}</p><div class="tr-acts"><button type="button" class="tr-btn" data-act="reload">다시 확인</button></div></section>`;root.querySelector('[data-act=reload]').onclick=()=>refresh();}
  const st=d&&stageOf(d).key;
  poll=setTimeout(()=>refresh(true),['uploading','submitting','submitted','waiting'].includes(st)?15000:60000);
 }
 // 1분마다 새로 그려도 사람이 고치던 값(설명 · 제목 · 태그 · 시각 등)은 그대로 둔다 — 같은 판일 때만
 const KEEP=['yt_title','yt_desc','pub_date','pub_time','episode_part','remarks','reject_note','is_aired'];
 let kept=null;
 function keepForm(){
  if(!d)return;const vals={};for(const n of KEEP){const el=root.querySelector(`[name="${n}"]`);if(el)vals[n]=el.value;}
  const meta=root.querySelector('details.tr-meta');
  if(Object.keys(vals).length)kept={fp:d.video.render_fingerprint,vals,metaOpen:meta?meta.open:null};
 }
 function restoreForm(){
  if(!kept||kept.fp!==d.video.render_fingerprint)return;
  for(const [n,v] of Object.entries(kept.vals)){const el=root.querySelector(`[name="${n}"]`);if(el)el.value=v;}
  const meta=root.querySelector('details.tr-meta');if(meta&&kept.metaOpen!==null)meta.open=kept.metaOpen;
 }
 function draw(){
  keepForm();
  const {video,review:r,channel,work,application:a,inspection:i,job,parts,release}=d,st=stageOf(d);
  const policy=work?.inspection_policy,aired=r?.is_aired;
  const route=r&&!['internal','rejected'].includes(st.key)?r.route:policy==='required'?'rights':policy==='none'?'direct':policy==='unaired_only'?null:undefined;
  const steps=route==='direct'?['내부 검수','예약발행']:['내부 검수','자동 신청','권리사 검수','예약발행'];
  const at={internal:0,rejected:0,uploading:route==='direct'?0:1,upload_failed:route==='direct'?0:1,submitting:1,attention:1,submitted:2,waiting:2,revision:2,cancelled:2,approved:3,scheduled:steps.length-1}[st.key]??0;
  const policyText=!work?(d.works>1?'같은 이름의 레이블리 작품이 여러 개예요':'레이블리 작품을 찾지 못했어요'):{required:'권리사 검수 필요',none:'내부 승인 후 바로 예약발행',unaired_only:'방영 여부에 따라 권리사 검수'}[policy]||'검수 정책이 정해지지 않았어요';
  const round=r?.inspection_round||i?.round;
  const status=(stage,head,body='')=>`<div class="workflow-status" data-stage="${stage}" role="status"><strong>${statusIcon(stage)}<span>${esc(head)}</span></strong>${body}</div>`;
  const p=t=>t?`<p>${esc(t)}</p>`:'';
  const links=()=>route==='rights'?`<div class="workflow-connections"><div><span>일부공개 링크</span>${r?.youtube_id?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(r.youtube_id)}" target="_blank" rel="noopener noreferrer">연결됨 ↗</a>`:'<b>아직 없음</b>'}</div><div><span>완성본 파일</span><b>${r?.attachment_key?'자동 첨부됨':'아직 없음'}</b></div></div>`:'';
  let body='',acts='',notice='';
  const blockers=[];
  if(!work)blockers.push(d.works>1?'레이블리에 같은 이름의 작품이 여러 개라 하나로 고를 수 없어요. 작품 이름을 확인해 주세요.':'레이블리에서 이 작품을 찾지 못했어요. 작품 관리에서 작품 이름을 확인해 주세요.');
  else if(!policy)blockers.push('이 작품의 검수 정책이 정해지지 않았어요. 권리사 검수 탭의 작품 검수 정책에서 정해 주세요.');
  if(work&&(!a||a.status!==true||a.rejected_bool))blockers.push('이 채널의 작품 사용 신청이 아직 승인되지 않았어요. 레이블리에서 사용 신청을 먼저 확인해 주세요.');
  const meta=r?.meta?.title&&st.key!=='internal'?r.meta:metaDefault(video,work);
  const metaHtml=(open=false)=>`<details class="tr-meta"${open?' open':''}><summary>유튜브에 올릴 정보 <small>제목 · 설명</small></summary><div class="tr-form"><label>제목<input name="yt_title" maxlength="100" value="${esc(meta.title)}"></label><label>설명<textarea name="yt_desc" rows="5">${esc(meta.description)}</textarea></label><p class="tr-hint">영상을 만들 때 정해진 값이에요. 고치면 올릴 때 고친 값으로 올라가요.</p></div></details>`;
  const releaseHtml=()=>release?`<div class="tr-must"><b>지켜야 할 공개 시각</b><p>${esc(video.episode||release.episode_label||'')}이 ${esc(release.platform||'원작 플랫폼')}에서 ${esc(longTime(release.release_at))}에 공개돼요. 그 뒤로 공개해 주세요.</p><small>발행 일정 · 작품 공개 일정에서 가져왔어요</small></div>`:'';
  const sug=suggestTime(d.channelTimes.map(x=>x.publish_at));
  const timeHtml=(label,hint,date,time)=>`<div class="tr-form"><label>${label} <small>${hint}</small><span class="tr-row"><input type="date" name="pub_date" value="${date}" required><input type="time" name="pub_time" value="${time}" required></span></label></div>`;
  if(st.key==='internal'){
   const nextPart=Math.max(0,...parts.map(x=>+x.episode_part||0))+1;
   const rejectBox=rejecting?`<div class="tr-form"><label>반려 사유<textarea name="reject_note" rows="3" required placeholder="편집실에서 고칠 내용을 적어 주세요"></textarea></label></div>`:'';
   if(st.newVersion&&r?.stage==='rejected')notice='반려 뒤 새로 만든 판이에요. 다시 내부 검수해 주세요.';
   else if(st.newVersion&&r?.prev_inspection_id)notice='수정 요청 뒤 새로 만든 판이에요. 승인하면 다음 차수로 다시 신청해요.';
   if(route==='rights'){
    body=`<dl class="tr-info"><dt>작품</dt><dd>${esc(work?.title||video.work_title)} · ${esc(video.episode||'')}</dd><dt>사용 신청</dt><dd>${a?.status===true&&!a.rejected_bool?'승인됨':'확인 필요'}</dd><dt>만든 곳</dt><dd>${esc(video.node_id||'')} · ${esc(video.suffix)}</dd></dl>`+
     `<div class="tr-form"><label>영상 번호 <small>${parts.length?`이 회차에서 이미 ${parts.length}개를 신청해서 ${nextPart}로 채웠어요`:'이 회차의 첫 신청이에요'}</small><input type="number" name="episode_part" min="1" value="${nextPart}" required></label><label>권리사에게 남길 말 <small>선택</small><textarea name="remarks" rows="2"></textarea></label></div>`+metaHtml()+rejectBox;
    acts=rejecting?'<button type="button" class="tr-btn" data-act="cancel-reject">취소</button><button type="button" class="tr-btn danger" data-act="reject">반려하기</button>':'<button type="button" class="tr-btn danger" data-act="open-reject">반려</button><button type="button" class="tr-btn pri" data-act="approve">승인하고 검수 신청</button>';
   }else if(route==='direct'||route===null){
    const airing=route===null?`<div class="tr-form"><label>방영 여부 <small>방영된 회차면 권리사 검수 없이 바로 예약해요</small><select name="is_aired"><option value="yes">방영됨</option><option value="no">아직 방영 전</option></select></label></div>`:'';
    body=airing+releaseHtml()+timeHtml('공개 시각',`${sug.known?`이 채널이 평소 올리던 ${clock(sug.time)}`:`이 채널의 공개 기록이 아직 없어 ${clock(sug.time)}`} · 예약이 없는 가장 가까운 날로 채웠어요`,sug.date,sug.time)+metaHtml(true)+rejectBox;
    acts=rejecting?'<button type="button" class="tr-btn" data-act="cancel-reject">취소</button><button type="button" class="tr-btn danger" data-act="reject">반려하기</button>':'<button type="button" class="tr-btn danger" data-act="open-reject">반려</button><button type="button" class="tr-btn pri" data-act="approve">승인하고 예약 발행</button>';
    if(!rejecting)acts+='';
    notice=notice||'예약 발행을 누르면 영상이 비공개로 먼저 올라가고, 정한 시각에 저절로 공개돼요.';
    if(work?.geo_block_required)notice+=' 지역 제한이 필요한 작품이라, 공개 시각 전에 유튜브 스튜디오에서 지역 제한을 설정해 주세요.';
   }else{body='';acts='';}
   if(blockers.length){acts=acts.replace(/data-act="approve"/,'data-act="approve" disabled');}
  }else if(st.key==='rejected'){
   body=status('rejected','내부 검수에서 반려했어요',p(`반려 사유: ${r.reject_note||''}`)+p('편집실에서 고쳐 제출하면 새 판으로 다시 내부 검수를 해요.'));
   acts=editHref()?`<a class="tr-btn pri" href="${esc(editHref())}">편집실에서 고치기</a>`:'';
  }else if(st.key==='uploading'){
   body=route==='direct'?status('uploading','예약해서 올리는 중',p(`비공개로 올리고 ${longTime(r.publish_at)}에 공개되게 걸어 둬요.`)):status('uploading','일부공개로 올리는 중',p('유튜브에 일부공개로 올리고 있어요. 다 올라가면 링크와 완성본을 붙여 레이블리에 검수를 신청해요.'))+links();
  }else if(st.key==='upload_failed'){
   body=status('error','유튜브에 올리지 못했어요',p(job?.error||'')+p('고친 뒤 다시 승인하면 다시 올려요.'));
   rejecting=false;acts='<button type="button" class="tr-btn pri" data-act="reopen">다시 승인하기</button>';
  }else if(st.key==='submitting'){
   body=status('attaching','레이블리에 검수를 신청하는 중',p('일부공개 링크와 완성본 파일을 붙여 신청하고 있어요.'))+links();
  }else if(st.key==='attention'){
   body=status('error','검수 신청을 확인해 주세요',p(r.error||'신청을 마치지 못했어요.'))+links();
   acts=r.youtube_id&&!r.inspection_id?'<button type="button" class="tr-btn pri" data-act="retry">신청 다시 시도</button>':'';
  }else if(st.key==='submitted'){
   body=status('pending','레이블리에 신청했어요',p('레이블리 기록을 가져오는 중이에요. 2분쯤 뒤에 답변 상태가 보여요.'))+links();
  }else if(st.key==='waiting'){
   body=status('pending','권리사 답변을 기다리고 있어요',p(`${i.created_at?historyTime(i.created_at)+'에 신청했어요. ':''}답변이 오면 여기에 바로 보여요(2분마다 확인).`))+links();
  }else if(st.key==='revision'){
   const items=Array.isArray(i.revision_items)?i.revision_items.map(x=>x?.text||x?.note||x).filter(x=>typeof x==='string'&&x.trim()):[];
   body=status('revision','수정 요청이 왔어요',items.length?`<ul class="tr-notes">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:p(i.revision_notes||''))+`<p class="workflow-notice">편집실에서 고쳐 제출하면 새 판이 만들어져요. 새 판에서 다시 신청하면 ${(round||1)+1}차 검수로 이어져요.</p>`;
   acts=editHref()?`<a class="tr-btn pri" href="${esc(editHref())}">편집실에서 고치기</a>`:'';
  }else if(st.key==='cancelled'){
   body=status('error','레이블리에서 신청이 취소됐어요',p('레이블리에서 이유를 확인해 주세요.'))+links();
  }else if(st.key==='approved'){
   const s0=r.publish_at?kst(r.publish_at):sug;
   body=status('approved','권리사가 승인했어요',p('유튜브 스튜디오에서 이 일부공개 영상을 공개로 바꾸거나 예약해 주세요. 권리사가 검수한 그 링크 그대로 공개돼야 해요.'))+releaseHtml()+
    timeHtml('공개(또는 예약)한 시각','스튜디오에서 정한 시각을 적어 두면 발행 일정에 올라가요',s0.date,s0.time);
   acts=`<a class="tr-btn" href="https://studio.youtube.com/video/${encodeURIComponent(r.youtube_id)}/edit" target="_blank" rel="noopener noreferrer">스튜디오에서 열기 ↗</a><button type="button" class="tr-btn pri" data-act="published">공개·예약했어요</button>`;
  }else if(st.key==='scheduled'){
   const when=r.publish_at?longTime(r.publish_at):'';
   const past=r.publish_at&&Date.parse(r.publish_at)<=Date.now();
   body=status('scheduled',when?`${when} ${past?'공개됨':'공개 예정'}`:'예약했어요',p(r.publish_kind==='studio'?'스튜디오에서 공개·예약한 시각이에요. 발행 일정에도 올라가요.':'정한 시각에 유튜브가 공개로 바꿔요. 발행 일정에도 올라가요.'));
   acts=r.youtube_id?`<a class="tr-btn" href="https://www.youtube.com/watch?v=${encodeURIComponent(r.youtube_id)}" target="_blank" rel="noopener noreferrer">유튜브에서 보기 ↗</a>`:'';
   if(r.meta?.geo_block_todo&&!past){   // 지역 제한은 사람이 스튜디오에서(올리기 권한만 있는 채널이 많다)
    body+=`<div class="tr-must"><b>지역 제한 설정</b><p>공개 시각 전에 유튜브 스튜디오에서 지역 제한을 설정해 주세요.</p></div>`;
    if(r.youtube_id)acts=`<a class="tr-btn" href="https://studio.youtube.com/video/${encodeURIComponent(r.youtube_id)}/edit" target="_blank" rel="noopener noreferrer">스튜디오에서 열기 ↗</a>`+acts;
   }
  }
  if(!canReview)acts='';
  const top=round?`${round}차 검수`:'내부 검수';
  root.innerHTML=`<section class="workflow-card tr-card"><div class="workflow-card-top"><span>검수 진행</span><span>${esc(top)}</span></div><h3>${esc(title||video.title||'')}</h3><p class="workflow-card-policy">${esc(policyText)}${channel?.name?' · '+esc(channel.name):''}</p><ol class="workflow-steps" aria-label="진행 단계">${steps.map((t,n)=>`<li ${n===at?'aria-current="step"':''}>${t}</li>`).join('')}</ol>${body}${blockers.length&&st.key==='internal'?blockers.map(b=>`<p class="workflow-notice">${esc(b)}</p>`).join(''):''}${notice?`<p class="workflow-notice">${esc(notice)}</p>`:''}<p class="tr-error" role="alert"></p>${acts?`<div class="tr-acts">${acts}</div>`:''}${!canReview&&st.key==='internal'?'<p class="workbench-note">검수는 검수자부터 할 수 있어요.</p>':''}</section>`;
  restoreForm();
  bind();
 }
 const val=n=>root.querySelector(`[name="${n}"]`)?.value;
 const fail=e=>{const el=root.querySelector('.tr-error');if(el)el.textContent=e.message||String(e);busy(false);};
 const rpc=async(fn,args)=>{const {data,error}=await client.rpc(fn,args);if(error)throw Error(error.message);return data;};
 const after=async msg=>{showToast(root,msg);onChange();await refresh(true);};
 function bind(){
  const on=(a,f)=>{const b=root.querySelector(`[data-act="${a}"]`);if(b)b.onclick=async()=>{busy(true);try{await f();}catch(e){fail(e);}};};
  on('open-reject',async()=>{rejecting=true;draw();root.querySelector('[name=reject_note]')?.focus();});
  on('cancel-reject',async()=>{rejecting=false;draw();});
  on('reject',async()=>{const note=val('reject_note')?.trim();if(!note)throw Error('반려 사유를 적어 주세요.');
   await rpc('tikitaka_review_reject',{p_video:videoId,p_based_on:d.video.render_fingerprint,p_note:note});rejecting=false;await after('반려했어요.');});
  on('approve',async()=>{
   const tags=[];   // 유튜브 태그 칸은 쓰지 않는다 — 해시태그는 설명란에만(2026-10-02 사용자 결정)
   const air=val('is_aired');const date=val('pub_date'),time=val('pub_time');
   const args={p_video:videoId,p_based_on:d.video.render_fingerprint,p_meta:{title:(val('yt_title')||'').trim(),description:val('yt_desc')||'',tags},
    p_episode_part:val('episode_part')?+val('episode_part'):null,p_remarks:val('remarks')||null,
    p_publish_at:date&&time?fromKst(date,time).toISOString():null,p_is_aired:air?air==='yes':null};
   const res=await rpc('tikitaka_review_approve',args);
   await after(res?.route==='direct'?'승인했어요. 비공개로 올리고 예약을 걸어요.':'승인했어요. 일부공개로 올린 뒤 레이블리에 신청해요.');});
  on('reopen',async()=>{d.review={...d.review,fingerprint:'-'};draw();});
  on('retry',async()=>{await rpc('tikitaka_review_retry_submit',{p_video:videoId});await after('레이블리 신청을 다시 해요.');});
  on('published',async()=>{const date=val('pub_date'),time=val('pub_time');if(!date||!time)throw Error('공개(또는 예약)한 시각을 적어 주세요.');
   await rpc('tikitaka_review_mark_published',{p_video:videoId,p_publish_at:fromKst(date,time).toISOString()});await after('공개 시각을 적어 뒀어요.');});
 }
 refresh();
 return()=>{disposed=true;clearTimeout(poll);};
}

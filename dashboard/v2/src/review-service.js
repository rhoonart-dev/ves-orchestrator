import {inspectEditor} from './editor-service.js';
import {hiddenChannels} from './channel-visibility.js';
import {fetchWorkPolicies} from './rights-service.js';
const fields='id,kind,work_order_id,job_id,clip_id,channel_slug,round_id,payload,status,decided_by,decided_at,decision_note,created_at';
export const reviewLabels={waiting:'내부 검수',approved:'승인',rejected:'반려',expired:'이전 판본'};
export const score=value=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toFixed(2);
const checked=({data,error})=>{if(error)throw error;return data||[]};
const unique=values=>[...new Set(values.filter(Boolean))];

// Stable ID ordering prevents records with the same timestamp crossing page boundaries.
export async function readAll(makeQuery){
 const rows=[];
 for(let start=0;;start+=200){
  const page=checked(await makeQuery().range(start,start+199));rows.push(...page);
  if(page.length<200)return rows;
 }
}
async function byIds(client,table,columns,key,ids){
 const rows=[];
 for(let i=0;i<ids.length;i+=80)rows.push(...await readAll(()=>client.from(table).select(columns).in(key,ids.slice(i,i+80)).order(key).order('created_at',{ascending:false})));
 return rows;
}
export function groupReviews(reviews,orders,channels){
 const byOrder=new Map(orders.map(o=>[o.id,o])),byChannel=new Map(channels.map(c=>[c.token_slug,c])),groups=new Map();
 for(const review of reviews){
  const order=byOrder.get(review.work_order_id)||{},slug=review.channel_slug||order.channel_slug;
  const id=review.job_id||review.work_order_id||review.id;
  let job=groups.get(id);
  if(!job){
   const episode=order.episode==null?'회차 미지정':`${order.episode}화`;
   job={id,workOrderId:review.work_order_id,source:'supabase',nodeId:review.execution?.node_id||null,work:order.work_title||review.payload?.run_id||'작품 미등록',workId:order.work_title||id,episode,title:episode,channelId:slug,channel:byChannel.get(slug)?.name||slug||'채널 미등록',youtubeChannelId:byChannel.get(slug)?.channel_id||null,channelAvatar:byChannel.get(slug)?.avatar_url||null,createdAt:review.created_at,reviews:[],videos:0};
   groups.set(id,job);
  }
  job.reviews.push(review);job.videos++;
  if(review.created_at>job.createdAt)job.createdAt=review.created_at;
 }
 for(const job of groups.values()){
  const statuses=unique(job.reviews.map(r=>r.status));
  job.status=statuses.length===1?(reviewLabels[statuses[0]]||statuses[0]):'검수 상태 혼합';
 }
 return [...groups.values()];
}
export function createReviewService(client){
 let cached=null,pending=null;
 async function listJobs(force=false){
  if(pending)return pending;
  if(!force&&cached&&Date.now()-cached.at<15000)return cached.jobs;
  pending=(async()=>{
   const reviews=await readAll(()=>client.from('review_queue').select(`${fields},execution:job_queue!job_id(node_id)`).order('created_at',{ascending:false}).order('id'));
   const [orders,channels]=await Promise.all([
    byIds(client,'work_orders','id,work_title,episode,channel_slug,created_at','id',unique(reviews.map(r=>r.work_order_id))),
    client.from('channels_mirror').select('token_slug,name,channel_id,avatar_url').order('token_slug').then(checked),
   ]);
   const hidden=await hiddenChannels(client);
   const jobs=groupReviews(reviews,orders,channels).filter(j=>!hidden.has(j.channelId));   // 숨긴 채널 작업은 빼고 보여 준다
   cached={jobs,at:Date.now()};return jobs;
  })();
  try{return await pending}finally{pending=null}
 }
 async function loadItems(job){
  const reviews=checked(await client.from('review_queue').select(fields).in('id',job.reviews.map(r=>r.id)).order('created_at',{ascending:false}).order('id'));
  const directIds=unique(reviews.map(r=>r.clip_id));
  const runs=unique(reviews.filter(r=>!r.clip_id).map(r=>r.payload?.run_id));
  const metaColumns='clip_id,ai_video_run_id,created_at,title:checkpoint_story->>title_text';
  const metadata=[...await byIds(client,'clip_metadata',metaColumns,'clip_id',directIds),...await byIds(client,'clip_metadata',metaColumns,'ai_video_run_id',runs)];
  const clipId=r=>r.clip_id||metadata.find(m=>m.ai_video_run_id===r.payload?.run_id)?.clip_id;
  const ids=unique(reviews.map(clipId));
  const [judges,clips]=await Promise.all([
   byIds(client,'judge_runs','id,clip_id,quality_score,confidence,rubric_scores,created_at','clip_id',ids),
   byIds(client,'clips','id,duration_sec,created_at','id',ids),
  ]);
  return reviews.map(r=>{
   const cid=clipId(r),pay=r.payload||{},meta=metadata.find(m=>m.clip_id===cid),clip=clips.find(c=>c.id===cid);
   return {id:r.id,title:meta?.title||pay.title||pay.metadata_draft?.title||pay.run_id||job.work,review:r,judge:judges.find(j=>j.clip_id===cid)||null,duration:clip?.duration_sec??null,width:null,height:null,filename:pay.preview_key?.split('/').pop()||'프리뷰 미등록',poster:'',src:null};
  });
 }
 async function preview(item){
  const p=item.review.payload||{};
  if(!p.preview_key)throw new Error('등록된 미리보기 파일이 없습니다.');
  const {data,error}=await client.storage.from(p.bucket||'ves-outputs').createSignedUrl(p.preview_key,1800);
  if(error)throw new Error('미리보기 파일을 열 수 없습니다. 파일 만료 또는 접근 권한을 확인해 주세요.');
  const url=new URL(data.signedUrl);url.searchParams.set('version',item.review.created_at);return url.href;
 }
 async function history(item){
  const r=item.review;
  if(!r.work_order_id)return [r];
  return readAll(()=>client.from('review_queue').select(fields).eq('work_order_id',r.work_order_id).order('created_at',{ascending:false}).order('id'));
 }
 async function reject(item,note){
  if(!note.trim())throw new Error('반려 사유를 입력해 주세요.');
  const {data:auth,error}=await client.auth.getSession();if(error||!auth.session)throw new Error('로그인이 필요합니다.');
  const response=await fetch('/api/workflow/'+encodeURIComponent(item.id),{method:'POST',headers:{Authorization:'Bearer '+auth.session.access_token,'Content-Type':'application/json'},body:JSON.stringify({action:'reject',note:note.trim()})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'반려 기록을 저장하지 못했습니다.');cached=null;
 }
 return {client,listJobs,loadItems,preview,history,reject,inspectEditor:id=>inspectEditor(client,id),workPolicies:signal=>fetchWorkPolicies(client,signal)};
}

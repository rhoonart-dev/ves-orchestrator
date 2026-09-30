// 권리사 검수 · 작품 검수 정책 — 레이블리 사본에서 읽는다(오케스트레이터 0117 · 맥미니가 2분마다 맞춘다).
// 예전에는 작업 컴퓨터의 로컬 서버(/api/rights-inspections · /api/work-policies)가 레이블리를 직접 읽었다. 이제 웹 주소에서도 된다.
const FIELDS='id,channel_name,video_title,company,episode,episode_part,round,status,revision_notes,remarks,created_at,updated_at,reviewed_at,respond_by,revision_outcome,auto_approved_at,supersedes_inspection_id,revision_items,youtube_url,file_link,original_file_url,published_youtube_url';

async function rows(q,signal){
 if(signal)q=q.abortSignal(signal);
 const {data,error}=await q;if(error)throw new Error(error.message);return data||[];
}
const newest=list=>list.reduce((m,r)=>r.synced_at&&r.synced_at>m?r.synced_at:m,'')||new Date().toISOString();

// {records, fetched_at, source} — 로컬 서버 rights_api.list_inspections 와 같은 모양. fetched_at 은 맥미니가 레이블리에서 맞춘 시각
export async function fetchRights(client,signal){
 if(!client)throw new Error('로그인이 필요합니다.');
 const list=await rows(client.from('laeebly_inspections').select(FIELDS+',synced_at').order('created_at',{ascending:false}).order('id'),signal);
 return {records:list.map(({synced_at,...r})=>r),fetched_at:newest(list),source:'laeebly.video_inspection'};
}

// {works:[{id,title,inspection_policy}], applications, fetched_at} — rights_api.list_work_policies 와 같은 모양
export async function fetchWorkPolicies(client,signal){
 if(!client)throw new Error('로그인이 필요합니다.');
 const [works,applications]=await Promise.all([
  rows(client.from('laeebly_works').select('id,title,inspection_policy').order('id').range(0,4999),signal),
  rows(client.from('laeebly_applications').select('id,channel_id,video_id,status,rejected_bool,rh_verdict,youtube_channel_id,channel_title,work_title,synced_at').order('id'),signal)]);
 return {works,applications:applications.map(({synced_at,...r})=>r),fetched_at:newest(applications)};
}

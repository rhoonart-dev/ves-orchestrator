import {assetRequest} from './work-assets.js';
// Local tikitaka bundles (ai-video videos/vN) shaped like 작업 목록 jobs: one job folder → N videos.
// 채널은 잡 폴더 모음의 channels.json(작품→채널) 또는 잡의 display.json channel 로 정한다 — 이름은 channels_mirror 에서.
export const localMedia=(key,f)=>`/api/local-videos/media?key=${encodeURIComponent(key)}&f=${encodeURIComponent(f)}`;
export function toJob(j,names=new Map()){
 return {id:j.id,source:'local-bundle',raw:j.job,work:j.work||j.job,workId:j.work||j.job,episode:j.episode||'',title:j.title,note:j.note||'',
  channelId:j.channel||null,channel:j.channel?(names.get(j.channel)?.name||j.channel):'채널 미배정',youtubeChannelId:names.get(j.channel)?.channel_id||null,channelAvatar:names.get(j.channel)?.avatar_url||null,createdAt:j.updated||new Date(0).toISOString(),videos:j.videos.length,
  status:'로컬 렌더',fileCountLabel:'완성 영상',bundles:j.videos};
}
// 맥미니에서 만든 편(0111 tikitaka_videos) — 작업지시 하나 = 잡 하나, 편마다 ves-outputs 에 올라온 번들. 영상은 서명 URL 로 연다.
// 편집실·썸네일은 아직 작업 컴퓨터 영상만 된다(잡 폴더가 맥미니에 있다) — bundle.remote 로 구분한다.
const epLabel=e=>/^\d+$/.test(String(e||''))?`${e}화`:String(e||'');
async function loadRemoteJobs(client,names){
 const {data,error}=await client.from('tikitaka_videos').select('id,work_order_id,node_id,suffix,version,tag,channel_slug,work_title,episode,title,status,render_fingerprint,review_items,duration_sec,files,created_at,updated_at')
  .order('created_at',{ascending:false}).limit(500);
 if(error)throw new Error(error.message);
 const rows=data||[],keys=rows.map(r=>r.files?.['shorts.mp4']?.key).filter(Boolean),signed=new Map();
 if(keys.length){const {data:urls}=await client.storage.from('ves-outputs').createSignedUrls(keys,6*3600);(urls||[]).forEach(u=>{if(u.signedUrl)signed.set(u.path,u.signedUrl);});}
 // 편집실 제출 → 그 맥미니에서 다시 렌더(tikitaka_apply_edit 잡) — 편마다 가장 최근 것의 상태
 const applies=new Map();
 if(rows.length){
  const {data:jobs}=await client.from('job_queue').select('id,status,error,params,created_at,finished_at,updated_at,node_id,required_caps').eq('kind','tikitaka_apply_edit')
   .in('work_order_id',[...new Set(rows.map(r=>r.work_order_id))]).order('created_at',{ascending:false}).limit(200);
  for(const j of jobs||[]){const vid=j.params?.video_id;if(vid&&!applies.has(vid))applies.set(vid,{edit_id:j.id,state:{pending:'queued',running:'running',succeeded:'done'}[j.status]||'failed',error:j.status==='failed'||j.status==='dead'?String(j.error||'').slice(-300):null,node:jobNode(j),finished_at:j.finished_at||j.updated_at});}
 }
 const byWo=new Map();
 for(const r of rows){if(!byWo.has(r.work_order_id))byWo.set(r.work_order_id,[]);byWo.get(r.work_order_id).push(r);}
 return [...byWo.entries()].map(([wo,list])=>{
  const r=list[0],ch=names.get(r.channel_slug);list.sort((a,b)=>(a.version||0)-(b.version||0)||a.suffix.localeCompare(b.suffix));
  return {id:'MV-'+wo,source:'local-bundle',remote:true,raw:wo,work:r.work_title,workId:r.work_title,episode:epLabel(r.episode),title:epLabel(r.episode)||'회차 미정',note:'',
   channelId:r.channel_slug||null,channel:r.channel_slug?(ch?.name||r.channel_slug):'채널 미배정',youtubeChannelId:ch?.channel_id||null,channelAvatar:ch?.avatar_url||null,
   createdAt:list.map(x=>x.updated_at||x.created_at).sort().pop(),videos:list.length,nodeId:r.node_id,status:'내부 검수',fileCountLabel:'완성 영상',
   bundles:list.map(x=>({key:`remote-${wo}/${x.suffix}`,apply:applies.get(x.id)||null,suffix:x.suffix,version:x.version,tag:x.tag,title:x.title,status:'ready',render_fingerprint:x.render_fingerprint,
    review_items:x.review_items,labels:0,duration:Number(x.duration_sec)||0,remote:true,node:x.node_id,src:signed.get(x.files?.['shorts.mp4']?.key)||''}))};
 });
}
// 잡을 맡았던 맥미니 — 실패하면 node_id 가 비어서, 편을 만든 노드로 박아 둔 required_caps(node:mm-02)로
export const jobNode=j=>j.node_id||(j.required_caps||[]).find(c=>String(c).startsWith('node:'))?.slice(5)||null;
// 작업 컴퓨터 영상과 맥미니 영상을 함께 — 한쪽을 못 읽어도(다른 컴퓨터에서 열었을 때 등) 다른 쪽은 보인다. 둘 다 실패면 첫 오류.
export async function loadLocalJobs(client){
 const ch=await client.from('channels_mirror').select('token_slug,name,channel_id,avatar_url').then(r=>r,()=>({data:[]}));
 const names=new Map((ch.data||[]).map(c=>[c.token_slug,c]));
 const [local,remote]=await Promise.allSettled([assetRequest(client,'/api/local-videos').then(({jobs})=>jobs.map(j=>toJob(j,names))),loadRemoteJobs(client,names)]);
 if(local.status==='rejected'&&remote.status==='rejected')throw local.reason;
 return [...(local.value||[]),...(remote.value||[])];
}
export const bundleItem=v=>({id:v.key,title:(v.title||v.suffix).replace(/\n/g,' / '),src:v.remote?v.src:localMedia(v.key,'shorts.mp4')+`&v=${encodeURIComponent(String(v.render_fingerprint||'').slice(0,12))}`,poster:'',
 duration:v.duration||0,bundle:v});

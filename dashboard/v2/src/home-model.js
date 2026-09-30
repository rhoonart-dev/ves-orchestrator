export function summarizeHome(jobs=[],rights=[]){
 const reviews=[...new Map(jobs.flatMap(j=>j.reviews||[]).map(r=>[r.id,r])).values()];
 const channels=new Map();
 for(const job of jobs){
  const key=job.channelId||'unassigned';
  if(!channels.has(key))channels.set(key,{id:key,name:job.channel,works:new Set(),jobs:0,waiting:0,latest:''});
  const ch=channels.get(key);ch.works.add(job.work);ch.jobs++;ch.waiting+=(job.reviews||[]).filter(r=>r.status==='waiting').length;
  if(job.createdAt>ch.latest)ch.latest=job.createdAt;
 }
 return {waiting:reviews.filter(r=>r.status==='waiting').length,
  rightsWaiting:rights.filter(r=>r.status==='pending').length,
  changes:rights.filter(r=>['revision_requested','resubmit_requested'].includes(r.status)).length,
  tasks:jobs.filter(j=>j.reviews?.some(r=>r.status==='waiting')).sort((a,b)=>b.createdAt.localeCompare(a.createdAt)),
  channels:[...channels.values()].sort((a,b)=>b.waiting-a.waiting||a.name.localeCompare(b.name,'ko'))};
}
export function nodeHealth(node,now=Date.now()){
 const seen=Date.parse(node.last_seen_at),fresh=Number.isFinite(seen)&&now-seen<=8*60*1000&&now-seen>=-60*1000;
 if(node.status==='disabled')return {label:'비활성',tone:'muted',online:false};
 if(!fresh)return {label:'응답 확인 필요',tone:'warning',online:false};
 if(node.status==='draining')return {label:'작업 마무리 중',tone:'warning',online:true};
 return {label:node.status==='active'?'응답 정상':node.status||'상태 미확인',tone:node.status==='active'?'good':'muted',online:node.status==='active'};
}

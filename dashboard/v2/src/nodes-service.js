import {readAll} from './review-service.js?v=web-1';
export const canManageNodes=role=>['operator','admin'].includes(role);
export function versionMatch(current,target){
 if(!current||!target)return 'unknown';
 const a=String(current).toLowerCase(),b=String(target).toLowerCase();
 if(!/^[a-f0-9]{7,40}$/.test(a)||!/^[a-f0-9]{7,40}$/.test(b))return 'unknown';
 return a.startsWith(b)||b.startsWith(a)?'match':'different';
}
export function createNodesService(client,role){
 const read=async(signal)=>{
  const [nodes,deployments,running]=await Promise.all([
   readAll(()=>client.from('node_registry').select('node_id,status,last_seen_at,disk_free_gb,engine_versions,updating_since,gemini_slots:meta->gemini_slots').order('node_id').abortSignal(signal)),
   readAll(()=>client.from('deployments').select('engine,auto_update,last_seen_sha,pinned_sha').order('engine').abortSignal(signal)),
   readAll(()=>client.from('job_queue').select('id,node_id,kind,work:params->>work_title,order:work_orders(work_title,episode)').eq('status','running').order('id').abortSignal(signal)),
  ]);
  return {nodes,deployments,running};
 };
 async function mutate(name,args){
  if(!canManageNodes(role))throw new Error('운영자 권한이 필요합니다.');
  const {error}=await client.rpc(name,args);if(error)throw error;
 }
 return {read,
  setStatus:(node,status)=>{
   if(!node||!['active','draining','disabled'].includes(status))throw new Error('운영 상태를 확인해 주세요.');
   return mutate('set_node_status',{p_node:node,p_status:status});
  },
  pin:(engine,sha)=>{
   const commit=String(sha).trim();
   if(!engine||!/^[a-fA-F0-9]{7,40}$/.test(commit))throw new Error('커밋 SHA는 7~40자리 영문 a~f와 숫자로 입력해 주세요.');
   return mutate('pin_engine',{p_engine:engine,p_sha:commit.toLowerCase(),p_note:'VES Workspace'});
  },
  unpin:engine=>{if(!engine)throw new Error('엔진을 확인해 주세요.');return mutate('unpin_engine',{p_engine:engine});},
 };
}

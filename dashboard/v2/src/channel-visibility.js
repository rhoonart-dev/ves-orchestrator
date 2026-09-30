// 워크스페이스에서 숨길 채널 — ops_config.workspace_hidden_channels(token_slug JSON 배열).
// 채널 정보와 지난 기록은 그대로 두고, 채널 목록·템플릿·성과·발행 일정·작업 목록·작업 이력에서만 뺀다. 다시 보이려면 배열에서 빼면 된다.
let cache=null,cacheClient=null;
export function hiddenChannels(client){
 if(!client)return Promise.resolve(new Set());
 if(!cache||cacheClient!==client){
  cacheClient=client;
  cache=client.from('ops_config').select('value').eq('key','workspace_hidden_channels').maybeSingle()
   .then(r=>{try{return new Set(JSON.parse(r.data?.value||'[]'));}catch{return new Set();}},()=>new Set());
 }
 return cache;
}
// 숨기기/보이기 — 운영자·관리자만(0110 set_workspace_channel_hidden). 성공하면 모든 화면이 새 목록을 읽도록 캐시를 바꿔 둔다.
export async function setChannelHidden(client,slug,hidden){
 const {data,error}=await client.rpc('set_workspace_channel_hidden',{p_slug:slug,p_hidden:hidden});
 if(error)throw new Error(error.message||'채널 표시를 바꾸지 못했어요.');
 cacheClient=client;cache=Promise.resolve(new Set(Array.isArray(data)?data:[]));
 return cache;
}
// 채널이 맡은 작품 — 관제 수정본(channel_works_overrides)이 있으면 그걸, 없으면 channels_mirror.works (기존 VES planner 와 같은 규칙)
export async function withWorkOverrides(client,list){
 const {data}=await client.from('channel_works_overrides').select('token_slug,works').then(r=>r,()=>({data:[]}));
 const over=new Map((data||[]).map(o=>[o.token_slug,o.works]));
 return (list||[]).map(c=>over.has(c.token_slug)?{...c,works:over.get(c.token_slug)}:c);
}
export async function visibleChannels(client,list){
 const hidden=await hiddenChannels(client);
 return (list||[]).filter(c=>!hidden.has(c.token_slug));
}

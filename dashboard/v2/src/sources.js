import {hiddenChannels} from './channel-visibility.js';
// 소스 창고 — 예전 VES 소스 탭(renderSources)을 옮겼다. 작품 탭 안에서 작품별로 보인다.
// 데이터: source_usage(원본 파일 1행) + source_usage_by_channel(채널별 소진, 0023) + 채널이 맡은 작품(channel_works_overrides > channels_mirror.works).
// 셈 규칙은 예전 그대로 — 숫자는 파일 행 단위로 더하고, planner 가 실제로 고를 수 있는 행(usable)만 한도·남음에 넣는다(0027·0031·0064).
const pageAll=async q=>{const out=[];for(let from=0;;from+=1000){const {data,error}=await q().range(from,from+999);if(error)throw error;out.push(...(data||[]));if(!data||data.length<1000)return out;}};

export async function loadSources(client){
 const [srcs,byCh,chans,ovr]=await Promise.all([
  pageAll(()=>client.from('source_usage').select('*').order('work_title').order('episode')),
  pageAll(()=>client.from('source_usage_by_channel').select('*')).catch(()=>null),
  client.from('channels_mirror').select('token_slug,name,works,avatar_url').order('token_slug').then(r=>r.data||[]),
  client.from('channel_works_overrides').select('token_slug,works').then(r=>r.data||[],()=>[]),
 ]);
 const over=new Map(ovr.map(o=>[o.token_slug,o.works]));
 const hidden=await hiddenChannels(client);
 const channels=chans.filter(c=>!hidden.has(c.token_slug)).map(c=>({...c,works:over.get(c.token_slug)||c.works||[]}));
 return {eps:buildEpMap(srcs,byCh||[]),channels,byChannelMissing:srcs.length>0&&!(byCh||[]).length};
}

const srcUsable=r=>r.usable!=null?r.usable===true:(r.is_active!==false&&(r.duration_sec==null||Number(r.duration_sec)>180));
export function buildEpMap(srcs,byCh){
 const map={},key=ep=>ep==null?'-':String(ep);
 (srcs||[]).forEach(r=>{
  const m=map[r.work_title]=map[r.work_title]||{};
  const e=m[key(r.episode)]=m[key(r.episode)]||{work:r.work_title,ep:r.episode,limit:0,active:false,dur:null,files:0,usable:0,usedAny:0,ids:[],limits:[],ch:{},videos:[]};
  if(r.is_active!==false)e.active=true;
  e.files+=1;e.ids.push(r.source_id);
  e.videos.push({sid:r.source_id,url:r.source_url||'',title:r.title||'',dur:Number(r.duration_sec)||null,limit:Number(r.use_limit)||0,
   usable:srcUsable(r),active:r.is_active!==false,wo:Number(r.times_used)||0,pin:0,ord:(r.published_ts||r.created_at||'')+'|'+r.source_id});
  if(!srcUsable(r))return;
  e.usable+=1;e.limit+=Number(r.use_limit)||0;e.usedAny+=Number(r.times_used)||0;e.limits.push(Number(r.use_limit)||0);
  const d=Number(r.duration_sec);if(!e.dur&&d>0)e.dur=d;
 });
 (byCh||[]).forEach(r=>{
  const e=(map[r.work_title]||{})[key(r.episode)];if(!e||!srcUsable(r))return;
  const c=e.ch[r.channel_slug]=e.ch[r.channel_slug]||{wo:0,lg:0,pin:0,used:0,pub:0,left:0};
  c.wo+=Number(r.used_wo)||0;c.pub+=Number(r.used_pub)||0;c.left+=Number(r.attempts_left)||0;
  c.pin+=Number(r.used_legacy_pin)||0;c.lg=Math.max(c.lg,Number(r.used_legacy)||0);c.used=c.wo+c.pin+c.lg;
  const v=e.videos.find(v=>v.sid===r.source_id);if(v)v.pin+=Number(r.used_legacy_pin)||0;
 });
 return map;
}

// 회차 안의 영상 — planner 와 같은 순서(업로드→등록)로 세우고, 못박히지 않은 레거시 몫은 앞선 영상부터 나눈다
export function videoRows(e){
 const vids=(e.videos||[]).slice().sort((a,b)=>a.ord<b.ord?-1:a.ord>b.ord?1:0);
 let lgUn=Object.values(e.ch||{}).reduce((s,c)=>s+(c.lg||0),0);
 return vids.map(v=>{let take=0;if(v.usable&&lgUn>0){take=Math.min(Math.max(v.limit-v.wo-v.pin,0),lgUn);lgUn-=take;}
  const used=v.wo+v.pin+take;return {...v,used,left:v.usable?Math.max(v.limit-used,0):0};});
}
export const epsOf=(data,w)=>Object.values(data.eps[w]||{}).sort((a,b)=>(a.ep??1e9)-(b.ep??1e9));
export const epUsable=e=>e.usable>0;
export const epUsed=(e,s)=>{const c=e.ch[s]||{};return (c.pub||0)+(c.pin||0)+(c.lg||0);};   // 한도에 세는 것 = 발행분 + 레거시 보정(0064)
export const epTries=(e,s)=>{const c=e.ch[s]||{};return (c.wo||0)+(c.pin||0)+(c.lg||0);};  // 반려·취소 포함 시도
export const epLeft=(e,s)=>(e.ch[s]||{}).left||0;
export const epRemain=(e,s)=>Math.max(0,e.limit-epUsed(e,s));
export const channelsOf=(data,w)=>data.channels.filter(c=>(c.works||[]).includes(w));

// 작품 요약 — 남은 편수 ÷ 배정 채널 수 = 며칠치(source_watch 의 보충 기준과 같은 셈)
export function workSummary(data,w){
 const eps=epsOf(data,w),chs=channelsOf(data,w);
 const rem=eps.filter(epUsable).reduce((s,e)=>s+Math.max(0,e.limit-e.usedAny),0);
 const days=chs.length?rem/chs.length:Infinity;
 const next=chs.map(c=>{const e=eps.find(x=>epUsable(x)&&epRemain(x,c.token_slug)>0);return {channel:c,ep:e?(e.ep!=null?e.ep+'회차':'단편'):null};});
 const nextSid=chs.length===1?(()=>{for(const e of eps){const v=videoRows(e).find(x=>x.usable&&x.left>0);if(v)return v.sid;}return null;})():null;
 return {eps,chs,rem,days,next,nextSid,state:!eps.length?'none':rem===0?'empty':days<=3?'low':'ok'};
}

export async function setLimit(client,sids,value){
 const rs=await Promise.all(sids.map(sid=>client.rpc('set_source_limit',{p_source:sid,p_limit:value})));
 const bad=rs.find(r=>r.error);if(bad)throw new Error(bad.error.message);
}
export async function setUsed(client,sid,channel,value){
 const {error}=await client.rpc('set_source_used',{p_source:sid,p_channel:channel,p_used:value});
 if(error)throw new Error(error.message);
}

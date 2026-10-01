import {hiddenChannels} from './channel-visibility.js';
// 작품(원작) 공개 일정 — VES public.work_release_schedule (migration 0107). Browser writes go through RLS
// (operator/admin); created/updated stamps are set by the DB trigger. Times are entered in KST.
export const STATUS={scheduled:'예정',released:'공개됨',delayed:'연기',cancelled:'결방'};
export const PLATFORMS=['티빙','쿠팡플레이','넷플릭스','웨이브','디즈니+','왓챠','KBS','MBC','SBS','JTBC','tvN','ENA','MBN','TV조선','채널A'];
export const EDITORS=['operator','admin'];
// 공개 종류(0109) — 본편이 주인공이라 본편만 포인트 색, 나머지는 회색 꼬리표
export const KINDS={main:'본편',preview:'선공개',recap:'몰아보기',trailer:'예고편',other:'기타'};
// 소스 위치(0109) — 우리 쇼츠 원본을 받는 곳. 공개 플랫폼과 따로 고른다(티빙 작품이어도 원본은 유튜브일 수 있다)
export const SOURCE_LOCATIONS={drive:'드라이브',youtube:'유튜브',other:'기타'};
export const kindOf=r=>KINDS[r?.release_kind]?r.release_kind:'main';
const pad=n=>String(n).padStart(2,'0');
export const kstISO=(date,time)=>`${date}T${time||'00:00'}:00+09:00`;
export function kstParts(iso){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(iso)).map(x=>[x.type,x.value]));
 return {date:`${p.year}-${p.month}-${p.day}`,time:`${p.hour}:${p.minute}`};
}
// Stored status stays as entered; a '예정' whose time has passed is flagged so it can be marked 공개됨.
export const isOverdue=(row,now=Date.now())=>row.status==='scheduled'&&Date.parse(row.release_at)<=now;
// 화면에 보이는 상태 — '예정'이 시각을 지나면 따로 누르지 않아도 '공개됨'으로 본다(연기·결방은 사람이 바꾼 그대로)
export const shownStatus=(row,now=Date.now())=>isOverdue(row,now)?'released':row.status;
export const episodeNo=label=>{const m=/(\d+)/.exec(label||'');return m?Math.min(10000,+m[1]):null;};
// {n} → '5' or, when several episodes open together, '5-6'. Every {n} is replaced.
export const episodeLabel=(fmt,n,last=n)=>(fmt||'{n}화').split('{n}').join(last>n?`${n}-${last}`:String(n));
// 매주 반복: from start date, each checked weekday opens the next `per` episodes until `to`. Pure.
export function weeklyRows({start,weekdays,time,from,to,fmt,per=1},limit=200){
 per=Math.max(1,Math.min(10,Math.floor(+per)||1));
 if(!start||!weekdays?.length||!(from>=0)||!(to>=from))return [];
 const [y,m,d]=start.split('-').map(Number),rows=[];let n=from;
 for(let i=0;n<=to&&i<7*120&&rows.length<limit;i++){
  const t=new Date(Date.UTC(y,m-1,d+i));
  if(!weekdays.includes(t.getUTCDay()))continue;
  const date=`${t.getUTCFullYear()}-${pad(t.getUTCMonth()+1)}-${pad(t.getUTCDate())}`;
  const last=Math.min(to,n+per-1);
  rows.push({date,time,episode_no:n,episode_label:episodeLabel(fmt,n,last)});n=last+1;
 }
 return rows;
}
export async function listRange(client,fromISO,toISO){
 const {data,error}=await client.from('work_release_schedule').select('*').gte('release_at',fromISO).lt('release_at',toISO).order('release_at').order('episode_no',{nullsFirst:false});
 if(error)throw new Error(error.message||'작품 일정을 불러오지 못했습니다.');
 return data||[];
}
const clean=r=>({work_id:r.work_id,work_title:r.work_title,episode_label:r.episode_label||null,episode_no:r.episode_no??episodeNo(r.episode_label),
 release_at:r.release_at,platform:r.platform||null,status:r.status||'scheduled',note:r.note||null,series_id:r.series_id||null,
 release_kind:KINDS[r.release_kind]?r.release_kind:'main',source_location:SOURCE_LOCATIONS[r.source_location]?r.source_location:null,
 source_channel_ids:r.source_location==='youtube'?[...new Set(r.source_channel_ids||[])].slice(0,10):[]});
export async function insertRows(client,rows){
 const {error}=await client.from('work_release_schedule').insert(rows.map(clean));
 if(error)throw new Error(error.message||'작품 일정을 저장하지 못했습니다.');
}
export async function updateRow(client,id,patch){
 const {error}=await client.from('work_release_schedule').update(patch).eq('id',id);
 if(error)throw new Error(error.message||'작품 일정을 고치지 못했습니다.');
}
// Series edits touch this episode and every later one in the same series (earlier ones stay as they aired).
export async function updateSeriesTime(client,row,time){
 const {data,error}=await client.from('work_release_schedule').select('id,release_at').eq('series_id',row.series_id).gte('release_at',row.release_at);
 if(error)throw new Error(error.message||'묶음 회차를 찾지 못했습니다.');
 for(const r of data){const {date}=kstParts(r.release_at);await updateRow(client,r.id,{release_at:kstISO(date,time)});}
 return data.length;
}
// 같은 반복 묶음에서 이 회차 **뒤의** 회차들에 같은 변경을 건다(앞선 회차는 이미 지나간 대로 둔다).
// time 은 회차마다 날짜를 두고 시각만 바꾸고, fields(플랫폼·공개 종류·소스 위치·원본 채널)는 한 번에 바꾼다.
export async function updateFollowing(client,row,{time=null,fields={}}={}){
 const {data,error}=await client.from('work_release_schedule').select('id,release_at').eq('series_id',row.series_id).gt('release_at',row.release_at).neq('id',row.id);
 if(error)throw new Error(error.message||'묶음 회차를 찾지 못했습니다.');
 if(!data.length)return 0;
 if(Object.keys(fields).length){const {error:e}=await client.from('work_release_schedule').update(fields).in('id',data.map(r=>r.id));if(e)throw new Error(e.message||'다음 회차들을 고치지 못했습니다.');}
 if(time)for(const r of data){const {date}=kstParts(r.release_at);await updateRow(client,r.id,{release_at:kstISO(date,time)});}
 return data.length;
}
export async function removeRows(client,row,{following=false}={}){
 let q=client.from('work_release_schedule').delete();
 q=following&&row.series_id?q.eq('series_id',row.series_id).gte('release_at',row.release_at):q.eq('id',row.id);
 const {error}=await q;
 if(error)throw new Error(error.message||'작품 일정을 지우지 못했습니다.');
}
// 우리 영상 = 채널에 실제로 공개된 쇼츠. perf_video_map is the YouTube channel sync (Studio uploads included,
// lags until the next sync); deleted videos carry dead_at. Read-only.
export async function listPublished(client,fromISO,toISO){
 const [videos,channels]=await Promise.all([
  client.from('perf_video_map').select('content_id,channel_id,title,work_title,published_at').is('dead_at',null).gte('published_at',fromISO).lt('published_at',toISO).order('published_at'),
  client.from('channels_mirror').select('channel_id,name,token_slug'),
 ]);
 if(videos.error)throw new Error(videos.error.message||'채널 영상을 불러오지 못했습니다.');
 const names=new Map((channels.data||[]).map(c=>[c.channel_id,c.name]));
 const hidden=await hiddenChannels(client),gone=new Set((channels.data||[]).filter(c=>hidden.has(c.token_slug)).map(c=>c.channel_id));
 const list=(videos.data||[]).filter(v=>!gone.has(v.channel_id));   // 숨긴 채널 영상은 달력·홈에서 뺀다
 // 작업 화면 검수 카드에서 예약·공개한 맥미니 영상(0120 tikitaka_reviews) — 채널 동기화가 따라오기 전에도 바로 보이게. 같은 영상이면 동기화 쪽을 쓴다
 try{
  const {data:revs}=await client.from('tikitaka_reviews').select('youtube_id,publish_at,meta,tikitaka_videos!inner(channel_slug,work_title,title)')
   .eq('stage','scheduled').not('youtube_id','is',null).gte('publish_at',fromISO).lt('publish_at',toISO);
  const have=new Set(list.map(v=>v.content_id)),slug=new Map((channels.data||[]).map(c=>[c.token_slug,c.channel_id]));
  for(const r of revs||[]){const ch=slug.get(r.tikitaka_videos?.channel_slug);if(!ch||gone.has(ch)||have.has(r.youtube_id))continue;
   list.push({content_id:r.youtube_id,channel_id:ch,title:r.meta?.title||String(r.tikitaka_videos?.title||'').replace(/\s*\n\s*/g,' '),work_title:r.tikitaka_videos?.work_title||'',published_at:r.publish_at});}
  list.sort((a,b)=>String(a.published_at).localeCompare(String(b.published_at)));
 }catch{}   // 못 읽어도 달력은 채널 동기화만으로 그린다
 const thumbs=await publishThumbs(client,list.map(v=>v.content_id));
 return list.map(v=>({...v,channel_name:names.get(v.channel_id)||'',thumb_url:thumbs.get(v.content_id)||''}));
}
// 발행 썸네일(publish_thumbnails · ves-outputs/publish_thumbs/) — 예약 영상은 공개 전까지 유튜브 썸네일이 없어서 이걸 먼저 쓴다.
// 못 읽어도 달력은 그대로 — 유튜브 썸네일로 돌아간다.
async function publishThumbs(client,ids){
 if(!ids.length)return new Map();
 try{
  const {data,error}=await client.from('publish_thumbnails').select('content_id,object_key').in('content_id',ids);
  if(error||!data?.length)return new Map();
  const signed=await client.storage.from('ves-outputs').createSignedUrls(data.map(r=>r.object_key),3600);
  const url=new Map((signed.data||[]).filter(s=>s.signedUrl).map(s=>[s.path,s.signedUrl]));
  return new Map(data.filter(r=>url.has(r.object_key)).map(r=>[r.content_id,url.get(r.object_key)]));
 }catch{return new Map();}
}
export const youtubeUrl=id=>`https://www.youtube.com/shorts/${encodeURIComponent(id)}`;
export const youtubeThumb=id=>`https://i.ytimg.com/vi/${encodeURIComponent(id)}/mqdefault.jpg`;

// ── 원본 유튜브 채널(public.source_channels, 0109) ──
export async function listSourceChannels(client){
 const {data,error}=await client.from('source_channels').select('id,name,url,handle,avatar_url,created_at').order('created_at');
 if(error)throw new Error(error.message||'원본 채널 목록을 불러오지 못했어요.');
 return data||[];
}
export async function addSourceChannel(client,{name,url,handle,avatar_url}){
 const {data,error}=await client.from('source_channels').insert({name,url,handle:handle||null,avatar_url:avatar_url||null}).select().single();
 if(error)throw new Error(error.code==='23505'?'이미 목록에 있는 채널이에요.':error.message||'채널을 추가하지 못했어요.');
 return data;
}
export async function removeSourceChannel(client,id){
 const {error}=await client.from('source_channels').delete().eq('id',id);
 if(error)throw new Error(error.message||'채널을 빼지 못했어요.');
}
// 작품 카드(work_cards, 0028) — 유튜브 원본 링크(playlist_url)가 소스 창고 자동 등록의 정본이다
export async function workCard(client,title){
 const {data,error}=await client.from('work_cards').select('work_title,playlist_url,title_filter').eq('work_title',title).maybeSingle();
 if(error)throw new Error(error.message||'작품 설정을 불러오지 못했어요.');
 return data;
}
export async function listWorkCards(client){
 const {data,error}=await client.from('work_cards').select('work_title,playlist_url').not('playlist_url','is',null);
 if(error)throw new Error(error.message||'작품 설정을 불러오지 못했어요.');
 return data||[];
}
// 채널 전체를 훑으므로 다른 프로그램이 섞이지 않게 제목 필터(작품 이름, 띄어쓰기 무시)를 같이 건다 — 이미 있으면 그대로
export async function linkWorkSource(client,title,channel,card){
 const args={p_work:title,p_playlist:channel.url.replace(/\/+$/,'')+'/videos'};
 if(!card?.title_filter)args.p_filter=title;
 const {error}=await client.rpc('set_work_card',args);
 if(error)throw new Error(error.message||'작품 원본 채널을 저장하지 못했어요.');
}

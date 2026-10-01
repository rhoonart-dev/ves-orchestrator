import {buildRoom,tasksOf,taskState,overlapNote,epText,shortTitle} from './source-room-model.js';
import {openSourceSettings,openCompile,openTask} from './source-dialogs.js';
import {esc} from './review-details.js?v=web-1';
// 소스 창고 새 구조(0121) — 회차마다 원본(합본 · 파일)과 그 원본으로 한 작업(#번호).
// 합본 만들기 · 작업하기 · 유튜브 원천 설정은 source-dialogs.js. 예전 파이프라인 숫자(한도 · 소진)는 works.js 가 접어서 아래에 둔다.

export async function loadRoom(client,work){
 const q=(t,sel)=>client.from(t).select(sel).eq('work_title',work);
 const [card,yt,sources,comps,tasks,chans]=await Promise.all([
  q('work_cards','work_title,episode_unit,compile_group,compile_recap,task_prev_ref').maybeSingle().then(r=>r.data||{}),
  q('work_youtube_sources','*').order('rank').then(r=>r.data||[],()=>[]),
  q('sources','id,episode,episode_label,clip_kind,title,source_url,duration_sec,published_ts,overlap,yt_source_id,is_active,sha256,compilation_id,origin,created_at').then(r=>{if(r.error)throw new Error(r.error.message);return r.data||[];}),
  q('source_compilations','*').neq('status','deleted').then(r=>r.data||[],()=>[]),
  q('tikitaka_tasks','*').neq('status','deleted').then(r=>r.data||[],()=>[]),
  client.from('source_channels').select('id,name,url,avatar_url').order('name').then(r=>r.data||[],()=>[]),
 ]);
 const wos=tasks.map(t=>t.work_order_id).filter(Boolean),stats=new Map();
 if(wos.length){
  const [vids,jobs,runs]=await Promise.all([
   client.from('tikitaka_videos').select('id,work_order_id,status').in('work_order_id',wos).then(r=>r.data||[]),
   client.from('job_queue').select('work_order_id,status').in('work_order_id',wos).in('status',['failed','dead']).then(r=>r.data||[],()=>[]),
   client.from('job_queue').select('work_order_id,progress').in('work_order_id',wos).eq('kind','tikitaka_generate').eq('status','running').then(r=>r.data||[],()=>[]),
  ]);
  const ids=vids.map(v=>v.id),pub=new Set();
  if(ids.length){const {data}=await client.from('tikitaka_reviews').select('video_id,stage').in('video_id',ids).eq('stage','scheduled');(data||[]).forEach(r=>pub.add(r.video_id));}
  for(const v of vids){const s=stats.get(v.work_order_id)||{videos:0,published:0};s.videos++;if(pub.has(v.id))s.published++;stats.set(v.work_order_id,s);}
  for(const j of jobs){const s=stats.get(j.work_order_id)||{videos:0,published:0};s.failed=true;stats.set(j.work_order_id,s);}
  for(const j of runs){const s=stats.get(j.work_order_id)||{videos:0,published:0};s.progress=j.progress;stats.set(j.work_order_id,s);}   // 진행 단계(0125)
 }
 return {work,card,yt,sources,comps,tasks,channels:chans,stats};
}

const mmss=s=>{s=Math.max(0,Math.round(Number(s)||0));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
const mins=s=>s>=3600?`${Math.floor(s/3600)}시간 ${Math.round(s%3600/60)}분`:`${Math.max(1,Math.round(s/60))}분`;
export const when=v=>new Intl.DateTimeFormat('ko-KR',{month:'long',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(v));
function ago(v){
 const m=Math.round((Date.now()-new Date(v))/60000);
 return m<60?`${Math.max(1,m)}분 전`:m<1440?`${Math.round(m/60)}시간 전`:`${Math.round(m/1440)}일 전`;
}
const av=(src,name,cls='sr-av')=>src?`<img class="${cls}" src="${esc(src)}" alt="" referrerpolicy="no-referrer">`:`<span class="${cls}">${esc((name||'?').slice(0,1))}</span>`;
export const chanChip=(name,avatar,extra='')=>`<span class="sr-chn">${av(avatar,name)}${esc(name)}${extra?' '+esc(extra):''}</span>`;

// host 에 작품 하나를 그린다. ctx: {client, canEdit, workChannels:[{token_slug,name,avatar_url}], reload()}
export function renderRoom(host,data,ctx){
 const room=buildRoom(data),open=ctx.openClips||(ctx.openClips=new Set());
 const chBy=new Map((ctx.workChannels||[]).map(c=>[c.token_slug,c]));
 const head=`<div class="sr-head">${room.youtube?`<span class="sr-head-src">${(data.yt||[]).map(s=>{const ch=data.channels.find(c=>c.id===s.channel_id);return chanChip(ch?.name?.replace(/\s*:.*$/,'')||s.label||'유튜브',ch?.avatar_url);}).join('')}</span>`:''}
  ${ctx.canEdit?`<button type="button" class="sr-btn" data-act="settings">작품 설정</button>`:''}</div>`;
 const groups=room.groups.map(g=>groupHtml(g)).join('')||'<p class="sr-empty">아직 원본이 없어요.</p>';
 host.innerHTML=head+`<div class="sr-groups">${groups}</div>`;

 function groupHtml(g){
  const clipN=g.clips.filter(c=>c.clip_kind!=='extra').length;
  const stat=g.byChannel.length?`<span class="sr-stat">${g.byChannel.map(c=>chanChip(c.name,c.avatar,`${c.n}개`)).join('')}${g.lastClip?`<span class="sr-ago">마지막 클립 ${ago(g.lastClip)}</span>`:''}</span>`
   :g.files.length?'':`<span class="sr-stat"><span class="sr-ago">아직 클립이 없어요</span></span>`;
  const canCompile=ctx.canEdit&&g.key!==''&&clipN>0;
  const rows=[...g.comps.map(c=>compRow(g,c)),...g.files.map(f=>fileRow(g,f))].join('');
  const clips=g.clips.length?`<details class="sr-clips" data-key="${esc(g.key)}" ${open.has(g.key)?'open':''}><summary>클립 ${g.clips.length}개 보기</summary>${clipList(g)}</details>`:'';
  return `<article class="sr-ep"><div class="sr-top"><b class="sr-no">${esc(g.label)}</b>${stat}${canCompile?`<button type="button" class="sr-btn" data-act="compile" data-key="${esc(g.key)}">합본 만들기</button>`:''}</div>${rows}${clips}</article>`;
 }
 function compRow(g,c){
  const busy=c.status==='queued'||c.status==='building',failed=c.status==='failed';
  const sub=busy?esc(c.progress||'합본을 만들고 있어요'):failed?`만들지 못했어요${c.error?` · <span title="${esc(c.error)}">이유 보기</span>`:''}`
   :`${esc(when(c.done_at||c.created_at))} · ${mins(Number(c.duration_sec)||0)} · 클립 ${c.clip_count||0}개`;
  const tasks=c.source_id?tasksOf(g,c.source_id):[];
  return `<div class="sr-src"><div class="sr-src-row"><span class="sr-thumb${busy?' busy':''}"></span><span class="sr-src-name"><b>${esc(c.name)}</b><small class="${failed?'bad':''}">${sub}</small></span>
   ${c.status==='ready'?`<button type="button" class="sr-link" data-act="recipe" data-comp="${esc(c.id)}">구성 보기</button>`:''}
   ${ctx.canEdit&&tasks.some(t=>t.status==='draft')?`<button type="button" class="sr-btn" data-act="start-drafts" data-src="${esc(c.source_id)}">시작 전 작업 모두 시작</button>`:''}
   ${ctx.canEdit&&c.status==='ready'?`<button type="button" class="sr-btn solid" data-act="task" data-src="${esc(c.source_id)}" data-key="${esc(g.key)}">이 합본으로 작업하기</button>`:''}
   ${ctx.canEdit&&failed?`<button type="button" class="sr-btn" data-act="compile" data-key="${esc(g.key)}">다시 만들기</button>`:''}</div>
   ${taskBtns(tasks)}</div>`;
 }
 function fileRow(g,f){
  const tasks=tasksOf(g,f.id);
  return `<div class="sr-src"><div class="sr-src-row"><span class="sr-thumb"></span><span class="sr-src-name"><b>${esc(f.title||`${g.label} 원본`)}</b><small>${f.duration_sec?mins(Number(f.duration_sec)):'길이 모름'}${f.sha256?'':' · 아직 파일을 안 받았어요'}</small></span>
   ${ctx.canEdit&&tasks.some(t=>t.status==='draft')?`<button type="button" class="sr-btn" data-act="start-drafts" data-src="${esc(f.id)}">시작 전 작업 모두 시작</button>`:''}
   ${ctx.canEdit&&f.sha256?`<button type="button" class="sr-btn solid" data-act="task" data-src="${esc(f.id)}" data-key="${esc(g.key)}">이 원본으로 작업하기</button>`:''}</div>
   ${taskBtns(tasks)}</div>`;
 }
 function taskBtns(tasks){
  if(!tasks.length)return '';
  return `<div class="sr-tasks">${tasks.map(t=>{const st=taskState(t,data.stats.get(t.work_order_id)),ch=chBy.get(t.channel_slug);
   const text=st.kind==='done'?esc(st.text).replace(/(\d+)편/g,'<b>$1편</b>'):esc(st.text);
   return `<button type="button" class="sr-task ${st.kind}" data-task="${esc(t.id)}" title="${esc(when(t.created_at))} 만듦"><span class="sr-num">#${t.work_no}</span>${av(ch?.avatar_url,ch?.name||t.channel_slug,'sr-av sm')}<span>${esc(ch?.name||t.channel_slug)} · ${text}</span><em>›</em></button>`;}).join('')}</div>`;
 }
 function clipList(g){
  const sec=(title,list)=>list.length?`<div class="sr-grp">${title}</div>`+list.map(c=>{
   const note=overlapNote(c,mmss),keep=(c.overlap?.keep||[]).reduce((s,[a,b])=>s+(b-a),0),dur=Number(c.duration_sec)||0;
   const out=c.overlap?.skip,partial=note&&!out;
   const bar=note?`<span class="sr-ov">${partial?(c.overlap.keep||[]).map(([a,b])=>`<i style="left:${a/dur*100}%;width:${(b-a)/dur*100}%"></i>`).join(''):''}</span>`:'';
   return `<div class="sr-clip${out?' out':''}"><span class="sr-clip-tw"><a href="${esc(c.source_url||'#')}" target="_blank" rel="noopener" class="sr-clip-tt" title="${esc(c.title||'')}">${esc(shortTitle(c.title,data.work))}</a>${note?`<span class="sr-ovn">${bar}${esc(note)}</span>`:''}</span>
    ${chanChip(c.channel,c.avatar)}<span class="sr-cd">${out?'안 씀':mmss(partial?keep:dur)}</span></div>`;}).join(''):'';
  const eps=[...new Set(g.clips.filter(c=>c.clip_kind==='clip').map(c=>c.episode))];
  return sec('앞 회차 몰아보기',g.clips.filter(c=>c.clip_kind==='recap'))+sec('선공개',g.clips.filter(c=>c.clip_kind==='prerelease'))
   +eps.map(e=>sec(e==null?'회차 모름':epText(e,room.unit),g.clips.filter(c=>c.clip_kind==='clip'&&c.episode===e))).join('')
   +sec('그 밖의 영상 · 합본에 안 넣어요',g.clips.filter(c=>c.clip_kind==='extra'));
 }

 // ── 동작 ──
 const groupOf=key=>room.groups.find(g=>g.key===key);
 host.querySelectorAll('details.sr-clips').forEach(d=>d.ontoggle=()=>{d.open?open.add(d.dataset.key):open.delete(d.dataset.key);});
 host.querySelector('[data-act="settings"]')?.addEventListener('click',()=>openSourceSettings({client:ctx.client,data,youtube:room.youtube,onSaved:ctx.reload}));
 host.querySelectorAll('[data-act="compile"]').forEach(b=>b.onclick=()=>openCompile({client:ctx.client,data,room,group:groupOf(b.dataset.key),onDone:ctx.reload}));
 host.querySelectorAll('[data-act="recipe"]').forEach(b=>b.onclick=()=>openCompile({client:ctx.client,data,room,comp:data.comps.find(c=>c.id===b.dataset.comp),readOnly:true}));
 host.querySelectorAll('[data-act="task"]').forEach(b=>b.onclick=()=>openTask({client:ctx.client,data,room,group:groupOf(b.dataset.key),sourceId:b.dataset.src,workChannels:ctx.workChannels,onDone:ctx.reload}));
 host.querySelectorAll('[data-act="start-drafts"]').forEach(b=>b.onclick=async()=>{
  const ids=data.tasks.filter(t=>t.source_id===b.dataset.src&&t.status==='draft').map(t=>t.id);
  b.disabled=true;const {error}=await ctx.client.rpc('start_tikitaka_tasks',{p_tasks:ids});
  if(error){b.disabled=false;ctx.toast?.(error.message);}else{ctx.toast?.(`작업 ${ids.length}개를 시작했어요.`);ctx.reload();}
 });
 host.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>{
  const t=data.tasks.find(x=>x.id===b.dataset.task);if(!t)return;
  if(t.status==='draft'){const g=room.groups.find(x=>x.tasks.includes(t));openTask({client:ctx.client,data,room,group:g,sourceId:t.source_id,task:t,workChannels:ctx.workChannels,onDone:ctx.reload,readOnly:!ctx.canEdit});}
  else if(t.work_order_id)location.hash=`review/MV-${t.work_order_id}`;
 });
}

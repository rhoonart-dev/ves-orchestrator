import {esc} from './review-details.js';
import {ON_WORK_PC,localChip} from './local-only.js';
import {assetRequest} from './work-assets.js';
import {localMedia} from './local-jobs.js?v=mv-4';
// 편집실 메뉴 — 다시 렌더 중인 영상, 이어서 할 초안, 최근 제출(7일)을 나눠 보여 준다. 새 편집은 작업 목록의 영상에서 시작한다.
// 렌더 중인 영상이 있으면 15초마다 다시 읽어 끝나는 대로 '최근 제출'로 옮긴다.
const EDITORS=['reviewer','operator','admin'];
const RECENT_MS=7*24*3600*1000;
const when=v=>{const d=new Date(v);return v&&Number.isFinite(d.getTime())?d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit'}):''};
const busyOf=v=>['queued','running'].includes(v.apply?.state);
const at=v=>busyOf(v)?v.apply.started_at:v.draft&&!v.draft.stale?v.draft.saved_at:v.apply?.finished_at||v.draft?.saved_at||'';
function kind(v){
 if(busyOf(v))return 'busy';
 if(v.draft&&!v.draft.stale)return 'draft';
 if(v.apply?.state==='failed')return 'failed';
 if(v.apply?.state==='done'&&Date.now()-new Date(v.apply.finished_at)<RECENT_MS)return 'done';
 if(v.draft?.stale)return 'stale';
 return null;
}
function row(job,v,k,canEdit){
 const editable=canEdit&&v.status==='ready'&&v.source_ok;
 const edit=label=>!ON_WORK_PC?(editable?localChip('편집은 작업 컴퓨터에서'):''):editable?`<a class="lv-edit" href="editor.html?local=1&run=${encodeURIComponent(v.key)}&back=${encodeURIComponent(job.id)}&from=editor">${label}</a>`:'';
 const [badge,line,action]={
  busy:()=>['<span class="lv-badge busy">렌더 중</span>',`${when(v.apply.started_at)} 제출${v.apply.by?' · '+v.apply.by:''} · 끝나면 새 판으로 바뀌어요`,''],
  draft:()=>['<span class="lv-badge">초안</span>',`${when(v.draft.saved_at)} 저장${v.draft.saved_by?' · '+v.draft.saved_by:''}`,edit('이어서 편집')],
  failed:()=>['<span class="lv-badge fail">렌더 실패</span>',v.apply.error||'다시 렌더하지 못했어요',edit(v.apply.restorable?'제출한 내용 고치기':'다시 편집')],
  done:()=>['<span class="lv-badge ok">새 판 완성</span>',`${when(v.apply.finished_at)} 완성${v.apply.by?' · '+v.apply.by:''}${v.apply.notes?.length?` · 달라진 점 ${v.apply.notes.length}가지`:''}`,edit('새 판 편집')],
  stale:()=>['<span class="lv-badge">지난 초안</span>','영상이 새로 만들어져서 이 초안은 이어갈 수 없어요',edit('새 판 편집')],
 }[k]();
 // 왼쪽 세로 캡처 — 완성본 1초 지점(렌더가 바뀌면 지문으로 새로 읽는다)
 const thumb=`<span class="lv-thumb"><video src="${esc(v.thumb||localMedia(v.key,'shorts.mp4')+'&v='+encodeURIComponent(String(v.render_fingerprint||'').slice(0,12)))}#t=1" muted playsinline preload="metadata" aria-hidden="true"></video></span>`;
 return `<article class="lv-row"><div class="lv-row-main">${thumb}<div class="lv-row-copy"><p class="lv-eyebrow">${esc([job.work,job.title].filter(Boolean).join(' · '))} · ${esc(v.suffix)}</p><h3>${badge}${esc((v.title||v.suffix).replace(/\n/g,' '))}</h3><p class="lv-row-state${k==='failed'?' lv-row-error':''}">${esc(line)}</p>${k==='done'&&v.apply.notes?.length?`<ul class="lv-notes">${v.apply.notes.map(n=>`<li class="${n.level==='warn'?'warn':''}">${esc(n.text)}</li>`).join('')}</ul>`:''}</div></div><div class="lv-actions"><a class="lv-folder" href="#review/${esc(job.id)}">작업 폴더</a>${action}</div></article>`;
}
// 맥미니 영상의 편집 — 초안(0113 tikitaka_edit_drafts, 사람별) · 다시 렌더(tikitaka_apply_edit 잡). 행 하나 = 초안 하나 또는 그 편의 최근 렌더
async function remoteRows(client){
 const since=new Date(Date.now()-RECENT_MS).toISOString();
 const [d,j]=await Promise.all([
  client.from('tikitaka_edit_drafts').select('video_id,email,based_on,saved_at,submitted_job').order('saved_at',{ascending:false}).limit(300),
  client.from('job_queue').select('id,status,error,params,created_at,started_at,finished_at').eq('kind','tikitaka_apply_edit').gte('created_at',since).order('created_at',{ascending:false}).limit(300)]);
 const drafts=d.data||[],jobs=j.data||[];
 const ids=[...new Set([...drafts.map(x=>x.video_id),...jobs.map(x=>x.params?.video_id)].filter(Boolean))];
 if(!ids.length)return [];
 const {data:vids}=await client.from('tikitaka_videos').select('id,work_order_id,suffix,title,render_fingerprint,work_title,episode,files').in('id',ids);
 const byId=new Map((vids||[]).map(v=>[v.id,v]));
 const keys=(vids||[]).map(v=>v.files?.['shorts.mp4']?.key).filter(Boolean),signed=new Map();
 if(keys.length){const {data:u}=await client.storage.from('ves-outputs').createSignedUrls(keys,6*3600);(u||[]).forEach(x=>{if(x.signedUrl)signed.set(x.path,x.signedUrl);});}
 const ep=e=>/^\d+$/.test(String(e||''))?`${e}화`:String(e||'');
 const base=x=>({key:`remote-${x.work_order_id}/${x.suffix}`,suffix:x.suffix,title:x.title,render_fingerprint:x.render_fingerprint,status:'ready',source_ok:true,remote:true,thumb:signed.get(x.files?.['shorts.mp4']?.key)||''});
 const jobOf=x=>({id:'MV-'+x.work_order_id,work:x.work_title,title:ep(x.episode)});
 const out=[],seen=new Set();
 for(const q of jobs){                       // 그 편의 가장 최근 렌더만
  const x=byId.get(q.params?.video_id);if(!x||seen.has(x.id))continue;seen.add(x.id);
  const state={pending:'queued',running:'running',succeeded:'done'}[q.status]||'failed';
  const v={...base(x),apply:{state,started_at:q.started_at||q.created_at,finished_at:q.finished_at||q.created_at,error:state==='failed'?String(q.error||'').slice(-200):null,by:q.params?.by||''}};
  if(state==='failed')v.apply.restorable=drafts.some(dd=>dd.video_id===x.id&&dd.submitted_job===q.id);
  out.push({job:jobOf(x),v,k:kind(v),who:q.params?.by||''});
 }
 for(const dd of drafts){
  const x=byId.get(dd.video_id);if(!x||dd.submitted_job)continue;
  const v={...base(x),draft:{saved_at:dd.saved_at,saved_by:dd.email||'',stale:dd.based_on!==x.render_fingerprint}};
  out.push({job:jobOf(x),v,k:kind(v),who:dd.email||''});
 }
 return out.filter(r=>r.k);
}
const GROUPS=[['busy','다시 렌더 중'],['draft','이어서 할 편집'],['failed','렌더 실패'],['done','최근 제출'],['stale','지난 초안']];
export function mountLocalVideos(root,{client,role}={}){
 let dead=false,timer=0,localOk=true;const canEdit=EDITORS.includes(role);
 let scope='mine';try{scope=localStorage.getItem('lv-scope')==='all'?'all':'mine'}catch{}
 root.innerHTML='<p role="status" class="lv-status">편집 목록을 불러오는 중…</p>';
 async function render(){
  clearTimeout(timer);
  try{
   // 작업 컴퓨터 영상(로컬 서버 — 없으면 건너뜀) + 맥미니 영상(Supabase 에서 바로 — 웹에서도 된다)
   const [local,remote,me]=await Promise.all([
    assetRequest(client,'/api/local-videos').then(r=>r.jobs,()=>null),
    remoteRows(client).catch(()=>[]),
    client.auth.getUser().then(r=>r.data?.user?.email||'',()=>'')]);
   if(dead)return;localOk=!!local;
   const all=[...(local||[]).flatMap(j=>j.videos.map(v=>({job:j,v,k:kind(v),who:(kind(v)==='draft'||kind(v)==='stale')?v.draft?.saved_by||'':''}))).filter(r=>r.k),...remote]
    .sort((a,b)=>String(at(b.v)).localeCompare(String(at(a.v))));
   // 내 편집 = 내가 저장·제출한 것(작업 컴퓨터의 제출은 누가 했는지 몰라 내 것으로 본다)
   const rows=scope==='mine'?all.filter(r=>!r.who||r.who===me):all;
   const sections=GROUPS.map(([k,title])=>{const list=rows.filter(r=>r.k===k);return list.length?`<section class="lv-group"><h2>${title} <span>${list.length}</span></h2><div class="lv-list">${list.map(r=>row(r.job,r.v,k,canEdit)).join('')}</div></section>`:'';}).join('');
   root.innerHTML=`<section class="lv-intro"><header class="lv-head"><div><h2>편집 중인 영상</h2><div class="lv-scope" role="radiogroup" aria-label="누구의 편집"><button type="button" role="radio" data-scope="mine" aria-checked="${scope==='mine'}">내 편집</button><button type="button" role="radio" data-scope="all" aria-checked="${scope==='all'}">모두</button></div><p>제출하면 편집한 그대로 다시 렌더해서 같은 번호의 새 판으로 바꿔요. 새 편집은 <a href="#review?source=local">작업 목록</a>에서 영상을 고른 뒤 <b>편집실</b> 버튼으로 시작해요.</p></div></header></section>`+
    (sections||`<section class="empty-state"><h2>편집 중인 영상이 없어요</h2><p>작업 목록에서 영상의 <b>편집실</b> 버튼으로 여세요.</p><p><a href="#review?source=local">작업 목록으로</a></p></section>`);
   root.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>{if(scope===b.dataset.scope)return;scope=b.dataset.scope;try{localStorage.setItem('lv-scope',scope)}catch{}render();});
   if(!localOk)root.querySelector('.lv-intro').insertAdjacentHTML('beforeend',`<p class="lv-local-off">${ON_WORK_PC?'작업 컴퓨터 영상은 작업 컴퓨터에서 워크스페이스를 켰을 때만 보여요.':'작업 컴퓨터 영상과 편집실은 작업 컴퓨터에서만 쓸 수 있어요. 맥미니 영상은 여기서 볼 수 있어요.'}</p>`);
   if(rows.some(r=>r.k==='busy'))timer=setTimeout(render,15000);
  }catch(e){if(dead)return;root.replaceChildren();const p=document.createElement('p');p.className='auth-notice';p.setAttribute('role','alert');p.textContent=e.message;root.append(p);}
 }
 if(!client){root.innerHTML='<p class="lv-status">로그인하면 편집 중인 영상을 볼 수 있어요.</p>';return()=>{};}
 render();
 return()=>{dead=true;clearTimeout(timer);};
}
